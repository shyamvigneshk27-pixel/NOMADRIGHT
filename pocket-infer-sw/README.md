# Suno Sutra Software

This repository contains all of the software required to prepare and operate a Suno Sutra pocket inference device. Suno Sutra is an open platform for running local AI inference at the edge. This software project can be used to quickly develop an application that takes audiovisual input from the world and runs it through one or more AI models.

At it's core, Suno Sutra is an embedded linux device with application code running in Python. The python module can be used to describe applications that communicate with the UI (screen, buttons, microphone, speaker) and run AI inference on an array of supported models. Since this is an embedded linux project, users can also simply shell into the device and install whatever software they like. However the application framework aims to simplify and streamline development. Break free from it if you like!

<a href="./assets/SunoSutra High-level Software Architecture.png"><img src="./assets/SunoSutra High-level Software Architecture.png" width="80%"></img></a>

# Software Components / Navigation

* [rootfs](./rootfs/) For information about how to prepare a Root Filesystem image, to install dependencies or update dependencies.
* [python](./python/) For information about the python library, which includes the Hardware Abstraction Layer (HAL), application templates and registry, model wrappers, application code and service.
* [Python templates](./python/pocketinfer/applications/) for defining applications to run on device
* A [Python service](./python/pocketinfer/service.py) that can serve applications on the device
* [ioexpander](./ioexpander/) firmware relating to the IO Expander component.

# Quickstart

## Running the application

### Devices with a UI (Handheld)

The Suno Sutra Demo device and other devices with a screen / UI should boot directly into the application. It could take around 30-60 seconds after applying power, after which the status bar at the bottom should display "ready".

Operation will depend on the default application. For example, for the "Hear the World" application, follow these steps:
1. Aim the device at a scene of interest
1. Press down the trigger button. The device will snap a photo.
1. Ask a question about your environment
1. Release the trigger button
1. After a short delay, the device will show the answer on the screen and read it back on the speaker

Press the back button (left-most button on the rear of the device) to open up the setings UI. You can use the touchscreen or device buttons to navigate. For the "Hear the World" demo, the input and output languages can be changed. And the settings UI can be used to switch between other applications. 

### Devices without a UI (Development Board)

The development board lacks a screen / UI, so it must be activated using a SSH console. The primary method of interaction is to manually execute the `pocketinfer-service` application and watch it's output.

If you have not assembled the development kit, see the [SunoSutraDevboard assembly-instructions](https://github.com/currentai-org/suno-sutra-hw/tree/main/SunoSutraDevboard#assembly-instructions)

1. Connect a USB cable to a Suno Sutra prototype device.
    * For a Suno Sutra Devboard, connect using the USB-C jack
    * For a Suno Sutra Demo (or other devices based on the Seeedstudio Mini ReComputer carrier board`), connect using the USB-Micro jack
    * The device should enumerate as a USB RNDIS (Ethernet) network device, as well as a USB CDC device for fallback terminal access.
1. Open a terminal and execute `ssh ubuntu@192.168.55.1` with password `ubuntu`. 
1. Execute `pocketinfer-service` to run the default application
    * For example, for the "Hear the World" sample application:
    1. Aim the device at a scene of interest
    1. Touch the capacitive touch button. The device will snap a photo.
    1. Ask a question about your environment (using the microphone inside of the camera)
    1. Release the button
    1. After a short delay, the device will print the result to the screen read it back on the speaker

For other options, see `pocketinfer-service --help`

## Development Quickstart

This section implies you have access to a Suno Sutra prototype device and have connected to over USB. The device should enumerate as a USB RNDIS (Ethernet) network device, as well as a USB CDC device for fallback terminal access. 

The easiest way to get up and running is to SSH into the device by executing `ssh ubuntu@192.168.55.1` with password `ubuntu`. Then the software can be edited directly on the device's filesystem. You could consider using VSCode with the Remote - SSH extension. For simplicity here's a sample way to get started that's fully terminal-based:

* Open a terminal and execute `ssh ubuntu@192.168.55.1` with password `ubuntu`
* Execute `cd ~/pocket-infer-sw/python/ && ls` to navigate to the python module you'll want to be editing
* Create a new application from the template by executing `cp applications/hear_the_world_en.py applications/<new name>.py`
* Edit the file with `vim applications/<new name>.py`. Rename the class from `HearTheWorldEn` to the name of your new application
* Edit the application manifest (which follows after `@RegisterApplication`). Update the name/description fields accordingly, and select any models and service_dependencies required by the application
* Implement your desired application in the `run(self)` method of the Application class - see comments for examples and tips
* Launch the application:
    * For the Suno Sutra Demo or devices with UI: Execute `sudo systemctl restart pocketinfer && journalctl -f -u pocketinfer` to restart the system service and view live logs. Use the device UI to activate the new application, and then watch the terminal 
    * For the Suno Sutra Devboard or devices without a UI: Execute `pocketinfer-service --app <new name>` to run the new application

## Hardware / Software Support

Suno Sutra was originally developed for the NVIDIA Jetson Orin Nano 8GB module, on Jetpack 6.2. However this project aims to be flexible to the underlying platform and support may be added for more platforms in the future. Here's the current status:

Platform:
* NVIDIA Jetson / Jetpack 6.2: Fully Supported
    * Other Jetpack versions: Untested
* Raspberry Pi 5: Not Supported yet
* Generic Linux: Not Supported Yet

Module:
* NVIDIA Jetson Orin Nano 8GB: Fully Supported
* NVIDIA Jetson Orin NX 8GB: In progress
* NVIDIA Jetson Orin NX 16GB: In progress
* NVIDIA jetson Thor: Not Supported Yet
* Raspberry Pi CM5: Not Supported Yet
* Hailo-10L: Not Supported Yet

Motherboard / Carrier Board / Development Board:
* NVIDIA Orin Nano 8GB Super Development Kit: Fully Supported
* Seeeedstudio ReComputer Mini Carrier Board: Fully Supported
* Waveshare NVIDIA Orin NX 16GB Development Kit: In Progress

# Contribution / Development Tips

### Platform

To add support for a new platform, you will need to first define a base system image to start from. For the Jetson, this is the image provided by JetPack. Then starting from this base image, the Ansible roles in the [rootfs/roles](./rootfs/roles/) folder will need to be updated / specified.

Then it will be likely that a new board object will need to be created to capture any differences in the new platform. The new board object should be a subclass of the base Board object. Also be sure to update the `Board.get_board()` classmethod with code to auto-detect the new board.

### Model

To add support for a new model, first add an ansible role that will pull down any necessary system dependencies. If the new model requires a different set of python dependencies from [this module's requirements](./python/requirements.txt), then it's recommended to install and run the model from it's own virtual environment and create a simple API service.

Next write a new model python class, subclassed on the base model class. Define a `verify()` classsmethod that can check that the model is available and reayd for use. Define an `update()` classmethod that can be used to download any models or updates to the model. The `args` argument to these methods is a dictionary containing whatever values are specified in the application manifest decorator. So it may be helpful to also spin up a test application.