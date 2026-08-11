"""
NomadRight BHASHINI Bridge Module

Thin orchestration layer over the low-level BHASHINI REST adapters
(pocketinfer.models.asr / nmt / tts), giving app.py and workflow.py a
small, welfare-domain-shaped API instead of raw infer() calls:

    listen(wav_bytes, lang)                    -> worker's spoken text
    to_pipeline_language(text, src_lang)       -> English text for the Decision Layer
    from_pipeline_language(text, tgt_lang)     -> worker's language, ready for TTS
    speak(text, lang)                          -> raw WAV bytes ready for AudioPlayer
    bridge_translate(text, src_lang, tgt_lang) -> "voice bridge" translation for an official

All calls are local BHASHINI REST calls to localhost:11400 — no cloud
endpoints are ever contacted (PROJECT IDENTITY constraint: zero data leaves
the device).
"""

import logging
import os
import shutil
import subprocess
import tempfile
import wave
from io import BytesIO
from typing import Optional

from pocketinfer.applications.nomad_right import constants
from pocketinfer.applications.nomad_right.config import NomadRightConfig
from pocketinfer.models.asr import Asr
from pocketinfer.models.nmt import Nmt
from pocketinfer.models.tts import Tts

logger = logging.getLogger(__name__)


def _apply_voice_style(wav_bytes: bytes) -> bytes:
    """
    Pitch-shifts and slightly speeds up synthesized speech via ffmpeg, as a
    male-leaning, more energetic approximation - see
    constants.TTS_VOICE_STYLE_ENABLED for why a DSP post-process is used
    instead of a different voice file (none is installed on this device).

    Never raises: on any failure (ffmpeg missing, bad input, timeout) this
    logs a warning and returns the original, unmodified audio so a styling
    problem can never break TTS playback.
    """
    if not wav_bytes or not shutil.which("ffmpeg"):
        return wav_bytes
    in_path = out_path = None
    try:
        # asetrate reinterprets the stream at a new nominal rate to shift
        # pitch - it must be computed from this WAV's ACTUAL sample rate,
        # not a hardcoded guess, or the shift comes out wrong/distorted.
        with wave.open(BytesIO(wav_bytes), "rb") as wf:
            source_rate = wf.getframerate()
        shifted_rate = int(source_rate * constants.TTS_PITCH_FACTOR)
        # Cancel the duration stretch asetrate introduces, then add the extra
        # energy boost on top - see constants.TTS_ENERGY_BOOST.
        tempo = (1.0 / constants.TTS_PITCH_FACTOR) * constants.TTS_ENERGY_BOOST
        filter_chain = (
            f"asetrate={shifted_rate},"
            f"aresample={source_rate},"
            f"atempo={tempo:.4f}"
        )

        # Real files, not pipes: a WAV written to a pipe can't be seeked back
        # to patch in the true RIFF/data chunk sizes once streaming is done,
        # so ffmpeg leaves a placeholder size there instead - Python's wave
        # module then reports a bogus, useless frame count on read. Writing
        # to an actual (seekable) file lets ffmpeg finalize a correct header.
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as in_f:
            in_f.write(wav_bytes)
            in_path = in_f.name
        out_fd, out_path = tempfile.mkstemp(suffix=".wav")
        os.close(out_fd)

        proc = subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y",
             "-i", in_path, "-af", filter_chain, out_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10.0,
        )
        if proc.returncode == 0 and os.path.getsize(out_path) > 0:
            with open(out_path, "rb") as f:
                return f.read()
        logger.warning(
            f"Voice styling (ffmpeg) failed with code {proc.returncode}: "
            f"{proc.stderr.decode(errors='replace')[:200]}. Using original audio."
        )
    except Exception as exc:
        logger.warning(f"Voice styling (ffmpeg) failed: {exc}. Using original audio.")
    finally:
        for p in (in_path, out_path):
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
    return wav_bytes


class BhashiniBridge:
    """
    Welfare-domain-shaped facade over the BHASHINI ASR/NMT/TTS model adapters.

    A single instance is created once per NomadRightApplication and reused
    across the whole session — the underlying Asr/Nmt/Tts adapters are
    stateless REST clients, so nothing about one query can leak into the next.
    """

    def __init__(
        self,
        asr: Optional[Asr] = None,
        nmt: Optional[Nmt] = None,
        tts: Optional[Tts] = None,
        config: Optional[NomadRightConfig] = None,
    ):
        self.asr = asr or Asr()
        self.nmt = nmt or Nmt()
        self.tts = tts or Tts()
        self.config = config or NomadRightConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

    def listen(self, wav_bytes: bytes, lang: str) -> str:
        """Transcribes the worker's recorded speech into text in their own language."""
        result = self.asr.infer(wav_bytes, lang)
        text = result.get("text", "")
        self.logger.info(f"ASR[{lang}] -> '{text}'")
        return text

    def to_pipeline_language(self, text: str, src_lang: str) -> str:
        """Translates worker's-language text to English for the Decision Layer."""
        if not text:
            return ""
        if src_lang.lower() == constants.PIPELINE_LANGUAGE.lower():
            return text
        result = self.nmt.infer(text, src_lang, constants.PIPELINE_LANGUAGE)
        return result.get("translated_text", text)

    def from_pipeline_language(self, text: str, tgt_lang: str) -> str:
        """Translates the English Decision Layer answer back into the worker's language."""
        if not text:
            return ""
        if tgt_lang.lower() == constants.PIPELINE_LANGUAGE.lower():
            return text
        result = self.nmt.infer(text, constants.PIPELINE_LANGUAGE, tgt_lang)
        return result.get("translated_text", text)

    def speak(self, text: str, lang: str) -> bytes:
        """Synthesizes speech audio (raw WAV bytes) for the given text and language."""
        if not text:
            return b""
        result = self.tts.infer(text, lang)
        wav_bytes = Tts.decode(result.get("audio_base64", ""))
        if self.config.voice_style_enabled:
            wav_bytes = _apply_voice_style(wav_bytes)
        return wav_bytes

    def bridge_translate(self, text: str, src_lang: str, tgt_lang: str) -> str:
        """
        "Voice bridge" translation: converts an answer already given to the
        worker into a destination-state official's language (Tamil/Gujarati/
        Marathi/Kannada) for the worker to play back to the official.

        Uses a single direct NMT hop — never routes through English or mixes
        languages within one TTS call (coding convention #6).
        """
        if not text:
            return ""
        if src_lang.lower() == tgt_lang.lower():
            return text
        result = self.nmt.infer(text, src_lang, tgt_lang)
        return result.get("translated_text", text)
