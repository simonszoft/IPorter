# IPorter - Local DNS Server

IPorter is a local DNS server with source-IP based policy control.

It can:
- allow domains,
- rewrite domains (redirect DNS answers),
- block domains (NXDOMAIN),
- apply policies by client IP groups,
- manage policies in SQLite,
- provide a protected web GUI for config and policy management.

## What it does

- Maps source IP addresses to groups using CIDRs or single IPs.
- Applies ordered DNS rules by group.
- Supports actions:
  - `allow`: forward request unchanged.
  - `rewrite`: query target domain instead.
  - `block`: return `NXDOMAIN`.
- Queries multiple upstream DNS servers in parallel and returns the first successful response.

Example:
- If an IP in group `students` requests `facebook.com`, IPorter can rewrite to `wikipedia.org`.

## Project structure

- `src/iporter/config.py`: config loading and validation
- `src/iporter/rules.py`: group matching and decision logic
- `src/iporter/server.py`: UDP DNS server and upstream forwarding
- `src/iporter/cli.py`: DNS server CLI entrypoint
- `src/iporter/policy_db.py`: SQLite policy storage and migration
- `src/iporter/web_ui.py`: authenticated Web UI (config + Policy DB tab)
- `config/config.yaml`: main configuration
- `config/secure.json`: Web UI password/session secret
- `scripts/iporter-service.sh`: systemd service manager
- `scripts/iporter_install.sh`: full installer

## Requirements

- Python 3.10+
- Linux with systemd (for service installation)

## Quick install (manual)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

## Full install (recommended)

```bash
./scripts/iporter_install.sh
```

What the full installer does:
- Syncs project files to install directory.
- Creates or reuses `.venv` in install directory.
- Installs all Python dependencies automatically.
- Creates `config/secure.json` if missing.
- Sets `web_gui.port` in config (default `8080`, configurable).
- Asks whether to create `/etc/iporter/settings` symlink.
- Runs `./scripts/iporter-service.sh install` in the installed copy.

Installer environment variables:
- `IPORTER_INSTALL_DIR`: target install directory (default: `/opt/IPorter`)
- `IPORTER_WEB_UI_PORT`: Web UI port (default: `8080`)
- `PYTHON_BIN`: Python executable (default: `python3`)
- `IPORTER_CONFIG`: config path (default: `<install-dir>/config/config.yaml`)
- `IPORTER_LOG_LEVEL`: service log level (`DEBUG|INFO|WARNING|ERROR`)
- `IPORTER_USER`: service user override
- `IPORTER_GROUP`: service group override

## Run DNS server

```bash
iporter --config config/config.yaml --log-level INFO
```

CLI parameters:
- `-c, --config`: YAML config path (default: `config/config.yaml`)
- `--log-level`: `DEBUG|INFO|WARNING|ERROR` (default: `INFO`)
- `--version`: print app version

## Run Web UI

```bash
iporter-config-ui --config config/config.yaml
```

Optional parameters:
- `--config`: YAML config path (default: `config/config.yaml`)
- `--host`: bind host override (otherwise uses `web_gui.host`)
- `--port`: bind port override (otherwise uses `web_gui.port`)

Open in browser:
- `http://127.0.0.1:8080` (or your configured `web_gui.port`)

Web UI behavior:
- Requires login (password from `config/secure.json`).
- Config tab validates YAML before save.
- Policy DB tab supports add/edit/delete for groups and rules.

Default `config/secure.json`:

```json
{
  "password": "P4ssw0rd!",
  "session_secret": "change-this-session-secret"
}
```

## systemd service management

Use:

```bash
./scripts/iporter-service.sh install
./scripts/iporter-service.sh start
./scripts/iporter-service.sh restart
./scripts/iporter-service.sh status
./scripts/iporter-service.sh stop
./scripts/iporter-service.sh uninstall
```

Managed units:
- `iporter.service` (DNS)
- `iporter-webui.service` (Web UI)

During `install`, the script asks:
- `Do you want to use the default DNS port (53)?`

If `yes`:
- sets `listen_port` to `53`
- updates `systemd-resolved` stub settings

If `no`:
- sets `listen_port` to `5353`

Service install environment overrides:
- `IPORTER_USER`
- `IPORTER_GROUP`
- `IPORTER_CONFIG`
- `IPORTER_LOG_LEVEL`

## DNS client testing

Query with your configured DNS port (`listen_port`):

```bash
dig @127.0.0.1 -p 5353 facebook.com
dig @127.0.0.1 -p 53 facebook.com
```

## Configuration reference

Main fields in `config/config.yaml`:
- `listen_host`: DNS bind host
- `listen_port`: DNS bind port
- `policy_db_path`: SQLite file path (relative paths resolve under config directory)
- `web_gui.host`: Web UI host
- `web_gui.port`: Web UI port
- `upstream_dns_servers`: list of upstream resolvers (min 2)
- `ip_groups`: optional migration seed only
- `rules`: optional migration seed only

Rule fields:
- `group`
- `domain`
- `action` (`allow|rewrite|block`)
- `target` (required when `action` is `rewrite`)

## Policy DB migration behavior

- Policies are loaded from SQLite at runtime.
- On first bootstrap (DB missing/empty), `ip_groups` and `rules` from YAML are migrated into SQLite.
- After migration, those two YAML sections are cleared.
- Ongoing policy management should be done in the Web UI Policy DB tab.

## Notes

- Rules are evaluated in order; first match wins.
- Current DNS transport is UDP only.
