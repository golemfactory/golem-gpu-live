FROM ubuntu:jammy

ARG DEBIAN_FRONTEND=noninteractive

# Add fepitre's GOLEM repository
COPY 473F57D3A9534D53F0128E9DFF0244C9D7E28146.asc /etc/apt/trusted.gpg.d/golem.asc
RUN bash -c 'echo deb http://mirror.notset.fr/golem/repo/ jammy main > /etc/apt/sources.list.d/golem.list'

# Accept GOLEM terms for install then Wizard will manage it
RUN bash -c 'echo golem golem/terms/subsidy-01 string yes | debconf-set-selections'

RUN apt-get update && apt-get install -y --no-install-recommends \
    linux-image-generic \
    live-boot \
    init \
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
    dialog \
    qemu-kvm \
    musl-tools \
    make \
    wget \
    fdisk \
    parted \
    unattended-upgrades \
    golem-provider \
    golem-nvidia-kernel \
    ya-runtime-vm-nvidia \
    ya-runtime-wasi-cli \
    ya-installer-resources && apt-get clean

# Blacklist 'nouveau'.
COPY vfio.conf /etc/modprobe.d/

# Disable RESUME
RUN bash -c "echo RESUME=none > /etc/initramfs-tools/conf.d/noresume.conf"

RUN update-initramfs -u

# Create 'golem' user.
RUN useradd -m golem -s /bin/bash
RUN bash -c "passwd -d golem"

# Configure sudo for 'golem'
RUN usermod -aG sudo golem
RUN bash -c 'echo "golem ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/golem'
RUN chage -d 0 golem

# Add 'golem' to KVM group
RUN usermod -aG kvm golem

# Autologin of golem on tty1
RUN mkdir -p '/etc/systemd/system/getty@tty1.service.d'
COPY override.conf /etc/systemd/system/getty@tty1.service.d/

# Ensure permissions on /dev/vfio/X
COPY 50-vfio.rules /etc/udev/rules.d/

# Let NetworkManager manages network
RUN set -i 's/managed=false/managed=true/g' /etc/NetworkManager/NetworkManager.conf
RUN bash -c 'echo > /usr/lib/NetworkManager/conf.d/10-globally-managed-devices.conf'

# Enable SSH on boot
RUN ln -sf /lib/systemd/system/ssh.service /etc/systemd/system/multi-user.target.wants/

# Copy fstab
COPY fstab /etc/

# unattented-upgrades conf
COPY 20auto-upgrades /etc/apt/apt.conf.d/

# Copy GOLEM Wizard and Systemd service
COPY golemwz.py /usr/local/bin/golemwz
COPY golemwz-wrapper.sh /usr/local/bin/golemwz-wrapper

COPY golemwz.service /etc/systemd/system
RUN ln -s /etc/systemd/system/golemwz.service /etc/systemd/system/multi-user.target.wants/

COPY golemsp.service /etc/systemd/system
RUN ln -s /etc/systemd/system/golemsp.service /etc/systemd/system/multi-user.target.wants/
