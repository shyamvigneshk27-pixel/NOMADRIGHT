"""
Tests for the three-page HandheldUI: the app view, the Settings page, and the
new pipeline-log page (topbar terminal icon).

The log page exists so the kiosk is usable with no terminal attached - every
pipeline stage boundary the application used to print only to the console is
now readable on the device itself. These tests cover the page switching (which
had to change: "not settings" stopped meaning "app" once a third page
existed), the log ring buffer, and the topbar geometry that adding a fourth
icon disturbed.

As with handheld_button_test.py, a real HandheldUI is built against mocked
display/touch objects - displayio and adafruit_button only need real SPI to
push pixels, which these tests never do.
"""
import unittest
from unittest.mock import MagicMock

import terminalio

from pocketinfer.ui.handheld import HandheldUI


def _make_ui():
    return HandheldUI(MagicMock(), MagicMock())


def _tap(ui, button_name):
    """One full press-and-release on a button, through the same code path the
    real poll loop uses."""
    butt = ui.buttons[button_name]
    ui.check_buttons(butt.x + butt.width // 2, butt.y + butt.height // 2)
    ui.touch.is_pressed.return_value = False
    ui._touch_was_down = True
    ui.check_touch()


def _text_width(font, text):
    """Rendered width in pixels, summing the same glyph advances displayio
    uses to lay the string out."""
    total = 0
    for char in text:
        glyph = font.get_glyph(ord(char))
        total += glyph.shift_x if glyph else 0
    return total


class TestPageSwitching(unittest.TestCase):
    """Exactly one page may ever be visible."""

    def _visible(self, ui):
        return {
            'app': not ui.appui.hidden,
            'settings': not ui.setpage.hidden,
            'log': not ui.logpage.hidden,
        }

    def test_app_page_is_the_startup_view(self):
        ui = _make_ui()
        self.assertEqual(self._visible(ui), {'app': True, 'settings': False, 'log': False})

    def test_log_button_toggles_the_log_page(self):
        ui = _make_ui()
        _tap(ui, 'Log')
        self.assertEqual(self._visible(ui), {'app': False, 'settings': False, 'log': True})
        _tap(ui, 'Log')
        self.assertEqual(self._visible(ui), {'app': True, 'settings': False, 'log': False})

    def test_settings_button_toggles_the_settings_page(self):
        ui = _make_ui()
        _tap(ui, 'Settings')
        self.assertEqual(self._visible(ui), {'app': False, 'settings': True, 'log': False})
        _tap(ui, 'Settings')
        self.assertEqual(self._visible(ui), {'app': True, 'settings': False, 'log': False})

    def test_opening_log_from_settings_closes_settings(self):
        """The bug the page manager replaced: toggling one overlay used to
        leave the other one stacked underneath/on top of it."""
        ui = _make_ui()
        _tap(ui, 'Settings')
        _tap(ui, 'Log')
        self.assertEqual(self._visible(ui), {'app': False, 'settings': False, 'log': True})

    def test_opening_settings_from_log_closes_log(self):
        ui = _make_ui()
        _tap(ui, 'Log')
        _tap(ui, 'Settings')
        self.assertEqual(self._visible(ui), {'app': False, 'settings': True, 'log': False})

    def test_home_returns_to_the_app_page_from_any_overlay(self):
        for overlay in ('Settings', 'Log'):
            ui = _make_ui()
            _tap(ui, overlay)
            _tap(ui, 'Home')
            self.assertEqual(
                self._visible(ui), {'app': True, 'settings': False, 'log': False},
                f"Home must close the {overlay} page - it is the app's universal "
                f"back/cancel control, and leaving the overlay up means the screen "
                f"stops matching what the application behind it is doing",
            )

    def test_settings_action_buttons_return_to_the_app_page(self):
        for name in ('Reset', 'Shutdown', 'Reboot'):
            ui = _make_ui()
            _tap(ui, 'Settings')
            _tap(ui, name)
            self.assertEqual(self._visible(ui), {'app': True, 'settings': False, 'log': False})

    def test_pages_survive_many_toggles(self):
        ui = _make_ui()
        for _ in range(20):
            _tap(ui, 'Log')
            _tap(ui, 'Settings')
            _tap(ui, 'Home')
        self.assertEqual(self._visible(ui), {'app': True, 'settings': False, 'log': False})


class TestLogFeed(unittest.TestCase):
    def test_lines_appear_on_the_page_oldest_first(self):
        ui = _make_ui()
        ui._show_page('log')
        for n in range(3):
            ui.log_line(f"line {n}")
        rendered = [lbl.text for lbl in ui._log_labels[:3]]
        self.assertEqual(rendered, ["line 0", "line 1", "line 2"])

    def test_buffer_scrolls_and_drops_the_oldest_line(self):
        ui = _make_ui()
        ui._show_page('log')
        total = HandheldUI.LOG_VISIBLE_LINES + 5
        for n in range(total):
            ui.log_line(f"line {n}")
        rendered = [lbl.text for lbl in ui._log_labels]
        self.assertEqual(len(rendered), HandheldUI.LOG_VISIBLE_LINES)
        self.assertEqual(rendered[-1], f"line {total - 1}", "newest line sits at the bottom")
        self.assertEqual(rendered[0], f"line {total - HandheldUI.LOG_VISIBLE_LINES}")

    def test_long_lines_are_truncated_rather_than_wrapped(self):
        """Each log line is a fixed-position Label, so a line that wrapped
        would push every line below it off the bottom of the page."""
        ui = _make_ui()
        ui._show_page('log')
        ui.log_line("x" * 200)
        drawn = ui._log_labels[0].text
        self.assertEqual(len(drawn), HandheldUI.LOG_LINE_MAX_CHARS)
        self.assertLessEqual(
            _text_width(terminalio.FONT, drawn), 320,
            "a log line must fit the 320px display width without wrapping",
        )

    def test_logging_while_hidden_records_without_touching_labels(self):
        """Logging happens on the pipeline's hot path, so it must stay cheap
        when nobody is looking at the log page."""
        ui = _make_ui()
        self.assertEqual(ui._current_page, 'app')
        ui.log_line("recorded while hidden")
        self.assertNotIn("recorded while hidden", [lbl.text for lbl in ui._log_labels])
        ui._show_page('log')
        self.assertEqual(ui._log_labels[0].text, "recorded while hidden")

    def test_clear_log_blanks_the_page(self):
        ui = _make_ui()
        ui._show_page('log')
        ui.log_line("something")
        ui.clear_log()
        self.assertEqual([lbl.text for lbl in ui._log_labels], [""] * HandheldUI.LOG_VISIBLE_LINES)

    def test_clear_screen_preserves_the_log(self):
        """clear_screen() runs at the top of an application's run(), which
        BaseApplication._run() re-enters after an unhandled exception -
        wiping the log there would destroy the record of the failure at
        exactly the moment it becomes worth reading."""
        ui = _make_ui()
        ui._show_page('log')
        ui.log_line("the failure")
        ui.clear_screen()
        self.assertEqual(ui._log_labels[0].text, "the failure")

    def test_log_page_fits_above_the_status_bar(self):
        last_y = HandheldUI._LOG_FIRST_Y + (HandheldUI.LOG_VISIBLE_LINES - 1) * HandheldUI._LOG_LINE_HEIGHT
        bottom = last_y + terminalio.FONT.get_bounding_box()[1]
        self.assertLessEqual(
            bottom, 228,
            "the last log line must clear the status bar, which occupies "
            "roughly y=228..240 at the bottom of the 240px display",
        )


class TestRadioSync(unittest.TestCase):
    """select_radio() lets an application make the Settings page agree with
    the language it is really running."""

    def test_selecting_a_language_deselects_its_siblings(self):
        ui = _make_ui()
        self.assertTrue(ui.buttons['ASR En'].selected, "constructor default")
        ui.select_radio('ASR ', 'ASR Hi')
        self.assertTrue(ui.buttons['ASR Hi'].selected)
        self.assertFalse(ui.buttons['ASR En'].selected)
        self.assertEqual(
            [n for n in ui.buttons if n.startswith('ASR ') and ui.buttons[n].selected],
            ['ASR Hi'],
            "exactly one language may be highlighted",
        )

    def test_other_radio_groups_are_untouched(self):
        ui = _make_ui()
        ui.select_radio('ASR ', 'ASR Ta')
        self.assertTrue(ui.buttons['Bridge Ta'].selected, "Bridge group unaffected")
        self.assertTrue(ui.buttons['TTS En'].selected, "TTS group unaffected")

    def test_selecting_is_idempotent(self):
        ui = _make_ui()
        self.assertTrue(ui.select_radio('ASR ', 'ASR Hi'), "first call changes state")
        self.assertFalse(ui.select_radio('ASR ', 'ASR Hi'), "second call is a no-op")

    def test_every_nomadright_language_has_a_matching_button(self):
        """app.py builds the button name as f'ASR {code.capitalize()}' - if a
        supported language had no such button the sync would silently
        deselect everything, leaving the page showing no language at all."""
        from pocketinfer.applications.nomad_right import constants
        ui = _make_ui()
        for code in constants.SOURCE_LANGUAGES:
            name = f"ASR {code.capitalize()}"
            self.assertIn(name, ui.buttons, f"no Settings button for language {code!r}")
            ui.select_radio('ASR ', name)
            self.assertTrue(ui.buttons[name].selected)


class TestTopbarLayout(unittest.TestCase):
    """Adding a fourth topbar icon moved the battery and RAM readouts left.
    These assert the row still lays out without overlaps at its worst case."""

    def _button_span(self, ui, name):
        butt = ui.buttons[name]
        return butt.x, butt.x + butt.width

    def test_the_four_topbar_icons_tile_without_overlapping(self):
        ui = _make_ui()
        spans = [self._button_span(ui, n) for n in ('Log', 'Camera', 'Settings', 'Home')]
        for (_, prev_right), (next_left, _) in zip(spans, spans[1:]):
            self.assertLessEqual(prev_right, next_left)
        self.assertEqual(spans[-1][1], 320, "the row ends flush with the screen edge")

    def test_battery_readout_clears_the_leftmost_icon(self):
        ui = _make_ui()
        right = ui.battval.anchored_position[0]
        left = right - _text_width(HandheldUI.ICON_FONT, ui.battval.text)
        log_left = self._button_span(ui, 'Log')[0]
        self.assertLessEqual(right, log_left, "battery must not run under the Log icon")
        self.assertGreater(left, 0)

    def test_ram_readout_clears_the_battery_readout(self):
        ui = _make_ui()
        ui.memory_text("100%")
        mem_right = ui.memval.anchored_position[0]
        mem_left = mem_right - _text_width(terminalio.FONT, "100%")
        batt_right = ui.battval.anchored_position[0]
        batt_left = batt_right - _text_width(HandheldUI.ICON_FONT, ui.battval.text)
        self.assertLessEqual(mem_right, batt_left, "RAM readout must not run under the battery icons")
        self.assertGreater(mem_left, 0)

    def test_longest_mode_text_clears_the_ram_readout(self):
        """mode_text() clamps rather than trusting callers, so no application
        can collide with the topbar by passing a longer label."""
        ui = _make_ui()
        ui.mode_text("X" * 80)
        self.assertLessEqual(len(ui.modeval.text), HandheldUI.MODE_TEXT_MAX_CHARS)
        mode_right = _text_width(terminalio.FONT, ui.modeval.text)
        mem_left = ui.memval.anchored_position[0] - _text_width(terminalio.FONT, "100%")
        self.assertLessEqual(mode_right, mem_left)

    def test_real_mode_labels_fit(self):
        ui = _make_ui()
        for text in ("HOME", "VOICE TRANSLATION", "DOCUMENT SCANNER", "App NomadRight"):
            ui.mode_text(text)
            self.assertEqual(ui.modeval.text, text, f"{text!r} should not need truncating")


if __name__ == "__main__":
    unittest.main()
