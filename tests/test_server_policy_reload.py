# IPorter - Test cases for runtime policy reload in the DNS daemon.
# Creator: Simon Nandor <simonszoft@gmail.com>
# GitHUB: https://github.com/simonszoft/IPorter

from pathlib import Path

from iporter.config import load_config
from iporter.policy_db import add_group_network, add_rule, apply_db_policy, resolve_policy_db_path
from iporter.server import DnsUdpProtocol


def test_policy_reloads_when_db_changes(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
listen_host: "0.0.0.0"
listen_port: 5353
policy_db_path: policy.db
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

    cfg = apply_db_policy(load_config(config_path), config_path)
    protocol = DnsUdpProtocol(cfg, str(config_path))

    assert protocol.config.ip_groups == {}
    assert protocol.config.rules == []

    db_path = resolve_policy_db_path(config_path)
    add_group_network(db_path, "students", "192.168.10.0/24")
    add_rule(db_path, "students", "facebook.com", "block", "")

    protocol._refresh_policy_if_needed()

    assert "students" in protocol.config.ip_groups
    assert protocol.config.rules
    assert protocol.config.rules[0].action == "block"
