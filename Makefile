
LOCAL_DIR ?= $(shell readlink -m $(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
WORK_DIR ?= $(LOCAL_DIR)/work

BUILD_ARGS ?=
VERSION ?=

all: image iso

root:
	sudo docker build $(BUILD_ARGS) -t golem-gpu-live -f $(LOCAL_DIR)/rootfs/Dockerfile rootfs
	sudo ./get-rootfs.sh golem-gpu-live:latest $(WORK_DIR)

image: root
	sudo $(LOCAL_DIR)/create-live-image.sh $(WORK_DIR) $(VERSION)

iso: root
	sudo $(LOCAL_DIR)/create-live-iso.sh $(WORK_DIR)

clean:
	sudo rm -rf $(WORK_DIR)
