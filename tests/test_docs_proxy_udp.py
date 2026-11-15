"""docs/proxies.md must not promise UDP through a SOCKS5 or HTTP proxy.

tunnel/cp-tunnel lets a socks5 or http tunnel out only over TCP to the
proxy's own address and port. A SOCKS5 UDP ASSOCIATE relay sends UDP to the
proxy, so the firewall drops it. The page used to say SOCKS5 carries UDP when
the provider supports UDP ASSOCIATE.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TUNNEL = ROOT / "tunnel" / "cp-tunnel"
PAGE = ROOT / "docs" / "proxies.md"

UDP_PROMISE = re.compile(
    r"(carries|works?|through) [^.|]*udp associate|(socks5|http connect)[^.|]*\bcarr(y|ies) udp",
    re.IGNORECASE,
)


def _socks_egress_rule() -> str:
    branch = TUNNEL.read_text(encoding="utf-8").split("socks5 | http)", 1)[1].split("tailscale)", 1)[0]
    rules = [line.strip() for line in branch.splitlines() if line.strip().startswith("PROXY_RULE=")]
    assert len(rules) == 1, "expected one PROXY_RULE in the socks5 | http branch of cp-tunnel"
    # Every way out to the proxy is built on it: the cgroup rules and the plain one.
    for line in branch.splitlines():
        if "accept" in line and "oifname" not in line:
            assert "$PROXY_RULE" in line, line
    return rules[0]


def promises_udp(text: str) -> bool:
    return bool(UDP_PROMISE.search(re.sub(r"\s+", " ", text)))


def test_the_socks_tunnel_lets_out_only_tcp():
    rule = _socks_egress_rule()
    assert "tcp dport $PROXY_PORT" in rule
    assert "udp" not in rule, "cp-tunnel now lets UDP out; this test's premise no longer holds"


def test_the_page_does_not_promise_udp_through_socks5():
    assert not promises_udp(PAGE.read_text(encoding="utf-8"))


def test_the_check_catches_the_old_claims():
    assert promises_udp("| SOCKS5 | host | Carries UDP only if the provider supports SOCKS5 UDP ASSOCIATE. |")
    assert promises_udp("and through SOCKS5\nonly when the provider supports UDP ASSOCIATE.")
    assert promises_udp("SOCKS5 carries UDP.")
    assert promises_udp("An HTTP CONNECT proxy carries UDP too.")


def test_the_check_accepts_the_true_claims():
    assert not promises_udp("SOCKS5 or HTTP CONNECT: the tunnel lets out only TCP. A Tailscale exit node carries UDP.")
