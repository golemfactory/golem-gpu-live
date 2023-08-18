#!/bin/bash

set -x

# ONLY FOR DEV TESTING

YA_RUNTIME_VM_PCI_DEVICE='01:00.0' bash $HOME/configure-runtime-nvidia.sh

devs="0000:01:00.0 0000:01:00.1"

if [ ! -z "$(ls -A /sys/class/iommu)" ]; then
    for dev in $devs; do
        echo "vfio-pci" > "/sys/bus/pci/devices/$dev/driver_override"
	      echo "$dev" > /sys/bus/pci/drivers/vfio-pci/bind
    done
fi

modprobe -i vfio-pci