# IPorter Web UI - A web-based GUI for editing IPorter YAML configuration and managing the policy database.
# Creator: Simon Nandor <simonszoft@gmail.com>
# GitHUB: https://github.com/simonszoft/IPorter

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hmac
import json
import os
import platform
import socket
from pathlib import Path
from typing import Any

import yaml
from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)

from . import PROGRAM_NAME, VERSION
from .config import load_config, parse_config_data
from .policy_db import (
    add_group_network,
    add_rule,
    apply_db_policy,
    bootstrap_policy_db,
    delete_group_network,
    delete_rule,
    list_group_networks,
    list_rules,
    resolve_policy_db_path,
    update_group_network,
    update_rule,
)

DEFAULT_GUI_PASSWORD = "P4ssw0rd!"
DEFAULT_SESSION_SECRET = "iporter-webui-session-secret"
CREATOR_NAME = "Simon Nandor (Simonszoft)"
GITHUB_URL = "https://github.com/simonszoft/IPorter"
DEFAULT_LOCAL_LAN_NAME = "LOCAL"
DEFAULT_SUPPORT_USER_NAME = "Support"
DEFAULT_SUPPORT_USER_EMAIL = "support@localhost"
ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"
RUNTIME_STATUS_FILENAME = "iporter-daemon-status.json"


def _validate_config_text(config_text: str) -> None:
    parsed = yaml.safe_load(config_text)
    if not isinstance(parsed, dict):
        raise ValueError("Top-level config must be a mapping")
    parse_config_data(parsed)


def _load_web_gui_bind(config_path: str) -> tuple[str, int]:
    default_host = "0.0.0.0"
    default_port = 8080

    path = Path(config_path)
    if not path.exists():
        return default_host, default_port

    parsed: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        return default_host, default_port

    web_gui = parsed.get("web_gui", {})
    if not isinstance(web_gui, dict):
        return default_host, default_port

    host = web_gui.get("host", default_host)
    port = web_gui.get("port", default_port)

    try:
        parsed_port = int(port)
    except (TypeError, ValueError):
        parsed_port = default_port

    return str(host), parsed_port


def _load_gui_security(config_path: str) -> tuple[str, str]:
    secure_path = Path(config_path).resolve().parent / "secure.json"
    if not secure_path.exists():
        return DEFAULT_GUI_PASSWORD, DEFAULT_SESSION_SECRET

    try:
        parsed: Any = json.loads(secure_path.read_text(encoding="utf-8"))
    except Exception:
        return DEFAULT_GUI_PASSWORD, DEFAULT_SESSION_SECRET

    if not isinstance(parsed, dict):
        return DEFAULT_GUI_PASSWORD, DEFAULT_SESSION_SECRET

    password_raw = parsed.get("password", DEFAULT_GUI_PASSWORD)
    secret_raw = parsed.get("session_secret", DEFAULT_SESSION_SECRET)

    password = str(password_raw).strip() or DEFAULT_GUI_PASSWORD
    secret = str(secret_raw).strip() or DEFAULT_SESSION_SECRET
    return password, secret


def _secure_json_path(config_path: str) -> Path:
    return Path(config_path).resolve().parent / "secure.json"


