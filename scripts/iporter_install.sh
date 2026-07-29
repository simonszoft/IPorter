#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

INSTALL_DIR="${IPORTER_INSTALL_DIR:-/opt/IPorter}"
WEB_UI_PORT="${IPORTER_WEB_UI_PORT:-8080}"
PROJECT_DIR="${INSTALL_DIR}"
SERVICE_SCRIPT="${PROJECT_DIR}/scripts/iporter-service.sh"

PYTHON_BIN="${PYTHON_BIN:-python3}"
CONFIG_PATH="${IPORTER_CONFIG:-${PROJECT_DIR}/config/config.yaml}"
LOG_LEVEL="${IPORTER_LOG_LEVEL:-INFO}"
VENV_DIR="${PROJECT_DIR}/.venv"
SECURE_JSON_PATH="${PROJECT_DIR}/config/secure.json"
SETTINGS_DIR="${PROJECT_DIR}/config"
ETC_IPORTER_DIR="/etc/iporter"
ETC_SETTINGS_LINK="${ETC_IPORTER_DIR}/settings"

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
  if [[ -f "${SECURE_JSON_PATH}" ]]; then
    return
  fi

  mkdir -p "$(dirname "${SECURE_JSON_PATH}")"
  cat >"${SECURE_JSON_PATH}" <<'EOF'
{
  "password": "P4ssw0rd!",
  "session_secret": "change-this-session-secret"
}
EOF
  echo "Created default secure file: ${SECURE_JSON_PATH}"
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

main() {
  if [[ $# -gt 0 ]]; then
    usage
    exit 1
  fi

  require_cmd systemctl
  deploy_project_files
  install_python_env

  if [[ ! -f "${CONFIG_PATH}" ]]; then
    echo "Config file not found: ${CONFIG_PATH}" >&2
    exit 1
  fi

  ensure_secure_json
  set_web_ui_port
  maybe_link_settings_to_etc
  run_service_install

  echo "IPorter full installation completed."
  echo "Installed at: ${PROJECT_DIR}"
  echo "Use ${PROJECT_DIR}/scripts/iporter-service.sh status to check services."
}

main "$@"
