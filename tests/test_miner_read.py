import asyncio
import socket
from ipaddress import ip_address
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
import yaml

from app import miner_read as miners

STAMP = "2026-11-25T12:00:00Z"


def test_axeos_prefers_one_minute_rate_and_active_fallback_pool():
    result = miners.parse_axeos(
        {
            "hashRate": 1000,
            "hashRate_1m": 950,
            "hashRate_1h": 900,
            "power": 17.5,
            "temp": 59.875,
            "vrTemp": 71.5,
            "bestDiff": 483000,
            "bestSessionDiff": "1.2M",
            "uptimeSeconds": 4,
            "version": "v2.12",
            "ASICModel": "BM1368",
            "stratumURL": "primary.example",
            "stratumPort": 3333,
            "isUsingFallbackStratum": 1,
            "fallbackStratumURL": "backup.example",
            "fallbackStratumPort": 4444,
            "fallbackStratumUser": "fixture",
        }
    )
    assert result == {
        "hashrate_ghs": 950,
        "hashrate_avg_ghs": 900,
        "watts": 17.5,
        "temp_c": 59.875,
        "vr_temp_c": 71.5,
        "best_diff": 483000,
        "best_session_diff": 1_200_000,
        "uptime_s": 4,
        "firmware": "v2.12",
        "model": "BM1368",
        "pool_url": "stratum+tcp://backup.example:4444",
        "pool_user": "fixture",
    }


@pytest.mark.parametrize("model, rate", [("BM1368", 1000), ("BM1370", 4817.5)])
def test_legacy_axeos_and_nerdqaxe_use_raw_ghs_without_an_average(model, rate):
    result = miners.parse_axeos({"ASICModel": model, "hashRate": rate, "bestDiff": "483k", "temp": 67.0})
    assert result["hashrate_ghs"] == rate
    assert result["hashrate_avg_ghs"] is None
    assert result["best_diff"] == 483000
    assert result["temp_c"] == 67


def test_stock_antminer_leaves_watts_unknown_and_uses_active_pool():
    data = {"SUMMARY": [{"GHS 5s": 110566.89, "GHS av": 111834.85, "Best Share": 12904207043, "Elapsed": 50474}]}
    pools = {
        "POOLS": [
            {"URL": "stratum+tcp://standby.example:700", "Stratum Active": False},
            {"URL": "stratum+tcp://pool.example:700", "Stratum Active": True, "User": "fixture"},
        ]
    }
    result = miners.parse_cgminer(data, pools)
    assert result["hashrate_ghs"] == 110566.89
    assert result["hashrate_avg_ghs"] == 111834.85
    assert result["best_diff"] == 12904207043
    assert result["watts"] is None
    assert result["temp_c"] is None
    assert result["pool_url"] == "stratum+tcp://pool.example:700"
    assert result["pool_user"] == "fixture"
    assert miners.parse_cgminer(data, {"POOLS": pools["POOLS"][:1]})["pool_url"] is None


def test_load_balanced_cgminer_names_no_single_pool():
    pools = {
        "POOLS": [
            {"URL": "stratum+tcp://first.example:700", "Stratum Active": True, "User": "first"},
            {"URL": "stratum+tcp://second.example:700", "Stratum Active": True, "User": "second"},
        ]
    }
    result = miners.parse_cgminer({"SUMMARY": [{"GHS 5s": 100.0}]}, pools)
    assert (result["pool_url"], result["pool_user"]) == (None, None)
    assert result["hashrate_ghs"] == 100


def test_avalon_average_and_whatsminer_v2_summary():
    avalon = miners.parse_cgminer({"SUMMARY": [{"MHS av": 44539601.86, "MHS 5s": 0.0, "MHS 1m": 0.0}]}, None)
    assert avalon["hashrate_avg_ghs"] == pytest.approx(44539.60186)
    assert avalon["hashrate_ghs"] == 0
    whatsminer = miners.parse_cgminer(
        {"SUMMARY": [{"MHS 1m": 65536000, "MHS 5s": 99000, "Power": 3140, "Temperature": 71}]}, None
    )
    assert whatsminer["hashrate_ghs"] == 65536
    assert whatsminer["watts"] == 3140
    assert whatsminer["temp_c"] == 71


def test_targets_accept_private_endpoints_and_deduplicate():
    targets, errors = miners.parse_targets(
        " axeos://192.168.1.50, cgminer://10.0.0.7:4028, axeos://[fd25::aa]:8080,"
        "axeos://[::ffff:192.168.1.50]:80,cgminer://unit.local. "
    )
    assert not errors
    assert [(target.host, target.port) for target in targets] == [
        ("192.168.1.50", 80),
        ("10.0.0.7", 4028),
        ("fd25::aa", 8080),
        ("unit.local.", 4028),
    ]
    assert targets[2].url == "axeos://[fd25::aa]:8080"


