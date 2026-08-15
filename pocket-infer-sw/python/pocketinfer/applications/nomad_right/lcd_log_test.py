#!/usr/bin/env python3
"""
NomadRight on-screen pipeline-log tests
=======================================
Covers app.py's _log() / _sync_language_buttons() / _startup_selfcheck(),
the pieces that make the kiosk usable with no terminal attached: every stage
boundary that previously existed only in console scrollback is pushed to the
LCD's log page (ui/handheld.py), and startup reports whether each subsystem
a turn depends on is actually up.

Does NOT touch the voice/vision pipeline itself - see pipeline_test.py and
audit_fix_regression_test.py for that.
"""
import os
import sys
import unittest
import unittest.mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_HERE, "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(_REPO_ROOT, "python"))

import logging
logging.basicConfig(level=logging.CRITICAL)

from pocketinfer.applications.nomad_right import constants
from pocketinfer.applications.nomad_right.app import NomadRightApplication
from pocketinfer.ui.handheld import HandheldUI


class LoggingBoard:
    """A board that records log lines and radio-group selections, plus the
    minimum LCD surface app.py touches."""

    def __init__(self):
        self.log_lines = []
        self.radio = []
        self.alsa_capture_card = 0
        self.alsa_playback_card = 1
        self.alsa_playback_device = "hw:1,0"

    def log_line(self, text):
        self.log_lines.append(text)
        return True

    def select_radio(self, prefix, name):
        self.radio.append((prefix, name))
        return True

    def clear_log(self):
        self.log_lines.clear()
        return True

    def top_text(self, t): pass
    def bottom_text(self, t): pass
    def statusbar(self, t): pass
    def mode_text(self, t): pass
    def clear_screen(self): pass
    def button_led(self, v): pass
    def subscribe_to_ui(self, cb): pass
    def camera_frame_jpg(self): return b"\xff\xd8\xff\xe0jpeg"


def _app(board=None, **settings):
    board = board or LoggingBoard()
    # Explicit settings every time: BaseApplication aliases self.settings to the
    # class-level METADATA["default_settings"] dict, so state written by one
    # instance is visible to the next one built in the same process.
    base = {
        "input_language": constants.DEFAULT_SOURCE_LANGUAGE,
        "bridge_language": constants.DEFAULT_BRIDGE_LANGUAGE,
        "log_directory": constants.DEFAULT_LOG_DIR,
    }
    base.update(settings)
    return NomadRightApplication(board, settings=base), board


class TestLogHelper(unittest.TestCase):
    def test_line_reaches_the_board_with_a_timestamp(self):
        app, board = _app()
        app._log("BTN DOWN - listening")
        self.assertEqual(len(board.log_lines), 1)
        line = board.log_lines[0]
        self.assertRegex(line, r"^\d{2}:\d{2}:\d{2} BTN DOWN - listening$")

    def test_native_script_is_stripped_not_passed_through(self):
        """The log page renders in terminalio.FONT, which has no Devanagari
        glyphs - such a character would draw as nothing while still
        consuming a column, silently shifting the rest of the line."""
        app, board = _app()
        app._log("ASR hi: मुझे राशन कार्ड चाहिए")
        line = board.log_lines[0]
        self.assertTrue(line.isascii(), f"non-ASCII reached the log page: {line!r}")

    def test_a_failing_board_never_breaks_the_caller(self):
        """Diagnostics are strictly less important than the answer in
        flight - a broken log push must not abort a real turn."""
        class BrokenBoard(LoggingBoard):
            def log_line(self, text):
                raise RuntimeError("UI subprocess died")

        app, _ = _app(BrokenBoard())
        app._log("still fine")  # must not raise

    def test_a_board_without_a_display_is_tolerated(self):
        """Older boards (and the console/headless path) have no log_line at
        all - app.py must degrade to logger-only rather than crash."""
        class NoDisplayBoard:
            alsa_capture_card = 0
            alsa_playback_card = 1
        app, _ = _app(NoDisplayBoard())
        app._log("logger only")  # must not raise

    def test_stage_lines_fit_the_log_page_width(self):
        app, board = _app()
        app._log("BTN UP - recorded 3.2s")
        app._log("ASR hi 42 chars  0.9s")
        app._log("NMT hi->EN  0.4s")
        app._log("DECIDE PDS  1.9s")
        app._log("NMT EN->hi  0.4s")
        app._log("TTS hi  0.6s")
        app._log("ANSWER after 4.2s - speaking")
        app._log("PHOTO CAPTURED 118 KB  0.3s")
        for line in board.log_lines:
            self.assertLessEqual(
                len(line), HandheldUI.LOG_LINE_MAX_CHARS,
                f"{line!r} would be truncated on screen",
            )


