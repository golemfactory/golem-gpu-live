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

YA_INSTALLER_LIB=/usr/lib/yagna

YA_MINIMAL_GOLEM_VERSION=0.13.0-rc9 

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

main() {
    configure_runtime "$YA_INSTALLER_LIB/plugins/ya-runtime-vm-nvidia.json"
    configure_preset
}

main "$@" || exit 1
