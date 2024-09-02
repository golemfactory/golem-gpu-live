# golem-gpu-live

## Overview

The **golem-gpu-live** project allows you to create a live image for a GOLEM provider with NVIDIA GPU.
This README provides instructions on how to set up the necessary dependencies and create the image using the provided Makefile.

## Prerequisites

Before attempting to use a GOLEM live image, make sure you have the following hardware requirements in place:

1. **Motherboard and CPU Support**: Verify that your motherboard and CPU support IOMMU (Input-Output Memory Management Unit) virtualization. You can often enable this in the BIOS or UEFI settings.

2. **IOMMU Groups**: Ensure that your passthrough GPU is isolated in its own IOMMU group. You can check this using the `lspci` command. If the GPU is in a group with other devices, you may need to put it into a separate PCIe slot. Installer wizard form GOLEM live image will check for that.

3. **NVIDIA GPU**: Your passthrough GPU must be an NVIDIA card. Some older NVIDIA GPUs may require workarounds due to driver restrictions.

4. **Additional GPU for Console Access (optional)**: For convenience, it's helpful to have a second GPU (integrated or low-end) to provide console access to your host machine.

> **Disclaimer**: Setting up GPU passthrough is a complex process and may vary depending on your hardware configuration.

## Dependencies

Before you can create the live image, you need to install several dependencies. Run the following command to install them:

```shell
sudo apt install \
    debootstrap \
    squashfs-tools \
    xorriso \
    isolinux \
    syslinux-efi \
    grub-pc-bin \
    grub-efi-amd64-bin \
    grub-efi-ia32-bin \
    mtools \
    dosfstools \
    jq \
    rsync \
    docker.io
```

## Creating the Image

To create the live image, follow these steps:

1. Ensure that Docker is installed and running on your system.

2. Clone or download the **golem-gpu-live** repository to your local machine.

3. Open a terminal and navigate to the directory where the Makefile is located.

4. Run the following command to create the image:

```shell
make root image
```

This command will build the Docker image and then use it to generate the live image. The resulting image `golem-gpu-live-VERSION.img` will be located in the `work` directory within the project folder.

During the build process, two directories are defined within the Makefile and can be customized with specific paths if desired:
- TMP_DIR (Temporary Directory): A variable representing the temporary directory used during the build process to store intermediate files.
- WORK_DIR (Working Directory): A variable representing the working directory where the final output, such as the live image, is stored after the build process is completed.

> Remark: Ensure that both TMP_DIR and WORK_DIR have at least 8GB of free space available for the build process.

## Write image to a USB stick

You can use `dd` in order to write the generated image to a USB stick. A minimal USB stick of `8GB` is required.

Assuming your USB stick is referenced as `/dev/sda` on your system, under `work` directory:
```shell
sudo dd if=work/golem-gpu-live-VERSION.img of=/dev/sda
```

The image contains a fifth partition for persistent storage with label `Golem storage`. It contains a hard-coded value for `PARTUUID` and if selected later for storage, it would be resized to the maximum available space remaining on the USB stick.

User can use another partition for persistent storage on another disk, but it has to be formatted with any Linux compatible filesystem.

> Remark: Custom persistent storage won't be automatically resized.

## Booting the image

### Wizard

It provided a wizard for configuring the setup of the Golem Provider software that will perform the following configurations:

1. **Terms of Use Acceptance:** The wizard will check if the user has accepted the terms of use for the Golem Provider software. If the terms have not been accepted, the wizard will display a message requesting the user's agreement. The user can accept or decline the terms.

2. **Persistent Storage Configuration:** The wizard will prompt the user to select a storage partition. It will display a list of available partitions and allow the user to choose one for use as persistent storage. The selected storage partition will be used for storing data related to the Golem Provider.

3. **Password Setup:** If a password for the 'golem' user has not been set previously, the wizard will generate a random password for this user account. It will use the `passwd` command to set the password for the 'golem' user. The generated password will be displayed to the user, and they are encouraged to save it securely.

4. **Network Configuration:** Check for network connectivity using `nm-online` and displaying available IP addresses.

5. **GLM (Golem Network Token) Configuration:** The user will be prompted to provide their GLM account information, including the GLM account name, GLM per hour rate, and GLM initial price. These values are essential for participating in the Golem Network and setting pricing for resource sharing.

6. **GPU Selection and Configuration:** The wizard will identify compatible GPUs and allow the user to select one for use with the Golem Provider. The selected GPU will be configured for Golem resource sharing.

7. **Runtime Configuration:** The wizard will configure the Golem runtime environment, specifically the 'vm-nvidia' runtime. It may update runtime JSON configuration files to include information about the selected GPU.

