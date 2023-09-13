FROM ubuntu:jammy

ARG DEBIAN_FRONTEND=noninteractive

## Add fepitre's PPA repository.
#COPY ppa:fepitre-golem-nvidia-kernel.list /etc/apt/sources.list.d
#COPY ppa:fepitre-golem-nvidia-kernel.gpg /etc/apt/trusted.gpg.d

# Add fepitre's GOLEM repository
COPY 473F57D3A9534D53F0128E9DFF0244C9D7E28146.asc /etc/apt/trusted.gpg.d/golem.asc
RUN bash -c 'echo deb http://mirror.notset.fr/golem/repo/ jammy main > /etc/apt/sources.list.d/golem.list'

# Accept GOLEM terms for install then Wizard will manage it
RUN bash -c 'echo golem golem/terms/subsidy-01 string yes | debconf-set-selections'

RUN apt update

RUN apt install -y --no-install-recommends \
    golem-provider \
    ya-runtime-vm \
    ya-runtime-wasi-cli

RUN apt install -y --no-install-recommends \
    linux-image-generic \
    live-boot \
    systemd \
    systemd-sysv \
    systemd-timesyncd \
    locales \
    locales-all \
    kbd \
    network-manager \
    iproute2 \
    net-tools \
    pciutils \
    iputils-ping \
    isc-dhcp-client \
    openssh-client \
    openssh-server \
    curl \
    git \
    vim \
    linux-firmware \
    zstd \
    dialog \
    ca-certificates \
    bc \
    jq \
    sudo \
    python3 \
    python3-dialog \
    dialog

RUN apt clean

# Set 'root' password.
RUN bash -c "echo -e 'root\nroot' | passwd"

# Blacklist 'nouveau'.
COPY vfio.conf /etc/modprobe.d/
RUN update-initramfs -u

# Create 'golem' user.
RUN useradd -m golem -s /bin/bash
RUN bash -c "echo -e 'golem\ngolem' | passwd golem"

# Configure sudo for 'golem'
RUN usermod -aG sudo golem
RUN bash -c 'echo "golem ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/golem'

# Add 'golem' to KVM group
RUN usermod -aG kvm golem

# Ensure permissions on /dev/vfio/X
COPY 50-vfio.rules /etc/udev/rules.d/

# Let NetworkManager manages network
RUN set -i 's/managed=false/managed=true/g' /etc/NetworkManager/NetworkManager.conf
RUN bash -c 'echo > /usr/lib/NetworkManager/conf.d/10-globally-managed-devices.conf'

# Enable SSH on boot
RUN /lib/systemd/systemd-sysv-install enable ssh

# Configure as Golem user
USER golem

#
# FIXME: use packaging to install Golem's content, NVIDIA runtime and configuration scripts.
#

# Configure Golem runtime on boot
COPY --chown=golem:golem configure-runtime.sh /tmp
RUN bash /tmp/configure-runtime.sh

# From https://github.com/golemfactory/ya-runtime-vm-nvidia/wiki/Development-instruction-for-ITL#installing-and-verifying

# Install Golem NVIDIA runtime.
COPY --chown=golem:golem install-runtime-nvidia.sh /tmp/
RUN PATH="$HOME/.local/bin:$PATH" bash /tmp/install-runtime-nvidia.sh

# Configure Golem NVIDIA on boot
COPY --chown=golem:golem configure-runtime-nvidia.sh /home/golem/

# Copy dev/debug script for configuring Golem and attaching GPU
COPY --chown=golem:golem attach.sh /home/golem/
