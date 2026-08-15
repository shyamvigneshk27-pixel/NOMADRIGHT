import time
import logging
import threading
import uuid
import displayio
import terminalio
from os.path import join
from adafruit_display_text import label, text_box
from adafruit_bitmap_font import bitmap_font
from adafruit_button.button import Button

from pocketinfer.ui import icons
from importlib.resources import files
from collections import deque
from multiprocessing import Queue, Pipe
import multiprocessing.connection
from typing import NamedTuple


class HandheldUI:
    ''' This is a graphical UI based on the Adafruit displayIO framework.
    It was originally designed for a circuitpython IO expander board, but has been adapted to run on an Embedded linux platform 
    via the Adafruit blinka compatibility layer. It is designed for a 320x240 pixel touchscreen.
    This class is agnostic to the underlying display and transport, but will be subclassed for specific hardware support.
    '''
    ICON_FONT = bitmap_font.load_font(str(files('pocketinfer.ui').joinpath('forkawesome-16.pcf')))
    HINDI_FONT = bitmap_font.load_font(str(files('pocketinfer.ui').joinpath('NotoSansDevanagari-Regular-12.pcf')))

    # ── Pipeline-log page (topbar terminal icon) ───────────────────────────
    # A scrolling on-screen copy of what the application would otherwise
    # only print to a terminal, so the device is genuinely usable headless -
    # press the terminal icon to see whether the trigger button registered,
    # how long each pipeline stage took, and why a turn failed, with no SSH
    # session or serial console attached. Rendered in terminalio.FONT (6x12
    # fixed-width, ASCII only) rather than the Devanagari face used
    # everywhere else: at 6px per glyph a 320px line holds 53 characters and
    # 14 lines fit vertically, versus ~36 characters and ~9 lines for the
    # 12px proportional face - a log wants density far more than it wants
    # script coverage. Callers are responsible for keeping log lines ASCII
    # (see nomad_right/app.py's _log()).
    LOG_VISIBLE_LINES = 14
    LOG_LINE_MAX_CHARS = 53
    _LOG_FIRST_Y = 20
    _LOG_LINE_HEIGHT = 14

    def __init__(self, display, touch, logger=None):
        ''' Load the UI into memory'''
        self.logger = logger or logging.getLogger(__name__)
        self.display = display
        self.touch = touch

        self.button_cbs = {}
        self.buttons = {}
        # Names of buttons that should visually un-press and become
        # pressable again as soon as the finger lifts (Home/Camera/Settings/
        # Reset/Shutdown/Reboot) - as opposed to radio-style language
        # buttons, whose .selected is meant to persist (the chosen option
        # stays highlighted until a sibling in the same group is picked via
        # _deselect_other_*). See check_buttons()/check_touch() below.
        self._momentary_buttons = set()
        # Names already dispatched during the CURRENT touch-down (cleared on
        # release) - this is the actual per-touch debounce guard. Previously
        # check_buttons() reused each button's own .selected flag for this,
        # which meant a momentary button (nothing ever clears its .selected
        # back to False after the press ends) could only ever fire once,
        # for the rest of the process's life - the root cause behind
        # "buttons aren't functioning" for Home/Camera/Settings/Reset/
        # Shutdown/Reboot.
        self._touch_active_buttons = set()
        self._touch_was_down = False
        # Which of the three full-screen pages is currently up ('app',
        # 'settings' or 'log'). Previously this was implied by reading
        # self.setpage.hidden, which only worked while there were exactly
        # two pages - with a third, "not settings" no longer means "app",
        # and toggling one page has to be able to close the other. See
        # _show_page().
        self._current_page = 'app'
        # Ring buffer of on-screen log lines, oldest first. Kept here (in
        # the UI process) rather than in the caller so each log_line() RPC
        # ships one short string instead of the whole re-joined page.
        self._log_lines = deque(maxlen=self.LOG_VISIBLE_LINES)

        # Make the display context
        self.layers = displayio.Group()
        self.topbar = displayio.Group()
        self.appui = displayio.Group()
        self.display.root_group = self.layers

        color_bitmap = displayio.Bitmap(320, 240, 1)
        color_palette = displayio.Palette(1)
        color_palette[0] = 0x000000

        # bg_sprite = displayio.TileGrid(color_bitmap,
        #                             pixel_shader=color_palette,
        #                             x=0, y=0)

        # Set text, font, and color
        font = terminalio.FONT
        color = 0xFFFFFF
        color_dim = 0x777777

        # Create the text label
        self.statusbar = label.Label(font, text=" "*52, color=color_dim)
        self.statusbar.anchor_point = (0.5, 1.0)
        self.statusbar.anchored_position = (160, 240)
        self.statusbar.text = "Initializing..."
        self.topbar.append(self.statusbar)


        self.modeval = label.Label(font, text=" "*52, color=color_dim)
        self.modeval.anchor_point = (0.0, 0.0)
        self.modeval.anchored_position = (0, 3)
        self.modeval.text = "Initializing..."
        self.topbar.append(self.modeval)

        def _toggle_setpage(name):
            self._show_page('app' if self._current_page == 'settings' else 'settings')

        def _toggle_logpage(name):
            self._show_page('app' if self._current_page == 'log' else 'log')

        def _go_home(name):
            # Home is the app's universal back/cancel control, so it must
            # also close whichever overlay page is open - otherwise pressing
            # Home from the Settings or Log page left the worker staring at
            # that page while the application behind it returned to its
            # ready state, i.e. the screen stopped matching the real state.
            self._show_page('app')

        self.topbar.append(self._button('Home', x=320-28, y=0, width=28, height=28, label=icons.home, font=self.ICON_FONT,
                                        label_color=color, fill_color=0x000000, outline_color=0x000000, cb=_go_home, momentary=True))
        self.topbar.append(self._button('Settings', x=320-28*2, y=0, width=28, height=28, label=icons.book, font=self.ICON_FONT,
                                        label_color=color, fill_color=0x000000, outline_color=0x000000, cb=_toggle_setpage, momentary=True))
        # NomadRight's form-reading flow (see nomad_right/app.py's ui_cb):
        # captures a photo via board.camera_frame_jpg() and waits for the
        # worker's next spoken question about it. Apps that don't subscribe
        # to the "Camera" message simply never receive it - safe to always
        # show.
        self.topbar.append(self._button('Camera', x=320-28*3, y=0, width=28, height=28, label=icons.camera, font=self.ICON_FONT,
                                        label_color=color, fill_color=0x000000, outline_color=0x000000, momentary=True))
        # Pipeline log page - handled entirely inside the UI process (the
        # 'Log' message is still queued to the application like every other
        # button, but no app needs to subscribe to it for the page to work).
        self.topbar.append(self._button('Log', x=320-28*4, y=0, width=28, height=28, label=icons.terminal, font=self.ICON_FONT,
                                        label_color=color, fill_color=0x000000, outline_color=0x000000, cb=_toggle_logpage, momentary=True))

        # Create the text label
        # Right-aligned, ending just left of the (now four) topbar icons.
        # Measured widths at these fonts: this string is 57px, so it spans
        # x=147..204 - clear of the Log button's left edge at x=208.
        self.battval = label.Label(self.ICON_FONT, text=f"{icons.microchip}     {icons.battery_full}", color=color)
        self.battval.anchor_point = (1.0, 0.0)
        self.battval.anchored_position = (320-28*4-4, 3)
        self.topbar.append(self.battval)

        # terminalio rather than the 12px Devanagari face: this only ever
        # shows a RAM percentage ("45%"), and at 6px/glyph that is 24px wide
        # instead of ~36px, which is what makes a fourth topbar icon fit
        # without colliding with the mode text on the left (see mode_text()).
        self.memval = label.Label(font, text="    ", color=color)
        self.memval.anchor_point = (1.0, 0.0)
        self.memval.anchored_position = (140, 3)
        self.topbar.append(self.memval)

        self.toptext = text_box.TextBox(x=0, y=0, width=320, height=100, line_spacing=0.80, font=self.HINDI_FONT, color=color)
        self.toptext.anchor_point = (0.0, 0.0)
        self.toptext.anchored_position = (0, 16)
        self.appui.append(self.toptext)


        self.bottomtext = text_box.TextBox(x=0, y=100, width=320, height=100, line_spacing=0.8, font=self.HINDI_FONT, color=color)
        self.bottomtext.anchor_point = (0.0, 0.0)
        self.bottomtext.anchored_position = (0, 100)
        self.appui.append(self.bottomtext)

        self.setpage = displayio.Group()

        settingslabel = label.Label(font, text=" "*52, color=color)
        settingslabel.anchor_point = (0.5, 0.0)
        settingslabel.anchored_position = (160, 16)
        settingslabel.text = "Settings"
        self.setpage.append(settingslabel)

        # ASR (spoken-language) selection - two rows to fit all 9 languages
        # supported across HearTheWorld (En/Hi/Ta) and NomadRight's migrant
        # worker languages (Or/Bho/Mai/Sat/Hne). Any app can read the
        # resulting `ASR <lang>` message via board.subscribe_to_ui().
        input_lang = label.Label(font, text="ASR Lang ", color=color)
        input_lang.anchor_point = (0.0, 0.5)
        input_lang.anchored_position = (0, 48)
        self.setpage.append(input_lang)

        def _deselect_other_asr(name):
            for other in filter(lambda x: x.startswith('ASR ') and x != name, self.buttons.keys()):
                self.buttons[other].selected = False

        self.setpage.append(self._button('ASR En', x=64, y=32, selected=True, cb=_deselect_other_asr))
        self.setpage.append(self._button('ASR Hi', x=64+64, y=32, cb=_deselect_other_asr))
        self.setpage.append(self._button('ASR Ta', x=64+64*2, y=32, cb=_deselect_other_asr))
        self.setpage.append(self._button('ASR Or', x=64+64*3, y=32, cb=_deselect_other_asr))
        self.setpage.append(self._button('ASR Bho', x=64, y=64, cb=_deselect_other_asr))
        self.setpage.append(self._button('ASR Mai', x=64+64, y=64, cb=_deselect_other_asr))
        self.setpage.append(self._button('ASR Sat', x=64+64*2, y=64, cb=_deselect_other_asr))
        self.setpage.append(self._button('ASR Hne', x=64+64*3, y=64, cb=_deselect_other_asr))

        # TTS (answer playback) language - used by HearTheWorld for the
        # response language. NomadRight always answers in the worker's own
        # ASR language, so this row does not apply to it.
        output_lang = label.Label(font, text="TTS Lang ", color=color)
        output_lang.anchor_point = (0.0, 0.5)
        output_lang.anchored_position = (0, 96+16)
        self.setpage.append(output_lang)

        def _deselect_other_tts(name):
            for other in filter(lambda x: x.startswith('TTS ') and x != name, self.buttons.keys()):
                self.buttons[other].selected = False

        self.setpage.append(self._button('TTS En', x=64, y=96, selected=True, cb=_deselect_other_tts))
        self.setpage.append(self._button('TTS Hi', x=64+64, y=96, cb=_deselect_other_tts))
        self.setpage.append(self._button('TTS Ta', x=64+64*2, y=96, cb=_deselect_other_tts))

        # Voice bridge language (NomadRight): the destination-state
        # official's language a citizen's answer can be translated into on
        # request. Delivered as a `Bridge <lang>` message.
        bridge_lang = label.Label(font, text="Bridge ", color=color)
        bridge_lang.anchor_point = (0.0, 0.5)
        bridge_lang.anchored_position = (0, 128+16)
        self.setpage.append(bridge_lang)

        def _deselect_other_bridge(name):
            for other in filter(lambda x: x.startswith('Bridge ') and x != name, self.buttons.keys()):
                self.buttons[other].selected = False

        self.setpage.append(self._button('Bridge Ta', x=64, y=128, selected=True, cb=_deselect_other_bridge))
        self.setpage.append(self._button('Bridge Gu', x=64+64, y=128, cb=_deselect_other_bridge))
        self.setpage.append(self._button('Bridge Mr', x=64+64*2, y=128, cb=_deselect_other_bridge))
        self.setpage.append(self._button('Bridge Kn', x=64+64*3, y=128, cb=_deselect_other_bridge))

        def _close_setpage(name):
            self._show_page('app')

        self.setpage.append(self._button('Reset', x=64, y=192, cb=_close_setpage, momentary=True))
        self.setpage.append(self._button('Shutdown', x=64*2, y=192, cb=_close_setpage, momentary=True))
        self.setpage.append(self._button('Reboot', x=64*3, y=192, cb=_close_setpage, momentary=True))

        # ── Pipeline log page ──────────────────────────────────────────────
        # One Label per line at a fixed y, rather than a single wrapping
        # TextBox: log lines are pre-truncated to fit (LOG_LINE_MAX_CHARS)
        # and must never re-wrap, since a wrapped line would silently push
        # every line below it off the bottom of the page.
        self.logpage = displayio.Group()
        self._log_labels = []
        for idx in range(self.LOG_VISIBLE_LINES):
            log_label = label.Label(font, text=" ", color=0x00C000)
            log_label.anchor_point = (0.0, 0.0)
            log_label.anchored_position = (2, self._LOG_FIRST_Y + idx * self._LOG_LINE_HEIGHT)
            self.logpage.append(log_label)
            self._log_labels.append(log_label)

        self.setpage.hidden = True
        self.logpage.hidden = True
        # self.layers.append(bg_sprite)
        self.layers.append(self.topbar)
        self.layers.append(self.appui)
        self.layers.append(self.setpage)
        self.layers.append(self.logpage)

    def _show_page(self, page):
        ''' Switch which full-screen page is visible ('app', 'settings' or 'log').
        Exactly one is ever shown, so a page can never be left stacked on top of
        another - which is what made the old two-page setpage.hidden toggling
        unsafe once a third page existed. '''
        self.appui.hidden = page != 'app'
        self.setpage.hidden = page != 'settings'
        self.logpage.hidden = page != 'log'
        self._current_page = page
        if page == 'log':
            # Catch the page up on anything logged while it was hidden.
            self._render_log()

    def _render_log(self):
        ''' Paint the ring buffer onto the fixed line Labels, oldest at the top.
        Each Label rebuilds its glyph bitmap on assignment, so unchanged lines are
        skipped - without that, one new line would repaint all LOG_VISIBLE_LINES. '''
        lines = list(self._log_lines)
        for idx, log_label in enumerate(self._log_labels):
            text = lines[idx] if idx < len(lines) else ""
            if log_label.text != text:
                log_label.text = text

    def log_line(self, text):
        ''' Append one line to the on-screen pipeline log (see LOG_VISIBLE_LINES).
        Safe to call at any time and from any application; when the log page isn't
        the visible one the line is still recorded but no Labels are touched, so
        logging from a hot pipeline path costs a deque append and nothing else. '''
        self._log_lines.append(str(text)[:self.LOG_LINE_MAX_CHARS])
        if self._current_page == 'log':
            self._render_log()
        return True

    def clear_log(self):
        ''' Drop every recorded log line and blank the page. '''
        self._log_lines.clear()
        self._render_log()
        return True

    def select_radio(self, prefix, name):
        ''' Set which button is highlighted within a radio group (e.g. prefix
        'ASR ', name 'ASR Hi'), deselecting its siblings - the same effect as a
        touch on that button, without dispatching its callback.

        This exists so an application can make the Settings page state agree with
        the language it is *actually* running: the page's own constructor default
        highlights 'ASR En', which for an app whose languages don't include
        English (NomadRight) meant the screen claimed English while the pipeline
        ran Hindi, and the highlighted button did nothing when pressed. '''
        changed = False
        for other in self.buttons:
            if other.startswith(prefix):
                wanted = (other == name)
                if self.buttons[other].selected != wanted:
                    self.buttons[other].selected = wanted
                    changed = True
        return changed

    def get_button_names(self):
        ''' Return a list of all button names in the UI '''
        return list(self.buttons.keys())
    
    def get_button_status(self):
        ''' Return a dict of button names and their selected status (True/False) '''
        return {name: self.buttons[name].selected for name in self.buttons.keys()}

    def _button(self, name, x, y, label=None, font=None, width=64, height=32,
                label_color=0xFF7E00, fill_color=0x5C5B5C, outline_color=0x767676, cb=None, selected=False,
                momentary=False):
        ''' Create a button and add it to the button list. If a callback is provided, it will be called when the button is pressed.
        Note that the button object returned should be added to the correct Group for it to be displayed.
        momentary=True marks a one-shot action button (Home/Camera/...) whose
        .selected highlight should clear as soon as the finger lifts, so it
        can be pressed again - see check_touch(). Leave False for radio-style
        buttons (language selection) that manage their own persistent
        .selected via a _deselect_other_* callback.'''
        if font is None:
            font = self.HINDI_FONT
        if label is None:
            label = name
        button = Button(
            x=x,
            y=y,
            width=width,
            height=height,
            label=label,
            label_font=font,
            label_color=label_color,
            fill_color=fill_color,
            outline_color=outline_color,
        )
        button.selected = selected
        self.buttons[name] = button
        if momentary:
            self._momentary_buttons.add(name)
        if cb:
            self.subscribe_to_button(name, cb)
        return button

    def top_text(self, text):
        ''' Set the top text area, which is the upper half of the screen. '''
        self.toptext.text = text
    
    def bottom_text(self, text):
        ''' Set the bottom text area, which is the lower half of the screen. '''
        self.bottomtext.text = text

    def statusbar_text(self, text):
        ''' Set the status bar text, which is the bottom line of the screen. '''
        self.statusbar.text = text
    
    # The mode label starts at x=0 and the RAM percentage's left edge sits at
    # x=116, so anything past 19 terminalio glyphs (19*6=114px) would run
    # underneath it. Clamped here rather than at each call site so no
    # application can collide with the topbar by passing a longer label.
    MODE_TEXT_MAX_CHARS = 19

    def mode_text(self, text):
        ''' Set the Mode value, in the upper left hand corner. '''
        self.modeval.text = str(text)[:self.MODE_TEXT_MAX_CHARS]

    def memory_text(self, text):
        ''' Set the RAM usage value. '''
        self.memval.text = text

    def clear_screen(self):
        self.toptext.text = ""
        self.bottomtext.text = ""
        self.statusbar.text = ""
        self.modeval.text = ""
        self.memval.text = ""
        # The log page is deliberately NOT cleared here. clear_screen() runs
        # at the top of an application's run(), which BaseApplication._run()
        # re-enters after an unhandled exception - wiping the log there would
        # destroy the record of the failure at exactly the moment it becomes
        # worth reading. Use clear_log() to blank it explicitly.

    def force_refresh(self):
        self.display.root_group = None
        self.display.root_group = self.layers
        self.display.refresh()

    def _dispatch_button_cb(self, button_name):
        ''' Call the callback for a button press, if one is registered. '''
        if button_name in self.button_cbs:
            cbs = self.button_cbs[button_name]
            for cb in cbs:
                if callable(cb):
                    cb(button_name)

    def subscribe_to_button(self, button_name, callback):
        ''' Register a callback for a button press. The callback will be called with the button name as an argument. '''
        if button_name not in self.button_cbs:
            self.button_cbs[button_name] = []
        self.button_cbs[button_name].append(callback)

    def unsubscribe_from_button(self, button_name, callback):
        ''' Unregister a callback for a button press. '''
        if button_name in self.button_cbs:
            cbs = self.button_cbs[button_name]
            if callback in cbs:
                cbs.remove(callback)

    def check_buttons(self, x, y):
        ''' Check if a touch event at (x, y) is within any button, and if so, call the callback for that button.
        Debounced per touch-down via self._touch_active_buttons (see check_touch()) rather than each
        button's own .selected flag - a momentary button's .selected is meant to be transient (cleared
        on release), so using it as the debounce guard too made those buttons fire once, ever. '''
        for name in self.buttons:
            if name in self._touch_active_buttons:
                continue
            butt = self.buttons[name]
            if butt.contains((x, y)):
                self._touch_active_buttons.add(name)
                butt.selected = True
                self._dispatch_button_cb(name)

    def check_touch(self):
        # TODO - this is specific to the xpt2046 controller and involves SPI internals, should be made generic or moved out
        # It's possible this method was called while the display is in in the process of a refresh and is using the SPI bus
        # IF that's the case, the touch read will fail and throw an exception, which we catch and ignore. This is not ideal, but it works for now.
        import xpt2046_circuitpython as xpt2046
        try:
            pressed = self.touch.is_pressed()
            if pressed:
                args = self.touch.get_coordinates()
                if args is not None:
                    # NOTE, this implies 90 degree rotation on the display
                    # TODO - make this more robust to different rotations and touch coordinate mappings
                    y, x = args
                    y = 240 - y
                    print(f"Touch at ({x}, {y})")
                    self.check_buttons(x, y)
            elif self._touch_was_down:
                # Falling edge - the finger just lifted. Un-press every
                # momentary button dispatched during the touch that just
                # ended so it's pressable again next time (see
                # _momentary_buttons's docstring in __init__). Radio-style
                # buttons are deliberately left alone here - their .selected
                # is managed by their own _deselect_other_* callback, not by
                # touch release.
                for name in self._touch_active_buttons:
                    if name in self._momentary_buttons:
                        self.buttons[name].selected = False
                self._touch_active_buttons.clear()
            self._touch_was_down = pressed
        except xpt2046.ReadFailedException:
            pass
        except Exception:
            # Any other touch-read failure (SPI contention, a stuck/noisy
            # touch controller reporting bad coordinates, etc.) must not
            # propagate out of this loop - multiprocess_launch's while-loop
            # has no other guard, so an uncaught exception here silently
            # kills the whole UI subprocess and breaks the RPC pipe for
            # every other board call (statusbar/top_text/memory_text/...).
            self.logger.exception("check_touch() failed, ignoring and continuing")

