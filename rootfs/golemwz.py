#!/usr/bin/python3
import argparse
import glob
import json
import locale
import logging
import os
import random
import re
import shutil
import string
import subprocess
import sys
import time
import toml
import tomli_w
from pathlib import Path
from textwrap import wrap

from dialog import Dialog

locale.setlocale(locale.LC_ALL, "")

import subprocess
import os
import glob
from pathlib import Path
from collections import defaultdict

PCI_HOST_BRIDGE_CLASS_ID = "0600"
PCI_BUS_BRIDGE_CLASS_ID = "0604"

PCI_VGA_CLASS_ID = "0300"

RELAXED_PCI_CLASSES = [PCI_HOST_BRIDGE_CLASS_ID, PCI_BUS_BRIDGE_CLASS_ID]

DURATION_GLM_PER_HOUR_DEFAULT = 1.0
CPU_GLM_PER_HOUR_DEFAULT = 0.0

logger = logging.getLogger(__name__)


class PCIDevice:
    def __init__(
        self, slot, class_code, vendor, device, description=None, iommu_group=None
    ):
        self.slot = slot
        self.class_code = class_code
        self.vendor = vendor
        self.device = device
        self.description = description
        self.iommu_group = iommu_group

        self.parent = None
        self.children = []
        self.consumers = []

    def __repr__(self):
        return f"PCIDevice(slot={self.slot}, class_code={self.class_code}, vendor={self.vendor}, device={self.device}, iommu_group={self.iommu_group})"

    def is_vga(self):
        return self.class_code == PCI_VGA_CLASS_ID


class PCIParser:
    def __init__(self):
        self.devices = []
        self.iommu_groups = defaultdict(list)

    @staticmethod
    def _fetch_device_description(slot):
        result = subprocess.run(
            ["lspci", "-D", "-vmm", "-s", slot], stdout=subprocess.PIPE, text=True
        )
        for line in result.stdout.splitlines():
            if line.startswith("Device"):
                return line.split(":", 1)[-1].strip()

    @staticmethod
    def _parse_lspci(lspci_output):
        pci_devices = {}
        device_blocks = lspci_output.strip().split("\n\n")

        for block in device_blocks:
            current_device = {}
            for line in block.splitlines():
                key, value = line.split(":", 1)
                current_device[key.strip()] = value.strip()

            slot = current_device.get("Slot")
            if slot:
                pci_devices[slot] = PCIDevice(
                    slot=slot,
                    class_code=current_device.get("Class", ""),
                    vendor=current_device.get("Vendor", ""),
                    device=current_device.get("Device", ""),
                    iommu_group=int(current_device.get("IOMMUGroup"))
                    if current_device.get("IOMMUGroup")
                    else None,
                )
        return pci_devices

    def _get_pci_devices(self):
        # Run lspci to get the list of PCI devices with detailed information
        lspci_command = ["lspci", "-D", "-vmm", "-n"]
        lspci_output = subprocess.run(
            lspci_command, check=True, text=True, capture_output=True
        ).stdout

        lspci_command = ["lspci", "-D", "-vmm"]
        lspci_output_strings = subprocess.run(
            lspci_command, check=True, text=True, capture_output=True
        ).stdout

        pci_devices = self._parse_lspci(lspci_output)
        pci_devices_with_strings = self._parse_lspci(lspci_output_strings)

        for slot in pci_devices:
            pci_device = pci_devices_with_strings[slot]
            pci_devices[
                slot
            ].description = (
                f"{pci_device.class_code} {pci_device.vendor} {pci_device.device}"
            )

        return pci_devices

    @staticmethod
    def _build_device_hierarchy(pci_devices):
        for device in pci_devices.values():
            # Determine the parent by resolving the full path of the device in sysfs
            device_path = f"/sys/bus/pci/devices/{device.slot}"
            full_path = Path(device_path).resolve()
            parent_path = full_path.parent
            parent_slot = parent_path.name
            if parent_slot in pci_devices:
                device.parent = pci_devices[parent_slot]
                pci_devices[parent_slot].children.append(device)

            # Find consumer devices
            consumer_pattern = f"/sys/bus/pci/devices/{device.slot}/consumer:pci:*"
            for consumer_path in glob.glob(consumer_pattern):
                consumer_slot = Path(consumer_path).name.lstrip("consumer:pci:")
                if consumer_slot in pci_devices:
                    device.consumers.append(pci_devices[consumer_slot])
            device.consumers = sorted(device.consumers, key=lambda x: x.slot)

        return pci_devices

    @staticmethod
    def _build_iommu_groups(pci_devices):
        iommu_groups = defaultdict(list)
        groups_dict = defaultdict(list)
        for device in pci_devices.values():
            if device.iommu_group is not None:
                groups_dict[device.iommu_group].append(device)

        for group, devices in sorted(groups_dict.items()):
            iommu_groups[group] = sorted(devices, key=lambda x: x.slot)

        return iommu_groups

    def get_devices(self, class_code=None, vendor=None):
        if not self.devices:
            pci_devices = self._get_pci_devices()
            pci_devices = self._build_device_hierarchy(pci_devices)
            self.iommu_groups = self._build_iommu_groups(pci_devices)
            self.devices = pci_devices.values()
        devices = self.devices
        if class_code:
            devices = filter(lambda x: x.class_code == class_code, devices)
        if vendor:
            devices = filter(lambda x: x.vendor == vendor, devices)
        return list(devices)

    def get_parents(self, device):
        if device.parent:
            return self.get_parents(device.parent) + [device.parent]
        else:
            return []

    def get_related_devices(self, device):
        return sorted(
            self.get_parents(device) + [device] + device.consumers, key=lambda x: x.slot
        )

    def is_isolated(self, device, relax=False, insecure=False):
        group_devices = set(self.iommu_groups[device.iommu_group])
        related_devices = set(self.get_related_devices(device))
        remaining_devices = group_devices.union(
            related_devices
        ) - group_devices.intersection(related_devices)
        if insecure or len(group_devices) <= 1 or not remaining_devices:
            return True
        elif relax:
            for remaining_device in remaining_devices:
                if remaining_device.class_code not in RELAXED_PCI_CLASSES:
                    return False
            return True
        return False


