# IPorter - Test cases for the web UI authentication of a local DNS server with source IP group based rewrite rules.
# Creator: Simon Nandor <simonszoft@gmail.com>
# GitHUB: https://github.com/simonszoft/IPorter

from pathlib import Path

from iporter.web_ui import create_app


VALID_CONFIG = """
listen_host: "0.0.0.0"
listen_port: 5353
web_gui:
  host: "127.0.0.1"
  port: 8080
upstream_dns_servers:
  - host: "1.1.1.1"
    port: 53
  - host: "8.8.8.8"
    port: 53
ip_groups: {}
rules: []
"""


def test_requires_login_for_index(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(VALID_CONFIG, encoding="utf-8")

    secure_path = tmp_path / "secure.json"
    secure_path.write_text('{"password":"P4ssw0rd!"}', encoding="utf-8")

    app = create_app(str(config_path))
    app.testing = True
    client = app.test_client()

    response = client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers.get("Location", "")


def test_login_and_save_flow(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(VALID_CONFIG, encoding="utf-8")

    secure_path = tmp_path / "secure.json"
    secure_path.write_text('{"password":"P4ssw0rd!"}', encoding="utf-8")

    app = create_app(str(config_path))
    app.testing = True
    client = app.test_client()

    bad = client.post("/login", data={"password": "wrong"})
    assert bad.status_code == 200
    assert b"Invalid password" in bad.data

    ok = client.post("/login", data={"password": "P4ssw0rd!"}, follow_redirects=False)
    assert ok.status_code == 302
    assert ok.headers.get("Location", "").endswith("/status")

    edited = VALID_CONFIG.replace("listen_port: 5353", "listen_port: 5354")
    saved = client.post("/save", data={"config_text": edited}, follow_redirects=False)
    assert saved.status_code == 302
    assert "message=Config+saved+successfully" in saved.headers.get("Location", "")

    reloaded = config_path.read_text(encoding="utf-8")
    assert "listen_port: 5354" in reloaded


def test_add_rule_warns_on_missing_group(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(VALID_CONFIG, encoding="utf-8")

    secure_path = tmp_path / "secure.json"
    secure_path.write_text('{"password":"P4ssw0rd!"}', encoding="utf-8")

    app = create_app(str(config_path))
    app.testing = True
    client = app.test_client()

    login = client.post("/login", data={"password": "P4ssw0rd!"}, follow_redirects=False)
    assert login.status_code == 302

    add_rule = client.post(
        "/policy/rule/add",
        data={
            "group_name": "missing-group",
            "domain": "facebook.com",
            "action": "block",
            "target": "",
        },
        follow_redirects=False,
    )
    assert add_rule.status_code == 302

    location = add_rule.headers.get("Location", "")
    assert "kind=warning" in location
    assert "does+not+exist" in location


def test_change_password_requires_login(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(VALID_CONFIG, encoding="utf-8")

    secure_path = tmp_path / "secure.json"
    secure_path.write_text('{"password":"P4ssw0rd!"}', encoding="utf-8")

    app = create_app(str(config_path))
    app.testing = True
    client = app.test_client()

    response = client.get("/change-password", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers.get("Location", "")


def test_change_password_flow(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(VALID_CONFIG, encoding="utf-8")

    secure_path = tmp_path / "secure.json"
    secure_path.write_text('{"password":"P4ssw0rd!","session_secret":"abc"}', encoding="utf-8")

    app = create_app(str(config_path))
    app.testing = True
    client = app.test_client()

    login = client.post("/login", data={"password": "P4ssw0rd!"}, follow_redirects=False)
    assert login.status_code == 302

    wrong = client.post(
        "/change-password",
        data={
            "current_password": "wrong",
            "new_password": "NewPass123",
            "confirm_password": "NewPass123",
        },
    )
    assert wrong.status_code == 200
    assert b"Current password is incorrect" in wrong.data

    changed = client.post(
        "/change-password",
        data={
            "current_password": "P4ssw0rd!",
            "new_password": "NewPass123",
            "confirm_password": "NewPass123",
        },
    )
    assert changed.status_code == 200
    assert b"Password changed successfully" in changed.data

    raw = secure_path.read_text(encoding="utf-8")
    assert "NewPass123" in raw

    client.get("/logout")
    relogin = client.post("/login", data={"password": "NewPass123"}, follow_redirects=False)
    assert relogin.status_code == 302


def test_logs_page_requires_login(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(VALID_CONFIG, encoding="utf-8")

    secure_path = tmp_path / "secure.json"
    secure_path.write_text('{"password":"P4ssw0rd!"}', encoding="utf-8")

    app = create_app(str(config_path))
    app.testing = True
    client = app.test_client()

    response = client.get("/logs", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers.get("Location", "")


def test_logs_page_shows_latest_log_content(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        VALID_CONFIG + "\nverbose_logging: true\nlog_file_path: iporter.log\n",
        encoding="utf-8",
    )

    secure_path = tmp_path / "secure.json"
    secure_path.write_text('{"password":"P4ssw0rd!"}', encoding="utf-8")

    # Create a newer rotated log file so the logs page picks it as latest.
    base_log = tmp_path / "iporter.log"
    rotated_log = tmp_path / "iporter.log.1"
    base_log.write_text("old log\n", encoding="utf-8")
    rotated_log.write_text("latest log line\n", encoding="utf-8")

    app = create_app(str(config_path))
    app.testing = True
    client = app.test_client()

    login = client.post("/login", data={"password": "P4ssw0rd!"}, follow_redirects=False)
    assert login.status_code == 302

    response = client.get("/logs")
    assert response.status_code == 200
    assert b"latest log line" in response.data


def test_logs_page_search_filters_lines(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        VALID_CONFIG + "\nverbose_logging: true\nlog_file_path: iporter.log\n",
        encoding="utf-8",
    )

    secure_path = tmp_path / "secure.json"
    secure_path.write_text('{"password":"P4ssw0rd!"}', encoding="utf-8")

    log_path = tmp_path / "iporter.log"
    log_path.write_text(
        "action=block ip=10.0.0.2 domain=facebook.com\n"
        "action=rewrite ip=10.0.0.3 domain=example.com target=wikipedia.org\n",
        encoding="utf-8",
    )

    app = create_app(str(config_path))
    app.testing = True
    client = app.test_client()

    login = client.post("/login", data={"password": "P4ssw0rd!"}, follow_redirects=False)
    assert login.status_code == 302

    response = client.get("/logs?q=rewrite")
    assert response.status_code == 200
    assert b"action=rewrite" in response.data
    assert b"action=block" not in response.data


def test_download_page_requires_login(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(VALID_CONFIG, encoding="utf-8")

    secure_path = tmp_path / "secure.json"
    secure_path.write_text('{"password":"P4ssw0rd!"}', encoding="utf-8")

    app = create_app(str(config_path))
    app.testing = True
    client = app.test_client()

    response = client.get("/download", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers.get("Location", "")


def test_download_endpoints_return_files(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        VALID_CONFIG + "\nverbose_logging: true\nlog_file_path: iporter.log\n",
        encoding="utf-8",
    )

    secure_path = tmp_path / "secure.json"
    secure_path.write_text('{"password":"P4ssw0rd!"}', encoding="utf-8")

    log_path = tmp_path / "iporter.log"
    log_path.write_text("hello log\n", encoding="utf-8")

    app = create_app(str(config_path))
    app.testing = True
    client = app.test_client()

    login = client.post("/login", data={"password": "P4ssw0rd!"}, follow_redirects=False)
    assert login.status_code == 302

    cfg_download = client.get("/download/config")
    assert cfg_download.status_code == 200
    assert "attachment" in cfg_download.headers.get("Content-Disposition", "")

    db_download = client.get("/download/policy-db")
    assert db_download.status_code == 200
    assert "attachment" in db_download.headers.get("Content-Disposition", "")

    log_download = client.get("/download/log")
    assert log_download.status_code == 200
    assert "attachment" in log_download.headers.get("Content-Disposition", "")


def test_download_log_redirects_when_missing(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(VALID_CONFIG, encoding="utf-8")

    secure_path = tmp_path / "secure.json"
    secure_path.write_text('{"password":"P4ssw0rd!"}', encoding="utf-8")

    app = create_app(str(config_path))
    app.testing = True
    client = app.test_client()

    login = client.post("/login", data={"password": "P4ssw0rd!"}, follow_redirects=False)
    assert login.status_code == 302

    response = client.get("/download/log", follow_redirects=False)
    assert response.status_code == 302
    assert "/download" in response.headers.get("Location", "")


def test_status_page_shows_runtime_summary(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        VALID_CONFIG + "\nverbose_logging: true\nlog_file_path: iporter.log\n",
        encoding="utf-8",
    )

    secure_path = tmp_path / "secure.json"
    secure_path.write_text('{"password":"P4ssw0rd!"}', encoding="utf-8")

    log_path = tmp_path / "iporter.log"
    log_path.write_text("abc", encoding="utf-8")

    app = create_app(str(config_path))
    app.testing = True
    client = app.test_client()

    login = client.post("/login", data={"password": "P4ssw0rd!"}, follow_redirects=False)
    assert login.status_code == 302

    response = client.get("/status")
    assert response.status_code == 200
    assert b"IPorter Status" in response.data
    assert b"Daemon Status" in response.data
    assert b"Daemon Run Time" in response.data
    assert b"Last Modified" in response.data
    assert b"Policy:" in response.data
    assert b"Config:" in response.data
    assert b"Group Count" in response.data
    assert b"Rule Count" in response.data
    assert b"Current Log File Size" in response.data


def test_status_data_endpoint_returns_live_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        VALID_CONFIG + "\nverbose_logging: true\nlog_file_path: iporter.log\n",
        encoding="utf-8",
    )

    secure_path = tmp_path / "secure.json"
    secure_path.write_text('{"password":"P4ssw0rd!"}', encoding="utf-8")

    app = create_app(str(config_path))
    app.testing = True
    client = app.test_client()

    # Requires auth.
    unauthorized = client.get("/status/data", follow_redirects=False)
    assert unauthorized.status_code == 302
    assert "/login" in unauthorized.headers.get("Location", "")

    login = client.post("/login", data={"password": "P4ssw0rd!"}, follow_redirects=False)
    assert login.status_code == 302

    response = client.get("/status/data")
    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload, dict)
    assert "policy_last_modified" in payload
    assert "group_count" in payload
    assert "rule_count" in payload
    assert "log_size" in payload