def _save_gui_password(config_path: str, new_password: str, session_secret: str) -> None:
    secure_path = _secure_json_path(config_path)
    secure_path.parent.mkdir(parents=True, exist_ok=True)

    parsed: Any = {}
    if secure_path.exists():
        try:
            loaded: Any = json.loads(secure_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                parsed = loaded
        except Exception:
            parsed = {}

    parsed["password"] = new_password
    current_secret = str(parsed.get("session_secret", "")).strip()
    if not current_secret:
        parsed["session_secret"] = session_secret

    secure_path.write_text(json.dumps(parsed, indent=2) + "\n", encoding="utf-8")


def _load_local_lan_name(config_path: str) -> str:
    path = Path(config_path)
    if not path.exists():
        return DEFAULT_LOCAL_LAN_NAME

    try:
        parsed: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return DEFAULT_LOCAL_LAN_NAME

    if not isinstance(parsed, dict):
        return DEFAULT_LOCAL_LAN_NAME

    local_lan_name = str(parsed.get("local_lan_name", DEFAULT_LOCAL_LAN_NAME)).strip()
    return local_lan_name or DEFAULT_LOCAL_LAN_NAME


def _extract_group_names(group_rows: list[dict[str, Any]]) -> list[str]:
    group_names = {
        str(row.get("group_name", "")).strip()
        for row in group_rows
        if str(row.get("group_name", "")).strip()
    }
    return sorted(group_names)


def _load_support_contact(config_path: str) -> tuple[str, str]:
    path = Path(config_path)
    if not path.exists():
        return DEFAULT_SUPPORT_USER_NAME, DEFAULT_SUPPORT_USER_EMAIL

    try:
        parsed: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return DEFAULT_SUPPORT_USER_NAME, DEFAULT_SUPPORT_USER_EMAIL

    if not isinstance(parsed, dict):
        return DEFAULT_SUPPORT_USER_NAME, DEFAULT_SUPPORT_USER_EMAIL

    support_name = str(parsed.get("support_user_name", DEFAULT_SUPPORT_USER_NAME)).strip()
    support_email = str(parsed.get("support_user_email", DEFAULT_SUPPORT_USER_EMAIL)).strip()

    if not support_name:
        support_name = DEFAULT_SUPPORT_USER_NAME
    if not support_email:
        support_email = DEFAULT_SUPPORT_USER_EMAIL

    return support_name, support_email


def _resolve_log_file_path(config_path: str) -> Path:
    path = Path(config_path).resolve()
    if not path.exists():
        return (path.parent / "iporter.log").resolve()

    try:
        parsed: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return (path.parent / "iporter.log").resolve()

    if not isinstance(parsed, dict):
        return (path.parent / "iporter.log").resolve()

    log_file_raw = parsed.get("log_file_path", "iporter.log")
    if not isinstance(log_file_raw, str) or not log_file_raw.strip():
        log_file_raw = "iporter.log"

    log_path = Path(log_file_raw.strip())
    if not log_path.is_absolute():
        log_path = (path.parent / log_path).resolve()
    return log_path


def _log_candidates(log_path: Path) -> list[Path]:
    candidates = [log_path]
    candidates.extend(
        sorted(
            log_path.parent.glob(f"{log_path.name}.*"),
            key=lambda p: p.name,
        )
    )
    return candidates


def _latest_existing_log_file(config_path: str) -> Path | None:
    log_path = _resolve_log_file_path(config_path)
    existing = [p for p in _log_candidates(log_path) if p.is_file() and p.stat().st_size > 0]
    if not existing:
        return None
    return max(existing, key=lambda p: p.stat().st_mtime)


def _detect_server_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            return str(ip)
    except Exception:
        return "127.0.0.1"


def _format_size(size_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(max(size_bytes, 0))
    idx = 0
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024
        idx += 1
    if idx == 0:
        return f"{int(value)} {units[idx]}"
    return f"{value:.2f} {units[idx]}"


def _format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec}s"
    hours, minute = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minute}m"
    days, hour = divmod(hours, 24)
    return f"{days}d {hour}h"


