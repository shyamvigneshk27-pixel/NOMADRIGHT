"""
NomadRight Response Generator Module

Synthesizes multi-modal output packages from pipeline results:
  - voice_text          : TTS-optimised speech (BHASHINI TTS), capped at
                           constants.MAX_VOICE_WORDS words
  - display_top_text    : header line for 320×240 LCD (≤30 chars)
  - display_bottom_text : body line for LCD (≤60 chars)
  - qr_payload          : offline verification JSON for QR code
  - severity            : INFO / WARNING / CRITICAL for logging

Priority chain:
  1. Rules Engine response      (statutory eligibility/registration/benefits -
                                 deterministic, never touches Qwen)
  2. RAG retrieve-then-GENERATE (Qwen answers from the retrieved chunks -
                                 grounded + sentinel-gated, see qwen_client.py)
  3. LLM fallback response      (qwen, scheme-KB-grounded or general assistant;
                                 reached whenever 2 didn't produce a grounded
                                 answer - a Qwen decline is a more trustworthy
                                 relevance signal than the raw RAG score alone)
  4. RAG retrieve-then-TEMPLATE (raw top chunk, last resort - both 2 and 3
                                 failed but a chunk was at least retrieved)
  5. KB-only context response   (scheme data found but no rule/RAG chunk matched)
  6. Unknown / fallback         (nothing matched, including the LLM)
"""

import hashlib
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, List, Optional

from pocketinfer.applications.nomad_right import constants
from pocketinfer.applications.nomad_right.config import NomadRightConfig
from pocketinfer.applications.nomad_right.classifier import ClassificationResult
from pocketinfer.applications.nomad_right.database import PortabilityRecord
from pocketinfer.applications.nomad_right.entities import EntityMap
from pocketinfer.applications.nomad_right.intent import IntentResult
from pocketinfer.applications.nomad_right.rules import RuleEvaluationResult
from pocketinfer.applications.nomad_right.rag_pipeline import RetrievedChunk

logger = logging.getLogger(__name__)


class SeverityLevel(Enum):
    """Severity classification for display rendering and audit logs."""
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class StructuredResponsePackage:
    """Dataclass storing synthesized multi-modal output."""
    voice_text: str
    display_top_text: str
    display_bottom_text: str
    qr_payload: Optional[Dict[str, Any]] = None
    severity: SeverityLevel = SeverityLevel.INFO
    # Scheme this answer was actually about (e.g. "PDS"), if any - lets the
    # caller remember conversation context for the next turn's generic
    # follow-ups ("what documents do I need?") without repeating the scheme
    # name. See EntityExtractor._CONTEXT_INHERITABLE_INTENTS.
    scheme_code: Optional[str] = None


class IResponseGenerator(ABC):
    """Abstract interface for NomadRight Response Generators."""

    @abstractmethod
    def generate(
        self,
        intent_result: IntentResult,
        classification: ClassificationResult,
        rule_result: Optional[RuleEvaluationResult] = None,
        kb_record: Optional[PortabilityRecord] = None,
        rag_chunks: Optional[List[RetrievedChunk]] = None,
        entities: Optional[EntityMap] = None,
        llm_answer: Optional[str] = None,
        rag_llm_answer: Optional[str] = None,
    ) -> StructuredResponsePackage:
        """Synthesizes voice, LCD screen, and QR output."""
        pass


