#!/bin/bash

set -eux -o pipefail

LOCALDIR="$(readlink -f "$(dirname "$0")")"
WORKDIR="${1:-"${LOCALDIR}/work"}"

# Cleanup
if [ -d "${WORKDIR}/content" ]; then
    rm -rf "${WORKDIR}/content"
fi

# Create directories
mkdir -p "${WORKDIR}"/content/{EFI/BOOT,boot/grub/x86_64-efi,isolinux,live}

# Compress the rootfs environment
mksquashfs \
    "${WORKDIR}/rootfs" \
    "${WORKDIR}/content/live/filesystem.squashfs" \
    -e boot

# Copy the kernel and initramfs
cp "${WORKDIR}/rootfs/boot/vmlinuz-"* "${WORKDIR}/content/live/vmlinuz"
cp "${WORKDIR}/rootfs/boot/initrd.img-"* "${WORKDIR}/content/live/initrd"

# Create ISOLINUX boot menu
cp "${LOCALDIR}/isolinux.cfg" "${WORKDIR}/content/isolinux/"

# Create GRUB boot menu
cp "${LOCALDIR}/grub.cfg" "${WORKDIR}/content/boot/grub/"

# Copy GRUB config to the EFI BOOT directory
cp "${WORKDIR}/content/boot/grub/grub.cfg" "${WORKDIR}/content/EFI/BOOT/"

# Copy BIOS/legacy boot required files
cp /usr/lib/ISOLINUX/isolinux.bin "${WORKDIR}/content/isolinux/"
cp /usr/lib/syslinux/modules/bios/* "${WORKDIR}/content/isolinux/"

# Copy EFI/modern boot required files
cp -r /usr/lib/grub/x86_64-efi/* "${WORKDIR}/content/boot/grub/x86_64-efi/"

# Generate EFI bootable GRUB image
grub-mkstandalone -O x86_64-efi \
    --modules="part_gpt part_msdos fat iso9660" \
    --locales="" \
    --themes="" \
    --fonts="" \
    --output="${WORKDIR}/content/EFI/BOOT/BOOTx64.EFI" \
    "boot/grub/grub.cfg=${LOCALDIR}/grub-embed.cfg"

# Create UEFI boot disk image
dd if=/dev/zero of="${WORKDIR}/content/efiboot.img" bs=1M count=20
/sbin/mkfs.vfat "${WORKDIR}/content/efiboot.img"
mmd -i "${WORKDIR}/content/efiboot.img" ::/EFI ::/EFI/BOOT
mcopy -vi \
    "${WORKDIR}/content/efiboot.img" \
    "${WORKDIR}/content/EFI/BOOT/BOOTx64.EFI" \
    "${WORKDIR}/content/boot/grub/grub.cfg" \
    ::/EFI/BOOT/

# Generate ISO disc image file
xorriso \
    -as mkisofs \
    -iso-level 3 \
    -o "${WORKDIR}/golem-gpu-live.iso" \
    -full-iso9660-filenames \
    -volid "GOLEM-GPU-LIVE" \
    --mbr-force-bootable -partition_offset 16 \
    -joliet -joliet-long -rational-rock \
    -isohybrid-mbr /usr/lib/ISOLINUX/isohdpfx.bin \
    -eltorito-boot \
        isolinux/isolinux.bin \
        -no-emul-boot \
        -boot-load-size 4 \
        -boot-info-table \
        --eltorito-catalog isolinux/isolinux.cat \
    -eltorito-alt-boot \
        -e --interval:appended_partition_2:all:: \
        -no-emul-boot \
        -isohybrid-gpt-basdat \
    -append_partition 2 C12A7328-F81F-11D2-BA4B-00A0C93EC93B "${WORKDIR}/content/efiboot.img" \
    "${WORKDIR}/content"