class WizardError(Exception):
    pass


def get_ip_addresses():
    ip_addresses = []
    try:
        output = subprocess.check_output(["ip", "addr"]).decode("utf-8")
        parsed_addresses = re.findall(r"inet ([\d.]+)", output)
        for addr in parsed_addresses:
            if addr == "127.0.0.1":
                continue
            ip_addresses.append(addr)
    except subprocess.CalledProcessError:
        pass
    return ip_addresses


def get_random_string(length):
    misleading_characters = "0Ool1"
    standard_characters = string.ascii_letters + string.digits
    excluded_characters = set(misleading_characters)
    characters_pool = list(set(standard_characters) - excluded_characters)
    return "".join(random.choices(characters_pool, k=length))


def is_mount_needed(directory, expected_device_path):
    if not os.path.ismount(directory):
        return True
    try:
        major, minor = (
            os.major(os.stat(directory).st_dev),
            os.minor(os.stat(directory).st_dev),
        )

        expected_major, expected_minor = (
            os.major(os.stat(expected_device_path).st_rdev),
            os.minor(os.stat(expected_device_path).st_rdev),
        )

        if (major, minor) != (expected_major, expected_minor):
            raise WizardError(
                f"The mount point for '{directory}' does not have the expected source device '{expected_device_path}'."
            )
        return False
    except (FileNotFoundError, TypeError) as e:
        raise WizardError(str(e)) from e


def select_compatible_gpus(allow_pci_bridge=True, insecure=False):
    parser = PCIParser()
    gpu_devices = parser.get_devices(class_code=PCI_VGA_CLASS_ID, vendor="10de")

    gpus = {}
    bad_isolation_groups = []

    for device in gpu_devices:
        if not parser.is_isolated(device, relax=allow_pci_bridge, insecure=insecure):
            bad_isolation_groups.append(
                (device, parser.iommu_groups[device.iommu_group])
            )
            continue
        vfio_devices = [device.slot for device in [device] + device.consumers]
        vfio = ",".join([slot for slot in vfio_devices])
        gpus[device.slot] = {
            "vfio": vfio,
            "slot": device.slot,
            "description": device.description,
            "vfio_devices": vfio_devices,
        }

    return gpus, bad_isolation_groups


def get_current_partition():
    cwd = os.path.dirname(__file__)

    with open("/proc/mounts", "r") as mounts_file:
        for line in mounts_file:
            parts = line.split()
            if len(parts) >= 2:
                device, mount_point = parts[0], parts[1]
                if cwd.startswith(mount_point):
                    return device
    return None


