#!/usr/bin/python3
import argparse
import glob
import locale
import logging
import os
import shutil
import subprocess
import sys
import re
import json
import traceback

from dialog import Dialog
from textwrap import wrap
from pathlib import Path

locale.setlocale(locale.LC_ALL, "")

PCI_VGA_CLASS_ID = "0300"
PCI_AUDIO_CLASS_ID = "0403"
PCI_BRIDGE_CLASS_ID = "0604"

logger = logging.getLogger(__name__)


class WizardError(Exception):
    pass


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


def get_pid_vid_from_slot(slot):
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
        # 2. At most one PCI bridge device
        # 3. At most one PCI audio device
        # 4. Only one GPU (we checked that one exists before)
        # 5. PCI bridge device being parent of GPU device
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
        vfio_devices = parsed_devices[PCI_VGA_CLASS_ID] + parsed_devices[PCI_AUDIO_CLASS_ID]
        vfio = ",".join(get_pid_vid_from_slot(device) for device in vfio_devices)

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


def get_partition_by_partlabel(partlabel):
    try:
        blkid_output = subprocess.check_output(["blkid"]).decode("utf-8").splitlines()
        pattern = rf'(.*):.*\s+LABEL="({partlabel})"\s+.*'
        for line in blkid_output:
            match = re.search(pattern, line)
            if match:
                return match.group(1)
    except Exception as e:
        raise WizardError(f"An error occurred: {e}")
    return ""


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


def configure_storage(storage_partition):
    if not os.path.exists(storage_partition):
        raise WizardError("Invalid storage provided.")

    mount_point = Path("~").expanduser() / ".local"

    if not is_mount_needed(mount_point, storage_partition):
        return

    mount_point.mkdir(exist_ok=True)

    mount_cmd = ["sudo", "mount", storage_partition, str(mount_point)]
    subprocess.run(mount_cmd, check=True)

    permissions_cmd = ["sudo", "chown", "-R", "golem:golem", str(mount_point)]
    subprocess.run(permissions_cmd, check=True)


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
    if not runtime_gpu_arg in runtime_content[0]["extra-args"]:
        runtime_content[0]["extra-args"].append(
            f"--runtime-arg=--pci-device={selected_gpu['slot']}"
        )
    runtime_path.write_text(json.dumps(runtime_content, indent=4))


