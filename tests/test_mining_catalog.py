from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path

import pytest

from app import catalog, orchestrator, preflight

XMRIG = Path("xmrig.yml")
WALLET = "4" + "A" * 94


@pytest.fixture
def xmrig():
    service = catalog.get_service("xmrig")
    assert service is not None
    return deepcopy(service)


def test_mining_pool_entries_do_not_require_a_miner_fee():
    for slug in ("ocean", "supportxmr"):
        service = catalog.get_service(slug)
        assert service is not None
        assert catalog.mining_facts(service) is None


@pytest.mark.parametrize("fee", [None, True, "1", -1, 11, float("nan"), float("inf")])
def test_invalid_or_missing_miner_developer_fee(xmrig, fee):
    if fee is None:
        del xmrig["mining"]["dev_fee_percent"]
    else:
        xmrig["mining"]["dev_fee_percent"] = fee
    assert any("mining.dev_fee_percent" in error for error in catalog._validate(xmrig, XMRIG))


def test_zero_is_a_valid_fee_when_stated(xmrig):
    xmrig["mining"]["dev_fee_percent"] = 0
    assert catalog._validate(xmrig, XMRIG) == []


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("hardware", "cpu", "unknown mining fields"),
        ("dev_fee_source", "http://example.com", "mining.dev_fee_source"),
        ("dev_fee_source", "https://[", "mining.dev_fee_source"),
        ("pool_fee_note", 0, "mining.pool_fee_note"),
    ],
)
def test_invalid_miner_facts_fail_validation(xmrig, field, value, error):
    xmrig["mining"][field] = value
    assert any(error in issue for issue in catalog._validate(xmrig, XMRIG))


def test_miner_requires_fee_hosting_note_and_pinned_images(xmrig):
    without_fee = deepcopy(xmrig)
    del without_fee["mining"]
    assert any("mining must be a mapping" in error for error in catalog._validate(without_fee, XMRIG))

    del xmrig["requirements"]["hosting_note"]
    xmrig["docker"]["image_by_arch"] = {"arm64": "example/miner:1.2.3"}
    errors = catalog._validate(xmrig, XMRIG)
    assert any("hosting_note" in error for error in errors)
    assert any("must pin each image" in error for error in errors)


def test_xmrig_uses_the_published_image_pin(xmrig):
    # A bump PR advances the build pin before main can publish its image.
    # The catalog keeps pulling its published digest until that update.
    image = re.fullmatch(
        r"drumsergio/cashpilot-xmrig:(\d+\.\d+\.\d+)-r[1-9]\d*@sha256:[0-9a-f]{64}",
        xmrig["docker"]["image"],
    )
    assert image is not None
    assert xmrig["mining"]["dev_fee_source"].endswith(f"/v{image[1]}/src/donate.h")
    assert xmrig["payout"]["address_env"] == "WALLET"
    assert "accrual" not in xmrig["collector"]


def test_xmrig_command_sets_the_fee_and_does_not_allow_wallet_flags(xmrig):
    docker = xmrig["docker"]
    wallet_pattern = next(field["pattern"] for field in docker["env"] if field["key"] == "WALLET")
    assert re.fullmatch(wallet_pattern, WALLET)
    injected = f"{WALLET} --donate-level=9"
    assert not re.fullmatch(wallet_pattern, injected)
    args = orchestrator._catalog_command_tokens(docker["command"], {"WALLET": injected})
    assert "--donate-level=9" not in args
    assert "--donate-level=1" in args
    assert "--randomx-wrmsr=-1" in args
    assert "--randomx-no-numa" in args
    assert "--http-host=127.0.0.1" in args
    assert "--http-port=18088" in args


@pytest.mark.parametrize("network_type", ["hosting", "residential", None])
def test_hosting_note_is_advice_for_a_reported_hosting_exit(xmrig, network_type):
    result = preflight.assess(xmrig, system_info={"egress_network_type": network_type})
    note = {
        "verdict": preflight.CHECK_YOURSELF,
        "message": xmrig["requirements"]["hosting_note"],
        "kind": "hosting_note",
    }
    assert (note in result["findings"]) is (network_type == "hosting")
    assert result["blocking"] is False


def test_a_second_miner_on_the_same_worker_shares_cpu(xmrig):
    result = preflight.assess(xmrig, already_deployed_slugs={"xmrig"})
    messages = [f["message"] for f in result["findings"]]
    assert any("shares its CPU" in message for message in messages)
    assert not any("shares the same connection" in message for message in messages)


@pytest.fixture
def unmineable():
    service = catalog.get_service("unmineable")
    assert service is not None
    return deepcopy(service)


def _user_token(service, env):
    args = orchestrator._catalog_command_tokens(service["docker"]["command"], env)
    [user] = [arg for arg in args if arg.startswith("--user=")]
    return args, user


def test_every_unmineable_worker_carries_the_referral_code(unmineable):
    code = unmineable["referral"]["code"]
    assert code == "awk6-j1z0"
    assert unmineable["referral"]["program"] is True
    assert code in unmineable["referral"]["signup_url"]
    args, user = _user_token(unmineable, {"PAYOUT_COIN": "SHIB", "WALLET": "0x" + "ab" * 20, "WORKER_NAME": "rig-1"})
    assert user == f"--user=SHIB:0x{'ab' * 20}.rig-1#{code}"
    assert "--url=stratum+ssl://rx.unmineable.com:443" in args
    assert "--algo=rx/0" in args
    assert "--donate-level=1" in args
    assert unmineable["docker"]["image"] == catalog.get_service("xmrig")["docker"]["image"]
    assert "#awk6-j1z0" in unmineable["mining"]["pool_fee_note"]
    guide = (Path(__file__).parents[1] / "docs/guides/unmineable.md").read_text()
    assert f"#{code}" in guide and "0.25%" in guide and "0.75%" in guide


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("WALLET", f"{WALLET}.other#someone-else"),
        ("WALLET", f"{WALLET}#someone-else"),
        ("WALLET", f"XMR:{WALLET}"),
        ("WALLET", f"{WALLET} --url=stratum+tcp://evil.example:3333"),
        ("WORKER_NAME", "rig#someone-else"),
        ("WORKER_NAME", "rig.two"),
        ("PAYOUT_COIN", "XMR:other"),
        ("PAYOUT_COIN", "X"),
    ],
)
def test_no_field_can_replace_or_drop_the_referral_code(unmineable, key, value):
    pattern = next(field["pattern"] for field in unmineable["docker"]["env"] if field["key"] == key)
    assert not re.fullmatch(pattern, value)


def test_unmineable_has_no_fixed_minimum_or_chain(unmineable):
    # One entry pays in many coins: the collector reports each coin's threshold.
    assert "min_amount" not in unmineable["cashout"]
    assert "chain" not in unmineable["payout"]
    assert "currency" not in unmineable["payment"]
    assert unmineable["payout"]["address_env"] == "WALLET"
    assert unmineable["collector"]["accrual"] == "pool"
