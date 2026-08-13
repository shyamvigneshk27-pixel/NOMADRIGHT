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

    def __init__(self, display, touch, logger=None):
        ''' Load the UI into memory'''
        self.logger = logger or logging.getLogger(__name__)
        self.display = display
        self.touch = touch

        self.button_cbs = {}
        self.buttons = {}

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
            self.buttons[name].selected = False # leave button deselected
            if self.setpage.hidden:
                self.setpage.hidden = False
                self.appui.hidden = True
            else:
                self.setpage.hidden = True
                self.appui.hidden = False

        self.topbar.append(self._button('Home', x=320-28, y=0, width=28, height=28, label=icons.home, font=self.ICON_FONT,
                                        label_color=color, fill_color=0x000000, outline_color=0x000000))
        self.topbar.append(self._button('Settings', x=320-28*2, y=0, width=28, height=28, label=icons.book, font=self.ICON_FONT,
                                        label_color=color, fill_color=0x000000, outline_color=0x000000, cb=_toggle_setpage))
        # NomadRight's form-reading flow (see nomad_right/app.py's ui_cb):
        # captures a photo via board.camera_frame_jpg() and waits for the
        # worker's next spoken question about it. Apps that don't subscribe
        # to the "Camera" message simply never receive it - safe to always
        # show.
        self.topbar.append(self._button('Camera', x=320-28*3, y=0, width=28, height=28, label=icons.camera, font=self.ICON_FONT,
                                        label_color=color, fill_color=0x000000, outline_color=0x000000))

        # Create the text label
        self.battval = label.Label(self.ICON_FONT, text=f"{icons.microchip}     {icons.battery_full}", color=color)
        self.battval.anchor_point = (1.0, 0.0)
        self.battval.anchored_position = (320-28*3-4, 3)
        self.topbar.append(self.battval)

        self.memval = label.Label(self.HINDI_FONT, text="    ", color=color)
        self.memval.anchor_point = (1.0, 0.0)
        self.memval.anchored_position = (320-28*5-4, 8)
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
            self.setpage.hidden = True
            self.appui.hidden = False

        self.setpage.append(self._button('Reset', x=64, y=192, cb=_close_setpage))
        self.setpage.append(self._button('Shutdown', x=64*2, y=192, cb=_close_setpage))
        self.setpage.append(self._button('Reboot', x=64*3, y=192, cb=_close_setpage))

        self.setpage.hidden = True
        # self.layers.append(bg_sprite)
        self.layers.append(self.topbar)
        self.layers.append(self.appui)
        self.layers.append(self.setpage)

    def get_button_names(self):
        ''' Return a list of all button names in the UI '''
        return list(self.buttons.keys())
    
    def get_button_status(self):
        ''' Return a dict of button names and their selected status (True/False) '''
        return {name: self.buttons[name].selected for name in self.buttons.keys()}

    def _button(self, name, x, y, label=None, font=None, width=64, height=32,
                label_color=0xFF7E00, fill_color=0x5C5B5C, outline_color=0x767676, cb=None, selected=False):
        ''' Create a button and add it to the button list. If a callback is provided, it will be called when the button is pressed.
        Note that the button object returned should be added to the correct Group for it to be displayed'''
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
    
    def mode_text(self, text):
        ''' Set the Mode value, in the upper left hand corner. '''
        self.modeval.text = text

    def memory_text(self, text):
        ''' Set the RAM usage value. '''
        self.memval.text = text
    
    def clear_screen(self):
        self.toptext.text = ""
        self.bottomtext.text = ""
        self.statusbar.text = ""
        self.modeval.text = ""
        self.memval.text = ""

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
        ''' Check if a touch event at (x, y) is within any button, and if so, call the callback for that button. '''
        for name in self.buttons:
            butt = self.buttons[name]
            if butt.selected:
                continue
            if butt.contains((x, y)):
                butt.selected = True
                self._dispatch_button_cb(name)

    def check_touch(self):
        # TODO - this is specific to the xpt2046 controller and involves SPI internals, should be made generic or moved out
        # It's possible this method was called while the display is in in the process of a refresh and is using the SPI bus
        # IF that's the case, the touch read will fail and throw an exception, which we catch and ignore. This is not ideal, but it works for now.
        import xpt2046_circuitpython as xpt2046
        try:
            if self.touch.is_pressed():
                    args = self.touch.get_coordinates()
                    if args is not None:
                        # NOTE, this implies 90 degree rotation on the display
                        # TODO - make this more robust to different rotations and touch coordinate mappings
                        y, x = args
                        y = 240 - y
                        print(f"Touch at ({x}, {y})")
                        self.check_buttons(x, y)
        except xpt2046.ReadFailedException as e:
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