#!/bin/bash

set -ex

# FIXME: use deb file
_resources_dir="$(mktemp -d /tmp/ya_installer_resources.XXXX)"
curl --proto '=https' --silent --show-error --fail --location https://github.com/golemfactory/ya-installer-resources/releases/latest/download/resources.tar.gz --output - | tar -C "$_resources_dir" -xz -f -

RUST_LOG=error golemsp setup --no-interactive
ya-provider pre-install
golemsp manifest-bundle add "${_resources_dir}"

rm -rf "${_resources_dir}"
