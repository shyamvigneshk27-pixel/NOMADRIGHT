# SPDX-FileCopyrightText: 2021 Kattni Rembor for Adafruit Industries
#
# SPDX-License-Identifier: MIT

"""Example for Pico. Blinks the built-in LED."""
import time
import board
import digitalio
import microcontroller
import supervisor
import usb_cdc
import neopixel
import busio
import adafruit_drv2605
import adafruit_focaltouch
import displayio
import terminalio
from adafruit_display_text import label, text_box
from adafruit_bitmap_font import bitmap_font
from adafruit_button.button import Button
import fourwire
import adafruit_ili9341
from adafruit_neokey.neokey1x4 import NeoKey1x4
import icons

supervisor.runtime.autoreload = False

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT
butled = digitalio.DigitalInOut(board.D7)
butled.direction = digitalio.Direction.OUTPUT
button = digitalio.DigitalInOut(board.D6)
button.direction = digitalio.Direction.INPUT
button.pull = digitalio.Pull.UP

ser = usb_cdc.console

rgb = neopixel.NeoPixel(board.NEOPIXEL, 1)
rgb.brightness = 0.25

i2c = board.I2C()
spi = board.SPI()
tft_cs = board.D3
tft_dc = board.D2
# Create a NeoKey object
neokey = NeoKey1x4(i2c, addr=0x30)
ts = adafruit_focaltouch.Adafruit_FocalTouch(i2c, debug=False)
# drv = adafruit_drv2605.DRV2605(i2c)

# If you use explicit pins with busio.SPI(...), calling release_displays() first
# prevents "pin in use" errors on subsequent reloads.
displayio.release_displays()
display_bus = fourwire.FourWire(spi, command=tft_dc, chip_select=tft_cs, baudrate=35000000)
display = adafruit_ili9341.ILI9341(display_bus, width=320, height=240, rotation=180)

# Make the display context
layers = displayio.Group()
topbar = displayio.Group()
appui = displayio.Group()
display.root_group = layers

color_bitmap = displayio.Bitmap(320, 240, 1)
color_palette = displayio.Palette(1)
color_palette[0] = 0x000000

bg_sprite = displayio.TileGrid(color_bitmap,
                            pixel_shader=color_palette,
                            x=0, y=0)

# Set text, font, and color
font = terminalio.FONT
color = 0xFFFFFF
color_dim = 0x777777
icon_font = bitmap_font.load_font('forkawesome-16.pcf')
hindi_font = bitmap_font.load_font('NotoSansDevanagari-Regular-12.pcf')

# Create the text label
statusbar = label.Label(font, text=" "*52, color=color_dim)
statusbar.anchor_point = (0.5, 1.0)
statusbar.anchored_position = (160, 240)
statusbar.text = "Initializing..."
topbar.append(statusbar)


modeval = label.Label(font, text=" "*52, color=color_dim)
modeval.anchor_point = (0.0, 0.0)
modeval.anchored_position = (0, 3)
# modeval.text = "App: HearTheWorldEn"
topbar.append(modeval)

# Create the text label
battval = label.Label(icon_font, text=f"{icons.microchip}   {icons.battery_full}   {icons.home}", color=color)
battval.anchor_point = (1.0, 0.0)
battval.anchored_position = (320, 3)
topbar.append(battval)

memval = label.Label(hindi_font, text="    ", color=color)
memval.anchor_point = (1.0, 0.0)
memval.anchored_position = (240, 8)
topbar.append(memval)

toptext = text_box.TextBox(x=0, y=0, width=320, height=100, line_spacing=0.80, font=hindi_font, color=color)
toptext.anchor_point = (0.0, 0.0)
toptext.anchored_position = (0, 16)
appui.append(toptext)


bottomtext = text_box.TextBox(x=0, y=100, width=320, height=100, line_spacing=0.8, font=hindi_font, color=color)
bottomtext.anchor_point = (0.0, 0.0)
bottomtext.anchored_position = (0, 100)
appui.append(bottomtext)

setpage = displayio.Group()

settingslabel = label.Label(font, text=" "*52, color=color)
settingslabel.anchor_point = (0.5, 0.0)
settingslabel.anchored_position = (160, 16)
settingslabel.text = "Settings"
setpage.append(settingslabel)

settings_buttons = {}

input_lang = label.Label(font, text="ASR Lang ", color=color)
input_lang.anchor_point = (0.0, 0.5)
input_lang.anchored_position = (0, 48)
setpage.append(input_lang)

settings_buttons['ASR En'] = Button(
    x=64,
    y=32,
    width=64,
    height=32,
    label="ASR En",
    label_font=hindi_font,
    label_color=0xFF7E00,
    fill_color=0x5C5B5C,
    outline_color=0x767676,
    selected_fill=0x1A1A1A,
    selected_outline=0x2E2E2E,
)