def parse_blkid_output():
    blkid_output = subprocess.check_output(["sudo", "blkid", "-o", "export"]).decode(
        "utf-8"
    )
    blocks = blkid_output.strip().split("\n\n")
    result = {}

    for block in blocks:
        lines = block.split("\n")
        device_info = {}

        for line in lines:
            key, value = line.split("=")
            key = key.strip()
            value = value.strip().replace("\\ ", " ")
            device_info[key] = value

        if "DEVNAME" in device_info:
            devname = device_info["DEVNAME"]
            result[devname] = device_info

    return result


def get_filtered_blkid_output():
    devices = parse_blkid_output()
    filtered_devices = {}
    for partition, info in devices.items():
        if not info.get("UUID", None):
            continue
        fs = info.get("TYPE", None)
        if fs not in ("ext4", "ext3", "xfs", "btrfs"):
            continue
        info["_label"] = info.get("PARTLABEL", "") or info.get("LABEL", "")
        filtered_devices[partition] = info
    return filtered_devices


def get_partition_description(device):
    description = f"UUID={device['UUID']}"
    if device["_label"]:
        description = f"{description} LABEL={device['_label']}"
    return description


def fix_paths(runtime_files_dir):
    for runtime_json in glob.glob(str(runtime_files_dir) + "/ya-*.json"):
        runtime_json_path = Path(runtime_json).resolve()
        runtime_content = json.loads(runtime_json_path.read_text())
        runtime_content[0]["supervisor-path"] = str(
            Path("/usr/lib/yagna/plugins").joinpath(
                Path(runtime_content[0]["supervisor-path"])
            )
        )
        runtime_content[0]["runtime-path"] = str(
            Path("/usr/lib/yagna/plugins").joinpath(
                Path(runtime_content[0]["runtime-path"])
            )
        )
        runtime_json_path.write_text(json.dumps(runtime_content, indent=4))


def mount_conf_storage():
    dev_partlabel = "/dev/disk/by-partlabel/Golem\\x20conf\\x20storage"

    if not is_mount_needed("/mnt", dev_partlabel):
        return

    mount_cmd = ["sudo", "mount", dev_partlabel, "/mnt"]
    try:
        subprocess.run(mount_cmd, check=True)
    except subprocess.CalledProcessError as e:
        raise WizardError(f"Failed to mount configuration partition: {str(e)}")


def configure_storage(device, resize_partition):
    uuid = device["UUID"]
    dev_by_uuid = f"/dev/disk/by-uuid/{uuid}"
    if not os.path.exists(dev_by_uuid):
        raise WizardError("Invalid storage provided.")

    mount_point = Path("~").expanduser() / "mnt"

    if not is_mount_needed(mount_point, dev_by_uuid):
        return

    if (
        resize_partition
        and device.get("PARTUUID", None) == "9b06e23f-74bb-4c49-b83d-d3b0c0c2bb01"
    ):
        devname_path = Path(device["DEVNAME"])
        device = Path(f"/sys/class/block/{devname_path.name}").readlink().parent.name
        if device and Path(f"/dev/{device}").exists():
            disk_operations = [
                f"echo ',+' | sfdisk --no-reread --no-tell-kernel -q -N 5 /dev/{device}",
                f"partprobe /dev/{device}",
                "udevadm settle",
                f"e2fsck -fy {devname_path}",
                f"resize2fs {devname_path}",
            ]
            subprocess.run(
                ["sudo", "bash", "-c", "&&".join(disk_operations)], check=True
            )

    mount_point.mkdir(exist_ok=True)

    mount_cmd = ["sudo", "mount", dev_by_uuid, str(mount_point)]
    subprocess.run(mount_cmd, check=True)


def configure_bind_mount(directory, bind_directory):
    if os.path.ismount(bind_directory):
        return True

    mkdir_cmd = ["sudo", "mkdir", "-p", str(directory), str(bind_directory)]
    subprocess.run(mkdir_cmd)

    permissions_cmd = [
        "sudo",
        "chown",
        "-R",
        "golem:golem",
        str(directory),
        str(bind_directory),
    ]
    subprocess.run(permissions_cmd, check=True)

    mount_cmd = ["sudo", "mount", "-o", "bind", str(directory), str(bind_directory)]
    subprocess.run(mount_cmd, check=True)


