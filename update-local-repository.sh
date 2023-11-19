#!/bin/bash

set -eux

# Set the local repository path
INPUT_DIR="$(readlink -f "${1:-$(dirname "$0")/packages}")"
REPO_DIR="$(readlink -f "${2:-$(dirname "$0")/debian}")"
DISTRIBUTION="${3:-ubuntu}"
SUITE="${4:-jammy}"
GPG_KEY_ID="${5:-473F57D3A9534D53F0128E9DFF0244C9D7E28146}"

# Function to add .deb files to the local repository
create_local_repository() {
    mkdir -p "$REPO_DIR/conf"

    cat << EOF > "${REPO_DIR}/conf/distributions"
Origin: GOLEM $DISTRIBUTION
Label: GOLEM $DISTRIBUTION
Codename: $SUITE
Architectures: amd64
Components: main
Description: APT repository with GOLEM components
Tracking: all
EOF

    # Add new .deb files to the local repository
    reprepro -S misc -b "$REPO_DIR" includedeb "$SUITE" "$INPUT_DIR"/*.deb

    # Sign the repository metadata
    rm -rf "$REPO_DIR/dists/$SUITE/Release.gpg" "$REPO_DIR/dists/$SUITE/InRelease"
    gpg --detach-sign --armor --local-user "$GPG_KEY_ID" --batch --no-tty --output "$REPO_DIR/dists/$SUITE/Release.gpg" "$REPO_DIR/dists/jammy/Release"
    gpg --clearsign --armor --local-user "$GPG_KEY_ID" --batch --no-tty --output "$REPO_DIR/dists/$SUITE/InRelease" "$REPO_DIR/dists/jammy/Release"
}

# Add the new .deb files to the local repository and sign the repository metadata
create_local_repository
