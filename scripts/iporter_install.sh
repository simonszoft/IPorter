#!/usr/bin/env bash
# This script installs IPorter on a Linux system. It should be run as root or with sudo privileges.

set -euo pipefail

# Check for root privileges and re-run with sudo if not
if [[ "${EUID}" -ne 0 ]]; then
    echo "This script must be run as root. Restarting with sudo..."
    exec sudo bash "$0" "$@"
fi

# Determine the scripts directory and the source directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Program metadata
PROGRAM_NAME="IPorter"
PROGRAM_VERSION="$(grep -m1 '^version' "${SOURCE_DIR}/pyproject.toml" | sed 's/.*= *"\(.*\)"/\1/')"

# Defaults (overridden interactively in main)
INSTALL_DIR="${IPORTER_INSTALL_DIR:-/opt/IPorter}"
WEB_UI_PORT="${IPORTER_WEB_UI_PORT:-8080}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
LOG_LEVEL="${IPORTER_LOG_LEVEL:-INFO}"
ETC_IPORTER_DIR="/etc/iporter"

# Derived paths — finalised in main() after prompts
PROJECT_DIR=""
SERVICE_SCRIPT=""
CONFIG_PATH=""
VENV_DIR=""
SECURE_JSON_PATH=""
SETTINGS_DIR=""
ETC_SETTINGS_LINK=""

usage() {
  cat <<'EOF'
Usage:
  ./scripts/iporter_install.sh

What it does:
  1. Syncs project files to install directory
  2. Creates or reuses local Python virtualenv (.venv)
  3. Installs/updates all Python dependencies automatically
  4. Creates config/secure.json if missing
  5. Sets web_gui.port in config (default 8080, customizable)
  6. Optionally symlinks settings into /etc/iporter/settings
  7. Runs systemd service install via scripts/iporter-service.sh install

Optional environment variables:
  PYTHON_BIN=<python executable>               (default: python3)
  IPORTER_INSTALL_DIR=<target directory>       (default: /opt/IPorter)
  IPORTER_CONFIG=<absolute path to config>     (default: ./config/config.yaml)
  IPORTER_LOG_LEVEL=<DEBUG|INFO|WARNING|ERROR> (default: INFO)
  IPORTER_WEB_UI_PORT=<port>                   (default: 8080)
  IPORTER_USER=<linux user>
  IPORTER_GROUP=<linux group>
EOF
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

run_privileged() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
    return
  fi

  if command -v sudo >/dev/null 2>&1; then
    sudo "$@"
    return
  fi

  echo "This action needs root privileges. Re-run as root or install sudo." >&2
  exit 1
}

deploy_project_files() {
  require_cmd tar

  mkdir -p "${PROJECT_DIR}"

  tar -C "${SOURCE_DIR}" \
    --exclude='.git' \
    --exclude='.log' \
    --exclude='.venv' \
    --exclude='.pytest_cache' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    -cf - . | tar -C "${PROJECT_DIR}" -xf -

  echo "Project synced to ${PROJECT_DIR}"
}

set_web_ui_port() {
  if [[ ! "${WEB_UI_PORT}" =~ ^[0-9]+$ ]] || [[ "${WEB_UI_PORT}" -lt 1 ]] || [[ "${WEB_UI_PORT}" -gt 65535 ]]; then
    echo "Invalid IPORTER_WEB_UI_PORT: ${WEB_UI_PORT}" >&2
    exit 1
  fi

  if [[ ! -f "${CONFIG_PATH}" ]]; then
    echo "Config file not found: ${CONFIG_PATH}" >&2
    exit 1
  fi

  awk -v port="${WEB_UI_PORT}" '
    BEGIN { in_web_gui=0; saw_web_gui=0; updated=0 }
    /^web_gui:[[:space:]]*$/ {
      print
      in_web_gui=1
      saw_web_gui=1
      next
    }
    {
      if (in_web_gui && $0 ~ /^[^[:space:]]/) {
        if (!updated) {
          print "  port: " port
          updated=1
        }
        in_web_gui=0
      }

      if (in_web_gui && $0 ~ /^[[:space:]]+port:[[:space:]]*/) {
        print "  port: " port
        updated=1
        next
      }

      print
    }
    END {
      if (in_web_gui && !updated) {
        print "  port: " port
        updated=1
      }
      if (!saw_web_gui) {
        print ""
        print "web_gui:"
        print "  host: 0.0.0.0"
        print "  port: " port
      }
    }
  ' "${CONFIG_PATH}" > "${CONFIG_PATH}.tmp"

  mv "${CONFIG_PATH}.tmp" "${CONFIG_PATH}"
  echo "Configured web GUI port to ${WEB_UI_PORT} in ${CONFIG_PATH}"
}