class ILI9341UIConfig(NamedTuple):
    ''' Configuration for the ILI9341 display and touch controller. '''
    reset_pin: str  # The Jetson SOC pin name for the LCD_RST line
    pwm_pin: str  # The Jetson SOC pin name for the LCD_BL line
    cs_pin: str  # The Jetson SOC pin name for the LCD_CS line
    dc_pin: str  # The Jetson SOC pin name for the LCD_DC line
    touch_cs: str  # The Jetson SOC pin name for the TP_CS line
    touch_irq: str  # The Jetson SOC pin name for the TP_IRQ line
    display_baudrate: int = 30000000    # Baud rate when communicating with the display controller over SPI
    touch_baudrate: int =    1000000    # Baud rate when communicating with the touch controller over SPI
    width: int = 320    # Width of the display in pixels
    height: int = 240   # Height of the display in pixels
    rotation: int = 90  # Rotation of the display in degrees

class UIRPCCall:
    ''' This class is used to send a function call from one process to another, and receive the result. It is used to allow the main application process to call functions in the UI process, and receive the result. '''
    def __init__(self, func_name, *args):
        ''' Initialize the UIRPCCall with the function name and arguments. The function name must be a string, and the arguments must be serializable. '''
        self.func_name = func_name
        self.args = args
        self.executed = False
        self.exception = None 
        self.result = None
        self._id = uuid.uuid4()
    
    def send(self, rpc_pipe: multiprocessing.connection.Connection):
        ''' Send this request to the other process via the provided pipe, and wait for the result. If the function raises an exception, it will be re-raised in this process.
         If the function returns a value, it will be returned to this process. '''
        rpc_pipe.send(self)
        ret = rpc_pipe.recv()
        if ret._id != self._id:
            raise RuntimeError("Mismatched RPC response ID, multiple RPC callers may be active at the same time, which is not supported.")
        if ret.exception is not None:
            raise ret.exception
        return ret.result
    
    def execute(self, func, rpc_pipe: multiprocessing.connection.Connection):
        ''' Execute the function in the other process, and send the result back via the provided pipe. If an exception is raised, it will be sent back to the calling process. '''
        if callable(func):
            try:
                self.result = func(*self.args)
            except Exception as e:
                self.exception = e 
            self.executed = True
        else:
            self.result = func
        rpc_pipe.send(self)


