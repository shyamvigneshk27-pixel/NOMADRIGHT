# Root File System (RootFS) Provisioning

The Suno Sutra platform can be configured to run on any number of hardware platforms. As such, there is no single system image or rootfs. Instead, each hardware platform will start from it's own base image and will be configured / provisioned with dependencies needed for this project. 

Provisioning will be done with Ansible. Ansible is the only pre-requisite - in theory everything else should be installable using the roles and playbook. Check the ansible docs for how to install it on the base system image - usually the `ansible-core` package is sufficient.

## NVIDIA Jetson

For step-by-step flashing instructions, see [Jetson_Flash](./Jetson_Flash.md)

The rootfs is built upon nvidia jetpack v6.2.1, installed to a device using nvidia sdk-manager. 
Sdk-manager should have flashed the device pre-configured with username "ubuntu" and password "ubuntu". It's strongly recommended to do this before flashing the device - otherwise you may need to connect an HDMI monitor and keyboard to the device in order to complete first-boot configuration.

Note also that SDK Manager or it's tools must be used for the initial flashing process - the Jetson will require a bootlooader firmware update that is applied automatically by SDK manager. This firmware update is needed in order to support the MAXN power mode, and gives a large performance boost.

After flashing, as long as the pre-configuration was successful, the device should come online as a compound USB device with RNDIS (Ethernet) and USB CDC interfaces. The virtual ethernet interface should come up with a 192.168.55.xxx ethernet address, and it should expose the SSH server.

Once the device comes online after flashing and enumerates as an RNDIS network interface, it's recommended to get the device connected to a wireless network with internet access. This is only needed for the initial provisonining and model updates. SSH to the device with `ssh ubuntu@192.168.55.1` and password ubuntu, then execute `nmcli device wifi connect <ssid> password <password>`

