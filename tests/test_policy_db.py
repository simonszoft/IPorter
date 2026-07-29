# IPorter - Test cases for the policy database module of a local DNS server with source IP group based rewrite rules.
# Creator: Simon Nandor <simonszoft@gmail.com>
# GitHUB: https://github.com/simonszoft/IPorter

from pathlib import Path

import yaml

from iporter.config import Rule, ServerConfig, UpstreamServer
from iporter.policy_db import (
    add_group_network,
    add_rule,
    apply_db_policy,
    delete_group_network,
    delete_rule,
    list_group_networks,
    list_rules,
    update_group_network,
    update_rule,
)


def _base_config() -> ServerConfig:
    return ServerConfig(
        listen_host="0.0.0.0",
        listen_port=5353,
        upstream_servers=[
            UpstreamServer(host="1.1.1.1", port=53),
            UpstreamServer(host="8.8.8.8", port=53),
        ],
        response_ttl=60,
        ip_groups={"students": ["192.168.10.0/24"]},
        rules=[Rule(group="students", domain="facebook.com", action="rewrite", target="wikipedia.org")],
    )


def test_apply_db_policy_bootstraps_from_config(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "config.yaml"
    config_path.write_text(
        """
listen_host: "0.0.0.0"
listen_port: 5353
policy_db_path: "policy.db"
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

    cfg = apply_db_policy(_base_config(), config_path)
    assert "students" in cfg.ip_groups
    assert cfg.rules[0].domain == "facebook.com"


def test_policy_crud(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "config.yaml"
    config_path.write_text(
        """
listen_host: "0.0.0.0"
listen_port: 5353
policy_db_path: "policy.db"
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

    cfg = apply_db_policy(_base_config(), config_path)
    db_groups = list_group_networks(config_dir / "policy.db")
    db_rules = list_rules(config_dir / "policy.db")
    assert db_groups
    assert db_rules

    group_id = int(db_groups[0]["id"])
    rule_id = int(db_rules[0]["id"])

    update_group_network(config_dir / "policy.db", group_id, "students", "10.0.0.0/24")
    update_rule(config_dir / "policy.db", rule_id, "students", "example.com", "block", "")

    groups_after = list_group_networks(config_dir / "policy.db")
    rules_after = list_rules(config_dir / "policy.db")
    assert groups_after[0]["cidr"] == "10.0.0.0/24"
    assert rules_after[0]["domain"] == "example.com"
    assert rules_after[0]["action"] == "block"

    add_group_network(config_dir / "policy.db", "teachers", "192.168.20.0/24")
    add_rule(config_dir / "policy.db", "teachers", "facebook.com", "allow", "")

    all_groups = list_group_networks(config_dir / "policy.db")
    all_rules = list_rules(config_dir / "policy.db")
    assert len(all_groups) >= 2
    assert len(all_rules) >= 2

    delete_group_network(config_dir / "policy.db", int(all_groups[-1]["id"]))
    delete_rule(config_dir / "policy.db", int(all_rules[-1]["id"]))

    final_cfg = apply_db_policy(cfg, config_path)
    assert final_cfg.ip_groups


def test_bootstrap_clears_groups_and_rules_in_yaml(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "listen_host": "0.0.0.0",
                "listen_port": 5353,
                "policy_db_path": "policy.db",
                "upstream_dns_servers": [
                    {"host": "1.1.1.1", "port": 53},
                    {"host": "8.8.8.8", "port": 53},
                ],
                "ip_groups": {"students": ["192.168.10.0/24"]},
                "rules": [
                    {
                        "group": "students",
                        "domain": "facebook.com",
                        "action": "rewrite",
                        "target": "wikipedia.org",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    cfg = _base_config()
    apply_db_policy(cfg, config_path)

    parsed = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert parsed["ip_groups"] == {}
    assert parsed["rules"] == []


def test_existing_db_does_not_rewrite_yaml(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "listen_host": "0.0.0.0",
                "listen_port": 5353,
                "policy_db_path": "policy.db",
                "upstream_dns_servers": [
                    {"host": "1.1.1.1", "port": 53},
                    {"host": "8.8.8.8", "port": 53},
                ],
                "ip_groups": {"students": ["192.168.10.0/24"]},
                "rules": [
                    {
                        "group": "students",
                        "domain": "facebook.com",
                        "action": "rewrite",
                        "target": "wikipedia.org",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    cfg = _base_config()
    apply_db_policy(cfg, config_path)
    after_first = config_path.read_text(encoding="utf-8")

    config_path.write_text(
        after_first.replace(
            "rules: []",
            "rules:\n- group: \"students\"\n  domain: \"example.com\"\n  action: \"block\"",
        ),
        encoding="utf-8",
    )
    apply_db_policy(cfg, config_path)

    parsed = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert isinstance(parsed.get("rules"), list)
    assert parsed["rules"]
