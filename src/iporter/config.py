# IPorter - Config module for a local DNS server with source IP group based rewrite rules.
# Creator: Simon Nandor <simonszoft@gmail.com>
# GitHUB: https://github.com/simonszoft/IPorter

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class UpstreamServer:
    host: str
    port: int = 53


@dataclass(frozen=True)
class Rule:
    group: str
    domain: str
    action: str
    target: str | None = None


@dataclass(frozen=True)
class LogRotateConfig:
    max_bytes: int = 10 * 1024 * 1024
    backup_count: int = 5


@dataclass(frozen=True)
class ServerConfig:
    listen_host: str
    listen_port: int
    upstream_servers: list[UpstreamServer]
    response_ttl: int
    ip_groups: dict[str, list[str]]
    rules: list[Rule]
    verbose_logging: bool = False
    log_file_path: str = "iporter.log"
    logrotate: LogRotateConfig = LogRotateConfig()


def _require(mapping: dict[str, Any], key: str) -> Any:
    if key not in mapping:
        raise ValueError(f"Missing required config key: {key}")
    return mapping[key]


def parse_config_data(data: dict[str, Any]) -> ServerConfig:
    if not isinstance(data, dict):
        raise ValueError("Top-level config must be a mapping")

    policy_db_path = data.get("policy_db_path")
    if policy_db_path is not None and not isinstance(policy_db_path, str):
        raise ValueError("policy_db_path must be a string")

    verbose_logging = data.get("verbose_logging", False)
    if not isinstance(verbose_logging, bool):
        raise ValueError("verbose_logging must be a boolean")

    log_file_path = data.get("log_file_path", "iporter.log")
    if not isinstance(log_file_path, str) or not log_file_path.strip():
        raise ValueError("log_file_path must be a non-empty string")

    logrotate_raw = data.get("logrotate", {})
    if logrotate_raw is None:
        logrotate_raw = {}
    if not isinstance(logrotate_raw, dict):
        raise ValueError("logrotate must be a mapping")

    max_bytes_raw = logrotate_raw.get("max_bytes", 10 * 1024 * 1024)
    backup_count_raw = logrotate_raw.get("backup_count", 5)
    try:
        max_bytes = int(max_bytes_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("logrotate.max_bytes must be an integer") from exc
    try:
        backup_count = int(backup_count_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("logrotate.backup_count must be an integer") from exc
    if max_bytes < 1:
        raise ValueError("logrotate.max_bytes must be greater than 0")
    if backup_count < 0:
        raise ValueError("logrotate.backup_count must be 0 or greater")

    web_gui = data.get("web_gui")
    if web_gui is not None:
        if not isinstance(web_gui, dict):
            raise ValueError("web_gui must be a mapping")
        if "host" in web_gui and not isinstance(web_gui["host"], str):
            raise ValueError("web_gui.host must be a string")
        if "port" in web_gui:
            try:
                port = int(web_gui["port"])
            except (TypeError, ValueError) as exc:
                raise ValueError("web_gui.port must be an integer") from exc
            if port < 1 or port > 65535:
                raise ValueError("web_gui.port must be between 1 and 65535")

    upstream_servers_raw = _require(data, "upstream_dns_servers")
    if not isinstance(upstream_servers_raw, list):
        raise ValueError("upstream_dns_servers must be a list")
    if len(upstream_servers_raw) < 2:
        raise ValueError("upstream_dns_servers must contain at least 2 servers")

    parsed_upstream_servers: list[UpstreamServer] = []
    for idx, item in enumerate(upstream_servers_raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"upstream_dns_servers[{idx}] must be a mapping")
        parsed_upstream_servers.append(
            UpstreamServer(
                host=str(_require(item, "host")).strip(),
                port=int(item.get("port", 53)),
            )
        )

    rules_raw = data.get("rules", [])
    if not isinstance(rules_raw, list):
        raise ValueError("rules must be a list")

    parsed_rules: list[Rule] = []
    for idx, item in enumerate(rules_raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Rule #{idx} must be a mapping")
        parsed_rules.append(
            Rule(
                group=str(_require(item, "group")).strip(),
                domain=str(_require(item, "domain")).strip().lower(),
                action=str(_require(item, "action")).strip().lower(),
                target=(
                    str(item["target"]).strip().lower()
                    if item.get("target") is not None
                    else None
                ),
            )
        )

    ip_groups = data.get("ip_groups", {})
    if not isinstance(ip_groups, dict):
        raise ValueError("ip_groups must be a mapping")

    normalized_ip_groups: dict[str, list[str]] = {}
    for group, cidrs in ip_groups.items():
        if not isinstance(cidrs, list) or not all(isinstance(x, str) for x in cidrs):
            raise ValueError(f"ip_groups.{group} must be a list of strings")
        normalized_ip_groups[str(group)] = cidrs

    return ServerConfig(
        listen_host=str(data.get("listen_host", "0.0.0.0")),
        listen_port=int(data.get("listen_port", 5353)),
        upstream_servers=parsed_upstream_servers,
        response_ttl=int(data.get("response_ttl", 60)),
        verbose_logging=verbose_logging,
        log_file_path=log_file_path.strip(),
        logrotate=LogRotateConfig(max_bytes=max_bytes, backup_count=backup_count),
        ip_groups=normalized_ip_groups,
        rules=parsed_rules,
    )


def load_config(path: str | Path) -> ServerConfig:
    cfg_path = Path(path)
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Top-level config must be a mapping")
    return parse_config_data(data)
