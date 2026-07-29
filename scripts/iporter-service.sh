#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="iporter.service"
WEB_UI_SERVICE_NAME="iporter-webui.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}"
WEB_UI_UNIT_PATH="/etc/systemd/system/${WEB_UI_SERVICE_NAME}"

DEFAULT_USER="${SUDO_USER:-${USER}}"
DEFAULT_GROUP="$(id -gn "${DEFAULT_USER}")"
RUN_USER="${IPORTER_USER:-${DEFAULT_USER}}"
RUN_GROUP="${IPORTER_GROUP:-${DEFAULT_GROUP}}"
CONFIG_PATH="${IPORTER_CONFIG:-${PROJECT_DIR}/config/config.yaml}"
LOG_LEVEL="${IPORTER_LOG_LEVEL:-INFO}"
EXEC_BIN="${PROJECT_DIR}/.venv/bin/iporter"
WEB_UI_EXEC_BIN="${PROJECT_DIR}/.venv/bin/iporter-config-ui"
DEFAULT_DNS_PORT="53"
ALT_DNS_PORT="5353"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/iporter-service.sh install
  ./scripts/iporter-service.sh uninstall
  ./scripts/iporter-service.sh start
  ./scripts/iporter-service.sh restart
  ./scripts/iporter-service.sh stop
  ./scripts/iporter-service.sh status

Optional environment overrides:
  IPORTER_USER=<linux_user>
  IPORTER_GROUP=<linux_group>
  IPORTER_CONFIG=<absolute_path_to_config>
  IPORTER_LOG_LEVEL=<DEBUG|INFO|WARNING|ERROR>
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

set_config_port() {
  local port="$1"
  if grep -qE '^[[:space:]]*listen_port:' "${CONFIG_PATH}"; then
    sed -i "s/^[[:space:]]*listen_port:.*/listen_port: ${port}/" "${CONFIG_PATH}"
  else
    printf '\nlisten_port: %s\n' "${port}" >> "${CONFIG_PATH}"
  fi
}

enable_port_53_mode() {
  local ts backup_path
  ts="$(date +%Y%m%d-%H%M%S)"
  backup_path="/etc/systemd/resolved.conf.bak.iporter-${ts}"

  run_privileged cp /etc/systemd/resolved.conf "${backup_path}"
  run_privileged sed -i 's/^[#[:space:]]*DNSStubListener=.*/DNSStubListener=no/' /etc/systemd/resolved.conf
  if ! grep -qE '^[[:space:]]*DNSStubListener=' /etc/systemd/resolved.conf; then
    echo 'DNSStubListener=no' | run_privileged tee -a /etc/systemd/resolved.conf >/dev/null
  fi

  run_privileged systemctl restart systemd-resolved
  run_privileged ln -sf /run/systemd/resolve/resolv.conf /etc/resolv.conf
  set_config_port "${DEFAULT_DNS_PORT}"
  echo "Configured to use DNS port ${DEFAULT_DNS_PORT}."
}

enable_non_53_mode() {
  set_config_port "${ALT_DNS_PORT}"
  echo "Configured to use DNS port ${ALT_DNS_PORT}."
}

ask_dns_port_mode() {
  local answer
  while true; do
    read -r -p 'Do you want to use the default DNS port (53)? [y/N] ' answer
    case "${answer}" in
      [Yy]|[Yy][Ee][Ss])
        enable_port_53_mode
        return
        ;;
      ""|[Nn]|[Nn][Oo])
        enable_non_53_mode
        return
        ;;
      *)
        echo "Please answer yes or no."
        ;;
    esac
  done
}

write_unit_file() {
  cat <<EOF | run_privileged tee "${UNIT_PATH}" >/dev/null
[Unit]
Description=IPorter Local DNS Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
Group=${RUN_GROUP}
WorkingDirectory=${PROJECT_DIR}
ExecStart=${EXEC_BIN} --config ${CONFIG_PATH} --log-level ${LOG_LEVEL}
Restart=on-failure
RestartSec=2
AmbientCapabilities=CAP_NET_BIND_SERVICE
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
}