class IlI9341HandheldUI(HandheldUI):
    ''' A subclass of HandheldUI that runs on a SPI ILI9341 display with an XPT2046 touch controller, using the Adafruit Blinka compatibility layer for Jetson SOCs. '''
    def __init__(self, ui_config: ILI9341UIConfig, logger=None):
        import digitalio
        import board
        import fourwire
        import adafruit_ili9341
        import xpt2046_circuitpython as xpt2046
        self.logger = logger or logging.getLogger(__name__)

        reset_pin = digitalio.DigitalInOut(board.pin.Pin(ui_config.reset_pin))
        pwm_pin = digitalio.DigitalInOut(board.pin.Pin(ui_config.pwm_pin))
        touch_cs = digitalio.DigitalInOut(board.pin.Pin(ui_config.touch_cs))
        touch_irq = digitalio.DigitalInOut(board.pin.Pin(ui_config.touch_irq))
        tft_cs = board.pin.Pin(ui_config.cs_pin)
        tft_dc = board.pin.Pin(ui_config.dc_pin)

        self.logger.debug('Starting SPI and reset')
        # Setup SPI bus using hardware SPI:
        spi = board.SPI()
        # RESET pin for display
        reset_pin.direction = digitalio.Direction.OUTPUT
        reset_pin.value = False
        time.sleep(0.005)
        reset_pin.value = True
        time.sleep(0.005)
        # Turn on the display backlight
        pwm_pin.direction = digitalio.Direction.OUTPUT
        pwm_pin.value = True

        self.logger.debug('Initialize bus and display')
        displayio.release_displays()
        display_bus = fourwire.FourWire(spi, command=tft_dc, chip_select=tft_cs, baudrate=ui_config.display_baudrate)
        display = adafruit_ili9341.ILI9341(display_bus, width=ui_config.width, height=ui_config.height, rotation=ui_config.rotation)
        touch = xpt2046.Touch(spi, cs=touch_cs, interrupt=touch_irq, force_baudrate=ui_config.touch_baudrate)

        self.logger.debug('load UI')
        super().__init__(display, touch, self.logger)
    
    @classmethod
    def multiprocess_launch(cls, ui_config: ILI9341UIConfig, rpc_pipe: multiprocessing.connection.Connection, button_queue: multiprocessing.Queue):
        ''' Instantiate a new UI object and continuously check for touch events and requests from a remote process
        This is designed to be run via multiprocessing.Process, and will block until the process is terminated.
        The rpc_pipe is used to receive requests from the main application process, and the button_queue is used to send button press events back to the main application process.  '''
        def button_cb(name):
            button_queue.put(name)
        UI = cls(ui_config)
        for name in UI.buttons:
            UI.subscribe_to_button(name, button_cb)
        UI.logger.debug('loop')
        while True:
            try:
                UI.check_touch()
                if rpc_pipe.poll(0.1):
                    call = rpc_pipe.recv()
                    func = getattr(UI, call.func_name, None)
                    if func is not None:
                        call.execute(func, rpc_pipe)
                    else:
                        UI.logger.error('Unknown RPC function: ' + call.func_name)
            except Exception:
                # Keep the UI subprocess alive no matter what goes wrong in
                # a single iteration - dying here silently closes rpc_pipe,
                # which then surfaces in the *parent* process as a confusing
                # EOFError/UnpicklingError on the next remote_call(), far
                # from the actual cause.
                UI.logger.exception("Unhandled error in UI process loop, continuing")
    
    @classmethod
    def get_remote(cls, rpc_pipe: multiprocessing.connection.Connection):
        ''' Return a proxy object that can be used to call functions in the UI process via the provided pipe.
    The proxy object will have the same methods as the UI class, and will send requests to the UI process and wait for the result.  '''
        # service.py's _update_stats() runs board.memory_text() from a
        # daemon thread every 2s, concurrently with the main thread's own
        # statusbar()/top_text()/bottom_text() calls - both go through this
        # same RemoteUI, i.e. the same multiprocessing.Connection object.
        # Connection.send()/recv() is not safe to call from multiple threads
        # at once: two threads racing here can interleave their pickled
        # writes and each other's reads, which is exactly what produced the
        # EOFError/UnpicklingError seen at startup (right when the main
        # thread's first statusbar() call landed alongside the freshly
        # started stats thread's first memory_text() call) - not a crashed
        # UI subprocess at all, which is why touch handling kept working
        # fine throughout. A lock around each full send+recv round trip
        # serializes RPC calls across threads and fixes it at the source.
        rpc_lock = threading.Lock()

        class RemoteUI:
            def __init__(self, rpc_pipe):
                self.rpc_pipe = rpc_pipe

            def __getattr__(self, name):
                def remote_call(*args):
                    call = UIRPCCall(name, *args)
                    with rpc_lock:
                        return call.send(self.rpc_pipe)
                return remote_call
        return RemoteUI(rpc_pipe)


