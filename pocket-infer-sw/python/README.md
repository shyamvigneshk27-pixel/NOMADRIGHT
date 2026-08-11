# pocketinfer Python module

### Overview

This python module contains application-level code for the Suno Sutra project. Although any code could be deployed directly to the underlying linux system as desired, this codebase may be necessary to interact with the rest of the Suno Sutra hardware such as the screen and buttons.

Furthermore, by implementing inference applications in this project, applications can be managed from within the TFT touchscreen GUI, allowing the user to switch applications with ease.

### Supported Environments

Each supported environment for this project will be implemented as a subclass in the [board](./board.py) module. For example:
* `PocketInferDemo` will run on an NVIDIA Jetson Orin Nano 8GB inserted into a Seeedstudio ReComputer Mini carrier board, with full support for the handheld UI
* `PocketInferDevboard` will run on an NVIDIA Jetson Orin nano 8GB development board, as a desk-top development environment. Not all UI elements may be supported
* `DummyBoard` is designed to run on an NVIDIA Jetson Orin Nano 8GB system without any UI at all (totally headless). It's used for automated testing. However it may be compatible with other ARM linux environments.

### CLI Applications / Entry Points

Once installed, this module will also create a `pocketinfer-service` application which is installed as a systemd service called `pocketinfer.service`. See `pocketinfer-service --help` for more info, but generally executing `sudo systemctl restart pocketinfer` will ensure that the service is running and will execute application code on the UI.

## Installation
On the Suno Sutra prototype, this repository is typically installed to `/home/ubuntu/pocket-infer-sw` (but check the [ansible task](../rootfs/roles/app/tasks/main.yaml) to be sure). 

It's recommended to use this code from within a python virtual environment:
* Create a virtual environment - `virtualenv /home/ubuntu/pocket-infer-sw/python/venv`
* Activate the environment - `source /home/ubuntu/pocket-infer-sw/python/venv/bin/activate`
* Install this package - `pip install -e /home/ubuntu/pocket-infer-sw/python/`

Python dependencies should be installed automatically. However they can also be installed by executing `pip install -r requirements.txt` from within the virtualenv. 

There are some additional system dependencies. See [the ansible task](../rootfs/roles/app/tasks/main.yaml) for a complete listing, but generally: `sudo apt install libasound-dev portaudio19-dev libportaudio2 ffmpeg flac` should cover what's needed for the base application.

Note that many more dependencies are needed for AI model support. They are too numerous to list here, see the [ansible folder](../rootfs/) for more information. 

### System Service

If installed to `/home/ubuntu/pocket-infer-sw/python/venv` like recommened above, then the provided [systemd service file](./pocketinfer.service) can be used to run the service automatically:
* `sudo cp ./pocketinfer.service /etc/systemd/system/`
* `sudo systemd daemon-reload`
* `sudo systemd enable pocketinfer`
* `sudo systemd start pocketinfer`

Logfiles can be monitored by executing `journalctl -f -u pocketinfer`

Note that superuser permissions are needed for a few things:
* Automatically starting other services (such as for models) that also require superuser permissions
* System management (rebooting, shutdown, etc)

# Codebase

Here are some files / classes of note:
* [service.py](./pocketinfer/service.py) contains source code for the `pocketinfer-service` CLI tool
* [board.py](./pocketinfer/board.py) contains the root Board object and Hardware Abstraction Layer (HAL). This object is the main way for the Application to communicate with the Suno Sutra hardware.
* [audio.py](./pocketinfer/audio.py) contains helper classes for recording and playing audio using ALSA / pyaudio.
* [serialcomms.py](./pocketinfer/serialcomms.py) contains a helper class for communicating with the IO Expander over a USB CDC port
* [applications/base.py](./pocketinfer/applications/base.py) contains the BaseApplication class that all applications should subclass from
* [application/hear_the_world_en.py](./pocketinfer/applications/hear_the_world_en.py) is a simple application that might be useful as an example
* [models/](./pocketinfer/models/) folder contains thin wrapper classes around many AI models that the Application classes can use for inference.