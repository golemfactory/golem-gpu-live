#!/bin/bash
# shellcheck shell=bash

#
# From https://github.com/golemfactory/ya-runtime-vm-nvidia/blob/main/install.sh
#

#
# WIP: Packaging will be used to configure provider
#

set -eux

YA_INSTALLER_RUNTIME_VER=${YA_INSTALLER_RUNTIME_VER:-v0.1.2}
YA_INSTALLER_RUNTIME_REPO_NAME="ya-runtime-vm-nvidia"
YA_INSTALLER_RUNTIME_ID=${YA_INSTALLER_RUNTIME_ID:-vm-nvidia}
YA_INSTALLER_RUNTIME_DESCRIPTOR="${YA_INSTALLER_RUNTIME_REPO_NAME}.json"

YA_RUNTIME_VM_PCI_DEVICE=${YA_RUNTIME_VM_PCI_DEVICE:-NULL}

YA_INSTALLER_GLM_PER_HOUR=${YA_INSTALLER_GLM_PER_HOUR:-0.025}
YA_INSTALLER_INIT_PRICE=${YA_INSTALLER_INIT_PRICE:-0}

YA_INSTALLER_DATA=${YA_INSTALLER_DATA:-$HOME/.local/share/ya-installer}
YA_INSTALLER_LIB=${YA_INSTALLER_LIB:-$HOME/.local/lib/yagna}

YA_MINIMAL_GOLEM_VERSION=0.13.0-rc9 

# Runtime tools #######################################################################################################

runtime_exists() {
    provider_entry_exists "exe-unit"
}

preset_exists() {
    provider_entry_exists "preset"
}

# Checks if provided entry (exe-unit or preset) with name $YA_INSTALLER_RUNTIME_ID exists.
provider_entry_exists() {
    local _provider_cmd _new_runtime

    _provider_cmd=$1
    _new_entry=$YA_INSTALLER_RUNTIME_ID

    for old_entry in $(ya-provider $_provider_cmd list --json | jq '.[] | {name} | join(" ")'); do
        if [ "$old_entry" = "\"$_new_entry\"" ]; then
            echo -n "true";
            return 0;
        fi
    done;

    echo -n "false"
}

configure_runtime() {
    local _descriptor_path _set_name_query _add_extra_arg_query

    _descriptor_path="$1"
    _set_name_query=".[0].name = \"$YA_INSTALLER_RUNTIME_ID\"";
    jq "$_set_name_query" $_descriptor_path > "$_descriptor_path.tmp" && mv "$_descriptor_path.tmp" "$_descriptor_path";
    _add_extra_arg_query=".[0][\"extra-args\"] += [\"--runtime-arg=--pci-device=$YA_RUNTIME_VM_PCI_DEVICE\"]";
    jq "$_add_extra_arg_query" $_descriptor_path > "$_descriptor_path.tmp" && mv "$_descriptor_path.tmp" "$_descriptor_path";
}

configure_preset() {
    local _duration_price _cpu_price _preset_cmd

    # based on https://github.com/golemfactory/yagna/blob/pre-rel-v0.13.0-raw-rc8/golem_cli/src/setup.rs#L139
    _duration_price=$(echo "$YA_INSTALLER_GLM_PER_HOUR / 3600.0 / 5.0" | bc -l);
    _cpu_price=$(echo "$YA_INSTALLER_GLM_PER_HOUR / 3600.0" | bc -l);

    if [ $(preset_exists) == "true" ]; then
        _preset_cmd="update --name $YA_INSTALLER_RUNTIME_ID";
    else
        _preset_cmd="create --preset-name $YA_INSTALLER_RUNTIME_ID";
    fi

    ya-provider preset $_preset_cmd \
        --no-interactive \
        --exe-unit $YA_INSTALLER_RUNTIME_ID \
        --pricing linear \
        --price Duration=$_duration_price CPU=$_cpu_price "Init price"=$YA_INSTALLER_INIT_PRICE;

    ya-provider preset activate $YA_INSTALLER_RUNTIME_ID
}

# IOMMU ###############################################################################################################

get_iommu_groups()
{
    ls -v /sys/kernel/iommu_groups
}

test_iommu_enabled()
{
    count_iommu_groups=$(get_iommu_groups | wc -l)
    if [ $count_iommu_groups -gt 0 ]; then
        echo enabled
    else
        echo disabled
    fi
}

get_iommu_group_devices()
{
    ls /sys/kernel/iommu_groups/$iommu_group/devices
}

# PCI #################################################################################################################

get_pid_vid_from_slot()
{
    lspci -n -s $1 | awk -F" " '{print $3}'
}

get_pci_full_string_description_from_slot()
{
    lspci -s $1
}

get_pci_short_string_description_from_slot()
{
    get_pci_full_string_description_from_slot $1 | awk -F": " '{print $2}'
}

list_pci_devices_in_iommu_group()
{
    ret="IOMMU Group "$1
    ret="$ret\n##############"
    for device in $2; do
        ret="$ret\n$(get_pci_full_string_description_from_slot $device)"
    done;
    echo $ret
}

test_pci_slot_as_vga()
{
    lspci -d ::0300 -s $1
}

test_pci_slot_as_audio()
{
    lspci -d ::0403 -s $1
}

# vfio ################################################################################################################

