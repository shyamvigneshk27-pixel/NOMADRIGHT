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

100% offline: BHASHINI ASR/NMT/TTS all talk to localhost:11400 only.
qwen2.5vl:3b (via Ollama, localhost:11434) is the only generative model in
the loop, and only in two narrow, explicitly-gated cases: a grounded text
fallback when intent/RAG matching finds nothing (see workflow.py Step 6.5),
and the Camera-button form-reading flow below - never as the primary answer
path. See qwen_client.py for the grounding/sentinel guarantees.
"""

import os
import time
import wave
import logging
import threading
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
        "ollama": {"model_name": constants.LLM_FALLBACK_MODEL},
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

    # Shared Home/ready-screen hint, kept short and reused everywhere it's
    # shown (run()'s idle screen, _on_home_pressed()'s two branches) so
    # there's exactly one string to keep within the display's safe line
    # length rather than several independently-drifting copies.
    HOME_HINT = "Hold: Voice Q&A  |  Camera: Scan Document"

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
        # Set when the worker presses the touchscreen Camera button (see
        # ui_cb below). The *next* voice query is answered against this
        # photo via workflow.process_vision_query() instead of the normal
        # Decision Layer, then cleared (one photo -> one follow-up question;
        # asking a second question about the same form means pressing
        # Camera again). Cleared without use if constants.LLM_VISION_PENDING_TTL_S
        # elapses first, so a stale photo can't attach to an unrelated
        # later question.
        self.pending_form_image: Optional[bytes] = None
        self.pending_form_image_ts: float = 0.0
        self._image_lock = threading.Lock()
        # Set for the duration of _on_camera_pressed() (which runs on the UI
        # callback thread, concurrently with the main run() loop below
        # blocking on wait_for_trigger_button_down()). Without this, a
        # worker who presses the trigger button again fast enough - before
        # the capture finishes and "Photo captured" is shown - could have
        # their follow-up question race ahead of pending_form_image being
        # set, and get answered as a normal voice query instead of a vision
        # one. run() waits on this before it starts listening, so the mic
        # is never armed until the capture is actually confirmed on screen.
        self._camera_busy = threading.Event()

        # ── Mode / navigation state (Home <-> Voice Translation <-> ────────
        # Document Scanner) - see module docstring's "UI modes" section.
        # Display-only label reflecting what the LCD's mode_text should
        # currently read; not a hard state machine gate - the real branch
        # logic still runs entirely on pending_form_image, exactly as
        # before. "HOME" is the idle/ready screen (both options available);
        # it switches to "VOICE TRANSLATION" or "DOCUMENT SCANNER" only for
        # the duration of one active turn, then reverts to "HOME".
        self._mode: str = "HOME"

        # Cancellable audio playback (Home button, see _on_home_pressed/
        # _stop_audio): the AudioPlayer currently on-air, if any. Written
        # by the main thread (_play()) and read/killed by the UI callback
        # thread, so access is lock-guarded even though CPython's GIL would
        # likely make the bare reference swap safe anyway - explicit is
        # cheap here and matches the existing _image_lock pattern.
        self._current_player = None
        self._player_lock = threading.Lock()
        # Set by _stop_audio() right before killing the player, cleared at
        # the start of every _play() call - lets _play() tell its caller
        # apart a user-initiated stop from a normal finish or a genuine
        # playback error (see _play()'s return value).
        self._audio_stop_requested = threading.Event()
        # Set by _on_home_pressed() (UI callback thread); polled by run()
        # (main thread) at safe checkpoints - never mid-inference, since a
        # live Qwen/RAG HTTP call can't be safely aborted once sent (see
        # module docstring) - to drop back to the Home/ready screen instead
        # of speaking out an answer the worker already tried to back out of.
        self._home_requested = threading.Event()

        # A "screen update" (mode_text + top_text + bottom_text + statusbar
        # together, describing one coherent state) is 2-4 separate RPC
        # calls to the UI subprocess (see ui/handheld.py's RemoteUI -
        # each individual call is lock-serialized there, but a *sequence*
        # of them is not atomic). run() (main thread) and
        # _on_camera_pressed()/_on_home_pressed() (UI callback thread, see
        # jetson.py's _process_ui_events) can call these concurrently -
        # without this lock, a Camera/Home press landing mid-transition can
        # interleave with the main loop's own update, leaving one field
        # from the old state and another from the new one on screen at
        # once - the intermittent "overlay" glitch this was added to fix.
        self._screen_lock = threading.Lock()

    # ── On-screen pipeline log ─────────────────────────────────────────────

    def _log(self, msg: str) -> None:
        """
        Emit one line to BOTH the Python logger and the LCD's pipeline-log
        page (topbar terminal icon, see ui/handheld.py).

        This is what makes the kiosk usable with no terminal attached: every
        stage boundary that previously only existed in the console scrollback
        is now readable on the device itself, including whether the trigger
        button actually registered and how long each stage took.

        Lines are forced to ASCII because the log page renders in
        terminalio.FONT, which has no Devanagari glyphs - a native-script
        character would draw as nothing while still consuming a column. Log
        *facts about* native text (its length, its language) here; the text
        itself belongs on the main screen, which uses a font that can render
        it.
        """
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        line = line.encode("ascii", "replace").decode("ascii")
        self.logger.info("[NomadRight] %s", msg)
        try:
            self.board.log_line(line)
        except Exception:
            # Diagnostics must never be able to break a real turn - a failed
            # log push is strictly less important than the answer in flight.
            self.logger.debug("[NomadRight] on-screen log push failed", exc_info=True)

    def _sync_language_buttons(self) -> None:
        """
        Make the Settings page's highlighted language match the language the
        pipeline is actually configured to use.

        The page's constructor default highlights 'ASR En' (correct for
        HearTheWorld, whose default input_language really is "en"), but
        NomadRight's SOURCE_LANGUAGES has no English entry at all - so on
        this app the screen claimed English while every turn ran in Hindi,
        and pressing that highlighted button did nothing whatsoever, because
        _lang_name_to_code('En', SOURCE_LANGUAGES) returns None and the
        setting is left untouched. Declaring the truth here fixes both the
        wrong highlight and the "that button is dead" symptom.
        """
        lang = self.settings.get("input_language", constants.DEFAULT_SOURCE_LANGUAGE)
        bridge_lang = self.settings.get("bridge_language", constants.DEFAULT_BRIDGE_LANGUAGE)
        try:
            # Button labels are the language code title-cased ('hi' ->
            # 'ASR Hi', 'bho' -> 'ASR Bho'), matching ui/handheld.py.
            self.board.select_radio("ASR ", f"ASR {lang.capitalize()}")
            self.board.select_radio("Bridge ", f"Bridge {bridge_lang.capitalize()}")
        except Exception:
            self.logger.debug("[NomadRight] language button sync failed", exc_info=True)

    def _startup_selfcheck(self) -> None:
        """
        Probe every subsystem a turn depends on and report each on the LCD
        log, so "is this thing ready?" is answerable by looking at the
        device instead of by pressing the button and waiting to see.

        Deliberately synchronous (before the ready screen appears) and
        tightly timed out: reaching "[READY]" should mean the checks
        actually passed, not that they haven't run yet. Nothing here can
        abort startup - a subsystem reported DOWN still surfaces its real
        error later through the existing per-turn error handling, exactly as
        it did before this existed.
        """
        import requests

        degraded = []

        def _probe(name: str, url: str) -> None:
            try:
                resp = requests.get(url, timeout=1.5)
                if resp.status_code == 200:
                    self._log(f"{name:<9} OK")
                    return
                self._log(f"{name:<9} DOWN (HTTP {resp.status_code})")
            except Exception:
                self._log(f"{name:<9} DOWN (no response)")
            degraded.append(name)

        _probe("BHASHINI", f"http://{self.app_config.bhashini_host}:"
                           f"{self.app_config.bhashini_port}/health")
        _probe("OLLAMA", "http://localhost:11434/api/tags")

        mic = getattr(self.board, "alsa_capture_card", None)
        spk = getattr(self.board, "alsa_playback_card", None)
        self._log(f"MIC       {'card ' + str(mic) if mic is not None else 'NOT FOUND'}")
        self._log(f"SPEAKER   {'card ' + str(spk) if spk is not None else 'NOT FOUND'}")
        if mic is None:
            degraded.append("MIC")
        if spk is None:
            degraded.append("SPEAKER")

        try:
            schemes = len(constants.SUPPORTED_SCHEME_CODES)
            self._log(f"KB        {schemes} schemes  lang={self.settings.get('input_language')}")
        except Exception:
            self._log("KB        unavailable")

        if degraded:
            self._log(f"WARNING: degraded -> {','.join(degraded)}")
        else:
            self._log("All subsystems OK")

    def start(self) -> None:
        """Application start hook. Instantiates the BHASHINI bridge and pipeline controller."""
        self._log(f"NomadRight v{constants.APP_VERSION} starting")

        load_start = time.time()
        self.bridge = BhashiniBridge(config=self.app_config)
        self.workflow = WorkflowController(config=self.app_config)
        self._log(f"Pipeline loaded  {time.time() - load_start:.1f}s")

        self.board.subscribe_to_ui(self.ui_cb)

        if not os.path.exists(self.app_config.log_dir):
            os.makedirs(self.app_config.log_dir, exist_ok=True)

        self._sync_language_buttons()
        self._startup_selfcheck()

        # Pre-warm the camera (device open + first-frame negotiation) at
        # startup rather than leaving it lazy until the worker's first
        # Camera press - CameraReader (boards/base.py) keeps streaming in
        # the background once started, so only the *first* call ever pays
        # this cost; every capture after it is already fast. Measured
        # on-device: ~1.8s for that first open+negotiate. Backgrounded so
        # a slow/unavailable camera can never delay reaching the ready
        # screen, and any failure here is silently swallowed - a real
        # failure surfaces normally (with its own error screen) the first
        # time the worker actually presses Camera, exactly as before this
        # existed; this is purely a latency head start, not new error
        # handling.
        threading.Thread(target=self._prewarm_camera, daemon=True).start()

        super().start()

    def _prewarm_camera(self) -> None:
        try:
            warm_start = time.time()
            frame = self.board.camera_frame_jpg()
            if frame:
                self._log(f"CAMERA    OK  {time.time() - warm_start:.1f}s")
            else:
                self._log("CAMERA    NO FRAME")
        except Exception as exc:
            self._log("CAMERA    UNAVAILABLE")
            self.logger.debug(f"[NomadRight] Camera pre-warm skipped: {exc}")

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
        elif msg == "Camera":
            self._on_camera_pressed()
        elif msg == "Home":
            self._on_home_pressed()

    def _on_camera_pressed(self) -> None:
        """
        Touchscreen Camera button handler: captures a form photo via the
        board's existing camera_frame_jpg() (boards/base.py - USB webcam,
        currently a SunplusIT "ABWB1002 PC WebCam", see boards/jetson.py's
        V4L_CAMERA_NAME comment for the hardware history/probing fallback;
        no new camera-driver code needed here) and puts the app into
        "waiting for your query" state -
        this IS the Document Scanner mode's entry point (see module
        docstring). Runs on the UI subprocess's callback thread, not the
        main run() loop thread - board.top_text/bottom_text/statusbar calls
        are thread-safe (see ui/handheld.py's RemoteUI rpc_lock).

        Single-frame only, deliberately: neither camera_frame_jpg() nor
        qwen_client.answer_vision() support multiple images per call, and
        this device's memory budget doesn't comfortably support buffering
        several full-resolution frames - see the multi-frame note in the
        final report for why this was scoped out rather than half-built.
        """
        # Any audio still playing from a *previous* turn must not keep
        # talking over a fresh scan - matches Home's own "stop audio first"
        # behavior for the same reason (see _on_home_pressed).
        self._stop_audio()
        self._camera_busy.set()
        try:
            with self._screen_lock:
                self.board.mode_text("DOCUMENT SCANNER")
                self.board.top_text("Capturing...")
                self.board.bottom_text("Hold camera steady")
                self.board.statusbar("[CAPTURING]")
            self._log("CAMERA pressed - capturing")
            capture_start = time.time()
            try:
                image_jpg = self.board.camera_frame_jpg()
            except Exception as exc:
                self.logger.error(f"[NomadRight] Camera capture failed: {exc}")
                self._log(f"CAMERA FAILED: {exc}"[:52])
                with self._screen_lock:
                    self.board.top_text("CAMERA ERROR")
                    self.board.bottom_text("Capture failed. Camera=retry, Home=cancel")
                    self.board.statusbar("[ERROR] Camera unavailable")
                self._mode = "HOME"
                return
            if not image_jpg:
                self.logger.warning("[NomadRight] Camera returned no frame.")
                self._log("CAMERA returned no frame")
                with self._screen_lock:
                    self.board.top_text("CAMERA ERROR")
                    self.board.bottom_text("No frame captured. Camera=retry, Home=cancel")
                    self.board.statusbar("[ERROR] Camera unavailable")
                self._mode = "HOME"
                return

            with self._image_lock:
                self.pending_form_image = bytes(image_jpg)
                self.pending_form_image_ts = time.time()
            self.logger.info(
                f"[NomadRight] Photo captured ({len(image_jpg)} bytes JPEG), "
                f"awaiting follow-up query."
            )
            self._log(
                f"PHOTO CAPTURED {len(image_jpg) // 1024} KB  "
                f"{time.time() - capture_start:.1f}s"
            )
            self._mode = "DOCUMENT SCANNER"
            # No checkmark/symbol here on purpose: the LCD's bitmap font
            # (NotoSansDevanagari-Regular-12.pcf) doesn't include a glyph
            # for U+2713 (checkmark) - confirmed via get_glyph() returning
            # None - an earlier version of this used one and it silently
            # contributed 0 width to the text-wrap calculation while still
            # occupying a character slot, which is the kind of thing that
            # can desync wrapping from what's actually drawn. Plain ASCII
            # only, matching every other screen in this app.
            with self._screen_lock:
                self.board.top_text("PHOTO CAPTURED")
                self.board.bottom_text("Hold button to ask, or Home to cancel")
                self.board.statusbar("[WAITING FOR QUERY] Ask about the photo")
        finally:
            # Cleared last, after pending_form_image and the "Photo
            # captured" screen text are both fully in place (or on any
            # early-return error path above) - run() only starts listening
            # once this clears.
            self._camera_busy.clear()

    def _on_home_pressed(self) -> None:
        """
        Touchscreen Home button handler - the app's single, always-
        available cancel/back/stop control (see module docstring's UI
        modes section). Runs on the UI callback thread, concurrently with
        whatever the main run() loop is doing. Two jobs, in priority order:

          1. If audio is currently playing, stop it immediately (see
             _stop_audio()) - the most likely reason a worker presses Home
             mid-turn is not wanting to hear the rest of an answer.
          2. Either way, clear any pending document-scanner photo and
             request a return to the Home/ready screen - run() checks
             self._home_requested at safe checkpoints (never mid-inference;
             a live Qwen/RAG call can't be safely aborted once sent) and
             drops back to Home there instead of speaking a stale answer.
        """
        stopped_audio = self._stop_audio()
        self._home_requested.set()
        with self._image_lock:
            had_pending_photo = self.pending_form_image is not None
            self.pending_form_image = None
        self._mode = "HOME"
        if stopped_audio:
            self.logger.info("[NomadRight] Home pressed - audio playback stopped.")
            with self._screen_lock:
                self.board.top_text("AUDIO STOPPED")
                self.board.bottom_text(self.HOME_HINT)
                self.board.statusbar("[READY]")
        elif had_pending_photo:
            self.logger.info("[NomadRight] Home pressed - Document Scanner cancelled.")
            with self._screen_lock:
                self.board.top_text("CANCELLED")
                self.board.bottom_text(self.HOME_HINT)
                self.board.statusbar("[READY]")
        else:
            self.logger.info("[NomadRight] Home pressed - already at Home.")

    def _stop_audio(self) -> bool:
        """
        Immediately stops any in-progress speaker playback by killing the
        underlying ffplay subprocess (see audio.py's AudioPlayer.stop()).
        Safe to call from any thread, and safe to call when nothing is
        playing (no-op, returns False). Used by both _on_home_pressed()
        (Home button) and _on_camera_pressed() (a fresh scan shouldn't
        have the previous turn's answer still talking over it).
        """
        with self._player_lock:
            player = self._current_player
        if player is None:
            return False
        self._audio_stop_requested.set()
        player.stop()
        return True

    @staticmethod
    def _lang_name_to_code(name: str, table: Dict[str, str]) -> Optional[str]:
        """Resolves a button label ('Hindi', 'hi') to its BHASHINI language code."""
        name_lower = name.strip().lower()
        for code, display_name in table.items():
            if display_name.lower() == name_lower or code.lower() == name_lower:
                return code
        return None

    # ── Audio playout ───────────────────────────────────────────────────────

    def _play(self, wav_bytes: bytes) -> bool:
        """
        Plays raw WAV bytes (as returned by BhashiniBridge.speak) on the
        speaker. Cancellable: _stop_audio() (Home button, see ui_cb) can
        interrupt playback mid-clip from another thread by killing the
        underlying ffplay subprocess - sound stops right away, and
        AudioPlayer.__exit__'s own wait() returns immediately once the
        process is gone, so this never hangs.

        Returns True if playback completed normally, False if it was
        stopped by the user or failed outright - run() uses this to avoid
        overwriting the "AUDIO STOPPED" screen _on_home_pressed() already
        showed with a normal "[READY]" message.
        """
        if not wav_bytes:
            return True
        self._audio_stop_requested.clear()
        try:
            wave_obj = wave.open(BytesIO(wav_bytes), "rb")
            with AudioPlayer(wave_obj.getframerate(), self.board.alsa_playback_device) as player:
                with self._player_lock:
                    self._current_player = player
                player.play(wave_obj.readframes(wave_obj.getnframes()))
            return not self._audio_stop_requested.is_set()
        except Exception as exc:
            self.logger.error(f"[NomadRight] Audio playback failed: {exc}")
            return False
        finally:
            with self._player_lock:
                self._current_player = None

    # ── Main loop ────────────────────────────────────────────────────────────

    def run(self) -> None:
        """
        Main application thread execution loop blocking on trigger button
        events.

        UI modes (see also __init__'s mode/navigation state and ui_cb):
          HOME               - idle/ready screen; both actions available:
                                hold the trigger button for Voice
                                Translation, or press the Camera icon for
                                Document Scanner. This is the state at the
                                top of every loop iteration unless a photo
                                is still pending an answer.
          VOICE TRANSLATION  - one voice-query turn, exactly the original
                                pipeline (unchanged - see module docstring).
          DOCUMENT SCANNER   - a photo is pending (or was just answered),
                                entered via the Camera icon (_on_camera_pressed).
        The Home icon (_on_home_pressed) is the single always-available
        cancel/back/stop-audio control for both modes.
        """
        self.board.clear_screen()
        with self._screen_lock:
            self.board.mode_text("HOME")
            self.board.top_text("NomadRight")
            self.board.bottom_text(self.HOME_HINT)
        # The one line that answers "is it ready for me to press the
        # button?" without a terminal attached. Logged once here rather than
        # per loop iteration - every turn already ends with its own ANSWER
        # line, so repeating this each time would only push real history off
        # the top of the page.
        self._log("READY - hold button to speak")

        while self.running:
            lang = self.settings.get("input_language", constants.DEFAULT_SOURCE_LANGUAGE)
            bridge_lang = self.settings.get("bridge_language", constants.DEFAULT_BRIDGE_LANGUAGE)
            self._home_requested.clear()

            with self._image_lock:
                scanner_pending = self.pending_form_image is not None
            if scanner_pending:
                # A photo is still waiting on its follow-up question -
                # Home hasn't cancelled it, so stay visibly in Document
                # Scanner mode rather than reverting to the generic Home
                # screen (_on_camera_pressed already set this text; this
                # just keeps it correct if we looped back here via an
                # ASR-empty retry - see step 1 below).
                self._mode = "DOCUMENT SCANNER"
                self.board.statusbar("[WAITING FOR QUERY] Ask about the photo")
            else:
                self._mode = "HOME"
                lang_name = constants.SOURCE_LANGUAGES.get(lang, lang.upper())
                with self._screen_lock:
                    self.board.mode_text("HOME")
                    self.board.statusbar(f"[READY] Lang:{lang_name}  Hold=ask")

            self.board.wait_for_trigger_button_down()

            if not self.running:
                break

            # A Camera-button capture may still be in flight on the UI
            # callback thread (see _on_camera_pressed) - don't start
            # listening until "Photo captured" is actually confirmed on
            # screen, so a follow-up question asked too quickly can never
            # race ahead of its own photo and get answered as a normal
            # voice query instead of a vision one.
            if self._camera_busy.is_set():
                self.board.statusbar("[WAIT] Capturing photo...")
                self._camera_busy.wait(timeout=5.0)

            try:
                self.board.button_led(True)
                with self._screen_lock:
                    self.board.statusbar("[LISTENING]")
                    self.board.top_text("")
                    self.board.bottom_text("")
                # Logged before audio.start() rather than after, so the log
                # confirms the press registered even if opening the capture
                # device is what goes wrong.
                self._log("BTN DOWN - listening")

                # Press & hold triggers the mic - matches the wired capacitive
                # touch button on GPIO09 (see jetson_suno_sutra_expansion_pinout.png).
                record_start = time.time()
                self.board.audio.start()
                self.board.wait_for_trigger_button_up()
                self.board.button_led(False)
                self.board.audio.stop()
                record_s = time.time() - record_start
                # Everything after the button is released counts against the
                # end-to-end budget - the worker's own hold time doesn't.
                turn_start = time.time()
                self._log(f"BTN UP - recorded {record_s:.1f}s")

                # ── 1. ASR: worker's spoken language -> native text ─────────
                self.board.statusbar("[PROCESSING] Recognizing speech")
                stage_start = time.time()
                wav_bytes = self.board.audio.to_audio_data().get_wav_data()
                native_query = self.bridge.listen(wav_bytes, lang)
                self._log(f"ASR {lang} {len(native_query)} chars  {time.time() - stage_start:.1f}s")

                if not native_query.strip():
                    self.logger.warning("[NomadRight] ASR returned empty text.")
                    self._log("ASR empty - ask again")
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
                stage_start = time.time()
                query_en = self.bridge.to_pipeline_language(native_query, lang)
                self._log(f"NMT {lang}->EN  {time.time() - stage_start:.1f}s")

                # ── 3. Camera follow-up short-circuit ────────────────────────
                # A pending form photo (Camera button, see ui_cb/_on_camera_pressed)
                # claims this turn's query before anything else - the worker
                # was explicitly told "waiting for your query...." after
                # snapping the photo. A stale photo past the TTL is dropped
                # silently and this turn falls through to the normal flow.
                image_for_this_turn: Optional[bytes] = None
                with self._image_lock:
                    if self.pending_form_image is not None:
                        if time.time() - self.pending_form_image_ts <= constants.LLM_VISION_PENDING_TTL_S:
                            image_for_this_turn = self.pending_form_image
                        else:
                            self.logger.info("[NomadRight] Pending form photo expired, discarding.")
                        self.pending_form_image = None

                if image_for_this_turn is not None:
                    self.logger.info("[PIPELINE] CAMERA_FORM")
                    self.logger.info("[CAMERA] Image captured")
                    self.logger.info(f"[ASR] lang={lang} text='{native_query}'")
                    self.logger.info(f"[LANGUAGE] input={lang}")
                    self.logger.info(f"[TRANSLATION] EN: '{query_en}'")
                    self.logger.info("[QWEN_VISION] RAG NOT called - image + question sent directly to Qwen")
                    self.board.statusbar("[ANALYZING PHOTO] This may take a moment")
                    self._log("QWEN-VL analyzing photo...")
                    stage_start = time.time()
                    response_pkg: StructuredResponsePackage = self.workflow.process_vision_query(
                        query_en, image_for_this_turn, context_scheme_code=self.last_scheme_code
                    )
                    self._log(f"QWEN-VL done  {time.time() - stage_start:.1f}s")
                    self.last_answer_en = response_pkg.voice_text
                    if response_pkg.scheme_code:
                        self.last_scheme_code = response_pkg.scheme_code

                else:
                    # ── 3b. Voice bridge short-circuit ────────────────────────
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

                        with self._screen_lock:
                            self.board.top_text("VOICE BRIDGE")
                            self.board.bottom_text(bridged_text[:100])
                            self.board.statusbar("[SPEAKING] Home=stop")
                        played_fully = self._play(self.bridge.speak(bridged_text, target_lang))
                        if played_fully:
                            with self._screen_lock:
                                self.board.statusbar("[READY]")
                                self.board.mode_text("HOME")
                        # else: _on_home_pressed() already set the
                        # "AUDIO STOPPED" screen - don't overwrite it here.
                        continue

                    # ── 4. Decision Layer: Intent -> Entity -> Rules/RAG -> Response ─
                    self.logger.info("[PIPELINE] VOICE_SCHEME")
                    self.logger.info(f"[ASR] lang={lang} text='{native_query}'")
                    self.logger.info(f"[LANGUAGE] input={lang}")
                    self.logger.info(f"[TRANSLATION] EN: '{query_en}'")
                    self.board.mode_text("VOICE TRANSLATION")
                    self.board.statusbar("[PROCESSING] Finding your answer")
                    stage_start = time.time()
                    response_pkg = self.workflow.process(
                        query_en, context_scheme_code=self.last_scheme_code
                    )
                    self._log(
                        f"DECIDE {response_pkg.scheme_code or 'no-match'}  "
                        f"{time.time() - stage_start:.1f}s"
                    )
                    self.last_answer_en = response_pkg.voice_text
                    # Only update on an actual scheme match this turn - keep the
                    # previous scheme remembered across a genuinely unrelated/
                    # unmatched follow-up rather than losing it (see
                    # EntityExtractor._CONTEXT_INHERITABLE_INTENTS).
                    if response_pkg.scheme_code:
                        self.last_scheme_code = response_pkg.scheme_code

                # Home was pressed while the Qwen/RAG call above was in
                # flight - it can't be safely aborted mid-request (see
                # module docstring), but we can at least not speak an
                # answer the worker already tried to back out of, and not
                # clobber the "CANCELLED"/"AUDIO STOPPED" screen
                # _on_home_pressed() already put up.
                if self._home_requested.is_set():
                    self.logger.info("[NomadRight] Home was pressed during processing - discarding this turn's answer.")
                    self._log("HOME pressed - turn discarded")
                    continue

                # ── 5. NMT: English answer -> worker's own language ─────────
                self.board.statusbar("[TRANSLATING]")
                stage_start = time.time()
                answer_native = self.bridge.from_pipeline_language(response_pkg.voice_text, lang)
                self._log(f"NMT EN->{lang}  {time.time() - stage_start:.1f}s")
                self.logger.info(f"[TRANSLATION_OUTPUT] {lang}: '{answer_native}'")

                # ── 6. Display + Speak — conversation view ────────────────────
                # top_text keeps showing "You: <question>" from step 1 above
                # (deliberately not overwritten here) so the worker's own
                # question and the answer are both visible together, instead
                # of the answer replacing the question the moment it arrives.
                answer_line = f"{response_pkg.display_top_text}: {response_pkg.display_bottom_text}"
                bottom_hint = f"{answer_line}  |  Say 'translate' for the officer"
                with self._screen_lock:
                    self.board.bottom_text(bottom_hint[:180])
                    self.board.statusbar(f"[SPEAKING] {response_pkg.display_top_text} Home=stop")
                self.logger.info("[TTS] Synthesizing and playing speaker output")
                stage_start = time.time()
                tts_wav = self.bridge.speak(answer_native, lang)
                # Logged before playback, so the end-to-end number below
                # measures time-to-first-sound (what the worker actually
                # waits for) rather than including however long the answer
                # takes to read out loud.
                self._log(f"TTS {lang}  {time.time() - stage_start:.1f}s")
                self._log(f"ANSWER after {time.time() - turn_start:.1f}s - speaking")
                played_fully = self._play(tts_wav)

                if played_fully:
                    with self._screen_lock:
                        self.board.statusbar("[READY] Hold=ask  Camera=scan  Home=menu")
                        self.board.mode_text("HOME")
                # else: _on_home_pressed() already put up the "AUDIO
                # STOPPED" screen - don't overwrite it here. The answer
                # text on bottom_text stays visible either way.

            except Exception as exc:
                self.logger.error(f"[NomadRight] Error in application processing loop: {exc}", exc_info=True)
                # Put the failure on the LCD log too - the whole point of
                # that page is that a failed turn is diagnosable from the
                # device. Truncated to fit one log line; the untruncated
                # traceback is in the logger call above.
                self._log(f"ERROR {type(exc).__name__}: {exc}"[:52])
                self.board.button_led(False)
                with self._screen_lock:
                    self.board.statusbar("[ERROR]")
                    self.board.top_text("SYSTEM ERROR")
                    self.board.bottom_text("Please try again")
                time.sleep(2.0)

    def stop(self) -> None:
        """Application shutdown hook."""
        super().stop()
