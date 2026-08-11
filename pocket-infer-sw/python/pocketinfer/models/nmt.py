"""
BHASHINI NMT Model Adapter

REST client for the local BHASHINI Neural Machine Translation engine served
by bhashini_models.service on localhost:11400 (CTranslate2, see
rootfs/roles/indic). Used by NomadRight in two places:

  1. Bracketing the English-language Decision Layer: worker's language -> English
     before Intent/Entity/Rules/RAG, then English -> worker's language for TTS.
  2. The "voice bridge" feature: translating an answer into a destination-state
     official's language (Tamil, Gujarati, Marathi, Kannada) on request.

100% offline at runtime - the only network call this class ever makes is to
localhost.
"""

import logging
from typing import Any, Dict, Tuple

import requests

from pocketinfer.models._bhashini_common import base_url, verify_service, restart_service, DEFAULT_TIMEOUT

logger = logging.getLogger(__name__)

# The on-device NMT engine (~/bhashini_models/nmt/infer.py) only recognizes
# "EN" (uppercase, English) or a lowercase ISO code that is a key in its own
# iso_to_flores map. Several of NomadRight's source languages don't have a
# dedicated NMT model and must be routed through the nearest language that
# engine actually supports (see nmt/inference/flores_codes_map_indic.py,
# where e.g. "bho_Deva"/"mai_Deva"/"hne_Deva" all map to iso "hi", and
# "sat_Olck" maps to iso "or") - passing the raw dialect code straight
# through raises "Unsupported translation direction" on their side.
_NMT_LANG_ROUTE = {
    "bho": "hi", "mai": "hi", "hne": "hi", "awa": "hi", "mag": "hi",
    "sat": "or",
}


def _nmt_lang_code(code: str) -> str:
    """Maps a NomadRight/BHASHINI language code to what the local NMT engine expects."""
    normalized = code.strip().lower()
    if normalized == "en":
        return "EN"
    return _NMT_LANG_ROUTE.get(normalized, normalized)


class Nmt:
    """Wraps the local BHASHINI NMT REST endpoint (POST /nmt)."""

    def __init__(self, timeout: float = DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.logger = logging.getLogger(self.__class__.__name__)

    def infer(self, text: str, src_lang: str, tgt_lang: str) -> Dict[str, str]:
        """
        Translates text from src_lang to tgt_lang using the local BHASHINI NMT engine.

        Args:
            text:     Source text to translate.
            src_lang: Source BHASHINI language code (e.g. "hi", "EN").
            tgt_lang: Target BHASHINI language code (e.g. "EN", "ta").

        Returns:
            {"translated_text": "<translation>"}. Falls back to returning the
            original text untranslated (never raises) on failure, so the
            pipeline degrades gracefully instead of crashing mid-query.
        """
        if not text or not text.strip():
            return {"translated_text": ""}
        try:
            payload = {
                "text": text,
                # NOTE: the service's Flask handler reads data['src_lang'] /
                # data['tgt_lang'] specifically (see ~/bhashini_models/main.py
                # handle_nmt) - it does NOT accept "source_language" /
                # "target_language", which silently sent None on both fields
                # and made every single NMT call 400 regardless of content.
                "src_lang": _nmt_lang_code(src_lang),
                "tgt_lang": _nmt_lang_code(tgt_lang),
            }
            resp = requests.post(f"{base_url()}/nmt", json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            translated = (data.get("translated_text") or "").strip()
            return {"translated_text": translated or text}
        except Exception as exc:
            self.logger.error(
                f"BHASHINI NMT inference failed ({src_lang}->{tgt_lang}): {exc}. "
                "Falling back to untranslated source text."
            )
            return {"translated_text": text}

    @classmethod
    def verify(cls, args: Dict[str, Any]) -> Tuple[bool, str]:
        return verify_service("Nmt")

    @classmethod
    def update(cls, args: Dict[str, Any]) -> bool:
        return restart_service("Nmt")
