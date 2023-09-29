#!/bin/bash

# Command-line tool that simplifies the process of extracting Docker images
# and their root filesystem layers. It saves provided image to a tarball and then
# extracts individual layers into a directory structure.

set -eux -o pipefail

if [ $# -ne 3 ]; then
    echo "Usage: $0 <image_name> <tmp_directory> <output_directory>"
    exit 1
fi

check_command_existence() {
    # Function to check if a command exists
    command -v "$1" >/dev/null 2>&1 || {
        echo >&2 "ERROR: '$1' is required but not found. Please install '$1' before running this script."
        exit 1
    }
}

cleanup() {
    # Function to clean up temporary files and directories
    local exit_code=$?
    # FIXME: add more safe checks before removing
    if [ -n "$output_directory" ] && [ -d "$output_directory" ]; then
        if [ $exit_code -gt 0 ]; then
            rm -rf "$output_directory/rootfs"
        fi
        rm -rf "$output_directory/image.tar" "$output_directory/image_extraction"
    fi
    if [[ "$tmp_directory" =~ /.*/tmp\.* ]] && [ -d "$tmp_directory" ]; then
        rm -rf "$tmp_directory"
    fi
}

# Check if docker and jq exist
check_command_existence "docker"
check_command_existence "jq"

image_name="$1"
mkdir -p "$(realpath "$2")"
tmp_directory="$(mktemp -p "$(realpath "$2")" -d)"
output_directory="$(realpath "$3")"

trap cleanup 0 1 2 3 6 15

# Step 1: Save the Docker image to a tarball
docker save -o "$tmp_directory/image.tar" "$image_name"

# Step 2: Extract the tarball to a temporary directory
mkdir "$tmp_directory/image_extraction"
tar -xf "$tmp_directory/image.tar" -C "$tmp_directory/image_extraction"

# Step 3: Read rootfs layers
manifest_file="$tmp_directory/image_extraction/manifest.json"
read -r -a rootfs_layers <<< "$(jq -r '.[0].Layers | join(" ")' "$manifest_file")"

# Step 4: Extract the root filesystem layer from the manifest
mkdir "$tmp_directory/rootfs"
for rootfs_layer in "${rootfs_layers[@]}"; do
    tar -xf "$tmp_directory/image_extraction/$rootfs_layer" -C "$tmp_directory/rootfs"
done

# Cleanup aufs stuff
find "$tmp_directory/rootfs" -name '.wh.*' -delete

mkdir -p "$output_directory"
rm -rf "$output_directory/rootfs"
mv "$tmp_directory/rootfs" "$output_directory/"

rm -rf "$tmp_directory"