8. **Supervisor and Runtime Path Adjustment:** The wizard may adjust the paths for the Golem Supervisor and runtime based on the system's configuration. This ensures that the Golem software can access the necessary files and plugins.

9. **Preset Configuration:** The wizard will configure the Golem preset for resource sharing. This includes specifying the runtime, GLM account information, and pricing details. The preset will be activated for use with the Golem Provider.

10. **VFIO Device Attachment (optional from command line only):** If the user chooses not to skip device passthrough, the wizard will attach the selected GPU and associated devices to VFIO (Virtual Function I/O). VFIO allows these devices to be used for virtualization and resource sharing.

11. **Configuration Saving (optional from command line only):** The wizard offers the option to save the configured settings for future use. If selected, the configuration details will be saved to a file for easy retrieval during subsequent system boots.

12. **Error Handling:** Throughout the process, the wizard will check for errors and handle them appropriately. If any errors occur, the user will be informed, and in some cases, the wizard may automatically log the user into TTY1 to diagnose and resolve issues.

These steps provide an overview of what the wizard is expected to do.

### Wizard - command line usage

```bash
usage: golemwz [-h] [--debug] [--no-relax-gpu-isolation] [--storage-only] [--glm-account GLM_ACCOUNT]
                  [--glm-per-hour GLM_PER_HOUR] [--init-price INIT_PRICE] [--gpu-pci-slot GPU_PCI_SLOT]
                  [--vfio-devices VFIO_DEVICES] [--no-passthrough] [--no-save]

options:
  -h, --help            show this help message and exit
  --debug
  --no-relax-gpu-isolation
                        Don't allow PCI bridge on which the GPU is connected in the same IOMMU group.
  --insecure            Ignore non-isolated IOMMU groups.
  --storage-only        Configure only persistent storage.
  --glm-account GLM_ACCOUNT
                        Account for payments.
  --glm-per-hour GLM_PER_HOUR
                        Recommended default value is 0.25.
  --init-price INIT_PRICE
                        For testing set it to 0.
  --no-passthrough      Don't attach devices to VFIO.
  --no-save             Don't save running configuration.
```

### Boot Options

There are two boot options available:

1. Default: When you boot your system with this option, it will automatically run the wizard without any user intervention. The wizard will guide you through the necessary setup steps, and if there are no errors, it will proceed to start the GolemSP software.

2. NO AUTOSTART: By choosing this option during boot, you will skip the wizard entirely, and your system will automatically log you into TTY1. Note that `golemsp` won't be start neither.

> Remark: Using NO AUTOSTART allows you to reset password for `golem` user.

### Automatic TTY1 Login on Wizard Issues

In the event of any issues or errors encountered during the execution of the wizard, your system will automatically log you into TTY1. This allows you to access a terminal interface to diagnose and resolve any problems that may have occurred during the wizard's execution.

The Wizard logfile is located at `~/golemwz.log`.

Yagna logfiles reside in the persistent storage selected during the wizard configuration.
If you've booted into 'NO AUTOSTART' mode and storage has already been configured, you need to mount it using the wizard itself:
```shell
golemwz --storage-only
```
The log files are located into `~/.local/share/yagna`.

## Setting up updates repository

This needs to be done once, by the maintainer.

The repository is built in GitHub Actions and then uploaded to GitHub Pages. To set it up:
1. Create a GPG key (just for signing), upload its private part to `APT_GPG_KEY` secret in the repository and save its public part into a file in `rootfs/` directory.
2. Adjust repository URL and key file name in `rootfs/Dockerfile` (at the very beginning).
3. Setup schedule or another trigger to your liking for the workflow defined in `.github/workflows/repository.yml`.

The APT repository combines the following components:
 - yagna
 - ya-runtime-wasi
 - ya-runtime-vm
 - ya-runtime-vm-nvidia (which incorporates ya-runtime-vm too, with nvidia-specific files added, especially gpu-aware self-test image)
 - golem-nvidia-kernel (kernel used by ya-runtime-vm-nvidia)
 - ya-installer-resources

Specific versions of each of them are defined in the worklow file mentioned above. They can be specified as a pattern (preferable) which means "latest version matching the pattern".

It is important for the GPU isolation security to update golem-nvidia-kernel frequently. See README in that repository for instructions.

## First boot configuration

A partition with label `Golem conf storage` has an example configuration file `golemwz.toml` that will be loaded by the wizard on first boot.
It can be customized to set up pre-defined values expected by the wizard. For example:
```toml
accepted_terms = true
glm_account = "0x..."
glm_per_hour = "0.25"
```
makes terms accepted, defines the wallet account to use, set GLM per hour value and set GLM initial price.
Once the wizard writes its final configuration file, the first boot configuration file will be deleted.
Any further attempt to provide a first boot configuration file into the `Golem conf storage` will be ignored.