def configure_preset(runtime_id, duration_price, cpu_price, init_price):
    env = get_env()

    golemsp_setup_cmd = ["golemsp", "setup", "--no-interactive"]
    subprocess.run(golemsp_setup_cmd, check=True, env=env)

    pre_install_cmd = ["ya-provider", "pre-install"]
    subprocess.run(pre_install_cmd, check=True, env=env)

    golemsp_manifest_bundle_cmd = [
        "golemsp",
        "manifest-bundle",
        "add",
        "/home/golem/resources_dir",
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
    for dev in devices:
        driver_override_path = f"/sys/bus/pci/devices/{dev}/driver_override"
        bind_path = "/sys/bus/pci/drivers/vfio-pci/bind"
        if Path(f"/sys/bus/pci/drivers/vfio-pci/{dev}").exists():
            continue
        subprocess.run(
            ["sudo", "bash", "-c", f'echo "vfio-pci" > "{driver_override_path}"'],
            check=True,
        )
        subprocess.run(
            ["sudo", "bash", "-c", f'echo "{dev}" > "{bind_path}"'], check=True
        )

    subprocess.run(["modprobe", "-i", "vfio-pci"], check=True)


class WizardDialog:
    dialog = Dialog(dialog="dialog", pass_args_via_file=False)

    @classmethod
    def __init__(cls):
        cls.dialog.set_background_title("GOLEM Provider Wizard")

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


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true", default=False)
    parser.add_argument(
        "--relax-gpu-isolation",
        action="store_true",
        default=False,
        help="Relax GPU isolation. For example, allow PCI bridge on which the GPU is connected in the same IOMMU group.",
    )
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
        "--storage-partition",
        default=None,
        help="Device partition to use for persistent storage. Using '/notset' allows to skip storage mount.",
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


def main():
    args = parse_args()

    wizard_conf = {}
    wizard_conf_path = Path("~").expanduser().resolve() / ".golemwz.conf"

    if wizard_conf_path.exists():
        try:
            wizard_conf.update(json.loads(wizard_conf_path.read_text()))
        except json.JSONDecodeError as e:
            logger.error(f"Failed to read configuration file: {str(e)}")

    updated_wizard_conf = wizard_conf.copy()

    if args.storage_partition:
        wizard_conf["storage_partition"] = args.storage_partition

    if args.glm_per_hour:
        wizard_conf["glm_per_hour"] = args.storage_partition

    if args.glm_per_hour:
        wizard_conf["init_price"] = args.init_price

    if args.gpu_pci_slot and args.vfio_devices:
        wizard_conf["gpu"] = {
            "slot": args.gpu_pci_slot,
            "devices": args.vfio_devices,
            "vfio": ",".join(get_pid_vid_from_slot(dev) for dev in args.vfio_devices),
            "description": get_pci_full_string_description_from_slot(args.gpu_pci_slot),
        }

    d = WizardDialog()

    #
    # STORAGE
    #

    if not wizard_conf.get("storage_partition", None):
        default_partition = get_partition_by_partlabel("GOLEM Storage")
        storage_partition = d.inputbox(
            "Storage partition selection",
            init=default_partition,
        )
        updated_wizard_conf["storage_partition"] = storage_partition
        if not storage_partition:
            if not d.yesno(
                    "No persistent storage defined. Would you like to continue?"
            ):
                raise WizardError("No persistent storage defined.")
    else:
        storage_partition = wizard_conf["storage_partition"]

    if storage_partition and storage_partition != "/notset":
        configure_storage(storage_partition)

    #
    # GLM related values
    #

    glm_per_hour = wizard_conf.get("glm_per_hour", None) or d.inputbox(
        "GLM per hour:", init="0.25"
    )
    glm_init_price = wizard_conf.get("init_price", None) or d.inputbox(
        "Init price:", init="0"
    )
    try:
        cpu_price = float(glm_per_hour) / 3600.0
        duration_price = cpu_price / 5.0
    except ValueError as e:
        raise WizardError(f"Invalid GLM values: {str(e)}")

    updated_wizard_conf["glm_per_hour"] = glm_per_hour
    updated_wizard_conf["init_price"] = glm_init_price

    #
    # GPU
    #

    if not wizard_conf.get("gpu", None):
        gpu_list, bad_isolation_groups = select_gpu_compatible(
            allow_pci_bridge=args.relax_gpu_isolation
        )
        if not gpu_list:
            if bad_isolation_groups:
                for iommu_group in bad_isolation_groups:
                    devices = bad_isolation_groups.get(iommu_group, [])
                    if devices:
                        msg = f"IOMMU Group '{iommu_group}' has bad isolation:\n\n"
                        for device in devices:
                            msg += "  " + device + "\n"
                        d.msgbox(msg, width=640)

            raise WizardError("No compatible GPU available.")

        gpu_choices = [(gpu["description"], "") for gpu in gpu_list]
        code, gpu_tag = d.menu("Select a GPU:", choices=gpu_choices)

        selected_gpu = None
        for gpu in gpu_list:
            if gpu["description"] == gpu_tag:
                selected_gpu = gpu
                break

        if selected_gpu:
            d.msgbox(
                f"Selected GPU: {selected_gpu['slot']} (VFIO: {selected_gpu['vfio']})"
            )

        if not code or not selected_gpu:
            raise WizardError("Invalid GPU selection.")

        updated_wizard_conf["gpu"] = selected_gpu
    else:
        selected_gpu = updated_wizard_conf["gpu"]

    #
    # CONFIGURE RUNTIME
    #

    # Copy missing runtime JSONs. We assume that GOLEM bins will update them if they exist.
    plugins_dir = Path("~").expanduser() / ".local/lib/yagna/plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)

    for runtime_json in Path("/usr/lib/yagna/plugins/").glob("ya-*.json"):
        if not (plugins_dir / runtime_json.name).exists():
            shutil.copy2(runtime_json, plugins_dir)

    runtime_path = (
        (Path("~").expanduser() / ".local/lib/yagna/plugins/ya-runtime-vm.json")
        .expanduser()
        .resolve()
    )
    if not runtime_path:
        raise WizardError(f"Cannot find runtime configuration file '{runtime_path}'.")

    configure_runtime(runtime_path, selected_gpu)

    #
    # FIX SUPERVISOR AND RUNTIME PATHS
    #

    runtime_files_dir = (
        (Path("~").expanduser() / ".local/lib/yagna/plugins/").expanduser().resolve()
    )
    fix_paths(runtime_files_dir)

    #
    # CONFIGURE PRESET
    #

    try:
        configure_preset(
            runtime_id="vm",
            duration_price=duration_price,
            cpu_price=cpu_price,
            init_price=glm_init_price,
        )
    except subprocess.CalledProcessError as e:
        raise WizardError(f"Failed to configure preset: {str(e)}.")

    #
    # VFIO
    #

    if not args.no_passthrough:
        try:
            bind_vfio(selected_gpu["devices"])
        except subprocess.CalledProcessError as e:
            raise WizardError(
                f"Failed to attach devices to VFIO: {str(e)}. Already bound?"
            )

    #
    # Save running config
    #

    if not args.no_save:
        try:
            wizard_conf_path.write_text(json.dumps(updated_wizard_conf, indent=4))
        except json.JSONDecodeError as e:
            logger.error(f"Failed to save configuration file: {str(e)}")


if __name__ == "__main__":
    main()