get_gpu_list_as_menu()
{
    menu=""
    gpu_list_size=$(expr ${#gpu_list[@]} / 3)
    for ((i=0; i<$gpu_list_size; i++));    do
        if [ "$menu" == "" ]; then
            menu="$i%${gpu_list[$i,0]}"
        else
            menu="$menu%$i%${gpu_list[$i,0]}"
        fi
    done;
    echo $menu
}

select_gpu_compatible()
{
    least_one_gpu_compatible=0
    declare -A gpu_list
    gpu_count=0

    iommu_groups=$(get_iommu_groups);
    for iommu_group in $iommu_groups; do

        devices=$(get_iommu_group_devices)
        devices_count=$(echo $devices | wc -w)

        for device in $devices; do
            gpu_vga=$(test_pci_slot_as_vga $device)

            if [ ! -z "$gpu_vga" ]; then
                gpu_vga_slot=$(echo $gpu_vga | awk -F" " '{print $1}')

                if [ $devices_count -gt 2 ]; then
                    display_bad_isolation $iommu_group "$devices"
                elif [ $devices_count -eq 2 ]; then

                    second_device=$(echo $devices | awk -F" " '{print $2}')
                    gpu_audio=$(test_pci_slot_as_audio $second_device)

                    if [ ! -z "$gpu_audio" ]; then

                        least_one_gpu_compatible=1

                        gpu_audio_slot=$(echo $gpu_audio | awk -F" " '{print $1}')

                        gpu_vga_pid_vid=$(get_pid_vid_from_slot $gpu_vga_slot)
                        gpu_audio_pid_vid=$(get_pid_vid_from_slot $gpu_audio_slot)
                        vfio=$gpu_vga_pid_vid","$gpu_audio_pid_vid

                        gpu_list[$gpu_count,0]=$(get_pci_short_string_description_from_slot $gpu_vga)
                        gpu_list[$gpu_count,1]=$vfio
                        gpu_list[$gpu_count,2]=$gpu_vga_slot
                        ((gpu_count+=1))

                    else
                        display_bad_isolation $iommu_group "$devices"
                    fi
                else

                    least_one_gpu_compatible=1

                    gpu_vga_pid_vid=$(get_pid_vid_from_slot $gpu_vga_slot)
                    vfio=$gpu_vga_pid_vid

                    gpu_list[$gpu_count,0]=$(get_pci_short_string_description_from_slot $device)
                    gpu_list[$gpu_count,1]=$vfio
                    gpu_list[$gpu_count,2]=$gpu_vga_slot
                    ((gpu_count+=1))
                fi
            fi
        done;
    done;

    if [ $least_one_gpu_compatible -eq 0 ]; then
        dialog --stdout --title "Error" --msgbox "\nNo compatible GPU available." 6 50
        exit 1
    else
        menu=$(get_gpu_list_as_menu $gpu_list)
        IFS=$'%'
        gpu_index=$(dialog --stdout --menu "Select GPU to share" 0 0 0 $menu)
        unset IFS
        if [ "$gpu_index" == "" ]; then
            dialog --stdout --title "Cancel" --msgbox "\nInstallation canceled." 6 30
            exit 2
        else
            gpu_vfio=${gpu_list[$gpu_index,1]}
            gpu_slot=${gpu_list[$gpu_index,2]}
            echo "$gpu_vfio $gpu_slot"
        fi
    fi
}

display_bad_isolation()
{
	msg=$(list_pci_devices_in_iommu_group $1 "$2")
	dialog --stdout --title "GPU bad isolation" --msgbox "\n$msg\n\nTry changing your GPU PCIe slot." 13 130
}

# Tools ###############################################################################################################

_dl_head() {
    local _sep
    _sep="-----"
    _sep="$_sep$_sep$_sep$_sep"
    printf "%-20s %25s\n" " Component " " Version" >&2
    printf "%-20s %25s\n" "-----------" "$_sep" >&2
}

_dl_start() {
    printf "%-20s %25s " "$1" "$(version_name "$2")" >&2
}

_dl_end() {
    printf "[done]\n" >&2
}

downloader() {
    local _dld
    if check_cmd curl; then
        _dld=curl
    elif check_cmd wget; then
        _dld=wget
    else
        _dld='curl or wget' # to be used in error message of need_cmd
    fi

    if [ "$1" = --check ]; then
        need_cmd "$_dld"
    elif [ "$_dld" = curl ]; then
        curl --proto '=https' --silent --show-error --fail --location "$1" --output "$2"
    elif [ "$_dld" = wget ]; then
        wget -O "$2" --https-only "$1"
    else
        err "Unknown downloader"   # should not reach here
    fi
}

version_name() {
    local name

    name=${1#pre-rel-}
    printf "%s" "${name#v}"
}

say() {
    printf 'golem-installer: %s\n' "$1"
}

err() {
    say "$1" >&2
    exit 1
}

need_cmd() {
    if ! check_cmd "$1"; then
        err "need '$1' (command not found)"
    fi
}

check_cmd() {
    command -v "$1" > /dev/null 2>&1
}

clear_exit() {
    clear;
    exit 1
}

display_bad_isolation()
{
	msg=$(list_pci_devices_in_iommu_group $1 "$2")
	dialog --stdout --title "GPU bad isolation" --msgbox "\n$msg\n\nTry changing your GPU PCIe slot." 13 130
}


# Main ################################################################################################################

main() {
    need_cmd ya-provider
    need_cmd uname
    need_cmd chmod
    need_cmd mkdir
    need_cmd mv
    need_cmd bc

    local _runtime_descriptor _bin

    # Init PATH
    _bin="$YA_INSTALLER_DATA/bin"
    test -d "$_bin" || mkdir -p "$_bin";
    export PATH=$_bin:$PATH

    _runtime_descriptor="$YA_INSTALLER_LIB/plugins/ya-runtime-vm-nvidia.json"

    # Select GPU
    if [ "$YA_RUNTIME_VM_PCI_DEVICE" == "NULL" ]; then
        YA_RUNTIME_VM_PCI_DEVICE=$(select_gpu_compatible) || err "Failed to select GPU."
    fi

    configure_runtime "$_runtime_descriptor"

    configure_preset
}

main "$@" || exit 1