settings_buttons['ASR Hi'] = Button(
    x=64+64,
    y=32,
    width=64,
    height=32,
    label="ASR Hi",
    label_font=hindi_font,
    label_color=0xFF7E00,
    fill_color=0x5C5B5C,
    outline_color=0x767676,
    selected_fill=0x1A1A1A,
    selected_outline=0x2E2E2E,
)

settings_buttons['ASR Ta'] = Button(
    x=64+64*2,
    y=32,
    width=64,
    height=32,
    label="ASR Ta",
    label_font=hindi_font,
    label_color=0xFF7E00,
    fill_color=0x5C5B5C,
    outline_color=0x767676,
    selected_fill=0x1A1A1A,
    selected_outline=0x2E2E2E,
)

output_lang = label.Label(font, text="TTS Lang ", color=color)
output_lang.anchor_point = (0.0, 0.5)
output_lang.anchored_position = (0, 64+32/2)
setpage.append(output_lang)

settings_buttons['TTS En'] = Button(
    x=64,
    y=64,
    width=64,
    height=32,
    label="TTS En",
    label_font=hindi_font,
    label_color=0xFF7E00,
    fill_color=0x5C5B5C,
    outline_color=0x767676,
    selected_fill=0x1A1A1A,
    selected_outline=0x2E2E2E,
)

settings_buttons['TTS Hi'] = Button(
    x=64+64,
    y=64,
    width=64,
    height=32,
    label="TTS Hi",
    label_font=hindi_font,
    label_color=0xFF7E00,
    fill_color=0x5C5B5C,
    outline_color=0x767676,
    selected_fill=0x1A1A1A,
    selected_outline=0x2E2E2E,
)

settings_buttons['TTS Ta'] = Button(
    x=64+64*2,
    y=64,
    width=64,
    height=32,
    label="TTS Ta",
    label_font=hindi_font,
    label_color=0xFF7E00,
    fill_color=0x5C5B5C,
    outline_color=0x767676,
    selected_fill=0x1A1A1A,
    selected_outline=0x2E2E2E,
)

settings_buttons['Reset'] = Button(
    x=64,
    y=192,
    width=64,
    height=32,
    label="Reset",
    label_font=hindi_font,
    label_color=0xFF7E00,
    fill_color=0x5C5B5C,
    outline_color=0x767676,
    selected_fill=0x1A1A1A,
    selected_outline=0x2E2E2E,
)

settings_buttons['Shutdown'] = Button(
    x=64*2,
    y=192,
    width=64,
    height=32,
    label="Shutdown",
    label_font=hindi_font,
    label_color=0xFF7E00,
    fill_color=0x5C5B5C,
    outline_color=0x767676,
    selected_fill=0x1A1A1A,
    selected_outline=0x2E2E2E,
)

settings_buttons['Reboot'] = Button(
    x=64*3,
    y=192,
    width=64,
    height=32,
    label="Reboot",
    label_font=hindi_font,
    label_color=0xFF7E00,
    fill_color=0x5C5B5C,
    outline_color=0x767676,
    selected_fill=0x1A1A1A,
    selected_outline=0x2E2E2E,
)

settings_buttons['ASR En'].selected = True
settings_buttons['TTS En'].selected = True

for but in settings_buttons.values():
    setpage.append(but)

setpage.hidden = True
layers.append(bg_sprite)
layers.append(topbar)
layers.append(appui)
layers.append(setpage)

last_blink = time.monotonic()
last_press = time.monotonic()
last_trigger_button = False
last_touched = False
last_buttons = [False, False, False, False]

def check_buttons(x, y):
    for name in settings_buttons:
        butt = settings_buttons[name]
        if butt.selected:
            continue
        if butt.contains((x, y)):
            names = list(settings_buttons.keys())
            for other in filter(lambda x: x.startswith(name.split(' ')[0]), names):
                settings_buttons[other].selected = False
            if name == 'Reset' or name == 'Reboot' or name == 'Shutdown':
                setpage.hidden = True
                appui.hidden = False
                print('C'+name)
                if name == 'Reboot':
                    time.sleep(0.1)
                    microcontroller.reset()
            else:
                butt.selected = True
            print('C'+name)

led_anim = 0
led_anim_start = 0.0
led_anim_speed = 3.0

def run_led_anim():
    global led_anim_start, led_anim_speed
    offset = (time.monotonic() - led_anim_start) % led_anim_speed
    if offset < led_anim_speed/4:
        intensity = offset / (led_anim_speed/4)
        neokey.pixels[0] = 0x0000FF * (1.0-intensity)
        neokey.pixels[3] = 0x0000FF * (intensity)
    elif offset < (led_anim_speed/4)*2:
        intensity = (offset - (led_anim_speed/4)) / (led_anim_speed/4)
        neokey.pixels[1] = 0x0000FF * (1.0-intensity)
        neokey.pixels[0] = 0x0000FF * (intensity)
    elif offset < (led_anim_speed/4)*3:
        intensity = (offset - (led_anim_speed/4)*2) / (led_anim_speed/4)
        neokey.pixels[2] = 0x0000FF * (1.0-intensity)
        neokey.pixels[1] = 0x0000FF * (intensity)
    else:
        intensity = (offset - (led_anim_speed/4)*3) / (led_anim_speed/4)
        neokey.pixels[3] = 0x0000FF * (1.0-intensity)
        neokey.pixels[2] = 0x0000FF * (intensity)

    

