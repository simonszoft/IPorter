# IPorter - Test cases for the configuration module of a local DNS server with source IP group based rewrite rules.
# Creator: Simon Nandor <simonszoft@gmail.com>
# GitHUB: https://github.com/simonszoft/IPorter

from pathlib import Path

import pytest

from iporter.config import load_config


def test_load_config_requires_at_least_two_upstream_servers(tmp_path: Path) -> None:
    config_text = """
listen_host: "0.0.0.0"
listen_port: 5353
upstream_dns_servers:
  - host: "1.1.1.1"
    port: 53
ip_groups: {}
rules: []
"""
    path = tmp_path / "config.yaml"
    path.write_text(config_text, encoding="utf-8")

    with pytest.raises(ValueError, match="at least 2"):
        load_config(path)


def test_load_config_with_multiple_upstreams(tmp_path: Path) -> None:
    config_text = """
listen_host: "0.0.0.0"
listen_port: 5353
upstream_dns_servers:
  - host: "1.1.1.1"
    port: 53
  - host: "8.8.8.8"
    port: 53
ip_groups: {}
rules: []
"""
    path = tmp_path / "config.yaml"
    path.write_text(config_text, encoding="utf-8")

    cfg = load_config(path)
    assert len(cfg.upstream_servers) == 2
    assert cfg.upstream_servers[0].host == "1.1.1.1"
    assert cfg.upstream_servers[1].host == "8.8.8.8"


def test_load_config_rejects_invalid_web_gui_port(tmp_path: Path) -> None:
    config_text = """
listen_host: "0.0.0.0"
listen_port: 5353
web_gui:
  host: "0.0.0.0"
  port: 70000
upstream_dns_servers:
  - host: "1.1.1.1"
    port: 53
  - host: "8.8.8.8"
    port: 53
ip_groups: {}
rules: []
"""
    path = tmp_path / "config.yaml"
    path.write_text(config_text, encoding="utf-8")

    with pytest.raises(ValueError, match="web_gui.port"):
        load_config(path)


def test_load_config_accepts_web_gui_settings(tmp_path: Path) -> None:
    config_text = """
listen_host: "0.0.0.0"
listen_port: 5353
web_gui:
  host: "127.0.0.1"
  port: 8088
upstream_dns_servers:
  - host: "1.1.1.1"
    port: 53
  - host: "8.8.8.8"
    port: 53
ip_groups: {}
rules: []
"""
    path = tmp_path / "config.yaml"
    path.write_text(config_text, encoding="utf-8")

    cfg = load_config(path)
    assert cfg.listen_port == 5353


def test_load_config_accepts_verbose_logging_settings(tmp_path: Path) -> None:
    config_text = """
listen_host: "0.0.0.0"
listen_port: 5353
verbose_logging: true
log_file_path: "custom/iporter.log"
upstream_dns_servers:
  - host: "1.1.1.1"
    port: 53
  - host: "8.8.8.8"
    port: 53
ip_groups: {}
rules: []
"""
    path = tmp_path / "config.yaml"
    path.write_text(config_text, encoding="utf-8")

    cfg = load_config(path)
    assert cfg.verbose_logging is True
    assert cfg.log_file_path == "custom/iporter.log"


def test_load_config_rejects_invalid_verbose_logging_type(tmp_path: Path) -> None:
    config_text = """
listen_host: "0.0.0.0"
listen_port: 5353
verbose_logging: "yes"
upstream_dns_servers:
  - host: "1.1.1.1"
    port: 53
  - host: "8.8.8.8"
    port: 53
ip_groups: {}
rules: []
"""
    path = tmp_path / "config.yaml"
    path.write_text(config_text, encoding="utf-8")

    with pytest.raises(ValueError, match="verbose_logging"):
        load_config(path)


def test_load_config_rejects_invalid_log_file_path(tmp_path: Path) -> None:
    config_text = """
listen_host: "0.0.0.0"
listen_port: 5353
verbose_logging: true
log_file_path: ""
upstream_dns_servers:
  - host: "1.1.1.1"
    port: 53
  - host: "8.8.8.8"
    port: 53
ip_groups: {}
rules: []
"""
    path = tmp_path / "config.yaml"
    path.write_text(config_text, encoding="utf-8")

    with pytest.raises(ValueError, match="log_file_path"):
        load_config(path)


def test_load_config_accepts_logrotate_settings(tmp_path: Path) -> None:
    config_text = """
listen_host: "0.0.0.0"
listen_port: 5353
verbose_logging: true
log_file_path: "iporter.log"
logrotate:
  max_bytes: 2048
  backup_count: 9
upstream_dns_servers:
  - host: "1.1.1.1"
    port: 53
  - host: "8.8.8.8"
    port: 53
ip_groups: {}
rules: []
"""
    path = tmp_path / "config.yaml"
    path.write_text(config_text, encoding="utf-8")

    cfg = load_config(path)
    assert cfg.logrotate.max_bytes == 2048
    assert cfg.logrotate.backup_count == 9


def test_load_config_rejects_invalid_logrotate_values(tmp_path: Path) -> None:
    config_text = """
listen_host: "0.0.0.0"
listen_port: 5353
verbose_logging: true
log_file_path: "iporter.log"
logrotate:
  max_bytes: 0
  backup_count: -1
upstream_dns_servers:
  - host: "1.1.1.1"
    port: 53
  - host: "8.8.8.8"
    port: 53
ip_groups: {}
rules: []
"""
    path = tmp_path / "config.yaml"
    path.write_text(config_text, encoding="utf-8")

    with pytest.raises(ValueError, match="logrotate.max_bytes"):
        load_config(path)


def test_load_config_rejects_invalid_policy_db_path(tmp_path: Path) -> None:
    config_text = """
listen_host: "0.0.0.0"
listen_port: 5353
policy_db_path:
  bad: true
upstream_dns_servers:
  - host: "1.1.1.1"
    port: 53
  - host: "8.8.8.8"
    port: 53
ip_groups: {}
rules: []
"""
    path = tmp_path / "config.yaml"
    path.write_text(config_text, encoding="utf-8")

    with pytest.raises(ValueError, match="policy_db_path"):
        load_config(path)
