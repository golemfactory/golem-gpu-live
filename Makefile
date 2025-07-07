
LOCAL_DIR ?= $(shell readlink -m $(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
WORK_DIR ?= $(LOCAL_DIR)/work
TMP_DIR ?= $(LOCAL_DIR)/tmp

BUILD_ARGS ?=
VERSION ?=

.PHONY: packages clean all root image iso

all: image iso

packages:
	dpkg-deb --build packages/golem-wizard
	dpkg-deb --build packages/golem-config-updater
	cp packages/golem-wizard.deb packages/golem-config-updater.deb rootfs/

root: packages
	sudo docker build $(BUILD_ARGS) -t golem-gpu-live -f $(LOCAL_DIR)/rootfs/Dockerfile rootfs
	sudo ./get-merged-rootfs.sh golem-gpu-live $(TMP_DIR) $(WORK_DIR)
	# FIXME:
	sudo rm -rf $(WORK_DIR)/rootfs/etc/apt/apt.conf.d/docker-disable-periodic-update \
	    $(WORK_DIR)/rootfs/usr/sbin/policy-rc.d \
	    $(WORK_DIR)/rootfs/etc/update-motd.d/*

image: root
	sudo $(LOCAL_DIR)/create-live-image.sh $(WORK_DIR) $(VERSION)

iso: root
	sudo $(LOCAL_DIR)/create-live-iso.sh $(WORK_DIR)

clean:
	sudo rm -rf $(WORK_DIR) $(TMP_DIR)
	rm -f packages/golem-wizard.deb packages/golem-config-updater.deb
	rm -f rootfs/golem-wizard.deb rootfs/golem-config-updater.deb