maybe_link_settings_to_etc() {
  local answer

  while true; do
    read -r -p "Do you want to symlink settings to ${ETC_IPORTER_DIR}? [y/N] " answer
    case "${answer}" in
      [Yy]|[Yy][Ee][Ss])
        run_privileged mkdir -p "${ETC_IPORTER_DIR}"

        if [[ -L "${ETC_SETTINGS_LINK}" || -e "${ETC_SETTINGS_LINK}" ]]; then
          run_privileged rm -rf "${ETC_SETTINGS_LINK}"
        fi

        run_privileged ln -s "${SETTINGS_DIR}" "${ETC_SETTINGS_LINK}"
        echo "Created symlink: ${ETC_SETTINGS_LINK} -> ${SETTINGS_DIR}"
        return
        ;;
      ""|[Nn]|[Nn][Oo])
        echo "Skipping /etc/iporter settings symlink."
        return
        ;;
      *)
        echo "Please answer yes or no."
        ;;
    esac
  done
}

ensure_secure_json() {
  local password="$1"

  if [[ -f "${SECURE_JSON_PATH}" ]]; then
    return
  fi

  local session_secret
  session_secret="$(head -c 32 /dev/urandom | base64 | tr -d '\n+/=' | head -c 40)"

  mkdir -p "$(dirname "${SECURE_JSON_PATH}")"
  cat >"${SECURE_JSON_PATH}" <<EOF
{
  "password": "${password}",
  "session_secret": "${session_secret}"
}
EOF
  echo "Created secure file: ${SECURE_JSON_PATH}"
}

install_python_env() {
  require_cmd "${PYTHON_BIN}"

  if [[ ! -d "${VENV_DIR}" ]]; then
    echo "Creating virtual environment at ${VENV_DIR}"
    "${PYTHON_BIN}" -m venv "${VENV_DIR}"
  fi

  # shellcheck disable=SC1091
  . "${VENV_DIR}/bin/activate"

  python -m pip install --upgrade pip
  pip install -e "${PROJECT_DIR}[dev]"
}

run_service_install() {
  if [[ ! -x "${SERVICE_SCRIPT}" ]]; then
    chmod +x "${SERVICE_SCRIPT}"
  fi

  export IPORTER_CONFIG="${CONFIG_PATH}"
  export IPORTER_LOG_LEVEL="${LOG_LEVEL}"

  echo "Starting service install."
  echo "You will be asked about DNS port 53 during installation."
  "${SERVICE_SCRIPT}" install
}

# Main program

