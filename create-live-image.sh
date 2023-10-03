#!/bin/bash

set -eux -o pipefail

LOCALDIR="$(readlink -f "$(dirname "$0")")"
WORKDIR="${1:-"${LOCALDIR}/work"}"
IMG="${WORKDIR}/golem-gpu-live.img"
MNTDIR="${WORKDIR}/mnt"

function cleanup() {
    local mountdir="$1"
    local imgfile="$2"

    if mountpoint -q "${mountdir}"; then
        umount "${mountdir}/boot/efi" || true
        umount "${mountdir}"
        img_loop=$(/sbin/losetup -P -f --show "$imgfile")
        losetup -d "${img_loop}"
    fi
}

# Cleanup
cleanup "${MNTDIR}" "${IMG}"
rm -f "${IMG}"

# Trap for cleanup mount points
trap "cleanup ${MNTDIR} ${IMG}" EXIT

truncate -s 6G "${IMG}"

# have static UUIDs to make partition table reproducible
/usr/sbin/sfdisk "$IMG" <<EOF || exit 1
label: gpt
label-id: f4796a2a-e377-45bd-b539-d6d49e569055

size=200MiB, type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B, uuid=fa4d6529-56da-47c7-ae88-e2dfecb72621, name="EFI System"
size=2MiB, type=21686148-6449-6E6F-744E-656564454649, uuid=1e6c9db4-1e91-46c4-846a-2030dcb13b8c, name="BIOS boot partition"
size=5000MiB, type=0FC63DAF-8483-4772-8E79-3D69D8477DE4, uuid=693244e6-3e07-47bf-ad79-acade4293fe7, name="Golem root filesystem"
type=0FC63DAF-8483-4772-8E79-3D69D8477DE4, uuid=693244e6-3e07-47bf-ad79-acade4293fe7, name="Golem storage"
EOF

IMG_LOOP=$(/sbin/losetup -P -f --show "$IMG")
EFI_IMG_DEV=${IMG_LOOP}p1
BIOS_IMG_DEV=${IMG_LOOP}p2
IMG_DEV=${IMG_LOOP}p3
STORAGE_DEV=${IMG_LOOP}p4

udevadm settle --exit-if-exists="$IMG_DEV"

# Creating filesystems
/sbin/mkfs.vfat "${EFI_IMG_DEV}"
/sbin/mkfs.ext4 -U 90a495f3-c8ce-45c6-97ac-3bd5edf3aebd -q -F "${IMG_DEV}"
/sbin/mkfs.ext4 -q -F "${STORAGE_DEV}"

mkdir -p "${MNTDIR}"
mount "${IMG_DEV}" "${MNTDIR}"

# Copy rootfs
rsync -a "${WORKDIR}/rootfs/" "${MNTDIR}/"

# Fixes
echo golem-provider > "${MNTDIR}/etc/hostname"
ln -sf /run/systemd/resolve/stub-resolv.conf "${MNTDIR}/etc/resolv.conf"

# Create EFI mount point
mkdir -p "${MNTDIR}/boot/efi/"
mount "${EFI_IMG_DEV}" "${MNTDIR}/boot/efi/"

# Create GRUB boot BIOS/EFI menu
mkdir -p "${MNTDIR}/boot/grub/"
mkdir -p "${MNTDIR}/boot/efi/EFI/BOOT/"

cp "${LOCALDIR}/live/grub.cfg" "${MNTDIR}/boot/grub/"
#cp "${LOCALDIR}/live/grub-efi.cfg" "${MNTDIR}/boot/efi/EFI/BOOT/"

# Copy EFI/modern boot required files
mkdir -p "${MNTDIR}/boot/grub/x86_64-efi/"
cp -r /usr/lib/grub/x86_64-efi/* "${MNTDIR}/boot/grub/x86_64-efi/"

# Generate EFI bootable GRUB image
grub-mkstandalone -O x86_64-efi \
    --modules="part_gpt part_msdos fat iso9660" \
    --locales="" \
    --themes="" \
    --fonts="" \
    --output="${MNTDIR}/boot/efi/EFI/BOOT/BOOTx64.EFI" \
    "boot/grub/grub.cfg=${LOCALDIR}/live/grub-efi.cfg"

# Generate BIOS bootable GRUB image
grub-install \
    --target=i386-pc \
    --modules="part_gpt part_msdos fat iso9660" \
    "${IMG_LOOP}"
