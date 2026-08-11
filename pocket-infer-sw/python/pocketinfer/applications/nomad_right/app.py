"""
NomadRight Application Entry Point

Pipeline: press & hold the trigger button -> record audio -> BHASHINI ASR
(worker's own language) -> BHASHINI NMT (-> English) -> Decision Layer
(Intent / Entity / Rules / RAG) -> BHASHINI NMT (English -> worker's
language) -> BHASHINI TTS -> LCD + speaker.

The worker's source language and the "voice bridge" destination-official
language are both selected from the touchscreen Settings page (see
ui/handheld.py) using the same `ASR <lang>` / `Bridge <lang>` message
convention already established by the HearTheWorld reference application.

100% offline: BHASHINI ASR/NMT/TTS all talk to localhost:11400 only. No
camera, no VLM, no generative LLM anywhere in the answer path.
"""

import os
import time
import wave
import logging
from io import BytesIO
from typing import Optional, Dict, Any

from pocketinfer.applications.base import BaseApplication
from pocketinfer.applications.registry import RegisterApplication
from pocketinfer.audio import AudioPlayer

from pocketinfer.applications.nomad_right import constants
from pocketinfer.applications.nomad_right.config import NomadRightConfig
from pocketinfer.applications.nomad_right.workflow import WorkflowController
from pocketinfer.applications.nomad_right.response import StructuredResponsePackage
from pocketinfer.applications.nomad_right.bhashini_bridge import BhashiniBridge
from pocketinfer.applications.nomad_right.intent import IntentType

logger = logging.getLogger(__name__)


