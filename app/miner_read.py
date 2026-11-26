"""Read operator-configured miners and keep only the heartbeat's public schema."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import SplitResult, urlsplit

import httpx

MAX_DEVICES = 64
READ_TIMEOUT = 3.0
# One device read, every address its name resolves to included.
READ_BUDGET = 10.0
MAX_BYTES = 262_144
READ_INTERVAL = 60
STALE_AFTER = 180

_DEFAULT_PORTS = {"axeos": 80, "cgminer": 4028}
_LAN = tuple(ipaddress.ip_network(cidr) for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"))
_IPV6_METADATA = ipaddress.ip_address("fd00:ec2::254")
_AUTHORITY = re.compile(r"(?:\[[0-9a-fA-F:.]+\]|[a-zA-Z0-9.-]+)(?::[0-9]{1,5})?")
_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_DIFFICULTY = re.compile(r"([0-9]+(?:\.[0-9]+)?)([kMGTPE]?)")
_DIFF_SCALE = {unit: 1000**index for index, unit in enumerate(("", "k", "M", "G", "T", "P", "E"))}
_FIGURES = {
    "hashrate_ghs": (0, 1e6),
    "hashrate_avg_ghs": (0, 1e6),
    "watts": (0, 20_000),
    "temp_c": (-40, 150),
    "vr_temp_c": (-40, 150),
    "best_diff": (0, 1e21),
    "best_session_diff": (0, 1e21),
}
_ERRORS = {"unreachable", "timed out", "refused (401)", "not JSON", "too large", "address not allowed", "no figures"}


@dataclass(frozen=True)
class Target:
    url: str
    protocol: str
    host: str
    port: int


class _ReadError(ValueError):
    """One of the fixed error messages safe to send in a heartbeat."""


def _normalized(addr: ipaddress.IPv4Address | ipaddress.IPv6Address):
    return getattr(addr, "ipv4_mapped", None) or addr


def _allowed(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    addr = _normalized(addr)
    return addr != _IPV6_METADATA and any(addr in net for net in _LAN)


def _endpoint(raw: str) -> SplitResult:
    if not raw.isascii() or not raw.isprintable() or " " in raw:
        raise ValueError("invalid URL")
    parsed = urlsplit(raw)
    host = parsed.hostname
    if not host or not _AUTHORITY.fullmatch(parsed.netloc) or parsed.port == 0:
        raise ValueError("invalid host or port")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        dns_name = host.removesuffix(".")
        if len(dns_name) > 253 or not all(_DNS_LABEL.fullmatch(label) for label in dns_name.split(".")):
            raise ValueError("invalid hostname") from None
    return parsed


def _netloc(host: str, port: int | None) -> str:
    authority = f"[{host}]" if ":" in host else host
    return f"{authority}:{port}" if port is not None else authority


def _target(raw: str) -> Target:
    if len(raw) > 200:
        raise ValueError("target too long")
    parsed = _endpoint(raw)
    protocol = parsed.scheme
    if protocol not in _DEFAULT_PORTS or parsed.path or "?" in raw or "#" in raw:
        raise ValueError("invalid target URL")
    host = parsed.hostname
    assert host is not None
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not _allowed(addr):
            raise _ReadError("address not allowed")
        host = str(_normalized(addr))
    return Target(f"{protocol}://{_netloc(host, parsed.port)}", protocol, host, parsed.port or _DEFAULT_PORTS[protocol])


def parse_targets(raw: str) -> tuple[list[Target], list[str]]:
    if not raw.strip():
        return [], []
    entries = raw.split(",", MAX_DEVICES)
    if len(entries) > MAX_DEVICES:
        return [], [f"CASHPILOT_MINERS accepts up to {MAX_DEVICES} entries"]
    targets, errors = [], []
    seen = set()
    for index, entry in enumerate(entries, 1):
        try:
            target = _target(entry.strip())
        except _ReadError:
            errors.append(f"{entry.strip()}: address not allowed"[:200])
        except ValueError:
            # A malformed URL can contain a password. Report its position.
            errors.append(f"Miner entry {index}: expected axeos://host[:port] or cgminer://host[:port]")
        else:
            key = target.protocol, target.host, target.port
            if key not in seen:
                seen.add(key)
                targets.append(target)
    return targets, errors


async def _resolve(target: Target) -> list[str]:
    async with asyncio.timeout(READ_TIMEOUT):
        infos = await asyncio.get_running_loop().getaddrinfo(target.host, target.port, type=socket.SOCK_STREAM)
    addresses = [ipaddress.ip_address(info[4][0]) for info in infos]
    if not addresses:
        raise _ReadError("unreachable")
    if not all(_allowed(addr) for addr in addresses):
        raise _ReadError("address not allowed")
    return list(dict.fromkeys(str(_normalized(addr)) for addr in addresses))


def _object(body: bytes | bytearray) -> dict:
    try:
        data = json.loads(body)
    except (ValueError, RecursionError):
        raise _ReadError("not JSON") from None
    if not isinstance(data, dict):
        raise _ReadError("not JSON")
    return data


async def _axeos_get(ip: str, port: int) -> dict:
    url = f"http://{_netloc(ip, port)}/api/system/info"
    async with (
        asyncio.timeout(READ_TIMEOUT),
        httpx.AsyncClient(
            trust_env=False, follow_redirects=False, timeout=READ_TIMEOUT, headers={"Accept-Encoding": "identity"}
        ) as client,
        client.stream("GET", url) as response,
    ):
        if response.status_code == 401:
            raise _ReadError("refused (401)")
        if response.status_code != 200:
            raise _ReadError(f"HTTP {response.status_code}")
        body = bytearray()
        async for chunk in response.aiter_raw(chunk_size=8192):
            if len(body) + len(chunk) > MAX_BYTES:
                raise _ReadError("too large")
            body.extend(chunk)
    return _object(body)


async def _cgminer_exchange(ip: str, port: int, command: str) -> dict:
    request = {"summary": b'{"command":"summary"}', "pools": b'{"command":"pools"}'}[command]
    async with asyncio.timeout(READ_TIMEOUT):
        reader, writer = await asyncio.open_connection(ip, port)
        try:
            writer.write(request)
            await writer.drain()
            body = bytearray()
            while chunk := await reader.read(min(8192, MAX_BYTES + 1 - len(body))):
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    raise _ReadError("too large")
                if chunk.endswith(b"\0"):
                    break
        finally:
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()
    return _object(body.rstrip(b"\0"))


def _number(value, minimum: float, maximum: float) -> float | None:
    if type(value) in (int, float) and minimum <= value <= maximum:
        return float(value)
    return None


def _text(value, limit: int) -> str | None:
    if isinstance(value, str):
        value = value[:limit].strip()
        if value.isprintable():
            return value
    return None


def _difficulty(value) -> float | None:
    if isinstance(value, str) and len(value) <= 40:
        match = _DIFFICULTY.fullmatch(value.strip())
        if match:
            value = float(match[1]) * _DIFF_SCALE[match[2]]
    return _number(value, *_FIGURES["best_diff"])


def _pool_url(value, port: int | None = None) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 200:
        return None
    try:
        parsed = _endpoint(value if "://" in value else f"stratum+tcp://{value}")
    except ValueError:
        return None
    host = parsed.hostname
    port = parsed.port or port
    if parsed.scheme and host and type(port) is int and 1 <= port <= 65535:
        result = f"{parsed.scheme}://{_netloc(host, port)}"
        if len(result) <= 200:
            return result
    return None


def parse_axeos(info: dict) -> dict:
    prefix = "fallbackStratum" if info.get("isUsingFallbackStratum") == 1 else "stratum"
    return {
        "hashrate_ghs": info.get("hashRate_1m", info.get("hashRate")),
        "hashrate_avg_ghs": info.get("hashRate_1h"),
        "watts": info.get("power"),
        "temp_c": info.get("temp"),
        "vr_temp_c": info.get("vrTemp"),
        "best_diff": _difficulty(info.get("bestDiff")),
        "best_session_diff": _difficulty(info.get("bestSessionDiff")),
        "uptime_s": info.get("uptimeSeconds"),
        "model": info.get("ASICModel"),
        "firmware": info.get("version"),
        "pool_url": _pool_url(info.get(f"{prefix}URL"), info.get(f"{prefix}Port")),
        "pool_user": info.get(f"{prefix}User"),
    }


def _first_record(records) -> dict:
    return records[0] if isinstance(records, list) and records and isinstance(records[0], dict) else {}


def _hashrate(record: dict, *keys: str) -> float | None:
    for key in keys:
        scale = 1000 if key.startswith("MHS") else 1
        if (number := _number(record.get(key), 0, 1e6 * scale)) is not None:
            return number / scale
    return None


def parse_cgminer(summary: dict, pools: dict | None) -> dict:
    stats = _first_record(summary.get("SUMMARY"))
    status = _first_record(summary.get("STATUS"))
    entries = (pools or {}).get("POOLS")
    connected = (
        [p for p in entries if isinstance(p, dict) and p.get("Stratum Active") is True]
        if isinstance(entries, list)
        else []
    )
    # Load-balance mode keeps several pools connected at once. Naming one of
    # them as the pool would be a guess, so show a pool only when it is alone.
    active = connected[0] if len(connected) == 1 else {}
    return {
        "hashrate_ghs": _hashrate(stats, "MHS 1m", "MHS 5s", "GHS 5s"),
        "hashrate_avg_ghs": _hashrate(stats, "MHS av", "GHS av"),
        "watts": stats.get("Power"),
        "temp_c": stats.get("Temperature"),
        "best_diff": stats.get("Best Share"),
        "uptime_s": stats.get("Elapsed"),
        "firmware": status.get("Description"),
        "pool_url": _pool_url(active.get("URL")),
        "pool_user": active.get("User"),
    }


def _timestamp(value) -> str | None:
    if isinstance(value, str) and len(value) <= 40:
        try:
            date = datetime.fromisoformat(value)
            if date.tzinfo is not None:
                return date.astimezone(UTC).isoformat()
        except (ValueError, OverflowError):
            pass
    return None


def sanitize_row(row) -> dict | None:
    if not isinstance(row, dict) or not isinstance(row.get("target"), str) or type(row.get("ok")) is not bool:
        return None
    try:
        target = _target(row["target"])
    except ValueError:
        return None
    read_at = _timestamp(row.get("read_at"))
    if target.protocol != row.get("protocol") or read_at is None:
        return None
    figures = {key: _number(row.get(key), *bounds) for key, bounds in _FIGURES.items()}
    uptime = row.get("uptime_s")
    ok = row["ok"] and any(value is not None for value in figures.values())
    error = row.get("error")
    if row["ok"] and not ok:
        error = "no figures"
    if not isinstance(error, str) or (error not in _ERRORS and not re.fullmatch(r"HTTP [1-5][0-9]{2}", error)):
        error = "unreachable"
    return {
        "target": target.url,
        "protocol": target.protocol,
        "ok": ok,
        "error": None if ok else error,
        "read_at": read_at,
        **(figures if ok else dict.fromkeys(_FIGURES)),
        "uptime_s": uptime if ok and type(uptime) is int and 0 <= uptime <= 1_000_000_000 else None,
        "model": _text(row.get("model"), 64) if ok else None,
        "firmware": _text(row.get("firmware"), 64) if ok else None,
        "pool_url": _pool_url(row.get("pool_url")) if ok else None,
        "pool_user": _text(row.get("pool_user"), 128) if ok else None,
    }


def sanitize_snapshot(obj) -> dict | None:
    if not isinstance(obj, dict):
        return None
    devices = obj.get("devices")
    errors = obj.get("errors")
    rows = {}
    if isinstance(devices, list):
        for item in devices[:MAX_DEVICES]:
            if (row := sanitize_row(item)) is not None:
                rows.setdefault(row["target"], row)
    return {
        "read_at": _timestamp(obj.get("read_at")),
        "errors": [error for item in errors[:MAX_DEVICES] if (error := _text(item, 200))]
        if isinstance(errors, list)
        else [],
        "devices": list(rows.values()),
    }


async def _read_address(target: Target, ip: str) -> dict:
    if target.protocol == "axeos":
        return parse_axeos(await _axeos_get(ip, target.port))
    summary = await _cgminer_exchange(ip, target.port, "summary")
    pools = None
    with suppress(OSError, _ReadError):
        pools = await _cgminer_exchange(ip, target.port, "pools")
    return parse_cgminer(summary, pools)


async def _read_target(target: Target) -> tuple[str | None, dict]:
    row = {"target": target.url, "protocol": target.protocol}
    ip = None
    try:
        async with asyncio.timeout(READ_BUDGET):
            addresses = await _resolve(target)
            # A name can resolve to an address that does not answer (an IPv6
            # address the miner never took, say). Move on to the next one.
            for index, address in enumerate(addresses, 1):
                try:
                    figures = await _read_address(target, address)
                except (TimeoutError, OSError, httpx.TransportError):
                    if index == len(addresses):
                        raise
                    continue
                ip = address
                row.update(figures)
                break
        row["ok"] = True
    except _ReadError as exc:
        row.update(ok=False, error=str(exc))
    except (TimeoutError, httpx.TimeoutException):
        row.update(ok=False, error="timed out")
    except (OSError, UnicodeError, httpx.RequestError):
        row.update(ok=False, error="unreachable")
    row["read_at"] = datetime.now(UTC).isoformat()
    return ip, row


async def read_all(targets: list[Target]) -> dict:
    readings = await asyncio.gather(*(_read_target(target) for target in targets))
    devices = []
    seen = set()
    for target, (ip, reading) in zip(targets, readings, strict=True):
        row = sanitize_row(reading)
        if row is None:
            continue
        # A DNS name and its literal IP can name one miner. Display the first
        # successful reading so both aliases do not appear as separate draw.
        if row["ok"]:
            endpoint = target.protocol, ip, target.port
            if endpoint in seen:
                continue
            seen.add(endpoint)
        devices.append(row)
    return {
        "read_at": datetime.now(UTC).isoformat(),
        "errors": [],
        "devices": devices,
    }
