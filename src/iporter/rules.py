# IPorter - Rule evaluation for a local DNS server with source IP group based rewrite rules.
# Creator: Simon Nandor <simonszoft@gmail.com>
# GitHUB: https://github.com/simonszoft/IPorter

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from fnmatch import fnmatch

from .config import Rule, ServerConfig


@dataclass(frozen=True)
class Decision:
    action: str
    target: str | None = None


def _normalize_domain(domain: str) -> str:
    return domain.rstrip(".").lower()


def client_groups(ip: str, group_map: dict[str, list[str]]) -> set[str]:
    client_ip = ipaddress.ip_address(ip)
    matched: set[str] = set()
    for group, ranges in group_map.items():
        for value in ranges:
            network = ipaddress.ip_network(value, strict=False)
            if client_ip in network:
                matched.add(group)
                break
    return matched


def domain_matches(rule_domain: str, query_domain: str) -> bool:
    rule_name = _normalize_domain(rule_domain)
    query_name = _normalize_domain(query_domain)

    if "*" in rule_name or "?" in rule_name:
        return fnmatch(query_name, rule_name)

    if query_name == rule_name:
        return True

    return query_name.endswith(f".{rule_name}")


def decide(config: ServerConfig, source_ip: str, query_domain: str) -> Decision:
    groups = client_groups(source_ip, config.ip_groups)

    for rule in config.rules:
        if rule.group not in groups:
            continue
        if not domain_matches(rule.domain, query_domain):
            continue

        if rule.action == "rewrite":
            if not rule.target:
                raise ValueError(f"Rewrite rule for {rule.domain} is missing target")
            return Decision(action="rewrite", target=rule.target)

        if rule.action == "block":
            return Decision(action="block")

        raise ValueError(f"Unsupported action: {rule.action}")

    return Decision(action="allow")
