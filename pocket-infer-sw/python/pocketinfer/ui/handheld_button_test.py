"""
Regression tests for HandheldUI's touch-button dispatch.

check_buttons() used to reuse each Button's own .selected flag as its
per-touch debounce guard. That's correct for radio-style buttons (language
selection), whose .selected is meant to persist once chosen - but for
momentary action buttons (Home, Camera, Settings, Reset, Shutdown, Reboot)
nothing ever reset .selected back to False after the press ended, so those
buttons fired their callback exactly once, ever, for the lifetime of the UI
subprocess. This is the concrete mechanism behind "the buttons aren't
functioning" - a single tap worked, every subsequent tap on the same
button silently did nothing.

The fix separates the per-touch debounce guard (self._touch_active_buttons,
cleared on release) from the button's visual .selected state, and clears
.selected on release only for buttons marked momentary=True.

These tests instantiate a real HandheldUI against mocked display/touch
objects - displayio Group/Bitmap/Palette and adafruit_button.Button don't
need real SPI hardware to construct or manipulate, only to actually push
pixels (which these tests never do).
"""
import unittest
from unittest.mock import MagicMock

from pocketinfer.ui.handheld import HandheldUI


def _make_ui():
    display = MagicMock()
    touch = MagicMock()
    return HandheldUI(display, touch), touch


def _center_of(button):
    return (button.x + button.width // 2, button.y + button.height // 2)


def _tap(ui, touch, button_name):
    """Simulate one full press-and-release touch on the named button,
    driving the same check_touch()/check_buttons() path the real
    multiprocess_launch() poll loop uses."""
    cx, cy = _center_of(ui.buttons[button_name])
    touch.is_pressed.return_value = True
    ui.check_buttons(cx, cy)
    touch.is_pressed.return_value = False
    ui._touch_was_down = True
    ui.check_touch()


class TestMomentaryButtonsRefire(unittest.TestCase):
    """The core bug: Home/Camera/Settings/Reset/Shutdown/Reboot must fire
    their callback on every tap, not just the first."""

    def _assert_refires(self, button_name, taps=5):
        ui, touch = _make_ui()
        count = {"n": 0}
        ui.subscribe_to_button(button_name, lambda name: count.__setitem__("n", count["n"] + 1))
        for _ in range(taps):
            _tap(ui, touch, button_name)
        self.assertEqual(
            count["n"], taps,
            f"{button_name!r} fired {count['n']}/{taps} times - a momentary "
            f"button must refire on every tap, not just the first",
        )
        self.assertFalse(
            ui.buttons[button_name].selected,
            f"{button_name!r} must be visually un-pressed after the touch releases",
        )

    def test_home_refires_every_tap(self):
        self._assert_refires("Home")

    def test_camera_refires_every_tap(self):
        self._assert_refires("Camera")

    def test_settings_refires_every_tap(self):
        self._assert_refires("Settings")

    def test_reset_refires_every_tap(self):
        self._assert_refires("Reset")

    def test_shutdown_refires_every_tap(self):
        self._assert_refires("Shutdown")

    def test_reboot_refires_every_tap(self):
        self._assert_refires("Reboot")


class TestRadioGroupButtonsUnaffected(unittest.TestCase):
    """Language-selection buttons must keep their persistent .selected
    highlight (managed by their own _deselect_other_* callback) - the
    momentary-button fix must not touch this behavior."""

    def test_selecting_a_language_persists_across_other_touches(self):
        ui, touch = _make_ui()
        self.assertTrue(ui.buttons["ASR En"].selected, "ASR En starts as the default")

        _tap(ui, touch, "ASR Hi")
        self.assertTrue(ui.buttons["ASR Hi"].selected)
        self.assertFalse(ui.buttons["ASR En"].selected)

        # An unrelated momentary button press must not disturb the choice.
        _tap(ui, touch, "Home")
        self.assertTrue(
            ui.buttons["ASR Hi"].selected,
            "language selection must survive an unrelated Home tap",
        )

    def test_tapping_the_already_selected_language_again_is_a_safe_noop(self):
        ui, touch = _make_ui()
        _tap(ui, touch, "ASR Hi")
        fired = []
        ui.subscribe_to_button("ASR Hi", lambda name: fired.append(name))
        _tap(ui, touch, "ASR Hi")
        self.assertTrue(ui.buttons["ASR Hi"].selected)


class TestDebounceWithinASingleTouch(unittest.TestCase):
    """A single held-down touch (multiple poll iterations before release)
    must dispatch its button's callback exactly once, not once per poll."""

    def test_holding_a_button_down_fires_once_not_per_poll(self):
        ui, touch = _make_ui()
        count = {"n": 0}
        ui.subscribe_to_button("Home", lambda name: count.__setitem__("n", count["n"] + 1))
        cx, cy = _center_of(ui.buttons["Home"])
        touch.is_pressed.return_value = True
        for _ in range(10):  # ten poll iterations while the finger stays down
            ui.check_buttons(cx, cy)
        self.assertEqual(count["n"], 1)


if __name__ == "__main__":
    unittest.main()
