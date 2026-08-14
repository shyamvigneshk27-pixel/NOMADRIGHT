"""
NomadRight qwen2.5vl:3b Client

Lazy Ollama HTTP client for the two places a generative model is allowed to
touch NomadRight's answer path:

  1. Text fallback - when intent/keyword matching AND the thresholded RAG
     pipeline both find nothing (see workflow.py Step 6.5 / response.py's
     LLM_FALLBACK priority).
  2. Vision form-reading - a worker photographs a government form via the
     touchscreen Camera button and asks a follow-up question about it (see
     workflow.py's process_vision_query).

Deliberately NOT a reuse of pocketinfer.models.ollama.Ollama: that class
hardcodes keep_alive=-1 (permanently resident - the opposite of "only use
RAM when necessary") and has no per-request timeout or num_gpu control, and
it's shared by other applications this module has no business changing.

Every request is grounded and sentinel-gated: the system prompt instructs
the model to answer ONLY from the provided context/image and to return
constants.LLM_SENTINEL_NOT_FOUND verbatim otherwise. Callers treat the
sentinel exactly like "no answer" and fall through to the existing constant
fallback message - this is what keeps the zero-confident-hallucination
guarantee response.py's docstring already commits to, extended rather than
broken.

num_gpu is forced high on every call rather than left to Ollama's own
auto-fit heuristic - see constants.LLM_NUM_GPU's comment for why (Jetson's
GPU/CPU share one physical RAM pool, and the auto-fit heuristic otherwise
offloads 0 layers whenever BHASHINI is already resident, which is always).
"""

import base64
import logging
import time
from dataclasses import dataclass
from typing import List, Optional

import requests

from pocketinfer.applications.nomad_right import constants

logger = logging.getLogger(__name__)

_OLLAMA_GENERATE_URL = "http://localhost:11434/api/generate"

_SYSTEM_PROMPT = (
    "You are a factual assistant for a welfare-rights kiosk used by migrant "
    "workers in India. Answer the question using ONLY the information given "
    "in the context below. Keep the answer under 40 words, plain factual "
    "sentences, no speculation. If the context does not contain the answer, "
    f"reply with exactly this text and nothing else: {constants.LLM_SENTINEL_NOT_FOUND}"
)

# Vision path (camera/form-reading) never receives text context - see
# workflow.py's process_vision_query and the module docstring above. The
# text-fallback prompt's "context below" framing measurably biased the
# model toward the not-found sentinel even with a clear, readable image in
# front of it (reproduced on-device: a synthetic form photo that answered
# correctly when (incorrectly) given RAG context returned the sentinel once
# that context was correctly removed) - this prompt instead frames the
# photographed image itself as the one and only source of truth.
_VISION_SYSTEM_PROMPT = (
    "You are a factual assistant for a welfare-rights kiosk used by migrant "
    "workers in India, reading a photographed government form/document on "
    "their behalf. Carefully look at the provided image and answer the "
    "question using ONLY what is visible in it. Keep the answer under 40 "
    "words, plain factual sentences, no speculation. If the image is "
    "unclear, blurry, cropped, or the requested field/text is not visible, "
    f"reply with exactly this text and nothing else: {constants.LLM_SENTINEL_NOT_FOUND}"
)

# For a query that isn't about any welfare scheme at all (no scheme named,
# RulesEngine and RAG both found nothing - see workflow.py Step 6.5) - no
# "context below" framing here on purpose. Grounding this case in loosely-
# related RAG chunks was the previous design, and it measurably backfired:
# a genuinely unrelated query ("Updating the app") pulled in an unrelated
# e-Shram chunk as "reading material" and the model fabricated an
# Aadhaar-OTP answer from it. There's nothing scheme-specific to hallucinate
# here since no scheme was named, so it's safe (and more useful) to let the
# model just answer directly instead of forcing it to pretend-ground itself
# in irrelevant scheme text - not sentinel-gated, since there's no context
# to fail to find an answer in.
_GENERAL_SYSTEM_PROMPT = (
    "You are a helpful voice assistant at an offline welfare-rights kiosk "
    "for migrant workers in India. The worker just asked something that "
    "isn't about a specific government welfare scheme. Answer directly and "
    "helpfully in plain, simple language. Keep the answer under 40 words. "
    "If you genuinely don't know, say so briefly rather than guessing."
)


@dataclass
class QwenAnswer:
    """Result of a qwen call, with enough timing info to log/debug latency."""
    text: str
    elapsed_s: float
    found: bool  # False if the model returned the not-found sentinel


class QwenClientError(RuntimeError):
    """Raised when the Ollama request itself fails (network/timeout/HTTP error)."""


