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
from pathlib import Path
from textwrap import wrap

from dialog import Dialog

locale.setlocale(locale.LC_ALL, "")

PCI_VGA_CLASS_ID = "0300"
PCI_AUDIO_CLASS_ID = "0403"
PCI_BRIDGE_CLASS_ID = "0604"

logger = logging.getLogger(__name__)


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
    letters = string.ascii_letters + string.digits
    return "".join(random.choice(letters) for _ in range(length))


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


def get_iommu_groups():
    iommu_groups = []
    if os.path.exists("/sys/kernel/iommu_groups"):
        iommu_groups = os.listdir("/sys/kernel/iommu_groups")
    return sorted(iommu_groups, key=lambda x: int(x))


def get_iommu_group_devices(iommu_group):
    devices = []
    devices_path = f"/sys/kernel/iommu_groups/{iommu_group}/devices"
    if os.path.exists(devices_path):
        devices = os.listdir(devices_path)
    return devices


def get_pci_full_string_description_from_slot(slot):
    result = subprocess.run(["lspci", "-s", slot], capture_output=True, text=True)
    return result.stdout.strip()


def get_pci_short_string_description_from_slot(slot):
    full_description = get_pci_full_string_description_from_slot(slot)
    return full_description.split(": ", 1)[1]


def list_pci_devices_in_iommu_group(devices):
    return [get_pci_full_string_description_from_slot(device) for device in devices]


def get_vid_pid_from_slot(slot):
    result = subprocess.run(["lspci", "-n", "-s", slot], capture_output=True, text=True)
    return result.stdout.split()[2]


def get_class_from_slot(slot):
    result = subprocess.run(["lspci", "-n", "-s", slot], capture_output=True, text=True)
    return result.stdout.split()[1].rstrip(":")


def parse_devices(devices, allowed_classes):
    parsed_devices = {}
    for device in devices:
        device_class = get_class_from_slot(device)
        if device_class in allowed_classes:
            parsed_devices.setdefault(device_class, []).append(device)
    return parsed_devices


def has_only_allowed_devices(parsed_devices, devices):
    filtered_devices_list = [
        device for devices in parsed_devices.values() for device in devices
    ]
    return set(filtered_devices_list) == set(devices)


def is_pci_bridge_of_device(pci_bridge_device: str, device: str):
    parsed_bridge_device = pci_bridge_device.split(":")
    if len(parsed_bridge_device) != 3:
        raise WizardError(f"Cannot parse PCI bridge device: '{pci_bridge_device}'")
    domain, bus, _ = parsed_bridge_device
    device_path = f"/sys/bus/pci/devices/{device}"
    real_device_path = f"/sys/devices/pci{domain}:{bus}/{pci_bridge_device}/{device}"
    return os.path.realpath(device_path) == real_device_path


def is_pci_supplier_of_device(pci_supplier_device: str, device: str):
    device_path = f"/sys/bus/pci/devices/{device}/supplier:pci:{pci_supplier_device}"
    return os.path.exists(device_path)


def select_gpu_compatible(allow_pci_bridge=True):
    allowed_classes = [PCI_VGA_CLASS_ID, PCI_AUDIO_CLASS_ID]
    if allow_pci_bridge:
        allowed_classes.append(PCI_BRIDGE_CLASS_ID)

    gpu_list = []
    bad_isolation_groups = {}

    iommu_groups = get_iommu_groups()
    for iommu_group in iommu_groups:
        devices = get_iommu_group_devices(iommu_group)
        parsed_devices = parse_devices(devices, allowed_classes)

        # Check if a GPU exists
        if PCI_VGA_CLASS_ID not in parsed_devices:
            continue

        pci_vga_device = parsed_devices[PCI_VGA_CLASS_ID][0]
        pci_bridge_device = parsed_devices.get(PCI_BRIDGE_CLASS_ID, [""])[0]
        pci_audio_device = parsed_devices.get(PCI_AUDIO_CLASS_ID, [""])[0]

        # Check if we have:
        # 1. Only allowed devices
        # 2. At most, one PCI bridge device
        # 3. At most, one PCI audio device
        # 4. Only one GPU (we checked that one exists before)
        # 5. PCI bridge device is the parent of GPU device
        # 6. GPU device is a supplier for audio device
        if (
            not has_only_allowed_devices(parsed_devices, devices)
            or len(parsed_devices.get(PCI_BRIDGE_CLASS_ID, [])) > 1
            or len(parsed_devices.get(PCI_AUDIO_CLASS_ID, [])) > 1
            or len(parsed_devices[PCI_VGA_CLASS_ID]) > 1
            or (
                pci_bridge_device
                and not is_pci_bridge_of_device(pci_bridge_device, pci_vga_device)
            )
            or (
                pci_audio_device
                and not is_pci_supplier_of_device(pci_vga_device, pci_audio_device)
            )
        ):
            bad_isolation_groups[iommu_group] = list_pci_devices_in_iommu_group(devices)
            continue

        gpu_vga_slot = parsed_devices[PCI_VGA_CLASS_ID][0]
        vfio_devices = parsed_devices[PCI_VGA_CLASS_ID] + parsed_devices.get(
            PCI_AUDIO_CLASS_ID, []
        )
        nvidia_vid_pid_devices = []
        for device in vfio_devices:
            vid_pid_device = get_vid_pid_from_slot(device)
            vid, pid = vid_pid_device.split(":")
            # NVIDIA vendor ID is '10DE'
            if vid.lower() != "10de":
                continue
            nvidia_vid_pid_devices.append(vid_pid_device)

        vfio = ",".join(nvidia_vid_pid_devices)

        gpu_list.append(
            {
                "description": get_pci_full_string_description_from_slot(gpu_vga_slot),
                "vfio": vfio,
                "slot": gpu_vga_slot,
                "devices": vfio_devices,
            }
        )

    return gpu_list, bad_isolation_groups


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
                f"echo ',+' | sfdisk --no-reread --no-tell-kernel -q -N 4 /dev/{device}",
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

    permissions_cmd = ["sudo", "chown", "-R", "golem:golem", str(mount_point)]
    subprocess.run(permissions_cmd, check=True)

    return mount_point