def get_env():
    env = os.environ.copy()
    env["EXE_UNIT_PATH"] = str(
        Path("~").expanduser() / ".local/lib/yagna/plugins/*.json"
    )
    env["DATA_DIR"] = str(Path("~").expanduser() / ".local/share/ya-provider")
    env["RUST_LOG"] = "error"
    return env


def provider_entry_exists(provider_cmd, new_entry):
    provider_list_cmd = ["ya-provider", provider_cmd, "list", "--json"]
    result = subprocess.run(
        provider_list_cmd, capture_output=True, check=True, env=get_env()
    )
    entries = json.loads(result.stdout)
    for entry in entries:
        if entry.get("name") == new_entry:
            return True
    return False


def preset_exists(runtime_id):
    return provider_entry_exists("preset", runtime_id)


def configure_runtime(runtime_path, selected_gpus):
    runtime_content = json.loads(runtime_path.read_text())

    runtime_gpu_args = [f"--runtime-arg=--pci-device={gpu['slot']}" for gpu in selected_gpus]

    runtime_content[0].setdefault("extra-args", [])
    runtime_content[0]["extra-args"] += runtime_gpu_args

    # Ensure there is no duplicate args
    runtime_content[0]["extra-args"] = list(set(runtime_content[0]["extra-args"]))

    runtime_path.write_text(json.dumps(runtime_content, indent=4))


def configure_preset(runtime_id, account, duration_price, cpu_price, node_name=None):
    env = get_env()

    if not account:
        raise WizardError(
            "Wallet account address must be provided to set up the preset!"
        )

    # FIXME: golemsp passing args is not working at the time of writing
    env["YA_ACCOUNT"] = account

    golemsp_setup_cmd = ["golemsp", "setup", "--no-interactive", "--account", account]
    subprocess.run(golemsp_setup_cmd, check=True, env=env)

    pre_install_cmd = ["ya-provider", "pre-install"]
    subprocess.run(pre_install_cmd, check=True, env=env)

    golemsp_manifest_bundle_cmd = [
        "golemsp",
        "manifest-bundle",
        "add",
        "/usr/lib/yagna/installer",
    ]
    subprocess.run(golemsp_manifest_bundle_cmd, check=True, env=env)

    # Set node name if provided
    if node_name:
        golemsp_set_node_name_cmd = [
            "golemsp",
            "settings",
            "set",
            "--node-name",
            node_name,
        ]
        subprocess.run(golemsp_set_node_name_cmd, check=True, env=env)

    pricing_cmd = [
        "--pricing",
        "linear",
        "--price",
        f"Duration={duration_price}",
        f"CPU={cpu_price}",
    ]
    preset_cmd = ["ya-provider", "preset"]
    if preset_exists(runtime_id):
        preset_cmd += ["update", "--name", runtime_id]
    else:
        preset_cmd += ["create", "--preset-name", runtime_id]
    preset_cmd += ["--no-interactive", "--exe-unit", runtime_id] + pricing_cmd
    subprocess.run(preset_cmd, check=True, env=env)

    activate_cmd = ["ya-provider", "preset", "activate", runtime_id]
    subprocess.run(activate_cmd, check=True, env=env)


def bind_vfio(slots):
    cmds = []
    for slot in set(slots):
        driver_override_path = f"/sys/bus/pci/devices/{slot}/driver_override"
        bind_path = "/sys/bus/pci/drivers/vfio-pci/bind"

        if Path(f"/sys/bus/pci/drivers/vfio-pci/{slot}").exists():
            continue

        driver = Path(f"/sys/bus/pci/devices/{slot}/driver").resolve()
        if driver.exists():
            cmds += [f'echo "{slot}" > {driver}/unbind']

        cmds += [
            f'echo vfio-pci > "{driver_override_path}"',
            f'echo "{slot}" > "{bind_path}"',
        ]
    if Path("/sys/class/vtconsole/vtcon0/bind").exists():
        cmds += ["echo 0 > /sys/class/vtconsole/vtcon0/bind"]
    if Path("/sys/class/vtconsole/vtcon1/bind").exists():
        cmds += ["echo 0 > /sys/class/vtconsole/vtcon1/bind"]
    if Path("/sys/bus/platform/drivers/efi-framebuffer/efi-framebuffer.0").exists():
        cmds += [
            "echo efi-framebuffer.0 > /sys/bus/platform/drivers/efi-framebuffer/unbind"
        ]
    cmds += ["modprobe -i vfio-pci"]
    for cmd in cmds:
        logger.debug(f"Running '{cmd}'")
        subprocess.run(
            ["sudo", "bash", "-c", cmd], capture_output=True, text=True, check=True
        )