class TestLanguageSync(unittest.TestCase):
    def test_default_language_corrects_the_settings_page(self):
        """The page's constructor default highlights 'ASR En', but
        NomadRight has no English at all - so without this the screen
        claimed English while every turn ran Hindi, and the highlighted
        button did nothing when pressed."""
        app, board = _app()
        app._sync_language_buttons()
        self.assertIn(("ASR ", "ASR Hi"), board.radio)

    def test_every_supported_language_maps_to_a_real_button(self):
        ui = HandheldUI(unittest.mock.MagicMock(), unittest.mock.MagicMock())
        for code in constants.SOURCE_LANGUAGES:
            app, board = _app(input_language=code)
            app._sync_language_buttons()
            prefix, name = board.radio[0]
            self.assertIn(
                name, ui.buttons,
                f"language {code!r} syncs to {name!r}, which is not a button",
            )

    def test_bridge_language_is_synced_too(self):
        app, board = _app(bridge_language="gu")
        app._sync_language_buttons()
        self.assertIn(("Bridge ", "Bridge Gu"), board.radio)

    def test_a_board_without_radio_support_is_tolerated(self):
        class NoRadioBoard(LoggingBoard):
            select_radio = None

            def __getattr__(self, name):
                raise AttributeError(name)

        app, _ = _app(NoRadioBoard())
        app._sync_language_buttons()  # must not raise


class TestStartupSelfCheck(unittest.TestCase):
    def _run_check(self, board, status_code=200, raises=False):
        def fake_get(url, timeout=None):
            if raises:
                raise OSError("connection refused")
            class Resp:
                pass
            resp = Resp()
            resp.status_code = status_code
            return resp

        app, _ = _app(board)
        with unittest.mock.patch("requests.get", side_effect=fake_get):
            app._startup_selfcheck()
        return board.log_lines

    def test_all_healthy_reports_ok(self):
        board = LoggingBoard()
        lines = self._run_check(board)
        joined = "\n".join(lines)
        self.assertIn("BHASHINI  OK", joined)
        self.assertIn("OLLAMA    OK", joined)
        self.assertIn("All subsystems OK", joined)
        self.assertNotIn("WARNING", joined)

    def test_unreachable_services_are_reported_as_down(self):
        board = LoggingBoard()
        lines = self._run_check(board, raises=True)
        joined = "\n".join(lines)
        self.assertIn("BHASHINI  DOWN", joined)
        self.assertIn("OLLAMA    DOWN", joined)
        self.assertIn("WARNING: degraded", joined)

    def test_missing_audio_hardware_is_reported(self):
        board = LoggingBoard()
        board.alsa_capture_card = None
        board.alsa_playback_card = None
        lines = self._run_check(board)
        joined = "\n".join(lines)
        self.assertIn("MIC       NOT FOUND", joined)
        self.assertIn("SPEAKER   NOT FOUND", joined)
        self.assertIn("MIC", joined.split("degraded ->")[-1])

    def test_selfcheck_never_raises_even_when_everything_is_broken(self):
        """A failed probe must not stop the app from reaching its ready
        screen - the real error still surfaces per-turn as it always did."""
        class HostileBoard(LoggingBoard):
            alsa_capture_card = None
            alsa_playback_card = None

        board = HostileBoard()
        self._run_check(board, raises=True)

    def test_selfcheck_lines_fit_the_log_page_width(self):
        board = LoggingBoard()
        lines = self._run_check(board, raises=True)
        for line in lines:
            self.assertLessEqual(len(line), HandheldUI.LOG_LINE_MAX_CHARS, repr(line))


class TestCameraLogging(unittest.TestCase):
    def test_successful_capture_is_logged(self):
        app, board = _app()
        app._on_camera_pressed()
        joined = "\n".join(board.log_lines)
        self.assertIn("CAMERA pressed - capturing", joined)
        self.assertIn("PHOTO CAPTURED", joined)

    def test_capture_failure_is_logged(self):
        class BrokenCamera(LoggingBoard):
            def camera_frame_jpg(self):
                raise RuntimeError("camera disconnected")

        app, board = _app(BrokenCamera())
        app._on_camera_pressed()
        self.assertIn("CAMERA FAILED", "\n".join(board.log_lines))

    def test_empty_frame_is_logged(self):
        class NoFrame(LoggingBoard):
            def camera_frame_jpg(self):
                return None

        app, board = _app(NoFrame())
        app._on_camera_pressed()
        self.assertIn("CAMERA returned no frame", "\n".join(board.log_lines))


if __name__ == "__main__":
    unittest.main()