@RegisterApplication({
    "name": "NomadRight",
    "description": "Offline, voice-first, multilingual rights navigator for interstate migrant workers.",
    "author": "STARK-X",
    "version": constants.APP_VERSION,
    "models": {
        "asr": {},
        "nmt": {},
        "tts": {},
    },
    "default_settings": {
        "input_language": constants.DEFAULT_SOURCE_LANGUAGE,
        "bridge_language": constants.DEFAULT_BRIDGE_LANGUAGE,
        "log_directory": constants.DEFAULT_LOG_DIR,
    },
    "service_dependencies": ["bhashini_models"],
})
class NomadRightApplication(BaseApplication):
    """
    NomadRight application wrapper integrated into the Suno Sutra application framework.
    Coordinates hardware inputs (trigger button, microphone), invokes the BHASHINI
    model adapters via BhashiniBridge, and drives display & audio playout through
    the WorkflowController Decision Layer.
    """

    def __init__(self, board: Any, settings: Optional[Dict[str, Any]] = None):
        super().__init__(board, settings)
        # BaseApplication.__init__ sets self.logger to the generic
        # "pocketinfer.applications.base" logger (since that's evaluated in
        # base.py, not here) - override so NomadRight's own log lines are
        # identifiable instead of blending into that shared bucket.
        self.logger = logging.getLogger(__name__)
        self.app_config = NomadRightConfig.from_settings(self.settings)
        # Remembers the last answer so a follow-up "translate this for the
        # officer" request (TRANSLATION_REQUEST intent) has something to bridge.
        self.last_answer_en: str = ""
        # Remembers the scheme discussed in the previous turn (e.g. "PDS")
        # so a generic follow-up like "what documents do I need?" resolves
        # without the worker having to repeat the scheme name - see
        # EntityExtractor._CONTEXT_INHERITABLE_INTENTS.
        self.last_scheme_code: Optional[str] = None

    def start(self) -> None:
        """Application start hook. Instantiates the BHASHINI bridge and pipeline controller."""
        self.bridge = BhashiniBridge(config=self.app_config)
        self.workflow = WorkflowController(config=self.app_config)
        self.board.subscribe_to_ui(self.ui_cb)

        if not os.path.exists(self.app_config.log_dir):
            os.makedirs(self.app_config.log_dir, exist_ok=True)
        super().start()

    # ── Touchscreen Settings page: language selection ──────────────────────

    def ui_cb(self, msg: str) -> None:
        """
        Handles touchscreen Settings page button presses. Reuses the exact
        `ASR <lang>` message convention from hear_the_world.py for the
        worker's spoken language, plus a NomadRight-specific `Bridge <lang>`
        convention for the voice-bridge destination-official language.
        """
        if msg.startswith("ASR "):
            code = self._lang_name_to_code(msg[4:], constants.SOURCE_LANGUAGES)
            if code:
                self.settings["input_language"] = code
                self.logger.info(f"[NomadRight] Worker language set to {code}")
        elif msg.startswith("Bridge "):
            code = self._lang_name_to_code(msg[7:], constants.BRIDGE_LANGUAGES)
            if code:
                self.settings["bridge_language"] = code
                self.logger.info(f"[NomadRight] Voice bridge language set to {code}")

    @staticmethod
    def _lang_name_to_code(name: str, table: Dict[str, str]) -> Optional[str]:
        """Resolves a button label ('Hindi', 'hi') to its BHASHINI language code."""
        name_lower = name.strip().lower()
        for code, display_name in table.items():
            if display_name.lower() == name_lower or code.lower() == name_lower:
                return code
        return None

    # ── Audio playout ───────────────────────────────────────────────────────

    def _play(self, wav_bytes: bytes) -> None:
        """Plays raw WAV bytes (as returned by BhashiniBridge.speak) on the speaker."""
        if not wav_bytes:
            return
        try:
            wave_obj = wave.open(BytesIO(wav_bytes), "rb")
            with AudioPlayer(wave_obj.getframerate(), self.board.alsa_playback_device) as player:
                player.play(wave_obj.readframes(wave_obj.getnframes()))
        except Exception as exc:
            self.logger.error(f"[NomadRight] Audio playback failed: {exc}")

    # ── Main loop ────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Main application thread execution loop blocking on trigger button events."""
        self.board.clear_screen()
        self.board.mode_text("Rights Navigator")
        self.board.top_text("NomadRight")
        self.board.bottom_text("Press & hold button to ask")

        while self.running:
            lang = self.settings.get("input_language", constants.DEFAULT_SOURCE_LANGUAGE)
            bridge_lang = self.settings.get("bridge_language", constants.DEFAULT_BRIDGE_LANGUAGE)
            self.board.statusbar("[READY] Hold button to ask")
            self.board.wait_for_trigger_button_down()

            if not self.running:
                break

            try:
                self.board.button_led(True)
                self.board.statusbar("[LISTENING]")
                self.board.top_text("")
                self.board.bottom_text("")

                # Press & hold triggers the mic - matches the wired capacitive
                # touch button on GPIO09 (see jetson_suno_sutra_expansion_pinout.png).
                self.board.audio.start()
                self.board.wait_for_trigger_button_up()
                self.board.button_led(False)
                self.board.audio.stop()

                # ── 1. ASR: worker's spoken language -> native text ─────────
                self.board.statusbar("Recognizing")
                wav_bytes = self.board.audio.to_audio_data().get_wav_data()
                native_query = self.bridge.listen(wav_bytes, lang)

                if not native_query.strip():
                    self.logger.warning("[NomadRight] ASR returned empty text.")
                    self.board.statusbar("[ERROR]")
                    self.board.top_text("Could not hear you")
                    self.board.bottom_text("Please try again")
                    time.sleep(1.5)
                    continue

                # Keep the worker's own question visible on screen for the
                # rest of this turn (not overwritten by the answer) so both
                # sides of the exchange stay readable at a glance.
                self.board.top_text(f"You: {native_query}"[:80])
                self.logger.info(f"[NomadRight] ASR[{lang}] query: '{native_query}'")

                # ── 2. NMT: native language -> English for the Decision Layer ─
                self.board.statusbar("[TRANSLATING]")
                query_en = self.bridge.to_pipeline_language(native_query, lang)

                # ── 3. Voice bridge short-circuit ────────────────────────────
                # If the worker is asking to translate the last answer for a
                # destination-state official, skip the Decision Layer entirely.
                intent_res = self.workflow.intent_recognizer.recognize(query_en)
                if intent_res.intent_type == IntentType.TRANSLATION_REQUEST and self.last_answer_en:
                    entities = self.workflow.entity_extractor.extract(query_en, intent_res)
                    target_lang = entities.language_code or bridge_lang
                    if target_lang not in constants.BRIDGE_LANGUAGES:
                        target_lang = bridge_lang
                    target_name = constants.BRIDGE_LANGUAGES.get(target_lang, target_lang)

                    self.board.statusbar(f"[TRANSLATING] for official ({target_name})")
                    bridged_text = self.bridge.bridge_translate(self.last_answer_en, "EN", target_lang)

                    self.board.top_text("VOICE BRIDGE")
                    self.board.bottom_text(bridged_text[:100])
                    self.board.statusbar("[SPEAKING]")
                    self._play(self.bridge.speak(bridged_text, target_lang))
                    self.board.statusbar("[READY] Hold button to ask")
                    continue

                # ── 4. Decision Layer: Intent -> Entity -> Rules/RAG -> Response ─
                self.board.statusbar("[THINKING]")
                response_pkg: StructuredResponsePackage = self.workflow.process(
                    query_en, context_scheme_code=self.last_scheme_code
                )
                self.last_answer_en = response_pkg.voice_text
                # Only update on an actual scheme match this turn - keep the
                # previous scheme remembered across a genuinely unrelated/
                # unmatched follow-up rather than losing it (see
                # EntityExtractor._CONTEXT_INHERITABLE_INTENTS).
                if response_pkg.scheme_code:
                    self.last_scheme_code = response_pkg.scheme_code

                # ── 5. NMT: English answer -> worker's own language ─────────
                self.board.statusbar("[TRANSLATING]")
                answer_native = self.bridge.from_pipeline_language(response_pkg.voice_text, lang)

                # ── 6. Display + Speak — conversation view ────────────────────
                # top_text keeps showing "You: <question>" from step 1 above
                # (deliberately not overwritten here) so the worker's own
                # question and the answer are both visible together, instead
                # of the answer replacing the question the moment it arrives.
                answer_line = f"{response_pkg.display_top_text}: {response_pkg.display_bottom_text}"
                bottom_hint = f"{answer_line}  |  Say 'translate' for the officer"
                self.board.bottom_text(bottom_hint[:180])

                self.board.statusbar(f"[SPEAKING] {response_pkg.display_top_text}")
                self._play(self.bridge.speak(answer_native, lang))

                self.board.statusbar("[READY] Hold button to ask")

            except Exception as exc:
                self.logger.error(f"[NomadRight] Error in application processing loop: {exc}", exc_info=True)
                self.board.button_led(False)
                self.board.statusbar("[ERROR]")
                self.board.top_text("SYSTEM ERROR")
                self.board.bottom_text("Please try again")
                time.sleep(2.0)

    def stop(self) -> None:
        """Application shutdown hook."""
        super().stop()