class WizardDialog:
    dialog = Dialog(dialog="dialog", pass_args_via_file=False)

    @classmethod
    def __init__(cls, show_welcome: bool = False):
        cls.dialog.set_background_title("GOLEM Provider Wizard")
        if show_welcome:
            cls.msgbox("Welcome to GOLEM Provider configuration wizard!")

    @classmethod
    def _auto_height(cls, width, text):
        _max = max(8, 5 + len(wrap(text, width=width)))  # Min of 8 rows
        _min = min(22, _max)  # Max of 22 rows
        return _min

    @classmethod
    def yesno(cls, text, **info):
        default = {"colors": True, "width": 72, "height": 8}
        default.update(info)

        code = cls.dialog.yesno(text, **default)

        if code == cls.dialog.OK:
            return True
        elif code == cls.dialog.CANCEL:
            return False
        elif code == cls.dialog.ESC:
            sys.exit("Escape key pressed. Exiting.")

    @classmethod
    def inputbox(cls, text, **info):
        default = {"colors": True, "width": 72, "height": 8}
        default.update(info)

        if not default["height"]:
            default["height"] = cls._auto_height(default["width"], default["text"])

        code, input_content = cls.dialog.inputbox(text, **default)
        if code == cls.dialog.OK:
            return input_content
        elif code == cls.dialog.CANCEL:
            return None
        elif code == cls.dialog.ESC:
            sys.exit("Escape key pressed. Exiting.")

    @classmethod
    def msgbox(cls, text, **info):
        default = {"colors": True, "width": 72, "height": 8}
        default.update(info)

        if not default["height"]:
            default["height"] = cls._auto_height(default["width"], default["text"])

        return cls.dialog.msgbox(text, **default)

    @classmethod
    def menu(cls, text, **info):
        default = {"colors": True, "width": 72, "height": 8}
        default.update(info)

        if not default["height"]:
            default["height"] = cls._auto_height(default["width"], default["text"])

        return cls.dialog.menu(text, **default)

    @classmethod
    def checklist(cls, text, **info):
        default = {"colors": True, "width": 72, "height": 8}
        default.update(info)

        if not default["height"]:
            default["height"] = cls._auto_height(default["width"], default["text"])

        return cls.dialog.checklist(text, **default)

    @classmethod
    def pause(cls, text, **info):
        default = {"colors": True, "width": 72, "height": 8}
        default.update(info)

        if not default["height"]:
            default["height"] = cls._auto_height(default["width"], default["text"])

        return cls.dialog.pause(text, **default)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true", default=False)
    parser.add_argument(
        "--no-relax-gpu-isolation",
        action="store_true",
        default=False,
        help="Don't allow PCI bridge on which the GPU is connected in the same IOMMU group.",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        default=False,
        help="Ignore non-isolated IOMMU groups.",
    )
    parser.add_argument(
        "--storage-only",
        action="store_true",
        default=False,
        help="Configure only persistent storage.",
    )
    parser.add_argument("--glm-node-name", default=None, help="Node name.")
    parser.add_argument("--glm-account", default=None, help="Account for payments.")
    parser.add_argument(
        "--glm-per-hour", default=None, help="Recommended default value is 0.25."
    )
    parser.add_argument("--init-price", default=None, help="For testing set it to 0.")
    parser.add_argument(
        "--no-passthrough",
        action="store_true",
        default=False,
        help="Don't attach devices to VFIO.",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        default=False,
        help="Don't save running configuration.",
    )
    return parser.parse_args()


