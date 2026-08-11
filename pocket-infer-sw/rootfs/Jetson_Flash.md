# Flashing a Jetson-based device

The instructions should be similar for all Jetson platform devices, with small differences on cable and jumper locations.

## Jetson Orin Nano Development Board

Here are step-by-step instructions for a Jetson Orin Nano Super Developer Kit:

### Unboxing and Entering Recovery Mode

<a href="../assets/jetson_prog_outer_box.jpg"><img src="../assets/jetson_prog_outer_box.jpg" width="50%"></img></a>

First unpack the kit contents, you should have a Jetson Orin Nano development board and a power adapter with two cable options

<a href="../assets/jetson_prog_contents.jpg"><img src="../assets/jetson_prog_contents.jpg" width="50%"></img></a>

Next, locate the MicroSD card holder. If using a MicroSD card for storage, insert it into this small slot. Make sure the metal contacts on the MicroSD card are oriented upwards.

<a href="../assets/jetson_prog_sd_location.jpg"><img src="../assets/jetson_prog_sd_location.jpg" width="50%"></img></a>

If using a SSD for storage, check the bottom side of the development board for M.2 sockets.

Next locate some female-to-female jumper wire or a shunt jumper, We will need to jumper between two pins on the side of the development kit

<a href="../assets/jetson_prog_jumper_wire.jpg"><img src="../assets/jetson_prog_jumper_wire.jpg" width="50%"></img></a>

Connect the jumper wire between the 3rd and 4th pins from the far side of the development board. The "FC_REC" pin should be connected to "GND" via this operation:

<a href="../assets/jetson_prog_jumper_location.jpg"><img src="../assets/jetson_prog_jumper_location.jpg" width="50%"></img></a>

Here's what it looks like with female-to-female jumper wire connected.

<a href="../assets/jetson_prog_jumper_installed.jpg"><img src="../assets/jetson_prog_jumper_installed.jpg" width="50%"></img></a>

Finally, connect the power adapter and a USB-C cable to the corresponding ports on the development board. 

<a href="../assets/jetson_prog_cable_location.jpg"><img src="../assets/jetson_prog_cable_location.jpg" width="50%"></img></a>

The USB-C cable should be connected to a Ubuntu 22.x or 24.x PC, or to a windows PC with WSL. The power cable should be connected to AC power. and should enumerate as an "APX" device.

<a href="../assets/jetson_prog_ready.jpg"><img src="../assets/jetson_prog_ready.jpg" width="50%"></img></a>

### Flashing using SDK Manager

If you are running a Ubuntu 22.04 or 24.04 PC, you can proceed with these instructions.