def configure_bind_mount(directory, bind_directory):
    if os.path.ismount(bind_directory):
        return True

    directory.mkdir(exist_ok=True)
    bind_directory.mkdir(exist_ok=True)

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


def configure_runtime(runtime_path, selected_gpu):
    runtime_content = json.loads(runtime_path.read_text())
    runtime_gpu_arg = f"--runtime-arg=--pci-device={selected_gpu['slot']}"
    runtime_content[0].setdefault("extra-args", [])
    if runtime_gpu_arg not in runtime_content[0]["extra-args"]:
        runtime_content[0]["extra-args"].append(
            f"--runtime-arg=--pci-device={selected_gpu['slot']}"
        )
    runtime_path.write_text(json.dumps(runtime_content, indent=4))


def configure_preset(runtime_id, account, duration_price, cpu_price, init_price):
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

    pricing_cmd = [
        "--pricing",
        "linear",
        "--price",
        f"Duration={duration_price}",
        f"CPU={cpu_price}",
        f"Init price={init_price}",
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


def bind_vfio(devices):
    inner_cmd = []
    for dev in devices:
        driver_override_path = f"/sys/bus/pci/devices/{dev}/driver_override"
        bind_path = "/sys/bus/pci/drivers/vfio-pci/bind"
        if Path(f"/sys/bus/pci/drivers/vfio-pci/{dev}").exists():
            continue
        inner_cmd += [
            f'echo vfio-pci > "{driver_override_path}"',
            f'echo "{dev}" > "{bind_path}"',
        ]
    if Path("/sys/class/vtconsole/vtcon0/bind").exists():
        inner_cmd += ["echo 0 > /sys/class/vtconsole/vtcon0/bind"]
    if Path("/sys/class/vtconsole/vtcon1/bind").exists():
        inner_cmd += ["echo 0 > /sys/class/vtconsole/vtcon1/bind"]
    if Path("/sys/bus/platform/drivers/efi-framebuffer/efi-framebuffer.0").exists():
        inner_cmd += [
            "echo efi-framebuffer.0 > /sys/bus/platform/drivers/efi-framebuffer/unbind"
        ]
    inner_cmd += ["modprobe -i vfio-pci"]
    subprocess.run(["sudo", "bash", "-c", "&&".join(inner_cmd)], check=True)


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
        "--storage-only",
        action="store_true",
        default=False,
        help="Configure only persistent storage.",
    )
    parser.add_argument("--glm-account", default=None, help="Account for payments.")
    parser.add_argument(
        "--glm-per-hour", default=None, help="Recommended default value is 0.25."
    )
    parser.add_argument("--init-price", default=None, help="For testing set it to 0.")
    parser.add_argument(
        "--gpu-pci-slot",
        default=None,
        help="GPU PCI slot ID. For example, '0000:01:00.1'.",
    )
    parser.add_argument(
        "--vfio-devices",
        default=[],
        action="append",
        help="List of PCI slot IDs to assign to VFIO.",
    )
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
    #
    # TERMS OF USE
    #

    logging.info("Check accepted license terms.")
    if not wizard_conf.get("accepted_terms", False):
        if not wizard_dialog.yesno(
            "By installing & running this software you declare that you have read, understood and hereby accept the "
            "disclaimer and privacy warning found at 'https://handbook.golem.network/see-also/terms'."
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
        mount_point = configure_storage(
            device=device, resize_partition=resize_partition
        )
        # Mount persistent storage directory .local onto ~/.local
        configure_bind_mount(
            mount_point / "golem-gpu-live", Path("~").expanduser() / ".local"
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
        or wizard_dialog.inputbox("GLM per hour:", init="0.25")
        or 0.25
    )
    glm_init_price = (
        wizard_conf.get("glm_init_price", None)
        or wizard_dialog.inputbox("GLM init price:", init="0")
        or 0
    )
    try:
        cpu_price = float(glm_per_hour) / 3600.0
        duration_price = cpu_price / 5.0
    except ValueError as e:
        raise WizardError(f"Invalid GLM values: {str(e)}")

    wizard_conf["glm_account"] = glm_account
    wizard_conf["glm_per_hour"] = glm_per_hour
    wizard_conf["glm_init_price"] = glm_init_price

    #
    # GPU
    #

    msg_freeze = (
        "Your screen might turn off or freeze. Check if your provider is visible on the network "
        "https://stats.golem.network/network/providers/online or log in using SSH."
    )

    logging.info("Configure GPU.")
    if not wizard_conf.get("gpu", None):
        gpu_list, bad_isolation_groups = select_gpu_compatible(
            allow_pci_bridge=not args.no_relax_gpu_isolation
        )
        if not gpu_list:
            if bad_isolation_groups:
                for iommu_group in bad_isolation_groups:
                    devices = bad_isolation_groups.get(iommu_group, [])
                    if devices:
                        msg = f"IOMMU Group '{iommu_group}' has bad isolation:\n\n"
                        for device in devices:
                            msg += "  " + device + "\n"
                        wizard_dialog.msgbox(msg, width=640)

            raise WizardError("No compatible GPU available.")

        gpu_choices = [(gpu["description"], "") for gpu in gpu_list]
        code, gpu_tag = wizard_dialog.menu(
            "Select a GPU:", choices=gpu_choices, height=32
        )

        selected_gpu = None
        for gpu in gpu_list:
            if gpu["description"] == gpu_tag:
                selected_gpu = gpu
                break

        if selected_gpu:
            wizard_dialog.msgbox(
                f"Selected GPU: {selected_gpu['slot']} (VFIO: {selected_gpu['vfio']})"
            )

        if not code or not selected_gpu:
            raise WizardError("Invalid GPU selection.")

        wizard_conf["gpu"] = selected_gpu

        wizard_dialog.msgbox(msg_freeze)
    else:
        selected_gpu = wizard_conf["gpu"]

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

        configure_runtime(runtime_path, selected_gpu)

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
        try:
            configure_preset(
                runtime_id="vm-nvidia",
                account=glm_account,
                duration_price=duration_price,
                cpu_price=cpu_price,
                init_price=glm_init_price,
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
            bind_vfio(selected_gpu["devices"])
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
        try:
            wizard_conf_path.write_text(json.dumps(wizard_conf, indent=4))
        except json.JSONDecodeError as e:
            logger.error(f"Failed to save configuration file: {str(e)}")


if __name__ == "__main__":
    wizard_dialog = None
    err_msg = None
    try:
        args = parse_args()

        setup_logging(args.debug)

        wizard_conf = {}
        wizard_conf_path = Path("~").expanduser().resolve() / ".golemwz.conf"

        if wizard_conf_path.exists():
            try:
                wizard_conf.update(json.loads(wizard_conf_path.read_text()))
            except json.JSONDecodeError as e:
                logger.error(f"Failed to read configuration file: {str(e)}")

        if args.glm_account:
            wizard_conf["glm_account"] = args.glm_account

        if args.glm_per_hour:
            wizard_conf["glm_per_hour"] = args.storage_partition

        if args.glm_per_hour:
            wizard_conf["glm_init_price"] = args.init_price

        if args.gpu_pci_slot and args.vfio_devices:
            wizard_conf["gpu"] = {
                "slot": args.gpu_pci_slot,
                "devices": args.vfio_devices,
                "vfio": ",".join(
                    get_vid_pid_from_slot(dev) for dev in args.vfio_devices
                ),
                "description": get_pci_full_string_description_from_slot(
                    args.gpu_pci_slot
                ),
            }

        system_configured = all(
            [
                wizard_conf.get("accepted_terms", False),
                wizard_conf.get("is_password_set", False),
                wizard_conf.get("storage_partition", None),
                wizard_conf.get("glm_account", None),
                wizard_conf.get("glm_per_hour", None),
                wizard_conf.get("glm_init_price", None),
                wizard_conf.get("gpu", None),
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