class QwenClient:
    """
    Thin, lazy client for qwen2.5vl:3b via Ollama's /api/generate. Nothing
    is loaded or warmed at construction time - the first real answer_text()/
    answer_vision() call is what triggers Ollama to load the model, and it
    stays resident only for constants.LLM_KEEP_ALIVE afterward.
    """

    def __init__(self, model: str = constants.LLM_FALLBACK_MODEL):
        self.model = model
        self.logger = logging.getLogger(self.__class__.__name__)

    # ── Shared request plumbing ─────────────────────────────────────────────

    def _build_prompt(self, query: str, context_snippets: List[str]) -> str:
        if context_snippets:
            context_block = "\n".join(f"- {c}" for c in context_snippets)
        else:
            context_block = "(no matching context found)"
        return (
            f"{_SYSTEM_PROMPT}\n\n"
            f"Context:\n{context_block}\n\n"
            f"Question: {query}\n"
            f"Answer:"
        )

    def _build_vision_prompt(self, query: str) -> str:
        return f"{_VISION_SYSTEM_PROMPT}\n\nQuestion: {query}\nAnswer:"

    def _build_general_prompt(self, query: str) -> str:
        return f"{_GENERAL_SYSTEM_PROMPT}\n\nQuestion: {query}\nAnswer:"

    def _call(
        self, prompt: str, images: Optional[List[bytes]], num_predict: int
    ) -> QwenAnswer:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": constants.LLM_KEEP_ALIVE,
            "options": {
                "num_gpu": constants.LLM_NUM_GPU,
                "num_thread": constants.LLM_NUM_THREAD,
                "num_ctx": constants.LLM_NUM_CTX,
                "num_predict": num_predict,
                "temperature": constants.LLM_TEMPERATURE,
            },
        }
        if images:
            # Ollama's REST API requires images as base64-encoded strings in
            # the JSON body, not raw bytes - passing raw JPEG bytes makes
            # requests' JSON encoder try to treat them as UTF-8 text and
            # fail immediately (JPEG's 0xFF magic byte isn't valid UTF-8).
            payload["images"] = [
                base64.b64encode(bytes(img) if isinstance(img, (bytearray, memoryview)) else img).decode("ascii")
                for img in images
            ]

        start = time.monotonic()
        try:
            resp = requests.post(
                _OLLAMA_GENERATE_URL, json=payload, timeout=constants.LLM_REQUEST_TIMEOUT_S
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            elapsed = time.monotonic() - start
            self.logger.error(f"qwen request failed after {elapsed:.1f}s: {exc}")
            raise QwenClientError(str(exc)) from exc

        elapsed = time.monotonic() - start
        text = (data.get("response") or "").strip()
        found = bool(text) and constants.LLM_SENTINEL_NOT_FOUND not in text
        self.logger.info(
            f"qwen answered in {elapsed:.1f}s (found={found}, "
            f"eval_count={data.get('eval_count')}, "
            f"load_ms={data.get('load_duration', 0) / 1e6:.0f})"
        )
        return QwenAnswer(text=text, elapsed_s=elapsed, found=found)

    # ── Public API ───────────────────────────────────────────────────────────

    def answer_text(self, query: str, context_snippets: List[str]) -> Optional[str]:
        """
        Text-only grounded QA for the intent/RAG fallback path. Returns None
        if the model errored, timed out, or couldn't answer from context -
        callers treat that identically to "no answer" (existing constant
        fallback).
        """
        if not query or not query.strip():
            return None
        prompt = self._build_prompt(query, context_snippets)
        try:
            result = self._call(prompt, images=None, num_predict=constants.LLM_NUM_PREDICT_TEXT)
        except QwenClientError:
            return None
        return result.text if result.found else None

    def answer_vision(
        self, query: str, image_jpg: bytes, context_snippets: Optional[List[str]] = None
    ) -> Optional[str]:
        """
        Image + text grounded QA for the camera/form-reading path. Returns
        None if the model errored, timed out, or the photographed document
        didn't answer the question - callers fall through to the existing
        constant fallback message.
        """
        if not image_jpg:
            return None
        query = query or "Describe what this document says and how it's relevant to the worker."
        # CAMERA_FORM never passes context_snippets (see workflow.py) - the
        # branch on context_snippets here exists only so this method still
        # behaves sensibly if some future caller does supply grounding text
        # alongside the image, without regressing the image-only case.
        if context_snippets:
            prompt = self._build_prompt(query, context_snippets)
        else:
            prompt = self._build_vision_prompt(query)
        try:
            result = self._call(
                prompt, images=[image_jpg], num_predict=constants.LLM_NUM_PREDICT_VISION
            )
        except QwenClientError:
            return None
        return result.text if result.found else None

    def answer_general(self, query: str) -> Optional[str]:
        """
        Ungrounded general-assistant QA for a query that isn't about any
        welfare scheme (no scheme named, RulesEngine and RAG both found
        nothing - see workflow.py Step 6.5). Not sentinel-gated - there's no
        context to fail to find an answer in, so any non-empty response is
        used as-is. Returns None only on an actual error/timeout.
        """
        if not query or not query.strip():
            return None
        prompt = self._build_general_prompt(query)
        try:
            result = self._call(prompt, images=None, num_predict=constants.LLM_NUM_PREDICT_TEXT)
        except QwenClientError:
            return None
        return result.text or None
