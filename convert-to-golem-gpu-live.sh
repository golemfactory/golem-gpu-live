#!/bin/bash

#
# Golem GPU Live System Converter
#
# This script converts an existing Ubuntu 22.04 installation to be compatible
# with the Golem GPU live image system, enabling GPU passthrough for distributed computing.
#
# Prerequisites:
# - Ubuntu 22.04 (Jammy) system
# - Root privileges
# - Internet connectivity
# - At least 2GB free disk space
#
# Usage:
#   sudo ./convert-to-golem-gpu-live.sh [--dry-run] [--no-backup] [--quiet]
#
# Options:
#   --dry-run     Show what would be done without making changes
#   --no-backup   Skip creating backups of modified files
#   --quiet       Reduce output verbosity
#   --help        Show this help message
#

set -euo pipefail

# Script configuration
readonly SCRIPT_VERSION="1.0.0"
readonly SCRIPT_NAME="$(basename "$0")"
readonly LOG_FILE="/var/log/golem-gpu-live-conversion.log"
readonly BACKUP_DIR="/var/backups/golem-conversion-$(date +%Y%m%d-%H%M%S)"

# Golem repository configuration
readonly GOLEM_GPG_KEY="A6FC0686E1EFC16F5D8AAAA6C69F9049D4AC7CD4"
readonly GOLEM_REPO_URL="https://gpu-live.cdn.golem.network/susteen"
# GPG certificate is embedded inline in setup_golem_repository function

# Package lists
readonly SYSTEM_PACKAGES=(
    "python3-dialog"
    "python3-toml"
    "python3-tomli-w"
    "qemu-kvm"
    "musl-tools"
    "avahi-daemon"
    "libnss-mdns"
    "unattended-upgrades"
    "bc"
    "jq"
    "dialog"
    "curl"
    "wget"
)

readonly GOLEM_PACKAGES=(
    "golem-provider"
    "golem-nvidia-kernel"
    "ya-runtime-vm-nvidia"
    "ya-runtime-wasi-cli"
    "ya-installer-resources"
    "golem-wizard"
    "golem-config-updater"
)

# Global flags
DRY_RUN=false
NO_BACKUP=false
QUIET=false
ERRORS_OCCURRED=false

#
# Utility Functions
#

log() {
    local level="$1"
    shift
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    local message="[$timestamp] [$level] $*"

    echo "$message" | tee -a "$LOG_FILE" >&2

    if [[ "$level" == "ERROR" ]]; then
        ERRORS_OCCURRED=true
    fi
}

info() { [[ "$QUIET" == "true" ]] || log "INFO" "$@"; }
warn() { log "WARN" "$@"; }
error() { log "ERROR" "$@"; }
debug() { [[ "${DEBUG:-}" == "true" ]] && log "DEBUG" "$@" || true; }

die() {
    error "$@"
    exit 1
}

progress() {
    local current=$1
    local total=$2
    local message=$3

    if [[ "$QUIET" != "true" ]]; then
        printf "\r[%3d/%3d] %-60s" "$current" "$total" "$message"
        if [[ "$current" -eq "$total" ]]; then
            echo " ✓"
        fi
    fi
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        die "This script must be run as root. Use: sudo $SCRIPT_NAME"
    fi
}

check_ubuntu_version() {
    if ! grep -q "Ubuntu 22.04" /etc/os-release 2>/dev/null; then
        warn "This script is designed for Ubuntu 22.04 (Jammy). Continuing anyway..."
        if ! grep -q "jammy\|22.04" /etc/os-release 2>/dev/null; then
            die "Unsupported Ubuntu version. This script requires Ubuntu 22.04."
        fi
    fi
}