class ResponseGenerator(IResponseGenerator):
    """
    Offline Response Generator producing structured output for BHASHINI TTS,
    a 320×240 LCD screen, and offline QR verification.
    """

    def __init__(self, config: Optional[NomadRightConfig] = None):
        self.config = config or NomadRightConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

    # ── Private helpers ────────────────────────────────────────────────────

    def _fmt_voice(self, text: str) -> str:
        """Expands abbreviations for smooth TTS pronunciation."""
        if not text:
            return ""
        clean = text.strip().replace("\n", " ")
        replacements = [
            ("PMJAY",    "P M Jan Arogya Yojana"),
            ("BOCW",     "Building and Other Construction Workers"),
            ("OSH Code", "Occupational Safety and Health Code"),
            ("UAN",      "Universal Account Number"),
            ("INR",      "rupees"),
            ("Rs.",      "rupees"),
            ("ePoS",     "electronic Point of Sale"),
            ("FPS",      "Fair Price Shop"),
            ("NFSA",     "National Food Security Act"),
            ("AAY",      "Antyodaya Anna Yojana"),
            ("PHH",      "Priority Household"),
            ("DBT",      "Direct Benefit Transfer"),
            ("PMGKAY",   "PM Garib Kalyan Ann Yojana"),
            ("CSC",      "Common Service Centre"),
            # PDS last so it doesn't expand inside already-expanded phrases
            ("PDS",      "Public Distribution System"),
        ]
        for abbr, expansion in replacements:
            clean = clean.replace(abbr, expansion)
        return clean

    def _cap_words(self, text: str, max_words: int = constants.MAX_VOICE_WORDS) -> str:
        """Caps voice_text at max_words for a comfortable listening experience."""
        if not text:
            return ""
        words = text.split()
        if len(words) <= max_words:
            return text
        capped = " ".join(words[:max_words])
        if not capped.endswith((".", "!", "?")):
            capped += "."
        return capped

    def _trunc(self, text: str, max_len: int) -> str:
        """Truncates text to LCD line length."""
        return (text or "")[:max_len]

    def _qr_payload(
        self, intent_code: str, status_code: str, summary: str
    ) -> Dict[str, Any]:
        """Generates a tamper-evident QR payload for offline verification."""
        ts = int(time.time())
        raw = f"{ts}:{intent_code}:{status_code}"
        chk = hashlib.sha256(raw.encode()).hexdigest()[:8]
        return {
            "app":     constants.APP_NAME,
            "ver":     constants.APP_VERSION,
            "ts":      ts,
            "intent":  intent_code,
            "status":  status_code,
            "summary": summary[:40],
            "hash":    chk,
        }

    # ── Vision form-reading synthesis (Camera button flow) ──────────────────

    def generate_vision_response(self, answer: str, scheme_code: Optional[str] = None) -> StructuredResponsePackage:
        """
        Synthesizes a StructuredResponsePackage from a qwen_client.answer_vision()
        result (see workflow.py's process_vision_query). Only called with an
        already sentinel-checked, non-empty answer - the caller falls
        through to the normal generate()'s Priority 5 fallback otherwise.
        """
        voice_txt = self._cap_words(self._fmt_voice(answer))
        return StructuredResponsePackage(
            voice_text=voice_txt,
            display_top_text=self._trunc("FORM HELP", constants.DISPLAY_HEADER_MAX_LEN),
            display_bottom_text=self._trunc(answer, constants.DISPLAY_BODY_MAX_LEN),
            qr_payload=self._qr_payload("VISION_FORM_QUERY", "VISION_FORM_QUERY", answer),
            severity=SeverityLevel.WARNING,
            scheme_code=scheme_code,
        )

    # ── Main synthesis method ──────────────────────────────────────────────

    def generate(
        self,
        intent_result: IntentResult,
        classification: ClassificationResult,
        rule_result: Optional[RuleEvaluationResult] = None,
        kb_record: Optional[PortabilityRecord] = None,
        rag_chunks: Optional[List[RetrievedChunk]] = None,
        entities: Optional[EntityMap] = None,
        llm_answer: Optional[str] = None,
        rag_llm_answer: Optional[str] = None,
    ) -> StructuredResponsePackage:
        """
        Synthesizes a StructuredResponsePackage from Decision Layer outputs.

        Args:
            intent_result:   IntentResult from IntentRecognizer.
            classification:  ClassificationResult from QueryClassifier.
            rule_result:     Optional RuleEvaluationResult from RulesEngine.
            kb_record:       Optional PortabilityRecord from SQLiteAccessLayer.
            rag_chunks:      Optional retrieved passages from RAGRetriever,
                              best match first - used directly (Priority 2b)
                              only if rag_llm_answer is empty.
            entities:        Optional EntityMap from EntityExtractor.
            llm_answer:      Optional grounded answer from qwen_client.py,
                              already sentinel-checked by the caller (workflow.py)
                              - only ever populated when rule_result/rag_chunks/
                              kb_record all found nothing usable.
            rag_llm_answer:  Optional grounded answer from qwen_client.py,
                              generated from exactly the rag_chunks above
                              (retrieve-then-GENERATE) - already sentinel-
                              checked by the caller.

        Returns:
            StructuredResponsePackage for voice, LCD, and QR.
        """
        intent_code = intent_result.intent_type.value
        scheme_label = (
            (entities.scheme_code or "SCHEME") if entities else "SCHEME"
        )

        self.logger.debug(
            f"Generating response: intent={intent_code}, "
            f"route={classification.route_type.value}, "
            f"rule={'yes' if rule_result else 'no'}, "
            f"rag_chunks={len(rag_chunks) if rag_chunks else 0}, "
            f"kb={'yes' if kb_record else 'no'}"
        )

        # ── Priority 1: Rules Engine statutory response ─────────────────────
        if rule_result:
            voice_txt = self._cap_words(self._fmt_voice(rule_result.summary_message))

            # LCD top: rule_id + status  (e.g. "PDS-PORT-001: PORTABILITY_ALLOWED")
            rule_label = rule_result.triggered_rule_id or scheme_label
            top_hdr = f"{rule_label}: {rule_result.status_code.value}"

            # LCD bottom: next steps or detail message
            bottom_txt = (
                rule_result.next_steps
                or rule_result.detail_message
                or rule_result.summary_message
            )

            # Append helpline if available (space permitting)
            if rule_result.helpline and len(bottom_txt) < 35:
                bottom_txt = f"{bottom_txt} | Helpline: {rule_result.helpline}"

            return StructuredResponsePackage(
                voice_text=voice_txt,
                display_top_text=self._trunc(top_hdr, constants.DISPLAY_HEADER_MAX_LEN),
                display_bottom_text=self._trunc(bottom_txt, constants.DISPLAY_BODY_MAX_LEN),
                qr_payload=self._qr_payload(
                    intent_code, rule_result.status_code.value, rule_result.summary_message
                ),
                severity=SeverityLevel.INFO,
                scheme_code=rule_result.scheme_code or (entities.scheme_code if entities else None),
            )

        # ── Priority 2: RAG retrieve-then-GENERATE (qwen, grounded) ────────
        if rag_llm_answer:
            best = rag_chunks[0] if rag_chunks else None
            top_hdr = f"{(best.scheme_code if best else None) or scheme_label} INFO"
            voice_txt = self._cap_words(self._fmt_voice(rag_llm_answer))
            return StructuredResponsePackage(
                voice_text=voice_txt,
                display_top_text=self._trunc(top_hdr, constants.DISPLAY_HEADER_MAX_LEN),
                display_bottom_text=self._trunc(rag_llm_answer, constants.DISPLAY_BODY_MAX_LEN),
                qr_payload=self._qr_payload(intent_code, "RAG_QWEN_HIT", rag_llm_answer),
                severity=SeverityLevel.INFO,
                scheme_code=(best.scheme_code if best else None) or (entities.scheme_code if entities else None),
            )

        # ── Priority 3: LLM fallback (qwen, scheme-KB-grounded or general) ──
        # Checked BEFORE the raw RAG top-chunk echo below on purpose: this
        # only exists when Step 6.5a's Qwen-grounded RAG answer failed, and
        # Qwen declining to answer from the retrieved chunks (sentinel) is
        # a more trustworthy relevance signal than the raw cosine score
        # that let a chunk through RAG_MIN_SCORE in the first place - some
        # of the newer, terser scheme chunks can spuriously cross that
        # floor against unrelated/garbled text (reproduced on-device: a
        # garbled query matched 3 PM_VISHWAKARMA chunks at >0.83 and Qwen
        # correctly declined all of them). This fallback gets a second,
        # smarter shot at a real answer instead of the query falling
        # through to a blind, possibly-spurious top-chunk echo.
        if llm_answer:
            voice_txt = self._cap_words(self._fmt_voice(llm_answer))
            return StructuredResponsePackage(
                voice_text=voice_txt,
                display_top_text=self._trunc(f"{scheme_label} INFO", constants.DISPLAY_HEADER_MAX_LEN),
                display_bottom_text=self._trunc(llm_answer, constants.DISPLAY_BODY_MAX_LEN),
                qr_payload=self._qr_payload(intent_code, "LLM_FALLBACK", llm_answer),
                severity=SeverityLevel.WARNING,
                scheme_code=entities.scheme_code if entities else None,
            )

        # ── Priority 4: RAG retrieve-then-TEMPLATE (last resort - qwen and ─
        # the smarter fallback above both failed, but a chunk was at least
        # retrieved; degrade to echoing it verbatim rather than nothing) ──
        if rag_chunks:
            best = rag_chunks[0]
            voice_txt = self._cap_words(self._fmt_voice(best.text))
            top_hdr = f"{best.scheme_code or scheme_label} INFO"
            return StructuredResponsePackage(
                voice_text=voice_txt,
                display_top_text=self._trunc(top_hdr, constants.DISPLAY_HEADER_MAX_LEN),
                display_bottom_text=self._trunc(best.text, constants.DISPLAY_BODY_MAX_LEN),
                qr_payload=self._qr_payload(intent_code, "RAG_HIT", best.text),
                severity=SeverityLevel.INFO,
                scheme_code=best.scheme_code or (entities.scheme_code if entities else None),
            )

        # ── Priority 5: KB data only (no rule or RAG chunk matched) ────────
        # Mutually exclusive with llm_answer in practice - workflow.py only
        # computes llm_answer when kb_record is falsy - kept as its own
        # tier for a clear, deterministic-data-first priority order.
        if kb_record:
            benefit_txt = (
                kb_record.benefits[0] if kb_record.benefits else "Scheme data available."
            )
            voice_txt = self._cap_words(self._fmt_voice(
                f"Here is what I know about the {scheme_label} scheme: {benefit_txt}"
            ))
            return StructuredResponsePackage(
                voice_text=voice_txt,
                display_top_text=self._trunc(
                    f"{scheme_label} INFO", constants.DISPLAY_HEADER_MAX_LEN
                ),
                display_bottom_text=self._trunc(benefit_txt, constants.DISPLAY_BODY_MAX_LEN),
                qr_payload=self._qr_payload(intent_code, "KB_HIT", benefit_txt),
                severity=SeverityLevel.INFO,
                scheme_code=entities.scheme_code if entities else None,
            )

        # ── Priority 6: Unknown / Fallback ────────────────────────────────
        self.logger.warning(
            f"No response data for intent={intent_code}. Returning fallback."
        )
        fallback_voice = (
            "I'm sorry, I could not find information for your query. "
            "Please ask about the ration card, Ayushman Bharat, e-Shram, "
            "or BOCW construction worker schemes."
        )
        return StructuredResponsePackage(
            voice_text=fallback_voice,
            display_top_text=self._trunc("QUERY NOT FOUND", constants.DISPLAY_HEADER_MAX_LEN),
            display_bottom_text=self._trunc(
                "Ask about PDS, PMJAY, e-Shram, BOCW", constants.DISPLAY_BODY_MAX_LEN
            ),
            qr_payload=self._qr_payload(intent_code, "FALLBACK", "No match"),
            severity=SeverityLevel.WARNING,
        )
