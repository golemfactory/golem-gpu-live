# golem-gpu-live

## Overview

The **golem-gpu-live** project allows you to create a live image for a GOLEM provider with NVIDIA GPU.
This README provides instructions on how to set up the necessary dependencies and create the image using the provided Makefile.

## Dependencies

Before you can create the live image and ISO, you need to install several dependencies. Run the following command to install them:

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

This command will build the Docker image and then use it to generate the live image. The resulting image will be located in the `work` directory within the project folder.

During the build process, two directories are defined within the Makefile and can be customized with specific paths if desired:
- TMP_DIR (Temporary Directory): A variable representing the temporary directory used during the build process to store intermediate files.
- WORK_DIR (Working Directory): A variable representing the working directory where the final output, such as the live image, is stored after the build process is completed.

> Remark: Ensure that both TMP_DIR and WORK_DIR have at least 8GB of free space available for the build process.