backup_file() {
    local file="$1"
    local backup_path="$BACKUP_DIR$(dirname "$file")"

    if [[ "$NO_BACKUP" == "true" ]]; then
        return 0
    fi

    if [[ -f "$file" ]]; then
        mkdir -p "$backup_path"
        cp "$file" "$backup_path/" 2>/dev/null || {
            warn "Failed to backup $file"
            return 1
        }
        debug "Backed up $file to $backup_path/"
    fi
}

restore_backups() {
    if [[ "$NO_BACKUP" == "true" || ! -d "$BACKUP_DIR" ]]; then
        return 0
    fi

    warn "Restoring backed up files..."

    # Restore files from backup
    if command -v rsync >/dev/null 2>&1; then
        rsync -av "$BACKUP_DIR/" / 2>/dev/null || warn "Some files could not be restored"
    else
        cp -r "$BACKUP_DIR"/* / 2>/dev/null || warn "Some files could not be restored"
    fi

    info "Backup restoration attempted. Check $BACKUP_DIR for details."
}

install_essential_packages() {
    info "Installing essential packages..."

    local essential_packages=("curl" "wget" "ca-certificates" "gnupg")

    if [[ "$DRY_RUN" != "true" ]]; then
        apt-get update -qq || die "Failed to update package lists"

        for package in "${essential_packages[@]}"; do
            if ! command -v "$package" >/dev/null 2>&1 && ! dpkg -l "$package" 2>/dev/null | grep -q "^ii"; then
                info "Installing $package..."
                apt-get install -y "$package" || die "Failed to install $package"
            else
                info "$package is already available"
            fi
        done

        # Verify curl is now available
        if ! command -v curl >/dev/null 2>&1; then
            die "curl is still not available after installation attempt"
        fi
    else
        info "DRY RUN: Would install essential packages: ${essential_packages[*]}"
    fi
}

verify_network() {
    info "Checking network connectivity..."

    if ! curl -s --connect-timeout 10 "$GOLEM_REPO_URL" >/dev/null; then
        die "Cannot reach Golem repository at $GOLEM_REPO_URL. Check network connectivity."
    fi
}

#
# System Configuration Functions
#

setup_logging() {
    mkdir -p "$(dirname "$LOG_FILE")"
    touch "$LOG_FILE"
    chmod 644 "$LOG_FILE"

    info "Starting Golem GPU Live conversion (v$SCRIPT_VERSION)"
    info "Log file: $LOG_FILE"
    [[ "$NO_BACKUP" != "true" ]] && info "Backup directory: $BACKUP_DIR"
}

setup_golem_repository() {
    info "Setting up Golem APT repository..."

    # Install GPG key (embedded)
    local gpg_key_path="/etc/apt/trusted.gpg.d/golem.asc"
    backup_file "$gpg_key_path"

    if [[ "$DRY_RUN" != "true" ]]; then
        cat > "$gpg_key_path" << 'EOF'
-----BEGIN PGP PUBLIC KEY BLOCK-----

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
0g==
=R7Fw
-----END PGP PUBLIC KEY BLOCK-----
EOF
        chmod 644 "$gpg_key_path"
    fi

    # Add repository to sources list
    local repo_list="/etc/apt/sources.list.d/golem.list"
    backup_file "$repo_list"

    if [[ "$DRY_RUN" != "true" ]]; then
        echo "deb $GOLEM_REPO_URL jammy main" > "$repo_list"
        chmod 644 "$repo_list"
    fi

    # Set debconf selection for golem terms
    if [[ "$DRY_RUN" != "true" ]]; then
        echo 'golem golem/terms/subsidy-01 string yes' | debconf-set-selections
    fi

    info "Golem repository configured successfully"
}

update_package_lists() {
    info "Updating package lists..."

    if [[ "$DRY_RUN" != "true" ]]; then
        export DEBIAN_FRONTEND=noninteractive
        apt-get update || die "Failed to update package lists"
    fi
}

install_system_packages() {
    info "Installing system packages..."

    local failed_packages=()
    local total=${#SYSTEM_PACKAGES[@]}
    local current=0

    if [[ "$DRY_RUN" == "true" ]]; then
        info "Would install: ${SYSTEM_PACKAGES[*]}"
        return 0
    fi

    export DEBIAN_FRONTEND=noninteractive

    for package in "${SYSTEM_PACKAGES[@]}"; do
        current=$((current + 1))
        progress $current $total "Installing $package..."

        if apt-get install -y --no-install-recommends "$package" >/dev/null 2>&1; then
            debug "Successfully installed $package"
        else
            warn "Failed to install $package"
            failed_packages+=("$package")
        fi
    done

    if [[ ${#failed_packages[@]} -gt 0 ]]; then
        error "Failed to install packages: ${failed_packages[*]}"
        return 1
    fi

    info "System packages installed successfully"
}

install_golem_packages() {
    info "Installing Golem packages..."

    local failed_packages=()
    local total=${#GOLEM_PACKAGES[@]}
    local current=0

    if [[ "$DRY_RUN" == "true" ]]; then
        info "Would install: ${GOLEM_PACKAGES[*]}"
        return 0
    fi

    export DEBIAN_FRONTEND=noninteractive

    for package in "${GOLEM_PACKAGES[@]}"; do
        current=$((current + 1))
        progress $current $total "Installing $package..."

        if apt-get install -y --no-install-recommends "$package" >/dev/null 2>&1; then
            debug "Successfully installed $package"
        else
            warn "Failed to install $package"
            failed_packages+=("$package")
        fi
    done

    if [[ ${#failed_packages[@]} -gt 0 ]]; then
        error "Failed to install Golem packages: ${failed_packages[*]}"
        return 1
    fi

    info "Golem packages installed successfully"
}

setup_golem_user() {
    info "Setting up golem user..."

    if [[ "$DRY_RUN" == "true" ]]; then
        info "Would create golem user with sudo and kvm groups"
        return 0
    fi

    # Create golem user if it doesn't exist
    if ! id "golem" >/dev/null 2>&1; then
        useradd -m -s /bin/bash golem || die "Failed to create golem user"
        passwd -d golem || warn "Failed to remove password for golem user"
    else
        info "User 'golem' already exists"
    fi

    # Add to groups
    usermod -aG sudo,kvm golem || die "Failed to add golem to groups"

    # Configure passwordless sudo
    local sudoers_file="/etc/sudoers.d/golem"
    backup_file "$sudoers_file"
    echo "golem ALL=(ALL) NOPASSWD: ALL" > "$sudoers_file"
    chmod 440 "$sudoers_file"

    # Set password expiry to force change (mimicking chage -d 0)
    chage -d 0 golem 2>/dev/null || warn "Could not set password expiry for golem user"

    info "Golem user configured successfully"
}

setup_autologin() {
    info "Configuring autologin for golem user..."

    local override_dir="/etc/systemd/system/getty@tty1.service.d"
    local override_file="$override_dir/override.conf"

    if [[ "$DRY_RUN" == "true" ]]; then
        info "Would configure autologin for golem on tty1"
        return 0
    fi

    mkdir -p "$override_dir"
    backup_file "$override_file"

    cat > "$override_file" << 'EOF'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin golem --noclear %I $TERM
EOF

    chmod 644 "$override_file"
    info "Autologin configured successfully"
}

configure_vfio() {
    info "Configuring VFIO for GPU passthrough..."

    # Create modprobe configuration
    local vfio_conf="/etc/modprobe.d/vfio.conf"
    backup_file "$vfio_conf"

    if [[ "$DRY_RUN" != "true" ]]; then
        cat > "$vfio_conf" << 'EOF'
blacklist nouveau
blacklist snd_hda_intel
EOF
        chmod 644 "$vfio_conf"
    fi

    # Create udev rules for VFIO permissions
    local vfio_rules="/etc/udev/rules.d/50-vfio.rules"
    backup_file "$vfio_rules"

    if [[ "$DRY_RUN" != "true" ]]; then
        cat > "$vfio_rules" << 'EOF'
SUBSYSTEM=="vfio", OWNER="root", GROUP="kvm"
KERNEL=="vfio", OWNER="root", GROUP="kvm", MODE="0660"
EOF
        chmod 644 "$vfio_rules"
    fi

    info "VFIO configuration completed"
}

configure_network_manager() {
    info "Configuring NetworkManager..."

    local nm_conf="/etc/NetworkManager/NetworkManager.conf"
    local nm_global_conf="/usr/lib/NetworkManager/conf.d/10-globally-managed-devices.conf"

    backup_file "$nm_conf"
    backup_file "$nm_global_conf"

    if [[ "$DRY_RUN" != "true" ]]; then
        # Enable NetworkManager to manage all devices
        sed -i 's/managed=false/managed=true/g' "$nm_conf" 2>/dev/null || warn "Failed to update NetworkManager.conf"

        # Clear globally managed devices configuration
        echo > "$nm_global_conf"
    fi

    info "NetworkManager configuration completed"
}

configure_services() {
    info "Configuring system services..."

    if [[ "$DRY_RUN" == "true" ]]; then
        info "Would enable: ssh, avahi-daemon services"
        return 0
    fi

    # Enable SSH service
    systemctl enable ssh.service || warn "Failed to enable SSH service"

    # Enable avahi-daemon for mDNS support
    systemctl enable avahi-daemon.service || warn "Failed to enable avahi-daemon service"

    info "System services configured successfully"
}

setup_golemsp_service() {
    info "Setting up Golem provider service..."

    local service_file="/etc/systemd/system/golemsp.service"
    local service_link="/etc/systemd/system/multi-user.target.wants/golemsp.service"

    if [[ "$DRY_RUN" == "true" ]]; then
        info "Would create golemsp.service and enable it"
        return 0
    fi

    backup_file "$service_file"

    # Create golemsp.service file
    cat > "$service_file" << 'EOF'
[Unit]
Description=GOLEM SP Boot
Wants=network-online.target
After=network-online.target golemwz.service
ConditionKernelCommandLine=!skip_autostart

[Service]
ExecStart=/usr/bin/golemsp run
Restart=always
Type=simple
User=golem
Group=golem
Environment=HOME=/home/golem
Environment=YAGNA_METRICS_GROUP=GolemGpuLive
EnvironmentFile=-/mnt/golem.env
LimitMEMLOCK=infinity
PIDFile=/home/golem/.local/share/ya-provider/ya-provider.pid

[Install]
WantedBy=default.target
EOF

    chmod 644 "$service_file"

    # Enable the service by creating symlink
    mkdir -p "$(dirname "$service_link")"
    ln -sf "$service_file" "$service_link" 2>/dev/null || warn "Failed to create service symlink"

    # Also enable it through systemctl for good measure
    systemctl enable golemsp.service || warn "Failed to enable golemsp service"

    info "Golem provider service configured successfully"
}

configure_grub() {
    info "Configuring GRUB bootloader..."

    local grub_default="/etc/default/grub"
    backup_file "$grub_default"

    if [[ "$DRY_RUN" == "true" ]]; then
        info "Would update GRUB configuration for IOMMU support"
        return 0
    fi

    # Update GRUB configuration for IOMMU and quiet boot
    sed -i 's/^GRUB_CMDLINE_LINUX_DEFAULT=.*/GRUB_CMDLINE_LINUX_DEFAULT="quiet intel_iommu=on amd_iommu=on"/' "$grub_default"
    sed -i 's/^GRUB_TIMEOUT=.*/GRUB_TIMEOUT=0/' "$grub_default"
    sed -i 's/^#GRUB_TIMEOUT_STYLE=.*/GRUB_TIMEOUT_STYLE=hidden/' "$grub_default"
    sed -i 's/^GRUB_TIMEOUT_STYLE=.*/GRUB_TIMEOUT_STYLE=hidden/' "$grub_default"

    # Add GRUB_TIMEOUT_STYLE if it doesn't exist
    if ! grep -q "GRUB_TIMEOUT_STYLE" "$grub_default"; then
        echo "GRUB_TIMEOUT_STYLE=hidden" >> "$grub_default"
    fi

    # Update GRUB
    update-grub || die "Failed to update GRUB configuration"

    info "GRUB configuration updated successfully"
}