def _daemon_runtime_status(config_path: str) -> dict[str, str]:
    status_path = Path(config_path).resolve().parent / RUNTIME_STATUS_FILENAME
    if not status_path.exists():
        return {
            "daemon_status": "Stopped",
            "daemon_started_at": "N/A",
            "daemon_run_time": "N/A",
        }

    try:
        raw: Any = json.loads(status_path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "daemon_status": "Unknown",
            "daemon_started_at": "Invalid status file",
            "daemon_run_time": "N/A",
        }

    if not isinstance(raw, dict):
        return {
            "daemon_status": "Unknown",
            "daemon_started_at": "Invalid status file",
            "daemon_run_time": "N/A",
        }

    pid_raw = raw.get("pid")
    started_raw = raw.get("started_at_utc", "")

    try:
        pid = int(pid_raw)
        os.kill(pid, 0)
        is_running = True
    except Exception:
        is_running = False

    try:
        started_dt = datetime.fromisoformat(str(started_raw).strip())
        if started_dt.tzinfo is None:
            started_dt = started_dt.replace(tzinfo=timezone.utc)
        started_at = started_dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        elapsed = int((datetime.now(timezone.utc) - started_dt.astimezone(timezone.utc)).total_seconds())
        run_time = _format_duration(max(elapsed, 0)) if is_running else "N/A"
    except Exception:
        started_at = "Unknown"
        run_time = "N/A"

    return {
        "daemon_status": "Running" if is_running else "Stopped",
        "daemon_started_at": started_at,
        "daemon_run_time": run_time,
    }


def _policy_last_modified(db_path: Path) -> str:
    if not db_path.exists() or not db_path.is_file():
        return "N/A"
    try:
        ts = db_path.stat().st_mtime
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return "Unknown"