write_web_ui_unit_file() {
  cat <<EOF | run_privileged tee "${WEB_UI_UNIT_PATH}" >/dev/null
[Unit]
Description=IPorter Config GUI Web Service
After=network-online.target ${SERVICE_NAME}
Wants=network-online.target
PartOf=${SERVICE_NAME}

[Service]
Type=simple
User=${RUN_USER}
Group=${RUN_GROUP}
WorkingDirectory=${PROJECT_DIR}
ExecStart=${WEB_UI_EXEC_BIN} --config ${CONFIG_PATH}
Restart=on-failure
RestartSec=2
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
}

install_service() {
  require_cmd systemctl

  if [[ ! -x "${EXEC_BIN}" ]]; then
    echo "Executable not found: ${EXEC_BIN}" >&2
    echo "Create venv and install first:" >&2
    echo "  python3 -m venv .venv && . .venv/bin/activate && pip install -e .[dev]" >&2
    exit 1
  fi

  if [[ ! -f "${CONFIG_PATH}" ]]; then
    echo "Config file not found: ${CONFIG_PATH}" >&2
    exit 1
  fi

  if [[ ! -x "${WEB_UI_EXEC_BIN}" ]]; then
    echo "Executable not found: ${WEB_UI_EXEC_BIN}" >&2
    echo "Install package first: pip install -e .[dev]" >&2
    exit 1
  fi

  ask_dns_port_mode

  write_unit_file
  write_web_ui_unit_file
  run_privileged systemctl daemon-reload
  run_privileged systemctl enable --now "${SERVICE_NAME}"
  run_privileged systemctl enable --now "${WEB_UI_SERVICE_NAME}"
  run_privileged systemctl status "${SERVICE_NAME}" --no-pager
  run_privileged systemctl status "${WEB_UI_SERVICE_NAME}" --no-pager
}

uninstall_service() {
  require_cmd systemctl

  run_privileged systemctl disable --now "${SERVICE_NAME}" || true
  run_privileged systemctl disable --now "${WEB_UI_SERVICE_NAME}" || true

  if [[ -f "${UNIT_PATH}" ]]; then
    run_privileged rm -f "${UNIT_PATH}"
  fi
  if [[ -f "${WEB_UI_UNIT_PATH}" ]]; then
    run_privileged rm -f "${WEB_UI_UNIT_PATH}"
  fi

  run_privileged systemctl daemon-reload
  run_privileged systemctl reset-failed "${SERVICE_NAME}" || true
  run_privileged systemctl reset-failed "${WEB_UI_SERVICE_NAME}" || true
  echo "Uninstalled ${SERVICE_NAME}."
}

start_service() {
  require_cmd systemctl
  run_privileged systemctl start "${SERVICE_NAME}"
  run_privileged systemctl start "${WEB_UI_SERVICE_NAME}"
  run_privileged systemctl status "${SERVICE_NAME}" --no-pager
  run_privileged systemctl status "${WEB_UI_SERVICE_NAME}" --no-pager
}

restart_service() {
  require_cmd systemctl
  run_privileged systemctl restart "${SERVICE_NAME}"
  run_privileged systemctl restart "${WEB_UI_SERVICE_NAME}"
  run_privileged systemctl status "${SERVICE_NAME}" --no-pager
  run_privileged systemctl status "${WEB_UI_SERVICE_NAME}" --no-pager
}

stop_service() {
  require_cmd systemctl
  run_privileged systemctl stop "${WEB_UI_SERVICE_NAME}" || true
  run_privileged systemctl stop "${SERVICE_NAME}"
  run_privileged systemctl status "${SERVICE_NAME}" --no-pager || true
  run_privileged systemctl status "${WEB_UI_SERVICE_NAME}" --no-pager || true
}

status_service() {
  require_cmd systemctl
  run_privileged systemctl status "${SERVICE_NAME}" --no-pager
  run_privileged systemctl status "${WEB_UI_SERVICE_NAME}" --no-pager
}

main() {
  if [[ $# -ne 1 ]]; then
    usage
    exit 1
  fi

  case "$1" in
    install)
      install_service
      ;;
    uninstall)
      uninstall_service
      ;;
    start)
      start_service
      ;;
    restart)
      restart_service
      ;;
    stop)
      stop_service
      ;;
    status)
      status_service
      ;;
    *)
      usage
      exit 1
      ;;
  esac
}

main "$@"