def setup_logging(debug=False):
    log_filename = Path("~").expanduser().resolve() / "golemwz.log"
    logging.basicConfig(
        filename=log_filename,
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    console_handler.setFormatter(console_formatter)
    logging.getLogger().addHandler(console_handler)


def main(args, wizard_conf, wizard_dialog):
    if not Path("/sys/firmware/efi").exists():
        wizard_dialog.msgbox("System is not started in UEFI mode!")

    #
    # TERMS OF USE
    #

    logging.info("Check accepted license terms.")
    if not wizard_conf.get("accepted_terms", False):
        if not wizard_dialog.yesno(
            "By installing & running this software you declare that you have read, understood and hereby accept the "
            "disclaimer and privacy warning found at 'https://glm.zone/GPUProviderTC'."
        ):
            return

        # Save it in conf
        wizard_conf["accepted_terms"] = True

    #
    # STORAGE
    #

    logging.info("Configure storage.")
    if not wizard_conf.get("storage_partition", None):
        devices = get_filtered_blkid_output()

        # Find GOLEM Storage
        default_partition = None
        for dev in devices.values():
            if dev["_label"] == "Golem storage":
                default_partition = dev["DEVNAME"]
                break

        # Put GOLEM Storage at the first position
        not_configure = ("-", "Do not configure persistent storage")
        begin_choices = []
        end_choices = []
        if default_partition:
            partitions = list(devices.keys())
            partitions.remove(default_partition)
            info = [devices[k] for k in [default_partition] + partitions]
            end_choices = [not_configure]
        else:
            begin_choices = [not_configure]
            info = devices.values()

        partition_choices = (
            begin_choices
            + [(dev["DEVNAME"], get_partition_description(dev)) for dev in info]
            + end_choices
        )

        code, partition_tag = wizard_dialog.menu(
            "Select a storage partition:",
            choices=partition_choices,
            height=64,
            width=128,
        )

        if not partition_tag or partition_tag == "-":
            if not wizard_dialog.yesno(
                "No persistent storage defined. Would you like to continue?"
            ):
                return
            device = {"DEVNAME": "/dev/notset"}
        else:
            device = devices[partition_tag]

        wizard_conf["storage_partition"] = device
        resize_partition = True
    else:
        device = wizard_conf["storage_partition"]
        resize_partition = False

    if device and device.get("DEVNAME", None) != "/dev/notset":
        configure_storage(device=device, resize_partition=resize_partition)
        # Mount persistent storage directory .local onto ~/.local
        configure_bind_mount(
            Path("~").expanduser() / "mnt/golem-gpu-live",
            Path("~").expanduser() / ".local",
        )

    if args.storage_only:
        logger.info(
            "Storage configured. Only storage configuration requested, exiting now."
        )
        return

    #
    # CONFIGURE PASSWORD
    #

    logging.info("Configure user password.")
    if not wizard_conf.get("is_password_set", False):
        try:
            password = get_random_string(14)
            subprocess.run(
                [
                    "sudo",
                    "passwd",
                    "golem",
                ],
                check=True,
                capture_output=True,
                input=f"{password}\n{password}".encode(),
            )
            wizard_dialog.msgbox(
                f"'golem' user has generated randomly password: {password}\n\n /!\ PLEASE SAVE IT AS IT WILL NEVER BE SHOWN AGAIN /!\\"
            )

            # Setup timeout for letting nm-online detecting activation
            cur = 0
            timeout = 30
            wizard_dialog.dialog.gauge_start(
                "Progress: 0%", title="Waiting for network activation..."
            )
            process = subprocess.Popen(
                ["nm-online", "--timeout", str(timeout)], stdout=subprocess.DEVNULL
            )
            while cur <= timeout:
                if process.poll() is not None:
                    wizard_dialog.dialog.gauge_update(
                        100, "Progress: 100%", update_text=True
                    )
                    break
                update = int(100 * cur / timeout)
                wizard_dialog.dialog.gauge_update(
                    update, "Progress: {0}%".format(update), update_text=True
                )
                time.sleep(1)
                cur += 1
            wizard_dialog.dialog.gauge_stop()

            # We rely on nm-online saying it has found activated connections
            if process.poll() == 0 and get_ip_addresses():
                addresses_str = "\n- " + "\n- ".join(get_ip_addresses())
                msg = f"Available IP addresses to connect to SSH for this host:{addresses_str}"
            else:
                msg = "Cannot determine available IP addresses. Please check documentation."
            wizard_dialog.msgbox(msg, height=8)
            wizard_conf["is_password_set"] = True
        except subprocess.CalledProcessError as e:
            raise WizardError(f"Failed to set 'golem' password: {str(e)}.")

    #
    # GLM related values
    #

    logging.info("Configure GLM values.")
    glm_account = wizard_conf.get("glm_account", None)
    while not glm_account:
        user_input = wizard_dialog.inputbox(
            "Account address for payments (e.g. 0xDaa04647e8ecb616801F9bE89712771F6D291a0C):",
            width=96,
        )
        if user_input and re.match("^0x[a-fA-F0-9]{40}$", user_input):
            glm_account = user_input
            break
        elif user_input and user_input == "/notset":
            glm_account = "0xDaa04647e8ecb616801F9bE89712771F6D291a0C"
            break
        else:
            wizard_dialog.msgbox(
                "Invalid account address provided. Please ensure account address contains 40 hexadecimal digits prefixed with '0x'."
            )

    glm_per_hour = (
        wizard_conf.get("glm_per_hour", None)
        or wizard_dialog.inputbox(
            "GLM per hour:", init=str(DURATION_GLM_PER_HOUR_DEFAULT)
        )
        or DURATION_GLM_PER_HOUR_DEFAULT
    )
    try:
        duration_price = float(glm_per_hour) / 3600.0
    except ValueError as e:
        raise WizardError(f"Invalid GLM values: {str(e)}")

    wizard_conf["glm_account"] = glm_account
    wizard_conf["glm_per_hour"] = glm_per_hour

    #
    # GPU
    #

    msg_freeze = (
        "Your screen might turn off or freeze. Check if your provider is visible on the network "
        "https://glm.zone/GPUProviderStats or log in using SSH."
    )

    logging.info("Configure GPUs.")
    if not wizard_conf.get("gpus", None):
        gpus, bad_isolation_groups = select_compatible_gpus(
            allow_pci_bridge=not args.no_relax_gpu_isolation, insecure=args.insecure
        )
        if bad_isolation_groups:
            for device, iommu_group_devices in bad_isolation_groups:
                msg = f"Cannot select '{device.description}'\n\nIOMMU Group '{device.iommu_group}' has bad isolation:\n\n"
                for iommu_device in iommu_group_devices:
                    msg += f"  - {iommu_device.slot} {iommu_device.description}\n"
                wizard_dialog.msgbox(msg, width=640, height=32)
        if not gpus:
            raise WizardError("No compatible GPU available.")

        gpu_choices = [(slot, gpu["description"], False) for slot, gpu in gpus.items()]
        code, gpu_tags = wizard_dialog.checklist(
            "Select at least one GPU:", choices=gpu_choices, width=128, height=32
        )

        selected_gpus = []
        for gpu_tag in gpu_tags:
            selected_gpus.append(gpus[gpu_tag])

        # sort GPUs by slot
        selected_gpus = sorted(selected_gpus, key=lambda x: x["slot"])

        if selected_gpus:
            msg = f"Selected GPUs:\n\n"
            for gpu in selected_gpus:
                msg += f"  - {gpu['slot']} {gpu['description']}\n"
            wizard_dialog.msgbox(msg, width=640, height=32)

        if not code or not selected_gpus:
            raise WizardError("Invalid GPU selection.")

        wizard_conf["gpus"] = selected_gpus

        wizard_dialog.msgbox(msg_freeze)
    else:
        selected_gpus = wizard_conf["gpus"]

    #
    # CONFIGURE RUNTIME
    #

    logging.info("Configure runtime.")
    if not wizard_conf.get("runtime_configured", False):
        # Copy missing runtime JSONs. We assume that GOLEM bins will update them if they exist.
        plugins_dir = Path("~").expanduser() / ".local/lib/yagna/plugins"
        plugins_dir.mkdir(parents=True, exist_ok=True)

        for runtime_json in Path("/usr/lib/yagna/plugins/").glob("ya-*.json"):
            if not (plugins_dir / runtime_json.name).exists():
                shutil.copy2(runtime_json, plugins_dir)

        runtime_path = (
            (
                Path("~").expanduser()
                / ".local/lib/yagna/plugins/ya-runtime-vm-nvidia.json"
            )
            .expanduser()
            .resolve()
        )
        if not runtime_path:
            raise WizardError(
                f"Cannot find runtime configuration file '{runtime_path}'."
            )

        configure_runtime(runtime_path, selected_gpus)

        #
        # FIX SUPERVISOR AND RUNTIME PATHS
        #

        runtime_files_dir = (
            (Path("~").expanduser() / ".local/lib/yagna/plugins/")
            .expanduser()
            .resolve()
        )
        fix_paths(runtime_files_dir)

        wizard_conf["runtime_configured"] = True

    #
    # CONFIGURE PRESET
    #

    logging.info("Configure preset.")
    if not wizard_conf.get("preset_configured", False):
        glm_node_name = wizard_conf.get(
            "glm_node_name", None
        ) or wizard_dialog.inputbox(
            "Node name (leave empty for automatic generated name):"
        )
        try:
            configure_preset(
                runtime_id="vm-nvidia",
                account=glm_account,
                duration_price=duration_price,
                cpu_price=CPU_GLM_PER_HOUR_DEFAULT,
                node_name=glm_node_name,
            )
            wizard_conf["preset_configured"] = True
        except subprocess.CalledProcessError as e:
            raise WizardError(f"Failed to configure preset: {str(e)}.")

    #
    # VFIO
    #

    # Add warning about a possible screen freeze
    logging.info(msg_freeze)

    logging.info("Configure passthrough.")
    if not args.no_passthrough:
        try:
            all_devices = []
            for gpu in selected_gpus:
                all_devices += gpu["vfio_devices"]
            bind_vfio(all_devices)
        except subprocess.CalledProcessError as e:
            raise WizardError(
                f"Failed to attach devices to VFIO: {str(e)}. Already bound?"
            )

    # Create the same file as "as-provider" script
    terms_path = Path("~").expanduser() / ".local/share/ya-installer/terms"
    terms_path.mkdir(parents=True, exist_ok=True)
    if not (terms_path / "testnet-01.tag").exists():
        (terms_path / "testnet-01.tag").write_text("")

    #
    # Save running config
    #

    logging.info("Save Wizard configuration file.")
    if not args.no_save:
        # Save Wizard configuration
        try:
            wizard_conf_path.write_text(tomli_w.dumps(wizard_conf))
        except toml.TomlDecodeError as e:
            raise WizardError(f"Failed to save configuration file: {str(e)}")

        # Once Wizard configuration written, we delete the first boot configuration
        try:
            subprocess.run(
                ["sudo", "rm", "-f", str(firstboot_wizard_conf_path)], check=True
            )
        except subprocess.CalledProcessError as e:
            raise WizardError(
                f"Failed to delete first boot configuration file: {str(e)}"
            )


if __name__ == "__main__":
    wizard_dialog = None
    err_msg = None
    try:
        args = parse_args()

        setup_logging(args.debug)

        mount_conf_storage()

        wizard_conf = {}

        # If exists, the first boot configuration file path provided in Golem conf partition
        firstboot_wizard_conf_path = Path("/mnt/golemwz.toml")

        # Wizard configuration file path
        wizard_conf_path = Path("~").expanduser().resolve() / ".golemwz.toml"

        try:
            conf_to_load = None
            if wizard_conf_path.exists():
                conf_to_load = wizard_conf_path
            elif firstboot_wizard_conf_path.exists():
                conf_to_load = firstboot_wizard_conf_path
            if conf_to_load:
                wizard_conf.update(toml.loads(conf_to_load.read_text()))
        except toml.TomlDecodeError as e:
            logger.error(
                f"Failed to read configuration file '{wizard_conf_path}': {str(e)}"
            )

        if args.glm_node_name:
            wizard_conf["glm_node_name"] = args.glm_node_name

        if args.glm_account:
            wizard_conf["glm_account"] = args.glm_account

        if args.glm_per_hour:
            wizard_conf["glm_per_hour"] = args.storage_partition

        system_configured = all(
            [
                wizard_conf.get("accepted_terms", False),
                wizard_conf.get("is_password_set", False),
                wizard_conf.get("storage_partition", None),
                wizard_conf.get("glm_account", None),
                wizard_conf.get("glm_per_hour", None),
                wizard_conf.get("gpus", None),
            ]
        )
        wizard_dialog = WizardDialog(show_welcome=not system_configured)
        main(args=args, wizard_conf=wizard_conf, wizard_dialog=wizard_dialog)
    except KeyboardInterrupt:
        err_msg = "Interrupting..."
    except WizardError as e:
        err_msg = f"Wizard error: {str(e)}"
    except Exception as e:
        err_msg = f"Unexpected error: {str(e)}"

    if err_msg:
        logger.error(err_msg)
        if wizard_dialog:
            wizard_dialog.msgbox(err_msg)
        sys.exit(1)