def _file_last_modified(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return "N/A"
    try:
        ts = path.stat().st_mtime
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return "Unknown"


def _collect_status_snapshot(config_path: str, db_path: Path) -> dict[str, Any]:
    groups = list_group_networks(db_path)
    rules = list_rules(db_path)
    log_path = _resolve_log_file_path(config_path)
    log_size = log_path.stat().st_size if log_path.exists() and log_path.is_file() else 0
    daemon = _daemon_runtime_status(config_path)

    return {
        "server_ip": _detect_server_ip(),
        "os_name": platform.platform(),
        "group_count": len(groups),
        "rule_count": len(rules),
        "log_path": str(log_path),
        "log_size": _format_size(log_size),
        "daemon_status": daemon["daemon_status"],
        "daemon_started_at": daemon["daemon_started_at"],
        "daemon_run_time": daemon["daemon_run_time"],
        "policy_last_modified": _file_last_modified(db_path),
        "config_last_modified": _file_last_modified(Path(config_path)),
    }


def create_app(config_path: str) -> Flask:
    app = Flask(__name__)
    cfg_path = Path(config_path).resolve()
    app.config["IPORTER_CONFIG_PATH"] = str(cfg_path)
    app.config["IPORTER_LOCAL_LAN_NAME"] = _load_local_lan_name(config_path)
    support_name, support_email = _load_support_contact(config_path)
    app.config["IPORTER_SUPPORT_USER_NAME"] = support_name
    app.config["IPORTER_SUPPORT_USER_EMAIL"] = support_email

    gui_password, session_secret = _load_gui_security(config_path)
    app.config["IPORTER_GUI_PASSWORD"] = gui_password
    app.secret_key = session_secret

    @app.context_processor
    def inject_template_meta() -> dict[str, str]:
        latest_log = _latest_existing_log_file(str(app.config["IPORTER_CONFIG_PATH"]))
        return {
            "program_name": PROGRAM_NAME,
            "version": VERSION,
            "creator_name": CREATOR_NAME,
            "github_url": GITHUB_URL,
            "local_lan_name": str(
                app.config.get("IPORTER_LOCAL_LAN_NAME", DEFAULT_LOCAL_LAN_NAME)
            ),
            "support_user_name": str(
                app.config.get("IPORTER_SUPPORT_USER_NAME", DEFAULT_SUPPORT_USER_NAME)
            ),
            "support_user_email": str(
                app.config.get("IPORTER_SUPPORT_USER_EMAIL", DEFAULT_SUPPORT_USER_EMAIL)
            ),
            "logs_available": latest_log is not None,
        }

    @app.get("/assets/<path:filename>")
    def asset_file(filename: str):
        return send_from_directory(str(ASSETS_DIR), filename)

    db_path = resolve_policy_db_path(cfg_path)
    try:
        seed_config = load_config(cfg_path)
        apply_db_policy(seed_config, cfg_path)
    except Exception:
        bootstrap_policy_db(db_path, {}, [])
    app.config["IPORTER_POLICY_DB_PATH"] = str(db_path)

    def _is_authenticated() -> bool:
        return bool(session.get("authenticated"))

    def _require_auth():
        if _is_authenticated():
            return None
        return redirect(url_for("login_page"))

    def _policy_db() -> Path:
        return Path(str(app.config["IPORTER_POLICY_DB_PATH"]))

    @app.get("/login")
    def login_page():
        if _is_authenticated():
            return redirect(url_for("status_page"))
        return render_template("login.html", error="")

    @app.post("/login")
    def login():
        input_password = request.form.get("password", "")
        expected_password = str(app.config["IPORTER_GUI_PASSWORD"])
        if hmac.compare_digest(input_password, expected_password):
            session["authenticated"] = True
            return redirect(url_for("status_page"))
        return render_template("login.html", error="Invalid password.")

    @app.get("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login_page"))

    @app.get("/change-password")
    def change_password_page():
        auth_redirect = _require_auth()
        if auth_redirect is not None:
            return auth_redirect

        return render_template(
            "change_password.html",
            message="",
            message_kind="ok",
        )

    @app.get("/logs")
    def logs_page():
        auth_redirect = _require_auth()
        if auth_redirect is not None:
            return auth_redirect

        query = request.args.get("q", "").strip()

        latest = _latest_existing_log_file(str(app.config["IPORTER_CONFIG_PATH"]))
        if latest is None:
            return render_template(
                "logs.html",
                log_path="",
                log_text="",
                query=query,
                filtered_count=0,
                message="No logs found yet.",
                message_kind="warning",
            )

        try:
            full_text = latest.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return render_template(
                "logs.html",
                log_path=str(latest),
                log_text="",
                query=query,
                filtered_count=0,
                message=f"Failed to read log file: {exc}",
                message_kind="error",
            )

        if query:
            filtered_lines = [
                line for line in full_text.splitlines() if query.lower() in line.lower()
            ]
            text = "\n".join(filtered_lines)
            filtered_count = len(filtered_lines)
        else:
            text = full_text
            filtered_count = len(full_text.splitlines())

        return render_template(
            "logs.html",
            log_path=str(latest),
            log_text=text,
            query=query,
            filtered_count=filtered_count,
            message="",
            message_kind="ok",
        )

    @app.get("/download")
    def download_page():
        auth_redirect = _require_auth()
        if auth_redirect is not None:
            return auth_redirect

        cfg = Path(str(app.config["IPORTER_CONFIG_PATH"]))
        db = _policy_db()
        latest_log = _latest_existing_log_file(str(app.config["IPORTER_CONFIG_PATH"]))
        return render_template(
            "download.html",
            config_path=str(cfg),
            config_exists=cfg.exists(),
            db_path=str(db),
            db_exists=db.exists(),
            log_path=str(latest_log) if latest_log is not None else "",
            log_exists=latest_log is not None,
            message=request.args.get("message", ""),
            message_kind=request.args.get("kind", "ok"),
        )

    @app.get("/download/config")
    def download_config_file():
        auth_redirect = _require_auth()
        if auth_redirect is not None:
            return auth_redirect

        cfg = Path(str(app.config["IPORTER_CONFIG_PATH"]))
        if not cfg.exists():
            return redirect(url_for("download_page", kind="warning", message="Config file not found."))
        return send_file(cfg, as_attachment=True, download_name=cfg.name)

    @app.get("/download/policy-db")
    def download_policy_db_file():
        auth_redirect = _require_auth()
        if auth_redirect is not None:
            return auth_redirect

        db = _policy_db()
        if not db.exists():
            return redirect(url_for("download_page", kind="warning", message="Policy DB file not found."))
        return send_file(db, as_attachment=True, download_name=db.name)

    @app.get("/download/log")
    def download_log_file():
        auth_redirect = _require_auth()
        if auth_redirect is not None:
            return auth_redirect

        latest = _latest_existing_log_file(str(app.config["IPORTER_CONFIG_PATH"]))
        if latest is None:
            return redirect(url_for("download_page", kind="warning", message="No log file found."))
        return send_file(latest, as_attachment=True, download_name=latest.name)

    @app.post("/change-password")
    def change_password():
        auth_redirect = _require_auth()
        if auth_redirect is not None:
            return auth_redirect

        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        expected_password = str(app.config["IPORTER_GUI_PASSWORD"])

        if not hmac.compare_digest(current_password, expected_password):
            return render_template(
                "change_password.html",
                message="Current password is incorrect.",
                message_kind="error",
            )
        if len(new_password.strip()) < 6:
            return render_template(
                "change_password.html",
                message="New password must be at least 6 characters.",
                message_kind="error",
            )
        if new_password != confirm_password:
            return render_template(
                "change_password.html",
                message="New password and confirmation do not match.",
                message_kind="error",
            )

        _save_gui_password(str(app.config["IPORTER_CONFIG_PATH"]), new_password, app.secret_key)
        app.config["IPORTER_GUI_PASSWORD"] = new_password
        return render_template(
            "change_password.html",
            message="Password changed successfully.",
            message_kind="ok",
        )

    @app.get("/status")
    def status_page():
        auth_redirect = _require_auth()
        if auth_redirect is not None:
            return auth_redirect

        cfg = str(app.config["IPORTER_CONFIG_PATH"])
        db = _policy_db()
        snapshot = _collect_status_snapshot(cfg, db)

        return render_template(
            "status.html",
            **snapshot,
        )

    @app.get("/status/data")
    def status_data():
        auth_redirect = _require_auth()
        if auth_redirect is not None:
            return auth_redirect

        cfg = str(app.config["IPORTER_CONFIG_PATH"])
        db = _policy_db()
        snapshot = _collect_status_snapshot(cfg, db)
        return jsonify(snapshot)

    @app.get("/")
    def index():
        auth_redirect = _require_auth()
        if auth_redirect is not None:
            return auth_redirect

        path = Path(str(app.config["IPORTER_CONFIG_PATH"]))
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        message = request.args.get("message", "")
        message_kind = request.args.get("kind", "ok")
        return render_template(
            "config.html",
            config_path=str(path),
            config_text=text,
            message=message,
            message_kind=message_kind,
        )

    @app.post("/save")
    def save():
        auth_redirect = _require_auth()
        if auth_redirect is not None:
            return auth_redirect

        path = Path(str(app.config["IPORTER_CONFIG_PATH"]))
        config_text = request.form.get("config_text", "")

        try:
            _validate_config_text(config_text)
            tmp_path = path.with_suffix(path.suffix + ".tmp")
            tmp_path.write_text(config_text, encoding="utf-8")
            tmp_path.replace(path)
            app.config["IPORTER_POLICY_DB_PATH"] = str(resolve_policy_db_path(path))
            app.config["IPORTER_LOCAL_LAN_NAME"] = _load_local_lan_name(str(path))
            support_name, support_email = _load_support_contact(str(path))
            app.config["IPORTER_SUPPORT_USER_NAME"] = support_name
            app.config["IPORTER_SUPPORT_USER_EMAIL"] = support_email
            return redirect(url_for("index", kind="ok", message="Config saved successfully."))
        except Exception as exc:
            return render_template(
                "config.html",
                config_path=str(path),
                config_text=config_text,
                message=f"Validation failed: {exc}",
                message_kind="error",
            )

    @app.get("/policy")
    def policy_page():
        auth_redirect = _require_auth()
        if auth_redirect is not None:
            return auth_redirect

        message = request.args.get("message", "")
        message_kind = request.args.get("kind", "ok")
        db = _policy_db()
        group_rows = list_group_networks(db)
        return render_template(
            "policy.html",
            db_path=str(db),
            group_rows=group_rows,
            group_names=_extract_group_names(group_rows),
            rule_rows=list_rules(db),
            message=message,
            message_kind=message_kind,
        )

    @app.post("/policy/group/add")
    def add_group():
        auth_redirect = _require_auth()
        if auth_redirect is not None:
            return auth_redirect

        try:
            add_group_network(
                _policy_db(),
                request.form.get("group_name", ""),
                request.form.get("cidr", ""),
            )
            return redirect(url_for("policy_page", kind="ok", message="Group network added."))
        except Exception as exc:
            return redirect(url_for("policy_page", kind="error", message=str(exc)))

    @app.post("/policy/group/<int:row_id>/update")
    def update_group(row_id: int):
        auth_redirect = _require_auth()
        if auth_redirect is not None:
            return auth_redirect

        try:
            update_group_network(
                _policy_db(),
                row_id,
                request.form.get("group_name", ""),
                request.form.get("cidr", ""),
            )
            return redirect(url_for("policy_page", kind="ok", message="Group network updated."))
        except Exception as exc:
            return redirect(url_for("policy_page", kind="error", message=str(exc)))

    @app.post("/policy/group/<int:row_id>/delete")
    def delete_group(row_id: int):
        auth_redirect = _require_auth()
        if auth_redirect is not None:
            return auth_redirect

        delete_group_network(_policy_db(), row_id)
        return redirect(url_for("policy_page", kind="ok", message="Group network deleted."))

    @app.post("/policy/rule/add")
    def add_rule_row():
        auth_redirect = _require_auth()
        if auth_redirect is not None:
            return auth_redirect

        group_name = request.form.get("group_name", "").strip()
        group_names = _extract_group_names(list_group_networks(_policy_db()))
        if group_name not in group_names:
            return redirect(
                url_for(
                    "policy_page",
                    kind="warning",
                    message=f"Group '{group_name or '(empty)'}' does not exist. Add it first in Group Networks.",
                )
            )

        try:
            add_rule(
                _policy_db(),
                group_name,
                request.form.get("domain", ""),
                request.form.get("action", ""),
                request.form.get("target", ""),
            )
            return redirect(url_for("policy_page", kind="ok", message="Rule added."))
        except Exception as exc:
            return redirect(url_for("policy_page", kind="error", message=str(exc)))

    @app.post("/policy/rule/<int:row_id>/update")
    def update_rule_row(row_id: int):
        auth_redirect = _require_auth()
        if auth_redirect is not None:
            return auth_redirect

        try:
            update_rule(
                _policy_db(),
                row_id,
                request.form.get("group_name", ""),
                request.form.get("domain", ""),
                request.form.get("action", ""),
                request.form.get("target", ""),
            )
            return redirect(url_for("policy_page", kind="ok", message="Rule updated."))
        except Exception as exc:
            return redirect(url_for("policy_page", kind="error", message=str(exc)))

    @app.post("/policy/rule/<int:row_id>/delete")
    def delete_rule_row(row_id: int):
        auth_redirect = _require_auth()
        if auth_redirect is not None:
            return auth_redirect

        delete_rule(_policy_db(), row_id)
        return redirect(url_for("policy_page", kind="ok", message="Rule deleted."))

    return app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="iporter-config-ui",
        description="Web GUI for editing IPorter YAML config",
    )
    parser.add_argument(
        "--config",
        default="config/config.yaml",
        help="Path to config file",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Host to bind",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to bind",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    app = create_app(args.config)
    config_host, config_port = _load_web_gui_bind(args.config)
    host = args.host if args.host is not None else config_host
    port = args.port if args.port is not None else config_port
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
