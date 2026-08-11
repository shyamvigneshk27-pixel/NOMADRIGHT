"""
BHASHINI TTS Model Adapter

REST client for the local BHASHINI Text-to-Speech engine (Flite-based, see
rootfs/roles/indic) served by bhashini_models.service on localhost:11400.
Used by NomadRight to speak answers back to the worker in their own language,
and to speak "voice bridge" translations in a destination-state official's
language.

100% offline at runtime - the only network call this class ever makes is to
localhost.
"""

import base64
import logging
from typing import Any, Dict, Tuple

import requests

from pocketinfer.models._bhashini_common import base_url, verify_service, restart_service, DEFAULT_TIMEOUT

logger = logging.getLogger(__name__)

# The on-device TTS engine (~/bhashini_models/tts/infer.py LANG_VOICE_MAP)
# keys Kannada as "ka", not the ISO-639-1 code "kn" used everywhere else in
# NomadRight (constants.BRIDGE_LANGUAGES, BHASHINI NMT, etc.) - translate at
# the wrapper boundary rather than letting the mismatch reach the service.
_TTS_LANG_ROUTE = {"kn": "ka"}


def _tts_lang_code(code: str) -> str:
    normalized = code.strip().lower()
    return _TTS_LANG_ROUTE.get(normalized, normalized)


class Tts:
    """Wraps the local BHASHINI TTS REST endpoint (POST /tts)."""

    def __init__(self, timeout: float = DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.logger = logging.getLogger(self.__class__.__name__)

    def infer(self, text: str, lang: str) -> Dict[str, str]:
        """
        Synthesizes speech audio for the given text using the local BHASHINI TTS engine.

        Args:
            text: Text to synthesize (should already be <60 words - see
                  ResponseGenerator - for a comfortable listening experience).
            lang: BHASHINI target language code, e.g. "hi", "ta", "or", "gu", "mr", "kn".

        Returns:
            {"audio_base64": "<base64-encoded WAV bytes>"}. Returns an empty
            string (never raises) on failure so the caller can fall back to
            an on-screen-only error state instead of crashing.
        """
        try:
            payload = {"text": text, "language": _tts_lang_code(lang)}
            resp = requests.post(f"{base_url()}/tts", json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return {"audio_base64": data.get("audio_base64", "")}
        except Exception as exc:
            self.logger.error(f"BHASHINI TTS inference failed (lang={lang}): {exc}")
            return {"audio_base64": ""}

    @staticmethod
    def decode(audio_base64: str) -> bytes:
        """Decodes a base64 audio payload from infer() into raw WAV bytes."""
        if not audio_base64:
            return b""
        return base64.b64decode(audio_base64)

    @classmethod
    def verify(cls, args: Dict[str, Any]) -> Tuple[bool, str]:
        return verify_service("Tts")

    @classmethod
    def update(cls, args: Dict[str, Any]) -> bool:
        return restart_service("Tts")
