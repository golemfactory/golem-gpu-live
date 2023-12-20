#!/bin/bash

set -eux -o pipefail

LOCALDIR="$(readlink -f "$(dirname "$0")")"
WORKDIR="${1:-"${LOCALDIR}/work"}"
VERSION="${2:-"$(date --utc +%y%m%dT%H%M%SZ)"}"
IMG="${WORKDIR}/golem-gpu-live-${VERSION}.img"
MNTDIR="${WORKDIR}/mnt"

function cleanup() {
    local mountdir="$1"

    if mountpoint -q "${mountdir}"; then
        if mountpoint -q "${mountdir}/boot/efi"; then
            umount -f -l "${mountdir}/boot/efi"
        fi
        umount -f -l "${mountdir}"
    fi

    if [ -n "${IMG_LOOP:-}" ]; then
        losetup -d "${IMG_LOOP:-}"
    fi
}

# Cleanup
cleanup "${MNTDIR}"
rm -rf "${WORKDIR}/golem-gpu-live-*.img"

# Trap for cleanup mount points
trap "cleanup ${MNTDIR}" 0 1 2 3 6 15

truncate -s 8G "${IMG}"

# have static UUIDs to make partition table reproducible
/usr/sbin/sfdisk "$IMG" <<EOF || exit 1
label: gpt
label-id: f4796a2a-e377-45bd-b539-d6d49e569055

size=200MiB, type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B, uuid=fa4d6529-56da-47c7-ae88-e2dfecb72621, name="EFI System"
size=2MiB, type=21686148-6449-6E6F-744E-656564454649, uuid=1e6c9db4-1e91-46c4-846a-2030dcb13b8c, name="BIOS boot partition"
size=1MiB, type=0FC63DAF-8483-4772-8E79-3D69D8477DE4, uuid=33b921b8-edc5-46a0-8baa-d0b7ad84fc71, name="Golem conf storage"
size=6000MiB, type=0FC63DAF-8483-4772-8E79-3D69D8477DE4, uuid=693244e6-3e07-47bf-ad79-acade4293fe7, name="Golem root filesystem"
type=0FC63DAF-8483-4772-8E79-3D69D8477DE4, uuid=9b06e23f-74bb-4c49-b83d-d3b0c0c2bb01, name="Golem storage"
EOF

IMG_LOOP=$(/sbin/losetup -P -f --show "$IMG")
EFI_IMG_DEV=${IMG_LOOP}p1
BIOS_IMG_DEV=${IMG_LOOP}p2
CONF_DEV=${IMG_LOOP}p3
IMG_DEV=${IMG_LOOP}p4
STORAGE_DEV=${IMG_LOOP}p5

udevadm settle --exit-if-exists="$IMG_DEV"

# Creating filesystems
/sbin/mkfs.vfat "${EFI_IMG_DEV}"
/sbin/mkfs.fat -F32 "${CONF_DEV}"
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
cp -r "${WORKDIR}/rootfs/usr/lib/grub/x86_64-efi"/* "${MNTDIR}/boot/grub/x86_64-efi/"

cp "${WORKDIR}/rootfs/usr/lib/grub/x86_64-efi-signed/gcdx64.efi.signed" \
       "${MNTDIR}/boot/efi/EFI/BOOT/grubx64.EFI"

cp "${WORKDIR}/rootfs/usr/lib/shim/shimx64.efi.signed.latest" \
       "${MNTDIR}/boot/efi/EFI/BOOT/BOOTx64.EFI"

# flag file used by grubx64.EFI to find the boot partition
mkdir -p "${MNTDIR}/.disk"
echo "Golem Live USB" > "${MNTDIR}/.disk/info"

# Umount root filesystem
umount "${MNTDIR}/boot/efi"
umount "${MNTDIR}"

# Mount conf filesystem
mount "${CONF_DEV}" "${MNTDIR}"
cat > "${MNTDIR}/golemwz-example.toml" << EOF
#accepted_terms = true
#glm_account = "0x..."
#glm_per_hour = "0.25"
EOF

# Generate BIOS bootable GRUB image
grub-install \
    --target=i386-pc \
    --modules="part_gpt part_msdos fat iso9660" \
    "${IMG_LOOP}"
