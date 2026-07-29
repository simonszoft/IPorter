# IPorter - Test cases for the rules module of a local DNS server with source IP group based rewrite rules.
# Creator: Simon Nandor <simonszoft@gmail.com>
# GitHUB: https://github.com/simonszoft/IPorter

from iporter.config import Rule, ServerConfig, UpstreamServer
from iporter.rules import client_groups, decide, domain_matches


def sample_config() -> ServerConfig:
    return ServerConfig(
        listen_host="0.0.0.0",
        listen_port=5353,
        upstream_servers=[
            UpstreamServer(host="1.1.1.1", port=53),
            UpstreamServer(host="8.8.8.8", port=53),
        ],
        response_ttl=60,
        ip_groups={
            "students": ["192.168.10.0/24"],
            "teachers": ["192.168.20.0/24"],
        },
        rules=[
            Rule(group="students", domain="facebook.com", action="rewrite", target="wikipedia.org"),
            Rule(group="students", domain="adult-example.com", action="block"),
        ],
    )


def test_client_groups() -> None:
    groups = client_groups("192.168.10.35", sample_config().ip_groups)
    assert "students" in groups
    assert "teachers" not in groups


def test_domain_matches_exact_and_subdomain() -> None:
    assert domain_matches("facebook.com", "facebook.com")
    assert domain_matches("facebook.com", "m.facebook.com")
    assert not domain_matches("facebook.com", "facebook.net")


def test_decide_rewrite_for_students() -> None:
    decision = decide(sample_config(), "192.168.10.44", "facebook.com")
    assert decision.action == "rewrite"
    assert decision.target == "wikipedia.org"


def test_decide_allow_for_non_students() -> None:
    decision = decide(sample_config(), "192.168.20.44", "facebook.com")
    assert decision.action == "allow"


def test_decide_block() -> None:
    decision = decide(sample_config(), "192.168.10.44", "adult-example.com")
    assert decision.action == "block"
