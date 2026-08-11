# IO Expander

## Overview
This is a CircuitPython project for a Seeeduino XIAO RP2350 microcontroller. This codebase was last tested on v10.0.3, but any v10.x firmware should work.

The IO Expander is a component of the original Suno Sutra prototype. This component is necessary when using the original Seeeedstudio ReComputer Mini carrier board, because it does not expose enough level-shifted GPIO lines to run the Suno Sutra project. Instead of adding an extension board to the carrier, or designing our own custom carrier, we opted to add this IO expander to the project to work around the issue.

The IO expander is a tiny Seeedstudio XIAO RP2350 development board that connects to the main carrier board over USB 2.0. It has the following features:
* Connects to the trigger button and reports button changes over USB
* Connects to the 4x1 NeoKey button matrix over i2c, reports changes and allows LEDs to be controlled over USB
* Connects to the drv2605l vibration motor controller over i2c, allows haptic vibrations to be played
* Connects to an ili9341 TFT touchscreen over SPI
* Implements a basic UI using Adafruit displayio: 
    * Text areas for query and response can be updated over USB
    * Button presses will be reported back over USB

Going forward, it is likely this IO expander will be deprecated in favor of running hardware directly off the Jetson.

## Installation

### Initial Setup: CircuitPython
The Seeeeduino XIAO tends to ship with MicroPython - it requires a one-time update to CircuitPython before use.
* Download a copy of CircuitPython compiled for the rp2350 from [circuitpython.org/board/seeeduino_xiao_rp2340](https://circuitpython.org/board/seeeduino_xiao_rp2350/)
* Hold down the BOOT botton on the XIAO while plugging it into a PC using a USB-C cable. The device should enumerate as a flash storage device.
* Copy the circuitpython .uf2 file onto the flash drive
* Eject the flash drive safely
* Reboot the XIAO, it should enumerate as several compound USB devices: a flash drive, a USB CDC serial interface, MIDI, etc

### Deploying Code

After flashing with circuitpython, simply copy the contents of this folder onto the flash storage device that appears when the RP2350 is connected to the PC.

In order for new code to take effect, the XIAO may need to be reset OR can be reset using the serial terminal (in some builds, autoreload may be disabled).

## Operation

The IO Expander is primarily controlled from [the IOInterface class](../python/pocketinfer/serialcomms.py), but in a nutshell the device communicates through simple newline (`\r\n`) delimited messages. They are organized based on the first letter of the line:
* `l` toggle trigger button LED on and off. `l0` for off, `l1` for on
* `L` set the value of an RGB LED. LEDs 0-3 correspond to LEDs installed behind each of the 4 buttons, and LED 4 is onboard the XIAO itself. Color is expressed as R, G and B values from 0-255. So `L0255,0,0` will turn LED0 red, and `L30,0,64` will turn LED3 dimly green.
* `b` controls the overall brightness of the onboard XIAO RGB LED, as a floating point value from 0.0-1.0
* `T` updates text on the display:
    * `TS` controls the statusbar at the bottom of the screen
    * `TT` sets text on the top half of the application screen
    * `TB` sets text on the bottom half of the application screen
    * `TM` controls the mode text in the upper-left hand corner
    * `Tm` updates the memory utilziation value
    * So for example `TBsample text` will display "sample text" on the screen, and `Tm94%` will update memory utilization to 94%
* `reboot` will reboot the XIAO
* `a` controls LED animation. Setting `a0` will disable the LED animation. Otherwise:
    * `a1` will display a "breathing" animation on the 4 NeoKey LEDs while the device is processing.

Note also that some messages will be spotaneously emitted by the IO Expander in response to user input:
* `B` messages will be emitted on button press:
    * `BT` is the trigger button
    * `BA` through `BD` are the NeoKey buttons, from left to right
    * a 1 value will be emitted when the button is pressed, and a 0 value will be emitted when the button is released.
    * So `BT1` means the trigger button was pressed, and `BC0` means the 3rd Neo key was released.
* `C` messages will be emitted when a button is pressed on the touchscreen GUI. The argument is the name / text of the button
    * `CReset`, `CReboot`, `CShutdown` for system control
    * `CASR En`, `CASR Hi`, `CASR Ta` for control over ASR language
    * `CTTS En`, `CTTS Hi`, `CTTS Ta` for control over TTS language

### Debugging

Connect to the USB CDC port using a serial console application to monitor program output. When modifications are made to code.py, the program can be reloaded by pressing `Ctrl-D` in the serial console. `Ctrl-C` can be pressed to pause program execution and enter the Python REPL. 