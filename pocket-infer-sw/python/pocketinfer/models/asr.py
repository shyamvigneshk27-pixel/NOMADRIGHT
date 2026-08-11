"""
BHASHINI ASR Model Adapter

REST client for the local BHASHINI Automatic Speech Recognition engine served
by bhashini_models.service on localhost:11400 (see rootfs/roles/indic). Used
by NomadRight to transcribe migrant workers' spoken queries in their own
language (Hindi, Tamil, Odia, Bhojpuri, Maithili, Santali, Chhattisgarhi).

100% offline at runtime: the only network call this class ever makes is to
localhost, and it never attempts to download model weights.
"""

import base64
import logging
from typing import Any, Dict, Tuple

import requests

from pocketinfer.models._bhashini_common import base_url, verify_service, restart_service, DEFAULT_TIMEOUT

logger = logging.getLogger(__name__)


class Asr:
    """Wraps the local BHASHINI ASR REST endpoint (POST /asr)."""

    def __init__(self, timeout: float = DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.logger = logging.getLogger(self.__class__.__name__)

    def infer(self, wav_bytes: bytes, lang: str) -> Dict[str, str]:
        """
        Transcribes WAV audio bytes to text using the local BHASHINI ASR engine.

        Args:
            wav_bytes: Raw WAV file bytes (mono, 16-bit PCM).
            lang: BHASHINI source language code, e.g. "hi", "ta", "or", "bho",
                  "mai", "sat", "hne".

        Returns:
            {"text": "<transcribed text>"}. Returns empty text (never raises)
            on any network or service failure so the caller can show a
            friendly "please try again" error instead of crashing.
        """
        try:
            payload = {
                "audio_base64": base64.b64encode(wav_bytes).decode("ascii"),
                "language": lang.lower(),
            }
            resp = requests.post(f"{base_url()}/asr", json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return {"text": (data.get("text") or "").strip()}
        except Exception as exc:
            self.logger.error(f"BHASHINI ASR inference failed (lang={lang}): {exc}")
            return {"text": ""}

    @classmethod
    def verify(cls, args: Dict[str, Any]) -> Tuple[bool, str]:
        return verify_service("Asr")

    @classmethod
    def update(cls, args: Dict[str, Any]) -> bool:
        return restart_service("Asr")
