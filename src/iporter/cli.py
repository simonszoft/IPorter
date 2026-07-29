# IPorter - A local DNS server with source IP group based rewrite rules.
# Creator: Simon Nandor <simonszoft@gmail.com>
# GitHUB: https://github.com/simonszoft/IPorter

from __future__ import annotations

import argparse
import asyncio
import logging
import sqlite3
from pathlib import Path
from logging.handlers import RotatingFileHandler

from . import VERSION
from .config import load_config
from .policy_db import apply_db_policy, resolve_policy_db_path
from .server import run_server


def _setup_verbose_action_logging(
    config_path: str,
    *,
    verbose_logging: bool,
    log_file_path: str,
    max_bytes: int,
    backup_count: int,
) -> None:
    if not verbose_logging:
        return

    cfg_path = Path(config_path).resolve()
    target_path = Path(log_file_path)
    if not target_path.is_absolute():
        target_path = (cfg_path.parent / target_path).resolve()

    target_path.parent.mkdir(parents=True, exist_ok=True)

    action_logger = logging.getLogger("iporter.action")
    action_logger.setLevel(logging.INFO)
    action_logger.propagate = False

    for existing in action_logger.handlers:
        if isinstance(existing, RotatingFileHandler) and Path(existing.baseFilename) == target_path:
            return

    handler = RotatingFileHandler(
        target_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    action_logger.addHandler(handler)


def _resolve_runtime_path(config_path: str, raw_path: str) -> Path:
    cfg_path = Path(config_path).resolve()
    resolved = Path(raw_path)
    if not resolved.is_absolute():
        resolved = (cfg_path.parent / resolved).resolve()
    return resolved


def _assert_log_path_writable(config_path: str, log_file_path: str) -> None:
    target_path = _resolve_runtime_path(config_path, log_file_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target_path.open("a", encoding="utf-8"):
            pass
    except Exception as exc:
        raise ValueError(f"Log file path is not writable: {target_path}") from exc


def _assert_db_path_writable(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("ROLLBACK")
    except Exception as exc:
        raise ValueError(f"Policy DB path is not writable: {db_path}") from exc


def _validate_startup_paths(config_path: str, *, log_file_path: str) -> None:
    db_path = resolve_policy_db_path(config_path)
    _assert_db_path_writable(db_path)
    _assert_log_path_writable(config_path, log_file_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="iporter",
        description="Local DNS server with source IP group based rewrite rules",
    )
    parser.add_argument(
        "-c",
        "--config",
        default="config/config.yaml",
        help="Path to YAML configuration file",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

    config = load_config(args.config)
    try:
        _validate_startup_paths(args.config, log_file_path=config.log_file_path)
    except ValueError as exc:
        logging.error("Startup check failed: %s", exc)
        raise SystemExit(1) from exc

    config = apply_db_policy(config, args.config)
    _setup_verbose_action_logging(
        args.config,
        verbose_logging=config.verbose_logging,
        log_file_path=config.log_file_path,
        max_bytes=config.logrotate.max_bytes,
        backup_count=config.logrotate.backup_count,
    )
    asyncio.run(run_server(config))


if __name__ == "__main__":
    main()
