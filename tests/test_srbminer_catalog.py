from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path

import pytest

from app import catalog, gpu, orchestrator, preflight

ROOT = Path(__file__).resolve().parents[1]
ENTRY = Path("srbminer-multi.yml")
PEARL = "prl1p" + "q" * 58
ZANO = "Zx" + "A" * 95
RAVEN = "R" + "a" * 33


@pytest.fixture
def srb():
    service = catalog.get_service("srbminer-multi")
    assert service is not None
    return deepcopy(service)


def _pattern(service, key):
    return next(field["pattern"] for field in service["docker"]["env"] if field["key"] == key)


def _args(service, **env):
    values = {field["key"]: str(field.get("default", "")) for field in service["docker"]["env"]}
    values.update(env)
    return orchestrator._catalog_command_tokens(service["docker"]["command"], values)


def test_entry_is_a_beta_nvidia_miner_on_the_published_image(srb):
    assert catalog._validate(srb, ENTRY) == []
    assert srb["status"] == "beta"
    image = re.fullmatch(
        r"drumsergio/cashpilot-srbminer-multi:(\d+\.\d+\.\d+)-r[1-9]\d*@sha256:[0-9a-f]{64}",
        srb["docker"]["image"],
    )
    assert image is not None
    # The fee list we cite is the README of the release the image downloads.
    assert srb["mining"]["dev_fee_source"].endswith(f"/blob/{image[1]}/README.md")
    assert srb["docker"]["platforms"] == ["linux/amd64"]
    assert gpu.spec_of(srb) == {"vendor": "nvidia", "count": 1, "rocm": False}
    assert srb["requirements"]["gpu"] is True


def test_the_fee_stated_is_the_highest_algorithm_fee(srb):
    # SRBMiner-Multi 3.9.0 README: pearlhash 2.00%, progpow_zano and kawpow 0.85%.
    algorithms = _pattern(srb, "ALGO").split("|")
    assert sorted(algorithms) == ["kawpow", "pearlhash", "progpow_zano"]
    assert srb["mining"]["dev_fee_percent"] == 2
    note = srb["mining"]["pool_fee_note"]
    assert "2%" in note and "0.85%" in note
    assert "1 PRL" in note


def test_the_cache_volume_is_where_the_image_installs_the_miner(srb):
    entrypoint = (ROOT / "images/srbminer-multi/entrypoint.sh").read_text()
    cache = re.search(r"^cache=(\S+)$", entrypoint, re.M)
    assert cache is not None
    (volume,) = srb["docker"]["volumes"]
    assert volume.split(":", 1)[1] == cache[1]


def test_the_default_command_mines_pearl_on_herominers_over_tls(srb):
    args = _args(srb, WALLET=PEARL, WORKER_NAME="rig-01")
    assert args == [
        "--disable-cpu",
        "--algorithm",
        "pearlhash",
        "--pool",
        "pearl.herominers.com:1200",
        "--wallet",
        f"{PEARL}.rig-01",
        "--tls",
        "true",
        # Without a terminal the miner logs nothing unless told to.
        "--log-file",
        "/dev/stdout",
    ]


@pytest.mark.parametrize("address", [PEARL, ZANO, RAVEN])
def test_each_supported_coin_address_is_accepted(srb, address):
    assert re.fullmatch(_pattern(srb, "WALLET"), address)


@pytest.mark.parametrize(
    "address",
    [
        f"{PEARL} --algorithm kawpow",
        f"{PEARL}.other-rig",
        "--algorithm",
        "prl1PQQQQQQQQQ",
        "prl1qqqqqqqqqb",
        "0x" + "a" * 40,
        "",
    ],
)
def test_a_wallet_cannot_carry_flags_a_worker_or_a_bad_charset(srb, address):
    assert not re.fullmatch(_pattern(srb, "WALLET"), address)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("ALGO", "randomx"),
        ("ALGO", "pearlhash --tls false"),
        ("POOL_URL", "-o:1200"),
        ("POOL_URL", "pool.example:1200 --wallet x"),
        ("POOL_URL", "stratum+tcp://pool.example:1200"),
        ("POOL_TLS", "yes"),
        ("WORKER_NAME", "rig 01"),
    ],
)
def test_other_fields_refuse_values_that_change_the_command(srb, key, value):
    assert not re.fullmatch(_pattern(srb, key), value)


def test_a_second_copy_names_the_gpu_not_the_cpu(srb):
    result = preflight.assess(srb, already_deployed_slugs={"srbminer-multi"})
    messages = [finding["message"] for finding in result["findings"]]
    assert any("shares its GPU" in message for message in messages)
    assert not any("shares its CPU" in message for message in messages)


def test_hosting_note_shows_only_for_a_hosting_exit(srb):
    for network_type, shown in (("hosting", True), ("residential", False), (None, False)):
        result = preflight.assess(srb, system_info={"egress_network_type": network_type})
        kinds = [finding.get("kind") for finding in result["findings"]]
        assert ("hosting_note" in kinds) is shown
        assert result["blocking"] is False
