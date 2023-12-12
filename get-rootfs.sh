#!/bin/bash

# Command-line tool that simplifies the process of extracting Docker images
# and their root filesystem layers.

set -eux -o pipefail

if [ $# -ne 2 ]; then
    echo "Usage: $0 <image_name> <output_directory>"
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
    fi
}

# Check if docker and jq exist
check_command_existence "docker"
check_command_existence "jq"

image_name="$1"
output_directory="$(realpath "$2")"

trap cleanup 0 1 2 3 6 15

# Create a container based on the provided docker image
container_id="$(docker create "$image_name")"

# Copy container rootfs content to output directory
rm -rf "$output_directory/rootfs"
mkdir -p "$output_directory/rootfs"
sudo docker cp "$container_id:/" "$output_directory/rootfs/"

# Delete created container
sudo docker rm "$container_id"
