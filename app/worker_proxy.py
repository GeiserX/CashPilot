"""SSRF-safe worker-URL validation for the CashPilot UI.

A worker's ``url`` arrives in the (fleet-key-authed) heartbeat body and is later
fetched WITH the fleet bearer token attached, so an attacker holding the fleet key
could otherwise turn the UI into a confused-deputy proxy into the internal network.
These helpers validate the URL and pin it to a checked IP (closing the DNS-rebinding
TOCTOU) before the UI ever connects. Kept as its own module so the policy/SSRF logic
is isolated and unit-testable apart from the request-handling in main.py; main.py's
``_get_verified_worker_url`` composes ``_validate_worker_url`` + ``_pin_url_to_ip``.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse, urlunparse

from fastapi import HTTPException

_ALLOWED_WORKER_SCHEMES = {"http", "https"}

# SSRF guard for worker URLs. The worker `url` arrives in the (fleet-key-authed)
# heartbeat body and is later fetched WITH the fleet bearer token attached, so an
# attacker holding the fleet key could otherwise turn the UI into a confused-deputy
# proxy into the internal network. Policy is OPT-IN: the default ("permissive")
# preserves today's behaviour — LAN (RFC1918) and Tailscale (CGNAT 100.64.0.0/10)
# workers keep working out of the box — while always closing the free gaps
# (cloud-metadata IPs, IPv6 loopback/link-local, IPv4-mapped bypasses, DNS rebinding).
# "strict" mode restricts to CASHPILOT_WORKER_ALLOWED_HOSTS (CIDRs + *.suffix names).
_WORKER_URL_POLICY = os.getenv("CASHPILOT_WORKER_URL_POLICY", "permissive").strip().lower()
_WORKER_ALLOW_METADATA = os.getenv("CASHPILOT_WORKER_ALLOW_METADATA", "false").strip().lower() == "true"

# Cloud metadata endpoints — never a valid worker; always blocked (unless the
# explicit escape hatch is set). The IPv6 one is inside ULA fd00::/8 so a
# "permissive" policy would otherwise allow it.
_METADATA_IPS = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),  # AWS/GCP/Azure IMDS (IPv4)
        ipaddress.ip_address("fd00:ec2::254"),  # AWS IMDS over IPv6
    }
)
# Loopback + link-local, IPv4 and IPv6 — always blocked.
_BLOCKED_NETWORKS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fe80::/10"),
)


def _parse_worker_allowlist() -> tuple[list[ipaddress._BaseNetwork], list[str], set[str]]:
    """Parse CASHPILOT_WORKER_ALLOWED_HOSTS into (cidrs, host_suffixes, exact_hosts)."""
    cidrs: list[ipaddress._BaseNetwork] = []
    suffixes: list[str] = []
    exact: set[str] = set()
    for entry in os.getenv("CASHPILOT_WORKER_ALLOWED_HOSTS", "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        if entry.startswith("*."):
            suffixes.append(entry[2:].lower())
            continue
        try:
            cidrs.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            exact.add(entry.lower())
    return cidrs, suffixes, exact


_WORKER_ALLOWED_CIDRS, _WORKER_ALLOWED_SUFFIXES, _WORKER_ALLOWED_HOSTS = _parse_worker_allowlist()


def _normalize_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address):
    """Collapse IPv4-mapped IPv6 (::ffff:a.b.c.d) to the underlying IPv4 address."""
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


def _assert_ip_not_blocked(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    """Always-on checks: metadata + loopback/link-local, regardless of policy."""
    addr = _normalize_ip(addr)
    if not _WORKER_ALLOW_METADATA and addr in _METADATA_IPS:
        raise HTTPException(status_code=400, detail="Worker URL points to a cloud metadata address")
    for net in _BLOCKED_NETWORKS:
        if addr.version == net.version and addr in net:
            raise HTTPException(status_code=400, detail="Worker URL points to loopback/link-local address")


def _assert_ip_strict_allowed(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    """In strict mode, the resolved IP must fall inside an allowed CIDR."""
    addr = _normalize_ip(addr)
    if any(addr.version == c.version and addr in c for c in _WORKER_ALLOWED_CIDRS):
        return
    raise HTTPException(status_code=400, detail="Worker URL not in allowed hosts (strict mode)")


def _validate_worker_url(raw_url: str) -> tuple[str, str | None]:
    """Validate a worker URL; raise 400 on SSRF-risky targets.

    Returns ``(safe_url, pinned_ip)``. ``pinned_ip`` is a validated IP the caller
    should connect to directly instead of re-resolving the hostname — this closes
    the DNS-rebinding TOCTOU where a name that resolved to a safe address here flips
    to a metadata/loopback address when httpx re-resolves at request time. It is
    ``None`` when the host is already a literal IP (nothing to re-resolve) or, in
    permissive mode, when the host could not be resolved (best-effort).

    Resolves hostnames and validates the resolved IP(s) so a DNS name that points at
    a metadata/loopback address is rejected (DNS-rebinding guard). Synchronous — its
    only blocking op is DNS resolution; event-loop callers MUST invoke it via
    ``asyncio.to_thread`` (see _get_verified_worker_url) so a slow/hanging resolver
    never blocks the whole UI.
    """
    parsed = urlparse(raw_url)
    if parsed.scheme not in _ALLOWED_WORKER_SCHEMES:
        raise HTTPException(status_code=400, detail=f"Invalid worker URL scheme: {parsed.scheme}")
    host = parsed.hostname or ""
    if not host:
        raise HTTPException(status_code=400, detail="Worker URL has no host")
    if host in ("localhost", "localhost.localdomain"):
        raise HTTPException(status_code=400, detail="Worker URL points to localhost")

    # Case A: literal IP — classify directly, no DNS needed.
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        addr = None
    if addr is not None:
        _assert_ip_not_blocked(addr)
        if _WORKER_URL_POLICY == "strict":
            _assert_ip_strict_allowed(addr)
        # Already a literal IP — httpx won't re-resolve, so no pinning needed.
        return raw_url.rstrip("/"), None

    # Case B: hostname. In strict mode an explicit name/suffix match short-circuits
    # the CIDR check (so Tailscale MagicDNS names work by name), but the resolved
    # IPs are still checked against the always-blocked set.
    hostname_allowed = host.lower() in _WORKER_ALLOWED_HOSTS or any(
        host.lower() == s or host.lower().endswith("." + s) for s in _WORKER_ALLOWED_SUFFIXES
    )
    try:
        infos = socket.getaddrinfo(host, parsed.port, proto=socket.IPPROTO_TCP)
        resolved = {ipaddress.ip_address(info[4][0]) for info in infos}
    except (socket.gaierror, ValueError):
        # Unresolvable: fatal in strict (can't prove it's allowed), non-fatal in
        # permissive (the request itself will fail if the host is truly dead; we
        # don't want a transiently-unresolvable worker to hard-400).
        if _WORKER_URL_POLICY == "strict" and not hostname_allowed:
            raise HTTPException(status_code=400, detail="Worker URL host does not resolve") from None
        # Permissive + unresolvable: best-effort, nothing to pin.
        return raw_url.rstrip("/"), None

    for addr in resolved:
        _assert_ip_not_blocked(addr)
    if _WORKER_URL_POLICY == "strict" and not hostname_allowed:
        for addr in resolved:
            _assert_ip_strict_allowed(addr)
    # Pin one validated IP for the actual request so a rebinding record that
    # resolved safe here can't flip to a blocked address when httpx re-resolves.
    # Deterministic pick over the just-checked set.
    return raw_url.rstrip("/"), str(min(resolved, key=str))


def _pin_url_to_ip(url: str, ip: str) -> tuple[str, str]:
    """Rewrite ``url``'s host to the validated ``ip`` and return (pinned_url, host_header).

    Connecting to the already-checked IP (with the original hostname carried in the
    Host header) means httpx never re-resolves the name, so a DNS-rebinding flip
    between validation and the request cannot redirect us to a blocked address.
    """
    parsed = urlparse(url)
    port = parsed.port
    host_header = f"{parsed.hostname}:{port}" if port else (parsed.hostname or "")
    ip_host = f"[{ip}]" if ":" in ip else ip  # bracket IPv6 literals
    netloc = f"{ip_host}:{port}" if port else ip_host
    return urlunparse(parsed._replace(netloc=netloc)), host_header