@pytest.mark.parametrize(
    "url",
    [
        "192.168.1.50",
        "http://192.168.1.50",
        "axeos://name:fixture-secret@10.0.0.1",
        "axeos://10.0.0.1/",
        "axeos://10.0.0.1?",
        "axeos://10.0.0.1#",
        "axeos://10.0.0.1:0",
        "axeos://10.0.0.1:65536",
        "axeos://[fd00::1]junk:80",
        "axeos://unit.local..",
        "axeos://10.0.0.1\n:80",
        "axeos://10.0.\t0.1",
        ",".join(["axeos://10.0.0.1"] * 65),
    ],
)
def test_bad_target_config_has_an_error_without_leaking_a_password(url):
    targets, errors = miners.parse_targets(url)
    assert not targets
    assert errors and "fixture-secret" not in str(errors)


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "0.0.0.0",
        "169.254.169.254",
        "100.64.1.1",
        "8.8.8.8",
        "224.0.0.1",
        "[::1]",
        "[fe80::1]",
        "[fd00:ec2::254]",
        "[::ffff:8.8.8.8]",
    ],
)
def test_out_of_scope_literal_never_becomes_a_target(host):
    assert miners.parse_targets(f"axeos://{host}") == ([], [f"axeos://{host}: address not allowed"])


@pytest.mark.asyncio
async def test_dns_checks_every_address_and_passes_only_the_pinned_ip(monkeypatch):
    targets, _ = miners.parse_targets("axeos://unit.local,axeos://broken.local,axeos://second.local")

    async def resolve(name, port, **_):
        if name == "broken.local":
            raise UnicodeError("resolver could not encode the name")
        addrs = ["192.168.1.15", "8.8.8.8"] if name == "unit.local" else ["192.168.1.16"]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, port)) for addr in addrs]

    read = AsyncMock(return_value={"hashRate": 1000})
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    monkeypatch.setattr(miners, "_axeos_get", read)
    devices = (await miners.read_all(targets))["devices"]
    assert devices[0]["error"] == "address not allowed"
    assert devices[1]["error"] == "unreachable"
    assert devices[2]["hashrate_ghs"] == 1000
    read.assert_awaited_once_with("192.168.1.16", 80)


@pytest.mark.asyncio
async def test_one_reading_for_aliases_of_the_same_endpoint(monkeypatch):
    targets, _ = miners.parse_targets("axeos://unit.local,axeos://192.168.1.16,axeos://unit.local:8080")
    monkeypatch.setattr(miners, "_resolve", AsyncMock(return_value=["192.168.1.16"]))
    monkeypatch.setattr(miners, "_axeos_get", AsyncMock(return_value={"power": 10}))

    devices = (await miners.read_all(targets))["devices"]
    assert [row["target"] for row in devices] == ["axeos://unit.local", "axeos://unit.local:8080"]


@pytest.mark.asyncio
async def test_a_name_falls_back_to_its_next_private_address(monkeypatch):
    targets, _ = miners.parse_targets("axeos://unit.local,axeos://192.168.1.16")

    async def resolve(name, port, **_):
        addrs = ["fd25::16", "192.168.1.16"] if name == "unit.local" else [name]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, port)) for addr in addrs]

    async def read(ip, port):
        if ip == "fd25::16":
            raise httpx.ConnectError("no route to host")
        return {"hashRate": 1000}

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    monkeypatch.setattr(miners, "_axeos_get", read)
    devices = (await miners.read_all(targets))["devices"]
    # The name answered on its IPv4 address, so the literal is the same miner.
    assert [(row["target"], row["ok"], row["hashrate_ghs"]) for row in devices] == [("axeos://unit.local", True, 1000)]


@pytest.mark.asyncio
async def test_trying_addresses_stops_at_the_read_budget(monkeypatch):
    target = miners.parse_targets("cgminer://unit.local")[0][0]
    tried = []

    async def exchange(ip, port, command):
        tried.append(ip)
        if ip == "10.0.0.1":
            raise ConnectionRefusedError()
        await asyncio.sleep(1)

    monkeypatch.setattr(miners, "READ_BUDGET", 0.05)
    monkeypatch.setattr(miners, "_resolve", AsyncMock(return_value=["10.0.0.1", "10.0.0.2", "10.0.0.3"]))
    monkeypatch.setattr(miners, "_cgminer_exchange", exchange)
    device = (await miners.read_all([target]))["devices"][0]
    assert (device["ok"], device["error"]) == (False, "timed out")
    assert tried == ["10.0.0.1", "10.0.0.2"]


@pytest.mark.parametrize(
    "compose", sorted(p.name for p in Path(__file__).resolve().parent.parent.glob("docker-compose*.yml"))
)
def test_every_worker_manifest_forwards_the_miner_list(compose):
    services = yaml.safe_load((Path(__file__).resolve().parent.parent / compose).read_text())["services"]
    assert "CASHPILOT_MINERS=${CASHPILOT_MINERS:-}" in services["cashpilot-worker"]["environment"]


def sample(**fields):
    return {"target": "axeos://10.0.0.4", "protocol": "axeos", "ok": True, "read_at": STAMP, "temp_c": 55, **fields}


