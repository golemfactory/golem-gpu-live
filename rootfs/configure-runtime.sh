#!/bin/bash

set -ex

# Fix env variables for golemsp, ya-provider, etc.
EXE_UNIT_PATH="$HOME/.local/lib/yagna/plugins/*.json"
DATA_DIR="$HOME/.local/share/ya-provider"

export EXE_UNIT_PATH DATA_DIR

# FIXME: use deb file
_resources_dir="$(mktemp -d /tmp/ya_installer_resources.XXXX)"
curl --proto '=https' --silent --show-error --fail --location https://github.com/golemfactory/ya-installer-resources/releases/latest/download/resources.tar.gz --output - | tar -C "$_resources_dir" -xz -f -

RUST_LOG=error golemsp setup --no-interactive
ya-provider pre-install
golemsp manifest-bundle add "${_resources_dir}"

rm -rf "${_resources_dir}"