configure_unattended_upgrades() {
    info "Configuring unattended upgrades..."

    local auto_upgrades="/etc/apt/apt.conf.d/20auto-upgrades"
    backup_file "$auto_upgrades"

    if [[ "$DRY_RUN" != "true" ]]; then
        cat > "$auto_upgrades" << 'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Download-Upgradeable-Packages "1";
APT::Periodic::AutocleanInterval "7";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::Enable "1";
Unattended-Upgrade::Allowed-Origins:: "GOLEM ubuntu:";
EOF
        chmod 644 "$auto_upgrades"

        # Remove conflicting files
        rm -f /etc/apt/apt.conf.d/docker-disable-periodic-update \
              /usr/sbin/policy-rc.d 2>/dev/null || true
    fi

    info "Unattended upgrades configured successfully"
}

setup_golem_directories() {
    info "Setting up Golem directories..."

    if [[ "$DRY_RUN" == "true" ]]; then
        info "Would create /opt/golem-config directory with default configuration"
        return 0
    fi

    # Create golem config directory (analog to config partition)
    mkdir -p /opt/golem-config
    chown golem:golem /opt/golem-config
    chmod 755 /opt/golem-config

    # Create default golemwz.toml configuration
    cat > /opt/golem-config/golemwz.toml << 'EOF'
# Golem Configuration
accepted_terms = true
glm_account = "0xC0CedB0282D285ad642D223081c9b3ADa2daA3A9"
glm_per_hour = "0.1"
non_interactive_install = true
ssh_keys = [
	"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJjQCRMBzVtRUaUZHy+6b+4NgMkBBywOMdYPMoAReZg5 colon@Hydra",
	"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPeI8LZGexCdqXozb+gPKnZCQLr7AlXqRCgJpM9eS/y3 reqc@pop-os"
]
configuration_server = "http://63.176.129.155/config.toml"

[whitelist]
susteen-servers = ["63.176.129.155"]

# Environment Variables
[env]
YA_NET_TYPE = "central"
SUBNET = "susteen"
YA_PAYMENT_NETWORK_GROUP = "testnet"
YAGNA_METRICS_URL = "http://63.176.129.155:9091"
#YAGNA_METRICS_URL = "http://192.168.102.32:8000"
YAGNA_METRICS_JOB_NAME = "community.1"
YAGNA_METRICS_GROUP = "dc2"
EOF

    chown golem:golem /opt/golem-config/golemwz.toml
    chmod 644 /opt/golem-config/golemwz.toml

    info "Golem directories and default susteen configuration created successfully"
}