def test_schema_drops_private_and_nonfinite_fields_and_caps_rows():
    raw = sample(
        ssid="fixture",
        macAddr="fixture",
        coinbaseOutputs=[{"address": "fixture"}],
        watts=-5,
        hashrate_ghs=1e999,
        hashrate_avg_ghs="abc",
        best_session_diff=float("nan"),
        vr_temp_c=True,
        model="x" * 100,
        firmware="bad\nversion",
        pool_user="u" * 160,
        pool_url="stratum+tcp://POOL.example:4444/path?secret=fixture",
        uptime_s=0,
    )
    inputs = [{**raw, "target": f"axeos://10.0.0.{index}"} for index in range(1, 71)]
    snap = miners.sanitize_snapshot({"devices": inputs, "errors": ["x" * 300] * 70})
    assert len(snap["devices"]) == len(snap["errors"]) == 64
    assert len(snap["errors"][0]) == 200
    device = snap["devices"][0]
    assert not {"ssid", "macAddr", "coinbaseOutputs"} & device.keys()
    assert all(
        device[key] is None
        for key in (
            "watts",
            "hashrate_ghs",
            "hashrate_avg_ghs",
            "best_session_diff",
            "vr_temp_c",
            "firmware",
        )
    )
    assert device["pool_url"] == "stratum+tcp://pool.example:4444"
    assert len(device["model"]) == 64
    assert len(device["pool_user"]) == 128
    assert device["uptime_s"] == 0
    assert len(miners.sanitize_snapshot({"devices": [raw, raw]})["devices"]) == 1


def test_bad_rows_are_dropped_and_failed_reads_cannot_claim_figures():
    assert miners.sanitize_snapshot(None) is None
    assert miners.sanitize_row(sample(read_at="yesterday")) is None
    assert miners.sanitize_row(sample(protocol="cgminer")) is None
    assert miners.sanitize_row(sample(target="axeos://8.8.8.8")) is None
    assert miners.sanitize_row(sample(ok="false")) is None
    failure = miners.sanitize_row(sample(ok=False, error="timed out", watts=10, pool_user="fixture"))
    assert (failure["ok"], failure["error"], failure["watts"], failure["temp_c"], failure["pool_user"]) == (
        False,
        "timed out",
        None,
        None,
        None,
    )
    assert miners.sanitize_row(sample(temp_c=None))["error"] == "no figures"
    assert miners.sanitize_row(sample(watts=0))["watts"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status, body, expected",
    [
        (401, b"", r"refused \(401\)"),
        (302, b"", "HTTP 302"),
        (200, b"x" * 65, "too large"),
        (200, b"not-json", "not JSON"),
        (200, b"[]", "not JSON"),
    ],
)
async def test_axeos_read_never_redirects_or_reads_oversized_bodies(monkeypatch, status, body, expected):
    async_client = httpx.AsyncClient
    requests = []

    def reply(request):
        requests.append(str(request.url))
        return httpx.Response(status, headers={"location": "http://elsewhere.invalid/"}, stream=httpx.ByteStream(body))

    def client(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        return async_client(transport=httpx.MockTransport(reply), **kwargs)

    monkeypatch.setattr(miners, "MAX_BYTES", 64)
    monkeypatch.setattr(miners.httpx, "AsyncClient", client)
    with pytest.raises(ValueError, match=expected):
        await miners._axeos_get("192.168.1.50", 80)
    assert requests == ["http://192.168.1.50/api/system/info"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reply, error",
    [
        (b'{"SUMMARY":[{"GHS 5s":110566.89}]}\0', None),
        (b"x" * 65, "too large"),
    ],
)
async def test_cgminer_only_sends_the_requested_command_and_handles_nul(monkeypatch, reply, error):
    commands = []

    async def handler(reader, writer):
        commands.append(await reader.readuntil(b"}"))
        writer.write(reply)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    monkeypatch.setattr(miners, "MAX_BYTES", 64)
    async with await asyncio.start_server(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        if error:
            with pytest.raises(ValueError, match=error):
                await miners._cgminer_exchange("127.0.0.1", port, "summary")
        else:
            result = await miners._cgminer_exchange("127.0.0.1", port, "summary")
            assert result["SUMMARY"][0]["GHS 5s"] == 110566.89
    assert commands == [b'{"command":"summary"}']


@pytest.mark.asyncio
async def test_optional_pools_timeout_keeps_cgminer_summary(monkeypatch):
    target = miners.parse_targets("cgminer://10.0.0.8")[0][0]
    exchange = AsyncMock(side_effect=[{"SUMMARY": [{"GHS 5s": 110566.89}]}, TimeoutError()])
    monkeypatch.setattr(miners, "_resolve", AsyncMock(return_value=["10.0.0.8"]))
    monkeypatch.setattr(miners, "_cgminer_exchange", exchange)
    device = (await miners.read_all([target]))["devices"][0]
    assert device["hashrate_ghs"] == 110566.89
    assert device["pool_url"] is None
    assert [call.args[-1] for call in exchange.await_args_list] == ["summary", "pools"]


def test_loopback_mapped_ipv6_is_rejected():
    assert not miners._allowed(ip_address("::ffff:127.0.0.1"))