def parse_msg(msg):
    global led_anim, led_anim_start
    try:
        if msg is None or len(msg) < 1:
            return
        if msg[0] == 'l':
            butled.value = int(msg[1:])
        elif msg[0] == 'L':
            idx = int(msg[1])
            if idx < 0 or idx > 4:
                raise ValueError("NeoKey index must be 0-4")
            if idx < 4:
                vals = tuple(int(x) for x in msg[2:].split(','))
                val = vals[2] & 0xFF | ((vals[1] & 0xFF) << 8) | ((vals[0] & 0xFF) << 16)
                neokey.pixels[idx] = val
            if idx == 4:
                rgb[0] = tuple(int(x) for x in msg[2:].split(','))
        elif msg[0] == 'b':
            rgb.brightness = float(msg[1:])
        elif msg[0] == 'd' and msg[0:4] == 'disp':
            # Previously used eval() which is unsafe; display commands via serial are no longer supported
            pass
        elif msg[0] == 'T':
            if msg[1] == 'S':
                statusbar.text = msg[2:].strip()
            elif msg[1] == 'T':
                toptext.text = msg[2:].strip()
            elif msg[1] == 'B':
                bottomtext.text = msg[2:].strip()
            elif msg[1] == 'M':
                modeval.text = msg[2:].strip()
            elif msg[1] == 'm':
                memval.text = msg[2:].strip()
            else:
                print(msg[0]+'Unk')
                return
        elif msg == 'reboot':
            microcontroller.reset()
        elif msg[0] == 'a':
            led_anim_start = time.monotonic()
            led_anim = int(msg[1:])
            if led_anim == 0:
                neokey.pixels[0] = 0
                neokey.pixels[1] = 0
                neokey.pixels[2] = 0
                neokey.pixels[3] = 0
            else:
                neokey.pixels[0] = 0x0000FF
                neokey.pixels[1] = 0x0000FF
                neokey.pixels[2] = 0x0000FF
                neokey.pixels[3] = 0x0000FF
        else:
            print(msg[0]+'Unk')
            return
        print(msg[0]+'OK')
    except Exception as e:
        print(msg[0]+'ERR: '+str(e))

try:
    msg_buf = b''
    while True:
        if (time.monotonic() - last_blink) > 0.5:
            led.value = not led.value
            last_blink = time.monotonic()
        button_val = button.value
        if button_val != last_trigger_button and (time.monotonic() - last_press > 0.1):
            last_press = time.monotonic()
            # butled.value = not button_val
            print("BT"+str(int(button_val)))
            last_trigger_button = button_val
        buttons = neokey.get_keys()
        if buttons[0] != last_buttons[0]:
            print("BA"+str(int(buttons[0])))
            neokey.pixels[0] = 0x0000FF * buttons[0]
            if buttons[0]:
                setpage.hidden = not setpage.hidden
                appui.hidden = not setpage.hidden
        if buttons[1] != last_buttons[1]:
            print("BB"+str(int(buttons[1])))
            neokey.pixels[1] = 0x0000FF * buttons[1]
        if buttons[2] != last_buttons[2]:
            print("BC"+str(int(buttons[2])))
            neokey.pixels[2] = 0x0000FF * buttons[2]
        if buttons[3] != last_buttons[3]:
            print("BD"+str(int(buttons[3])))
            neokey.pixels[3] = 0x0000FF * buttons[3]
        last_buttons = buttons
        if ts.touched != last_touched:
            if ts.touched:
                for touch in ts.touches:
                    y = 240-touch["x"]
                    x = touch["y"]
                    check_buttons(x, y)
            last_touched = ts.touched
        if led_anim > 0:
            run_led_anim()
        if ser.in_waiting:
            # Read all available bytes from serial port
            msg_buf += ser.read(ser.in_waiting)
            # Extract any messages delimited by '\n' or '\r'
            while '\r' in msg_buf or '\n' in msg_buf:
                if '\r' in msg_buf:
                    msg = msg_buf[:msg_buf.find(b'\r')].strip().rstrip()
                    parse_msg(msg.decode('utf-8'))
                    msg_buf = msg_buf[msg_buf.find(b'\r')+1:]
                elif '\n' in msg_buf:
                    msg = msg_buf[:msg_buf.find(b'\n')].strip().rstrip()
                    parse_msg(msg.decode('utf-8'))
                    msg_buf = msg_buf[msg_buf.find(b'\n')+1:]
except Exception as e:
    print(f"Caught Exception: {e}")
    print("Reloading in 1 second")
    time.sleep(1)
    supervisor.reload()
