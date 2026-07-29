# IPorter - Local DNS Server

IPorter is a local DNS server with source-IP based policy control, SQLite-backed policy storage, and a protected Web UI.

## Features

- DNS policy actions by client IP group:
  - `allow`
  - `rewrite`
  - `block` (NXDOMAIN)
- Parallel upstream DNS queries (first successful reply wins)
- Policy persistence in SQLite
- One-time policy migration from YAML to SQLite
- Web UI with authentication
- Web UI pages:
  - Config
  - Policy DB
  - Logs (with search)
  - Download
  - Change Password
- Verbose action logging for `block` and `rewrite`
- Rotating log files (`max_bytes`, `backup_count`)
- Startup checks for DB and log writability
- systemd service management scripts
- Full installer script

## Project Structure

- `src/iporter/cli.py`: DNS server CLI entrypoint and startup checks
- `src/iporter/server.py`: UDP DNS server and upstream forwarding
- `src/iporter/config.py`: YAML model and validation
- `src/iporter/rules.py`: decision engine
- `src/iporter/policy_db.py`: SQLite schema, CRUD, migration
- `src/iporter/web_ui.py`: Flask Web UI routes and logic
- `src/iporter/templates/`: HTML templates
- `src/iporter/static/iporter.css`: Web UI stylesheet
- `config/config.yaml`: runtime config
- `config/secure.json`: Web UI auth secret/password
- `scripts/iporter-service.sh`: systemd helper script
- `scripts/iporter_install.sh`: full install script

## Requirements

- Python 3.10+
- Linux
- systemd (for service installation)

## Install

### Manual install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

### Full install (recommended)

```bash
./scripts/iporter_install.sh
```

The installer:
- syncs files to target directory (default `/opt/IPorter`)
- creates/reuses `.venv`
- installs dependencies
- creates `config/secure.json` if missing
- sets `web_gui.port`
- optionally creates `/etc/iporter/settings` symlink
- runs service installation

Installer environment variables:
- `PYTHON_BIN` (default `python3`)
- `IPORTER_INSTALL_DIR` (default `/opt/IPorter`)
- `IPORTER_CONFIG` (default `<install-dir>/config/config.yaml`)
- `IPORTER_LOG_LEVEL` (default `INFO`)
- `IPORTER_WEB_UI_PORT` (default `8080`)
- `IPORTER_USER`
- `IPORTER_GROUP`

## Run DNS Server

```bash
iporter --config config/config.yaml --log-level INFO
```

CLI options:
- `-c, --config`: config path
- `--log-level`: `DEBUG|INFO|WARNING|ERROR`
- `--version`

Startup checks:
- checks policy DB path is writable
- checks log file path is writable
- exits with error if either check fails

## Run Web UI

```bash
iporter-config-ui --config config/config.yaml
```

Web UI options:
- `--config`: config path
- `--host`: override web bind host
- `--port`: override web bind port

Default URL:
- `http://127.0.0.1:8080`

## Web UI Functions

### Config page
- edit and save `config.yaml`
- validation before write

### Policy DB page
- add/edit/delete group networks
- add/edit/delete rules
- rule group autocomplete from existing groups
- warning when adding a rule with non-existing group

### Logs page
- shows full latest log file
- search box to filter log lines (case-insensitive)

### Download page
- download current policy DB
- download latest/current log file
- download current config file

### Change Password page
- change Web UI password (stored in `secure.json`)
- checks current password
- confirms new password

## systemd Service Script

```bash
./scripts/iporter-service.sh install
./scripts/iporter-service.sh start
./scripts/iporter-service.sh restart
./scripts/iporter-service.sh status
./scripts/iporter-service.sh stop
./scripts/iporter-service.sh uninstall
```

Managed units:
- `iporter.service`
- `iporter-webui.service`

Install behavior:
- asks whether to use DNS port `53`
- if yes, applies `systemd-resolved` stub changes
- if no, sets DNS port to `5353`

Service-related environment overrides:
- `IPORTER_USER`
- `IPORTER_GROUP`
- `IPORTER_CONFIG`
- `IPORTER_LOG_LEVEL`

## Configuration Reference (`config/config.yaml`)

Required:
- `upstream_dns_servers`: list of at least 2 servers

Core DNS:
- `listen_host`: bind host (default `0.0.0.0`)
- `listen_port`: bind port (default `5353`)
- `response_ttl`: response TTL (default `60`)

Policy/DB:
- `policy_db_path`: SQLite DB path (default `policy.db`)
- `ip_groups`: optional migration seed
- `rules`: optional migration seed

Rule fields:
- `group`
- `domain`
- `action`: `allow|rewrite|block`
- `target`: required for `rewrite`

Web UI identity/settings:
- `local_lan_name`: shown in header
- `support_user_name`: shown in header
- `support_user_email`: shown in header/mail link
- `web_gui.host`
- `web_gui.port`

Logging:
- `verbose_logging`: enable action logs for `block` and `rewrite`
- `log_file_path`: target log file path
- `logrotate.max_bytes`: rotation threshold in bytes
- `logrotate.backup_count`: number of backup files to keep

Example:

```yaml
listen_host: 0.0.0.0
listen_port: 53
response_ttl: 60
policy_db_path: policy.db
local_lan_name: TESTER
support_user_email: support@localhost
support_user_name: Support
web_gui:
  host: 0.0.0.0
  port: 8080
upstream_dns_servers:
  - host: 1.1.1.1
    port: 53
  - host: 8.8.8.8
    port: 53
verbose_logging: true
log_file_path: iporter.log
logrotate:
  max_bytes: 10485760
  backup_count: 5
```

## `secure.json`

Default format:

```json
{
  "password": "P4ssw0rd!",
  "session_secret": "change-this-session-secret"
}
```

## Policy Migration Behavior

- On first startup with empty/missing DB:
  - migrate `ip_groups` and `rules` from YAML into DB
  - clear those sections in YAML
- Afterwards, policy is managed from DB/UI.

## Testing

```bash
.venv/bin/pytest -q
```

## Notes

- DNS transport is UDP.
- Rules are evaluated in order (first match wins).
