# IPorter - Policy database management for a local DNS server with source IP group based rewrite rules.
# Creator: Simon Nandor <simonszoft@gmail.com>
# GitHUB: https://github.com/simonszoft/IPorter

from __future__ import annotations

import ipaddress
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

from .config import Rule, ServerConfig

_ALLOWED_ACTIONS = {"allow", "rewrite", "block"}


def resolve_policy_db_path(config_path: str | Path) -> Path:
    cfg = Path(config_path).resolve()
    data: Any = yaml.safe_load(cfg.read_text(encoding="utf-8")) if cfg.exists() else {}

    db_raw = "policy.db"
    if isinstance(data, dict):
        db_value = data.get("policy_db_path", "policy.db")
        if isinstance(db_value, str) and db_value.strip():
            db_raw = db_value.strip()

    db_path = Path(db_raw)
    if not db_path.is_absolute():
        db_path = (cfg.parent / db_path).resolve()
    return db_path


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(db_path: Path) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS group_networks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_name TEXT NOT NULL,
                cidr TEXT NOT NULL,
                UNIQUE(group_name, cidr)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_name TEXT NOT NULL,
                domain TEXT NOT NULL,
                action TEXT NOT NULL,
                target TEXT,
                CHECK (action IN ('allow', 'rewrite', 'block'))
            )
            """
        )
        conn.commit()


def _is_empty(conn: sqlite3.Connection, table_name: str) -> bool:
    count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    return int(count) == 0


def _clear_policy_from_config_yaml(config_path: str | Path) -> None:
    cfg_path = Path(config_path).resolve()
    if not cfg_path.exists():
        return

    parsed: Any = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        return

    parsed["ip_groups"] = {}
    parsed["rules"] = []
    cfg_path.write_text(yaml.safe_dump(parsed, sort_keys=False), encoding="utf-8")


def _validate_group_network(group_name: str, cidr: str) -> tuple[str, str]:
    group = group_name.strip()
    network = cidr.strip()
    if not group:
        raise ValueError("Group name is required")
    ipaddress.ip_network(network, strict=False)
    return group, network


def _validate_rule(group_name: str, domain: str, action: str, target: str | None) -> Rule:
    group = group_name.strip()
    rule_domain = domain.strip().lower()
    rule_action = action.strip().lower()
    rule_target = target.strip().lower() if target is not None and target.strip() else None

    if not group:
        raise ValueError("Rule group is required")
    if not rule_domain:
        raise ValueError("Rule domain is required")
    if rule_action not in _ALLOWED_ACTIONS:
        raise ValueError("Rule action must be one of allow/rewrite/block")
    if rule_action == "rewrite" and not rule_target:
        raise ValueError("Rewrite rule requires target")
    if rule_action != "rewrite":
        rule_target = None

    return Rule(group=group, domain=rule_domain, action=rule_action, target=rule_target)


def bootstrap_policy_db(db_path: Path, seed_groups: dict[str, list[str]], seed_rules: list[Rule]) -> bool:
    ensure_schema(db_path)
    seeded = False
    with _connect(db_path) as conn:
        groups_empty = _is_empty(conn, "group_networks")
        rules_empty = _is_empty(conn, "rules")

        # Seed once only when the DB is fully empty.
        if groups_empty and rules_empty:
            for group, cidrs in seed_groups.items():
                for cidr in cidrs:
                    valid_group, valid_cidr = _validate_group_network(group, cidr)
                    conn.execute(
                        "INSERT OR IGNORE INTO group_networks (group_name, cidr) VALUES (?, ?)",
                        (valid_group, valid_cidr),
                    )
            for seed in seed_rules:
                rule = _validate_rule(seed.group, seed.domain, seed.action, seed.target)
                conn.execute(
                    "INSERT INTO rules (group_name, domain, action, target) VALUES (?, ?, ?, ?)",
                    (rule.group, rule.domain, rule.action, rule.target),
                )
            seeded = True

        conn.commit()
    return seeded


def list_group_networks(db_path: Path) -> list[dict[str, Any]]:
    ensure_schema(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, group_name, cidr FROM group_networks ORDER BY group_name, cidr"
        ).fetchall()
    return [dict(row) for row in rows]


def add_group_network(db_path: Path, group_name: str, cidr: str) -> None:
    group, network = _validate_group_network(group_name, cidr)
    ensure_schema(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO group_networks (group_name, cidr) VALUES (?, ?)",
            (group, network),
        )
        conn.commit()


def update_group_network(db_path: Path, row_id: int, group_name: str, cidr: str) -> None:
    group, network = _validate_group_network(group_name, cidr)
    ensure_schema(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE group_networks SET group_name = ?, cidr = ? WHERE id = ?",
            (group, network, row_id),
        )
        conn.commit()


def delete_group_network(db_path: Path, row_id: int) -> None:
    ensure_schema(db_path)
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM group_networks WHERE id = ?", (row_id,))
        conn.commit()


def list_rules(db_path: Path) -> list[dict[str, Any]]:
    ensure_schema(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, group_name, domain, action, target FROM rules ORDER BY group_name, domain"
        ).fetchall()
    return [dict(row) for row in rows]


def add_rule(db_path: Path, group_name: str, domain: str, action: str, target: str | None) -> None:
    rule = _validate_rule(group_name, domain, action, target)
    ensure_schema(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO rules (group_name, domain, action, target) VALUES (?, ?, ?, ?)",
            (rule.group, rule.domain, rule.action, rule.target),
        )
        conn.commit()


def update_rule(db_path: Path, row_id: int, group_name: str, domain: str, action: str, target: str | None) -> None:
    rule = _validate_rule(group_name, domain, action, target)
    ensure_schema(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE rules SET group_name = ?, domain = ?, action = ?, target = ? WHERE id = ?",
            (rule.group, rule.domain, rule.action, rule.target, row_id),
        )
        conn.commit()


def delete_rule(db_path: Path, row_id: int) -> None:
    ensure_schema(db_path)
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM rules WHERE id = ?", (row_id,))
        conn.commit()


def load_policy(db_path: Path) -> tuple[dict[str, list[str]], list[Rule]]:
    ensure_schema(db_path)

    group_map: dict[str, list[str]] = {}
    with _connect(db_path) as conn:
        group_rows = conn.execute(
            "SELECT group_name, cidr FROM group_networks ORDER BY group_name, cidr"
        ).fetchall()
        for row in group_rows:
            group = str(row["group_name"])
            group_map.setdefault(group, []).append(str(row["cidr"]))

        rule_rows = conn.execute(
            "SELECT group_name, domain, action, target FROM rules ORDER BY id"
        ).fetchall()

    rules = [
        _validate_rule(
            str(row["group_name"]),
            str(row["domain"]),
            str(row["action"]),
            str(row["target"]) if row["target"] is not None else None,
        )
        for row in rule_rows
    ]
    return group_map, rules


def apply_db_policy(config: ServerConfig, config_path: str | Path) -> ServerConfig:
    db_path = resolve_policy_db_path(config_path)
    seeded = bootstrap_policy_db(db_path, config.ip_groups, config.rules)
    if seeded:
        _clear_policy_from_config_yaml(config_path)
    group_map, rules = load_policy(db_path)
    return replace(config, ip_groups=group_map, rules=rules)
