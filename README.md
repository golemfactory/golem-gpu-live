# golem-gpu-live

!!! WARNING !!!

This branch is subject to force-push.

### Dependencies

```commandline
sudo apt install \
    debootstrap \
    squashfs-tools \
    xorriso \
    isolinux \
    syslinux-efi \
    grub-pc-bin \
    grub-efi-amd64-bin \
    grub-efi-ia32-bin \
    mtools \
    dosfstools \
    jq \
    rsync \
    docker.io
```

### Create `rootfs`

```bash
$ sudo docker rootfs -t golem-gpu-live -f rootfs/Dockerfile rootfs
$ sudo ./get-merged-rootfs.sh golem-gpu-live /path/to/tmp/dir /path/to/work/dir
```

Your directory `/path/to/work/dir` contains a `rootfs` directory.

> Remark: Alternative idea is to run a container and then to `docker copy` it.
> At least, our approach should be reproducible.

### Create Live ISO file

```
$ sudo ./create-live-iso.sh /path/to/work/dir
```

Your directory `/path/to/work/dir` contains `golem-gpu-live.iso`.
