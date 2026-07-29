# IPorter - Test cases for CLI logging setup.
# Creator: Simon Nandor <simonszoft@gmail.com>
# GitHUB: https://github.com/simonszoft/IPorter

from pathlib import Path

import pytest

from iporter.cli import _setup_verbose_action_logging
from iporter.cli import _validate_startup_paths


def test_setup_verbose_action_logging_writes_to_relative_path(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("listen_port: 5353\n", encoding="utf-8")

    _setup_verbose_action_logging(
        str(cfg_path),
        verbose_logging=True,
        log_file_path="iporter.log",
        max_bytes=1024,
        backup_count=2,
    )

    action_log_path = tmp_path / "iporter.log"

    import logging

    logging.getLogger("iporter.action").info("action=block ip=10.0.0.2 domain=facebook.com")

    assert action_log_path.exists()
    text = action_log_path.read_text(encoding="utf-8")
    assert "action=block" in text


def test_setup_verbose_action_logging_no_file_when_disabled(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("listen_port: 5353\n", encoding="utf-8")

    _setup_verbose_action_logging(
        str(cfg_path),
        verbose_logging=False,
        log_file_path="iporter.log",
        max_bytes=1024,
        backup_count=2,
    )

    assert not (tmp_path / "iporter.log").exists()


def test_validate_startup_paths_success(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
listen_host: "0.0.0.0"
listen_port: 5353
policy_db_path: policy.db
log_file_path: iporter.log
upstream_dns_servers:
  - host: "1.1.1.1"
    port: 53
  - host: "8.8.8.8"
    port: 53
ip_groups: {}
rules: []
""",
        encoding="utf-8",
    )

    _validate_startup_paths(str(cfg_path), log_file_path="iporter.log")


def test_validate_startup_paths_fails_for_non_writable_log_target(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
listen_host: "0.0.0.0"
listen_port: 5353
policy_db_path: policy.db
log_file_path: iporter.log
upstream_dns_servers:
  - host: "1.1.1.1"
    port: 53
  - host: "8.8.8.8"
    port: 53
ip_groups: {}
rules: []
""",
        encoding="utf-8",
    )

    blocked = tmp_path / "blocked"
    blocked.mkdir()

    with pytest.raises(ValueError, match="Log file path is not writable"):
        _validate_startup_paths(str(cfg_path), log_file_path="blocked")
