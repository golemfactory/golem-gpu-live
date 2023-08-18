#!/bin/bash
# shellcheck shell=bash

#
# From https://github.com/golemfactory/ya-runtime-vm-nvidia/blob/main/install.sh
#

#
# WIP: Packaging will be used to install dependencies
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

download_vm_gpu() {
    local _ostype _url

    _ostype="$1"
    test -d "$YA_INSTALLER_DATA/bundles" || mkdir -p "$YA_INSTALLER_DATA/bundles"

    _url="https://github.com/golemfactory/${YA_INSTALLER_RUNTIME_REPO_NAME}/releases/download/${YA_INSTALLER_RUNTIME_VER}/${YA_INSTALLER_RUNTIME_REPO_NAME}-${_ostype}-${YA_INSTALLER_RUNTIME_VER}.tar.gz"
    _dl_start "ya-runtime-vm-nvidia" "$YA_INSTALLER_RUNTIME_VER"
    (downloader "$_url" - | tar -C "$YA_INSTALLER_DATA/bundles" -xz -f -) || err "failed to download $_url"
    _dl_end
    echo -n "$YA_INSTALLER_DATA/bundles/${YA_INSTALLER_RUNTIME_REPO_NAME}-${_ostype}-${YA_INSTALLER_RUNTIME_VER}"
}

# Copies Runtime to plugins dir.
# Returns path to Runtime descriptor.
install_vm_gpu() {
    local _src _plugins_dir

    _src="$1"
    _plugins_dir="$YA_INSTALLER_LIB/plugins"
    mkdir -p "$_plugins_dir"

    # remove old descriptor and runtime binaries
    for _file in $(ls "$_src"); do
        rm -rf "$_plugins_dir/$_file"
    done

    if [ $(runtime_exists) == "true" ]; then
        echo "Runtime with name \"$YA_INSTALLER_RUNTIME_ID\" already exists. Aborting.";
        exit 1;
    fi
    
    cp -r "$_src"/* "$_plugins_dir/"

    echo -n "$_plugins_dir/$YA_INSTALLER_RUNTIME_DESCRIPTOR";
}

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

display_error()
{
	dialog --title "$1" --msgbox "\n$2" $3 $4
	clear
	exit
}

# Main ################################################################################################################

main() {
    need_cmd ya-provider
    need_cmd uname
    need_cmd chmod
    need_cmd mkdir
    need_cmd mv
    need_cmd bc

    local _download_dir _runtime_descriptor _bin

    # Init PATH
    _bin="$YA_INSTALLER_DATA/bin"
    test -d "$_bin" || mkdir -p "$_bin";
    export PATH=$_bin:$PATH

    # Download runtime
    _download_dir=$(download_vm_gpu "linux") || exit 1

    # Install runtime
    _runtime_descriptor=$(install_vm_gpu "$_download_dir") || err "Failed to install $_runtime_descriptor."
}

main "$@" || exit 1
