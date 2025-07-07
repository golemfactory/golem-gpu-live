#!/usr/bin/env python3
import os
import subprocess
import toml
import logging
import json
import socket
from pathlib import Path
from urllib import request, error
from urllib.parse import urlencode

# --- Configuration ---
LOG_FILE = Path.home() / "golem-updater.log"
CONFIG_FILE = Path.home() / ".golemwz.toml"
ETAG_FILE = Path.home() / ".golem_updater.etag"
# Assumes golemwz is in the same directory
WIZARD_SCRIPT_PATH = Path(__file__).parent.resolve()
WIZARD_SCRIPT = WIZARD_SCRIPT_PATH / "golemwz"

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

def get_config():
    """Loads the local golemwz.toml configuration."""
    if not CONFIG_FILE.exists():
        logging.warning(f"Configuration file not found: {CONFIG_FILE}")
        return None
    try:
        return toml.load(CONFIG_FILE)
    except toml.TomlDecodeError as e:
        logging.error(f"Error decoding {CONFIG_FILE}: {e}")
        return None

def get_last_etag():
    """Reads the last known ETag from the state file."""
    if not ETAG_FILE.exists():
        return None
    return ETAG_FILE.read_text().strip()

def save_last_etag(etag):
    """Saves the latest ETag to the state file."""
    ETAG_FILE.write_text(etag)
    logging.info(f"Saved new ETag: {etag}")

def get_local_ip():
    """Gets the local IP address by connecting to a remote server."""
    try:
        # Connect to a public DNS server to determine our local IP
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            logging.info(f"Local IP address: {ip}")
            return ip
    except Exception as e:
        logging.error(f"Failed to get local IP: {e}")
        return None

def get_node_name():
    """Gets the node name from ya-provider config."""
    try:
        result = subprocess.run(
            ["ya-provider", "config", "get", "--json"],
            capture_output=True,
            text=True,
            check=True
        )
        config = json.loads(result.stdout)
        node_name = config.get("node_name")
        if node_name:
            logging.info(f"Node name: {node_name}")
            return node_name
        else:
            logging.warning("No node_name found in ya-provider config")
            return None
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to get ya-provider config: {e}")
        return None
    except json.JSONDecodeError as e:
        logging.error(f"Failed to parse ya-provider config JSON: {e}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error getting node name: {e}")
        return None

def check_for_updates(url, last_etag):
    """
    Checks the remote URL for changes using ETag.
    Returns the new ETag if changed, None otherwise.
    """
    # Get machine information
    local_ip = get_local_ip()
    node_name = get_node_name()

    # Build URL with query parameters
    params = {}
    if local_ip:
        params['ip'] = local_ip
    if node_name:
        params['node'] = node_name

    if params:
        separator = '&' if '?' in url else '?'
        query_string = urlencode(params)
        full_url = f"{url}{separator}{query_string}"
    else:
        full_url = url

    logging.info(f"Checking for updates at {full_url}...")
    req = request.Request(full_url, method="HEAD")
    if last_etag:
        req.add_header("If-None-Match", last_etag)

    try:
        with request.urlopen(req, timeout=30) as response:
            # Server returned 200 OK, which means the resource HAS changed.
            new_etag = response.headers.get("ETag")
            logging.info("Configuration has changed. New ETag found.")
            return new_etag
    except error.HTTPError as e:
        if e.code == 304:
            # 304 Not Modified is the expected response when nothing has changed.
            logging.info("Configuration is up-to-date (304 Not Modified).")
            return None
        else:
            logging.error(f"HTTP Error: {e.code} {e.reason}")
            return None
    except error.URLError as e:
        logging.error(f"Network or URL error: {e.reason}")
        return None
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        return None


def run_wizard():
    """Executes the main wizard script to apply the new configuration."""
    logging.info(f"Running configuration wizard: {WIZARD_SCRIPT}")
    logging.info(f"Config file exists: {CONFIG_FILE.exists()}")

    try:
        # Run wizard directly as golem user - no sudo needed since service runs as golem
        result = subprocess.run(
            [str(WIZARD_SCRIPT), "--non-interactive", "--config-update"],
            check=True,
            capture_output=True,
            text=True
        )
        logging.info("Wizard executed successfully.")
        logging.info(f"STDOUT: {result.stdout}")
        if result.stderr:
            logging.warning(f"STDERR: {result.stderr}")
    except subprocess.CalledProcessError as e:
        logging.error("Wizard script failed to execute.")
        logging.error(f"Return Code: {e.returncode}")
        logging.error(f"STDOUT: {e.stdout}")
        logging.error(f"STDERR: {e.stderr}")
    except FileNotFoundError:
        logging.error(f"Wizard script not found at {WIZARD_SCRIPT}")


def main():
    # Script now runs as golem user, so config files are in the correct home directory
    global CONFIG_FILE, ETAG_FILE, LOG_FILE
    CONFIG_FILE = Path.home() / ".golemwz.toml"
    ETAG_FILE = Path.home() / ".golem_updater.etag"
    LOG_FILE = Path.home() / "golem-updater.log"

    config = get_config()
    if not config:
        return

    server_url = config.get("configuration_server")
    if not server_url:
        logging.info("No 'configuration_server' URL found in config. Exiting.")
        return

    last_etag = get_last_etag()
    new_etag = check_for_updates(server_url, last_etag)

    if new_etag:
        save_last_etag(new_etag)
        run_wizard()
    else:
        logging.info("No action needed.")

if __name__ == "__main__":
    main()