if __name__ == "__main__":
    import digitalio
    import board
    import fourwire
    import adafruit_ili9341
    import xpt2046_circuitpython as xpt2046


    reset_pin = digitalio.DigitalInOut(board.pin.Pin("GP36_SPI3_CLK"))
    pwm_pin = digitalio.DigitalInOut(board.D18)
    cs_pin = digitalio.DigitalInOut(board.D8)
    dc_pin = digitalio.DigitalInOut(board.D22)
    #reset_pin = digitalio.DigitalInOut(board.D13)
    tft_cs = board.D8
    tft_dc = board.D22
    touch_cs = board.D7
    touch_irq = board.D25

    # Config for display baudrate (default max is 24mhz):
    BAUDRATE = 240000

    # Setup SPI bus using hardware SPI:
    i2c = board.I2C()
    spi = board.SPI()
    # Turn on the display backlight
    pwm_pin.direction = digitalio.Direction.OUTPUT
    pwm_pin.value = True

    # disp = ili9341.ILI9341(spi, rotation=180, width=320, height=240,                           # 2.2", 2.4", 2.8", 3.2" ILI9341
    #                        cs=cs_pin, dc=dc_pin, rst=reset_pin, baudrate=BAUDRATE)
    displayio.release_displays()
    display_bus = fourwire.FourWire(spi, command=tft_dc, chip_select=tft_cs, baudrate=50000000)
    display = adafruit_ili9341.ILI9341(display_bus, width=320, height=240, rotation=90)
    touch = xpt2046.Touch(spi, cs=digitalio.DigitalInOut(touch_cs), interrupt=digitalio.DigitalInOut(touch_irq), force_baudrate=1000000)

    UI = HandheldUI(display, touch)

    while True:
        UI.check_touch()
        time.sleep(0.1)