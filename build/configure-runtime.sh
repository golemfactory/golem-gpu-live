#!/bin/bash

YA_INSTALLER_DATA=${YA_INSTALLER_DATA:-$HOME/.local/share/ya-installer}
YA_INSTALLER_LIB=${YA_INSTALLER_LIB:-$HOME/.local/lib/yagna}

RUST_LOG=error golemsp setup <&2 || exit 1
ya-provider pre-install >/dev/null 2>&1
golemsp manifest-bundle add $_resources_dir >/dev/null 2>&1
