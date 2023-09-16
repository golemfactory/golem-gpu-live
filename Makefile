
LOCAL_DIR ?= $(shell readlink -m $(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
WORK_DIR ?= $(LOCAL_DIR)/work
TMP_DIR ?= $(LOCAL_DIR)/tmp

all: rootfs live-iso

rootfs: rootfs
	sudo docker build -t golem-gpu-live -f $(LOCAL_DIR)/rootfs/Dockerfile build
	sudo ./get-merged-rootfs.sh golem-gpu-live $(TMP_DIR) $(WORK_DIR)

live-iso: rootfs
	sudo ./create-live-iso.sh $(WORK_DIR)