If you are running a Windows PC, you will need to first install WSL2 with Ubuntu 24.04 as the OS. See [ubuntu.com:install-ubuntu-wsl2](https://ubuntu.com/wsl/docs/stable/howto/install-ubuntu-wsl2/). You will also need to install the Zadig APX driver by following [these instructions](https://developer.nvidia.com/w/sdkmanager/resources/help/index.html#apx-driver). Make sure the development board is powered on and connected to the test PC as per the instructions above before installing the driver. 

Previously SDK manager needed to be run from within the WSL2 environment. However recent releases of SDK manager can be run directly from the Windows host OS. Other steps, such as rootfs provisioning in Ansible, will require WSL2 to be run. So for any of the following steps requiring a command to be run from a termianl, please open a WSL2 terminal by pressing the window key and typing `ubuntu`.

Next install the [NVIDIA SDK Manager tool](https://developer.nvidia.com/sdk-manager#i7njvai) to the PC. Note that you will need to register for a NVIDIA developer account in order to access some SDKs. But once SDKs are downloaded it's not necessary to remain logged into the NVIDIA developer account.

Launch SDK manager. The Jetson development boards should be detected and SDK manager should display the following pop-up. Select the "Developer Kit Version" entry from the list and press OK

<a href="../assets/sdk_manager_board_detected.png"><img src="../assets/sdk_manager_board_detected.png" width="70%"></img></a>

Next make the following selections:
* Ensure that "Jetson" is the only entry selected at the top
* Ensure that "Host Machine" is deselected, and "Target hardware" is selected
* Ensure the latest JetPack 6.x.y is selected
    * (At the time of this writing, Jetpack 7 does not support the Orin Nano 8GB, and 6.2.2 was the latest JetPack release)
* Ensure no additional SDKs are selected

Then press Continue

<a href="../assets/sdk_manager_step01_selection.png"><img src="../assets/sdk_manager_step01_selection.png" width="70%"></img></a>

When prompted, enter your Sudo password (often the same password you used to log into the PC)

<a href="../assets/sdk_manager_step02_sudo.png"><img src="../assets/sdk_manager_step02_sudo.png" width="70%"></img></a>

SDK manager will take a few minutes to prepare for the next step

<a href="../assets/sdk_manager_step02_process.png"><img src="../assets/sdk_manager_step02_process.png" width="70%"></img></a>

Next, make the following selections:
* Ensure that the "Jetson Linux" entry is selected, and all sub-items are also selected
* Ensure that "Jetson Runtime Components" is selected, and all sub-items are also selected
* Ensure that "Jetson SDK Components" is NOT selected, and nothing else below in the is selected
* Check the box marked "I accept the terms and conditions"
* Click the Continue button

If doing this for the first time, it may take a long time to download the pre-requisites.

<a href="../assets/sdk_manager_step02_selection.png"><img src="../assets/sdk_manager_step02_selection.png" width="70%"></img></a>

Once the necessary dependencies are downloaded, SDK Manager will begin preparing the system image:

<a href="../assets/sdk_manager_step03_progress_making_image.png"><img src="../assets/sdk_manager_step03_progress_making_image.png" width="70%"></img></a>

Once the system image is complete, SDK manager will show the following prompt.
* Enter "ubuntu" as the username
* Enter "ubuntu" as the password
* Under "Storage Device", select "SD Card" if a MicroSD card was selected as the storage medium, or "NVME" if an SSD was selected.
* Click "Flash"

<a href="../assets/sdk_manager_step03_preconfig_settings.png"><img src="../assets/sdk_manager_step03_preconfig_settings.png" width="70%"></img></a>

SDK manager will begin flashing the system image to the device

<a href="../assets/sdk_manager_step03_progress_flashing.png"><img src="../assets/sdk_manager_step03_progress_flashing.png" width="70%"></img></a>

Once flashing is complete, SDK manager will show the following prompt. The default values should work, but triple check they match this image. Then Click Install.

<a href="../assets/sdk_manager_step03_network_settings.png"><img src="../assets/sdk_manager_step03_network_settings.png" width="70%"></img></a>

Finally, once the flashing is complete you should see this screen.

<a href="../assets/sdk_manager_step03_progress_installing.png"><img src="../assets/sdk_manager_step03_progress_installing.png" width="70%"></img></a>

**Remove the jumper wire before proceeding**

### Provisioning with Ansible

First, it's a good idea to verify the development board is connected and communicable. Open a terminal and execute

```
ssh ubuntu@192.168.55.1
```
Use password `ubuntu` when prompted. You should be greeted with a login prompt.

Next we will need to get the Jetson board connected to the internet in order to pull additional dependencies. There are two methods for this:

**Sharing the network connection over USB**

The Jetson will show up as a USB Ethernet device to the development PC. One quick way to give the jetson internet access is to configure the development PC to share it's network connection with this USB Ethernet device. See [this post](https://askubuntu.com/questions/1104506/share-wireless-internet-connection-through-ethernet-on-18-04-lts) for a step-by-step walkthrough.

Alternatively, if connection sharing isn't working out you can configure the Jetson to connect directly to your local Wifi hotspot:

**Connecting over Wifi**

```
sudo nmcli device wifi connect <SSID> password <PASSWORD>
```

Enter the sudo password `ubuntu` when prompted. You should see `Device 'wlP1p1s0' successfully activated with '<UUID>'.` in response after a short wait.

You may want to verify this has worked by executing `ping www.google.com` in the Jetson terminal window. You should see output like this:
```
ubuntu@pocket-infer-6a8f:~$ ping www.google.com
PING www.google.com (142.250.189.196) 56(84) bytes of data.
64 bytes from sfo03s25-in-f4.1e100.net (142.250.189.196): icmp_seq=1 ttl=114 time=25.5 ms
64 bytes from sfo03s25-in-f4.1e100.net (142.250.189.196): icmp_seq=2 ttl=114 time=33.0 ms
```

**Provisioning with Ansible**

First, on the development PC, ensure that the `ansible-core` package is installed. This can be done by executing `sudo apt install ansible ansible-core`.

Next clone this repository to the development PC (or [Download it](../archive/refs/heads/main.zip) and extract it to a folder on the PC)

Finally execute the following command in a new terminal:
```
ansible-playbook -i inventory.ini install_all_usb.yml
```

You should see output like this as Ansible begins installing dependencies
```
tergia@tergia-T490:~/build/CurrentAI/pocket-infer-sw/rootfs$ ansible-playbook -i inventory.ini ./install_all_usb.yml

PLAY [usb] ************************************************************************************************************************************************************************************************************************************************************************************************************************************************************************************

TASK [Gathering Facts] ************************************************************************************************************************************************************************************************************************************************************************************************************************************************************************
ok: [192.168.55.1]

TASK [initial : Collect serial-number] ********************************************************************************************************************************************************************************************************************************************************************************************************************************************************
changed: [192.168.55.1]

TASK [initial : Collect hostname] *************************************************************************************************************************************************************************************************************************************************************************************************************************************************************
changed: [192.168.55.1]

TASK [initial : Set Hostname] *****************************************************************************************************************************************************************************************************************************************************************************************************************************************************************
changed: [192.168.55.1]

TASK [initial : Store hostname] ***************************************************************************************************************************************************************************************************************************************************************************************************************************************************************
changed: [192.168.55.1]

TASK [initial : Disable GUI session] **********************************************************************************************************************************************************************************************************************************************************************************************************************************************************
changed: [192.168.55.1]
[...]
PLAY RECAP ************************************************************************************************************************************************************************************
192.168.55.1               : ok=31   changed=14   unreachable=0    failed=0    skipped=1    rescued=0    ignored=0   

```

# Troubleshooting

### APX Driver Not FOund

If during the SDK manager install process you see "APX Driver Not Found":

<a href="../assets/troubleshooting_apx_fail.png"><img src="../assets/troubleshooting_apx_fail.png" width="70%"></img></a>

Ensure the NVIDIA APX driver is installed [using these instructions](https://developer.nvidia.com/w/sdkmanager/resources/help/index.html#apx-drive)

### SDK Manager fails to detect jetson when installing SDK components

If the SDK manager install process gets stuck on this screen:

<a href="../assets/sdk_manager_step03_network_settings.png"><img src="../assets/sdk_manager_step03_network_settings.png" width="70%"></img></a>

But the Jetson isn't detected in the "Selected Device" field:
* Remove the jumper wire required to put the Jetson into recovery mode
* Disconnect power from the jetson and then reconnect it, to force reboot into normal mode

If running using WSL2, you may also need to force WSL2 to use the `mirrored` networking mode to remove NAT between SDK Manager and the local network. Edit `%UserProfile%\.wslconfig` and add the following lines:

<a href="../assets/troubleshooting_networking_wsl2.png"><img src="../assets/troubleshooting_networking_wsl2.png" width="70%"></img></a>

NOTE: Ensure that the path matches the version of JetPack being used.

### SSH or Ansible fails to connect to the Jetson after flashing

For example, if you see the following Ansible error:

<a href="../assets/troubleshooting_ansible_ssh_host_key_checking.png"><img src="../assets/troubleshooting_ansible_ssh_host_key_checking.png" width="70%"></img></a>

Try the following:

<a href="../assets/troubleshooting_ansible_ssh_known_hosts.png"><img src="../assets/troubleshooting_ansible_ssh_known_hosts.png" width="70%"></img></a>