"""Whether a bearer key may travel to a URL over plain http.

The same rule as CashPilot-Desktop (``internal/upstream/serverurl.go``) and
CashPilot-android (``ServerUrlPolicy``), so all three stacks agree on which
hosts are private:

- https to any host;
- http only to a host that cannot be on the public internet: loopback,
  RFC1918, CGNAT/Tailscale 100.64.0.0/10, link-local, IPv6 ULA, a
  single-label name, or a name under .local, .lan, .home.arpa, .internal or
  .ts.net.

The answer comes from the URL's literal host and never from DNS, so it does
not depend on the network the box is on, and a public name that happens to
resolve to a LAN address still counts as public. Only a host already in
canonical form is judged: a percent-encoded or Unicode-dotted host is refused
rather than decoded, because a client may decode it to a public address.

Used by the worker before each heartbeat (``CASHPILOT_UI_URL``) and by the UI
before each command to a worker (the URL the worker advertised).
"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

_CANONICAL = re.compile(r"[a-z0-9.:-]+")
# A dotless number is an IPv4 address to the system resolver (134744072 is 8.8.8.8).
_NUMERIC = re.compile(r"0x[0-9a-f]*|\d+")
PRIVATE_SUFFIXES = (".local", ".lan", ".home.arpa", ".internal", ".ts.net")
_CLEARTEXT_NETS = tuple(
    ipaddress.ip_network(c)
    for c in (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "100.64.0.0/10",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    )
)

#: What "private" means, for a message that tells the user what to use instead.
PRIVATE_HOSTS_TEXT = (
    "localhost, a LAN, link-local or Tailscale IP (10.x.x.x, 172.16-31.x.x, 192.168.x.x, "
    "169.254.x.x, 100.64-127.x.x, or IPv6 fc00::/7 or fe80::/10), a single-label name such as "
    "cashpilot-ui, or a name under .local, .lan, .home.arpa, .internal or .ts.net"
)


def cleartext_allowed(host: str) -> bool:
    """Whether plain http may go to ``host``: a host name or IP, without brackets."""
    host = host.lower().removeprefix("[").removesuffix("]").rstrip(".")
    if not _CANONICAL.fullmatch(host):
        return False
    if host == "localhost":
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        addr = None
    if addr is not None:
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
            addr = addr.ipv4_mapped
        return any(addr.version == net.version and addr in net for net in _CLEARTEXT_NETS)
    if "." in host:
        return any(host.endswith(s) and len(host) > len(s) for s in PRIVATE_SUFFIXES)
    return ":" not in host and not _NUMERIC.fullmatch(host)


def bearer_allowed(url: str) -> bool:
    """Whether a bearer key may be sent to ``url``: https anywhere, http to a private host only."""
    try:
        parts = urlsplit(url.strip())
        host = parts.hostname or ""
    except ValueError:
        return False
    if not host:
        return False
    scheme = parts.scheme.lower()
    if scheme == "https":
        return True
    return scheme == "http" and cleartext_allowed(host)


def host_of(url: str) -> str:
    """The URL's host, safe to show: never its userinfo."""
    try:
        return urlsplit(url.strip()).hostname or "(no host)"
    except ValueError:
        return "(unparseable)"
