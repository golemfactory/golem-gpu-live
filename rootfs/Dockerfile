FROM ubuntu:jammy

ARG DEBIAN_FRONTEND=noninteractive

# Add fepitre's GOLEM repository
COPY 473F57D3A9534D53F0128E9DFF0244C9D7E28146.asc /etc/apt/trusted.gpg.d/golem.asc
RUN bash -c 'echo deb http://mirror.notset.fr/golem/repo/ jammy main > /etc/apt/sources.list.d/golem.list'

# Accept GOLEM terms for install then Wizard will manage it
RUN bash -c 'echo golem golem/terms/subsidy-01 string yes | debconf-set-selections'

RUN apt update

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
    dialog \
    qemu-kvm \
    musl-tools \
    make \
    wget

RUN apt install -y --no-install-recommends \
    golem-provider \
    golem-nvidia-kernel \
    ya-runtime-vm \
    ya-runtime-wasi-cli

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

# FIXME: This temporary until we update QEMU
RUN mv /usr/lib/yagna/plugins/ya-runtime-vm/runtime/vmrt \
       /usr/lib/yagna/plugins/ya-runtime-vm/runtime/vmrt.orig
RUN ln -s /usr/bin/qemu-system-x86_64 /usr/lib/yagna/plugins/ya-runtime-vm/runtime/vmrt

# FIXME: This is temporary until we allow multiple -initrd to vmrt and update devtmpfs mount options in init
COPY --chown=golem:golem repack-initramfs.sh /tmp
RUN bash /tmp/repack-initramfs.sh

# Configure as Golem user
USER golem

RUN mkdir -p /home/golem/.local/lib/yagna/plugins && \
    cp -r /usr/lib/yagna/plugins/*.json /home/golem/.local/lib/yagna/plugins

# FIXME: This is temporary until ressource content is available as DEB.
# Configure Golem runtime
COPY --chown=golem:golem configure-runtime.sh /tmp
RUN bash /tmp/configure-runtime.sh

# Copy GOLEM Wizard
COPY --chown=golem:golem wizard.py /home/golem
