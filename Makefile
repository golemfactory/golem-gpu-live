
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
	# Extract versions from control files and rename packages
	WIZARD_VER=$$(grep '^Version:' packages/golem-wizard/DEBIAN/control | cut -d' ' -f2); \
	UPDATER_VER=$$(grep '^Version:' packages/golem-config-updater/DEBIAN/control | cut -d' ' -f2); \
	mv packages/golem-wizard.deb packages/golem-wizard_$${WIZARD_VER}_all.deb; \
	mv packages/golem-config-updater.deb packages/golem-config-updater_$${UPDATER_VER}_all.deb; \
	cp packages/golem-wizard_$${WIZARD_VER}_all.deb rootfs/golem-wizard.deb; \
	cp packages/golem-config-updater_$${UPDATER_VER}_all.deb rootfs/golem-config-updater.deb

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
	rm -f packages/golem-wizard*.deb packages/golem-config-updater*.deb
	rm -f rootfs/golem-wizard.deb rootfs/golem-config-updater.deb
