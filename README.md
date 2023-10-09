# golem-gpu-live

## Overview

The **golem-gpu-live** project allows you to create a live image for a GOLEM provider with NVIDIA GPU.
This README provides instructions on how to set up the necessary dependencies and create the image using the provided Makefile.

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

This command will build the Docker image and then use it to generate the live image. The resulting image `golem-gpu-live.img` will be located in the `work` directory within the project folder.

During the build process, two directories are defined within the Makefile and can be customized with specific paths if desired:
- TMP_DIR (Temporary Directory): A variable representing the temporary directory used during the build process to store intermediate files.
- WORK_DIR (Working Directory): A variable representing the working directory where the final output, such as the live image, is stored after the build process is completed.

> Remark: Ensure that both TMP_DIR and WORK_DIR have at least 8GB of free space available for the build process.

## Write image to a USB stick

You can use `dd` in order to write the generated image to a USB stick. Assuming your USB stick is referenced as `/dev/sda` on your system, under `work` directory:
```shell
sudo dd if=work/golem-gpu-live.img of=/dev/sda
```

## Booting the image

### Wizard

It provided a wizard for configuring the setup of the Golem Provider software that will perform the following configurations:

1. **Terms of Use Acceptance:** The wizard will check if the user has accepted the terms of use for the Golem Provider software. If the terms have not been accepted, the wizard will display a message requesting the user's agreement. The user can accept or decline the terms.

2. **Password Setup:** If a password for the 'golem' user has not been set previously, the wizard will generate a random password for this user account. It will use the `passwd` command to set the password for the 'golem' user. The generated password will be displayed to the user, and they are encouraged to save it securely.

3. **Network Configuration:** Check for network connectivity using `nm-online` and displaying available IP addresses.

4. **Persistent Storage Configuration:** The wizard will prompt the user to select a storage partition. It will display a list of available partitions and allow the user to choose one for use as persistent storage. The selected storage partition will be used for storing data related to the Golem Provider.

5. **GLM (Golem Network Token) Configuration:** The user will be prompted to provide their GLM account information, including the GLM account name, GLM per hour rate, and GLM initial price. These values are essential for participating in the Golem Network and setting pricing for resource sharing.

6. **GPU Selection and Configuration:** The wizard will identify compatible GPUs and allow the user to select one for use with the Golem Provider. The selected GPU will be configured for Golem resource sharing.

7. **Runtime Configuration:** The wizard will configure the Golem runtime environment, specifically the 'vm-nvidia' runtime. It may update runtime JSON configuration files to include information about the selected GPU.

8. **Supervisor and Runtime Path Adjustment:** The wizard may adjust the paths for the Golem Supervisor and runtime based on the system's configuration. This ensures that the Golem software can access the necessary files and plugins.

9. **Preset Configuration:** The wizard will configure the Golem preset for resource sharing. This includes specifying the runtime, GLM account information, and pricing details. The preset will be activated for use with the Golem Provider.

10. **VFIO Device Attachment (optional):** If the user chooses not to skip device passthrough, the wizard will attach the selected GPU and associated devices to VFIO (Virtual Function I/O). VFIO allows these devices to be used for virtualization and resource sharing.

11. **Configuration Saving (optional):** The wizard may offer the option to save the configured settings for future use. If selected, the configuration details will be saved to a file for easy retrieval during subsequent system boots.

12. **Error Handling:** Throughout the process, the wizard will check for errors and handle them appropriately. If any errors occur, the user will be informed, and in some cases, the wizard may automatically log the user into TTY1 to diagnose and resolve issues.

These steps provide an overview of what the wizard is expected to do.

### Boot Options

There is two boot options available:

1. Default: When you boot your system with this option, it will automatically run the wizard without any user intervention. The wizard will guide you through the necessary setup steps, and if there are no errors, it will proceed to start the GolemSP software.

2. No Autostart: By choosing this option during boot, you will skip the wizard entirely, and your system will automatically log you into TTY1.

### Automatic TTY1 Login on Wizard Issues

In the event of any issues or errors encountered during the execution of the wizard, your system will automatically log you into TTY1. This allows you to access a terminal interface to diagnose and resolve any problems that may have occurred during the wizard's execution.