main() {
  if [[ $# -gt 0 ]]; then
    # Usage
    usage
    exit 1
  fi

  echo "${PROGRAM_NAME} v${PROGRAM_VERSION} installer"
  echo "==============================="
  echo ""

  # Compute derived paths now that INSTALL_DIR is finalised
  PROJECT_DIR="${INSTALL_DIR}"
  SERVICE_SCRIPT="${PROJECT_DIR}/scripts/iporter-service.sh"
  CONFIG_PATH="${IPORTER_CONFIG:-${PROJECT_DIR}/config/config.yaml}"
  VENV_DIR="${PROJECT_DIR}/.venv"
  SECURE_JSON_PATH="${PROJECT_DIR}/config/secure.json"
  SETTINGS_DIR="${PROJECT_DIR}/config"
  ETC_SETTINGS_LINK="${ETC_IPORTER_DIR}/settings"


  # Step 0: Check already installed
  if [[ -d "${INSTALL_DIR}" ]]; then
    echo "Warning: ${INSTALL_DIR} already exists."
    read -r -p "Do you want to continue and overwrite? [y/N] " _overwrite
    case "${_overwrite}" in
      [yY][eE][sS]|[yY]) ;;
      *)
        echo "Installation cancelled."
        exit 0
        ;;
    esac
    echo ""
  fi

  # if overwrite and service is running, stop it
  if [[ -f "${SERVICE_SCRIPT}" ]]; then
    echo "Stopping existing service before installation..."
    "${SERVICE_SCRIPT}" stop || true
  fi

  # if overwrite and virtualenv exists, remove it
  if [[ -d "${VENV_DIR}" ]]; then
    echo "Removing existing virtual environment at ${VENV_DIR}..."
    rm -rf "${VENV_DIR}"
  fi

  # if overwrite and config exists, back it up
  if [[ -f "${CONFIG_PATH}" ]]; then
    echo "Backing up existing config at ${CONFIG_PATH} to ${CONFIG_PATH}.bak"
    cp "${CONFIG_PATH}" "${CONFIG_PATH}.bak"
  fi

  # if overwrite and secure.json exists, back it up
  if [[ -f "${SECURE_JSON_PATH}" ]]; then
    echo "Backing up existing secure.json at ${SECURE_JSON_PATH} to ${SECURE_JSON_PATH}.bak"
    cp "${SECURE_JSON_PATH}" "${SECURE_JSON_PATH}.bak"
  fi

  # if overwrite not need confirmation go ahead step 2
      
  # Step 1: Confirm installation if not overwrite
  if [[ ! -d "${INSTALL_DIR}" ]]; then
    read -r -p "Do you want to install ${PROGRAM_NAME}? [y/N] " _confirm
    case "${_confirm}" in
      [yY][eE][sS]|[yY]) ;;
      *)
        echo "Installation cancelled."
        exit 0
        ;;
    esac
    echo ""
  fi

  # Step 2: Installation directory
  read -r -p "Installation directory [${INSTALL_DIR}]: " _install_input
  INSTALL_DIR="${_install_input:-${INSTALL_DIR}}"
  echo ""

  # Step 3: Web UI port
  read -r -p "Web UI port [${WEB_UI_PORT}]: " _port_input
  WEB_UI_PORT="${_port_input:-${WEB_UI_PORT}}"
  echo ""
  set_web_ui_port "${WEB_UI_PORT}"

  # Step 4: Check for systemctl command
  require_cmd systemctl

  # Step 5: Check for required commands
  deploy_project_files

  # Step 6: Install Python environment
  install_python_env

  if [[ ! -f "${CONFIG_PATH}" ]]; then
    echo "Config file not found: ${CONFIG_PATH}" >&2
    exit 1
  fi

  # Step 7: Web UI password
  local _default_pass="P4ssw0rd!"
  local _web_password
  echo "Default Web UI password: ${_default_pass}"
  read -r -p "Set a custom password? [y/N] " _pass_choice
  case "${_pass_choice}" in
    [yY][eE][sS]|[yY])
      while true; do
        read -r -s -p "Enter new password: " _web_password
        echo ""
        read -r -s -p "Confirm password: " _web_password2
        echo ""
        if [[ "${_web_password}" == "${_web_password2}" && -n "${_web_password}" ]]; then
          break
        fi
        echo "Passwords do not match or are empty. Please try again."
      done
      ;;
    *)
      _web_password="${_default_pass}"
      echo "Using default password."
      ;;
  esac
  echo ""

  ensure_secure_json "${_web_password}"

  # Step 8: Get local_lan_name, support_user_email, support_user_name
  local _local_lan_name
  read -r -p "Enter local LAN name (default: 'local'): " _local_lan_name
  _local_lan_name="${_local_lan_name:-local}"
  local _support_user_email
  read -r -p "Enter support user email: " _support_user_email
  _support_user_email="${_support_user_email:-support@example.com}"

  local _support_user_name
  read -r -p "Enter support user name: " _support_user_name
  _support_user_name="${_support_user_name:-Support User}"

  # Update config.yaml with the provided values
  sed -i "s/^local_lan_name:.*/local_lan_name: ${_local_lan_name}/" "${CONFIG_PATH}"
  sed -i "s/^support_user_email:.*/support_user_email: ${_support_user_email}/" "${CONFIG_PATH}"
  sed -i "s/^support_user_name:.*/support_user_name: ${_support_user_name}/" "${CONFIG_PATH}"

  # Step 9: Log file location
  local _log_file
  read -r -p "Enter log file location (default: ${PROJECT_DIR}/logs): " _log_file
  _log_file="${_log_file:-${PROJECT_DIR}/logs}"
  sed -i "s|^log_file:.*|log_file: ${_log_file}|" "${CONFIG_PATH}"
  
  # Step 10: Symlink settings to /etc/iporter/settings
  maybe_link_settings_to_etc

  # Step 11: Install systemd service
  run_service_install

  # Final message
  echo "IPorter full installation completed."
  echo "Installed at: ${PROJECT_DIR}"
  echo "Use ${PROJECT_DIR}/scripts/iporter-service.sh status to check services."
}

main "$@"