configure_kernel() {
    info "Configuring kernel parameters..."

    local noresume_conf="/etc/initramfs-tools/conf.d/noresume.conf"
    backup_file "$noresume_conf"

    if [[ "$DRY_RUN" != "true" ]]; then
        # Disable resume to avoid issues with hibernation
        mkdir -p "$(dirname "$noresume_conf")"
        echo "RESUME=none" > "$noresume_conf"

        # Update initramfs
        update-initramfs -u || warn "Failed to update initramfs"
    fi

    info "Kernel configuration completed"
}

setup_motd() {
    info "Setting up welcome message..."

    if [[ "$DRY_RUN" == "true" ]]; then
        info "Would configure Golem welcome message"
        return 0
    fi

    # Remove existing motd files
    rm -rf /etc/update-motd.d/* 2>/dev/null || true

    # Create Golem header
    local header_file="/etc/update-motd.d/00-header"
    cat > "$header_file" << 'EOF'
#!/bin/sh

printf 'Welcome to GOLEM provider environment\n\n'
printf ' * Wizard logfile -- ~/golemwz.log\n'
printf ' * Yagna logfile -- ~/.local/share/yagna/yagna_rCURRENT.log\n\n'
EOF

    chmod +x "$header_file"
    info "Welcome message configured successfully"
}

#
# Verification Functions
#

verify_installation() {
    info "Verifying installation..."

    local verification_failed=false

    # Check if golem user exists and has correct groups
    if ! id golem >/dev/null 2>&1; then
        error "Golem user was not created"
        verification_failed=true
    elif ! groups golem | grep -q "sudo\|kvm"; then
        error "Golem user is not in required groups"
        verification_failed=true
    fi

    # Check if packages are installed
    local missing_packages=()
    for package in "${GOLEM_PACKAGES[@]}"; do
        if ! dpkg -l "$package" >/dev/null 2>&1; then
            missing_packages+=("$package")
        fi
    done

    if [[ ${#missing_packages[@]} -gt 0 ]]; then
        error "Missing packages: ${missing_packages[*]}"
        verification_failed=true
    fi

    # Check if configuration files exist
    local config_files=(
        "/etc/modprobe.d/vfio.conf"
        "/etc/udev/rules.d/50-vfio.rules"
        "/etc/systemd/system/getty@tty1.service.d/override.conf"
        "/etc/systemd/system/golemsp.service"
        "/etc/initramfs-tools/conf.d/noresume.conf"
        "/etc/apt/sources.list.d/golem.list"
        "/etc/apt/trusted.gpg.d/golem.asc"
    )

    for file in "${config_files[@]}"; do
        if [[ ! -f "$file" ]]; then
            error "Missing configuration file: $file"
            verification_failed=true
        fi
    done

    if [[ "$verification_failed" == "true" ]]; then
        error "Installation verification failed"
        return 1
    fi

    info "Installation verification passed"
    return 0
}

#
# Cleanup and Error Handling
#

cleanup() {
    local exit_code=$?

    if [[ "$exit_code" -ne 0 && "$ERRORS_OCCURRED" == "true" ]]; then
        error "Script failed with errors. Check $LOG_FILE for details."

        if [[ "$NO_BACKUP" != "true" && -d "$BACKUP_DIR" ]]; then
            echo
            echo "To restore original configuration:"
            echo "  sudo rsync -av $BACKUP_DIR/ /"
            echo
        fi
    fi

    exit $exit_code
}

rollback() {
    warn "Rolling back changes due to critical error..."
    restore_backups
    die "Rollback completed. System restored to previous state."
}

#
# Main Execution Functions
#

show_help() {
    cat << EOF
$SCRIPT_NAME - Golem GPU Live System Converter v$SCRIPT_VERSION

DESCRIPTION:
    Converts an existing Ubuntu 22.04 installation to be compatible with the
    Golem GPU live image system, enabling GPU passthrough for distributed computing.

USAGE:
    sudo $SCRIPT_NAME [OPTIONS]

OPTIONS:
    --dry-run       Show what would be done without making changes
    --no-backup     Skip creating backups of modified files
    --quiet         Reduce output verbosity
    --help          Show this help message

REQUIREMENTS:
    - Ubuntu 22.04 (Jammy) system
    - Root privileges
    - Internet connectivity
    - At least 2GB free disk space

WHAT THIS SCRIPT DOES:
    1. Adds Golem APT repository and GPG key
    2. Installs required system and Golem packages
    3. Creates 'golem' user with proper permissions
    4. Configures autologin for golem user
    5. Sets up VFIO for GPU passthrough
    6. Configures NetworkManager and system services
    7. Updates GRUB for IOMMU support
    8. Configures unattended upgrades
    9. Sets up kernel parameters and initramfs

LOGS:
    Conversion log: $LOG_FILE
    Backups (if enabled): $BACKUP_DIR

EXAMPLES:
    # Standard conversion
    sudo $SCRIPT_NAME

    # Preview changes without applying
    sudo $SCRIPT_NAME --dry-run

    # Quiet conversion without backups
    sudo $SCRIPT_NAME --quiet --no-backup

EOF
}

main() {
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            --no-backup)
                NO_BACKUP=true
                shift
                ;;
            --quiet)
                QUIET=true
                shift
                ;;
            --help)
                show_help
                exit 0
                ;;
            *)
                die "Unknown option: $1. Use --help for usage information."
                ;;
        esac
    done

    # Set up error handling
    trap cleanup EXIT
    trap rollback ERR

    # Initial checks
    check_root
    check_ubuntu_version
    setup_logging
    install_essential_packages
    verify_network

    if [[ "$DRY_RUN" == "true" ]]; then
        info "DRY RUN MODE - No changes will be made"
        echo
    fi

    # Create backup directory
    if [[ "$NO_BACKUP" != "true" && "$DRY_RUN" != "true" ]]; then
        mkdir -p "$BACKUP_DIR"
    fi

    # Main conversion steps
    local total_steps=12
    local current_step=0

    info "Starting Golem GPU Live system conversion..."
    echo

    current_step=$((current_step + 1)); progress $current_step $total_steps "Setting up Golem repository"
    setup_golem_repository

    current_step=$((current_step + 1)); progress $current_step $total_steps "Updating package lists"
    update_package_lists

    current_step=$((current_step + 1)); progress $current_step $total_steps "Installing system packages"
    install_system_packages

    current_step=$((current_step + 1)); progress $current_step $total_steps "Installing Golem packages"
    install_golem_packages

    current_step=$((current_step + 1)); progress $current_step $total_steps "Setting up golem user"
    setup_golem_user

    current_step=$((current_step + 1)); progress $current_step $total_steps "Configuring autologin"
    setup_autologin

    current_step=$((current_step + 1)); progress $current_step $total_steps "Configuring VFIO"
    configure_vfio

    current_step=$((current_step + 1)); progress $current_step $total_steps "Configuring NetworkManager"
    configure_network_manager

    current_step=$((current_step + 1)); progress $current_step $total_steps "Configuring services"
    configure_services
    setup_golemsp_service

    current_step=$((current_step + 1)); progress $current_step $total_steps "Updating GRUB configuration"
    configure_grub

    current_step=$((current_step + 1)); progress $current_step $total_steps "Configuring unattended upgrades"
    configure_unattended_upgrades

    current_step=$((current_step + 1)); progress $current_step $total_steps "Setting up directories and kernel"
    setup_golem_directories
    configure_kernel
    setup_motd

    echo

    # Verification
    if [[ "$DRY_RUN" != "true" ]]; then
        if ! verify_installation; then
            die "Installation verification failed. Check logs for details."
        fi
    fi

    # Success message
    echo
    info "======================================"
    if [[ "$DRY_RUN" == "true" ]]; then
        info "DRY RUN COMPLETED SUCCESSFULLY"
        info "No changes were made to your system."
    else
        info "CONVERSION COMPLETED SUCCESSFULLY"
        info "Your system is now configured as a Golem GPU Live system."
        echo
        info "IMPORTANT NEXT STEPS:"
        info "1. Reboot your system to apply kernel changes"
        info "2. Log in as 'golem' user (autologin should work)"
        info "3. Run 'golemwz' to configure your Golem provider"
        info "4. Check GPU passthrough with 'lspci' and 'lsmod | grep vfio'"
        echo
        info "Logs: $LOG_FILE"
        [[ "$NO_BACKUP" != "true" ]] && info "Backups: $BACKUP_DIR"
    fi
    info "======================================"
}

# Run main function with all arguments
main "$@"
