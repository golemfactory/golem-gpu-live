#!/bin/bash

set -eux

tmpdir="$(mktemp -d /tmp/ya_runtime_vm.XXXX)"
cd "$tmpdir"

git clone https://github.com/golemfactory/ya-runtime-vm
cd ya-runtime-vm

git submodule update --init
cd runtime/init-container

sed -i 's/exec,mode=0755,size=2M/mode=0755,size=2M/' src/init.c

make init

mkdir initramfs
cp init initramfs/
cd initramfs
zcat /usr/lib/yagna/plugins/ya-runtime-vm/runtime/modules.cpio.gz | cpio -idmv

mv /usr/lib/yagna/plugins/ya-runtime-vm/runtime/initramfs.cpio.gz \
   /usr/lib/yagna/plugins/ya-runtime-vm/runtime/initramfs.cpio.gz.orig

find . | cpio --quiet -o -H newc -R 0:0 | gzip -9 > /usr/lib/yagna/plugins/ya-runtime-vm/runtime/initramfs.cpio.gz

rm -rf "$tmpdir"
