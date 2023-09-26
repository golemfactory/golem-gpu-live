
LOCAL_DIR ?= $(shell readlink -m $(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
WORK_DIR ?= $(LOCAL_DIR)/work
TMP_DIR ?= $(LOCAL_DIR)/tmp

all: image iso

root:
	sudo docker build -t golem-gpu-live -f $(LOCAL_DIR)/rootfs/Dockerfile rootfs
	sudo ./get-merged-rootfs.sh golem-gpu-live $(TMP_DIR) $(WORK_DIR)

image:
	sudo ./create-live-image.sh $(WORK_DIR)

iso:
	sudo ./create-live-iso.sh $(WORK_DIR)

clean:
	rm -rf $(WORK_DIR) $(TMP_DIR)
