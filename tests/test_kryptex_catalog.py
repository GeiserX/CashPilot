from __future__ import annotations

import json
import shlex
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import HTTPException

from app import catalog, exchange_rates, main, orchestrator, preflight
from tests import test_power

SLUG = "kryptex-pearl"
EMAIL = "miner+rig@example.com"
GPU = {"vendor": "nvidia", "count": 1, "rocm": False}


@pytest.fixture
def service():
    entry = catalog.get_service(SLUG)
    assert entry is not None
    return entry


def test_kryptex_uses_the_referral_and_keeps_payouts_on_account(service):
    signup = urlsplit(service["referral"]["signup_url"])
    assert (signup.scheme, signup.netloc) == ("https", "pool.kryptex.com")
    assert parse_qs(signup.query)["ref"] == [service["referral"]["code"]] == ["2444cca8"]
    assert service["mining"]["dev_fee_percent"] == 0
    assert service["payment"]["currency"] == "PRL"
    assert exchange_rates.CRYPTO_IDS["PRL"] == "pearl-2"
    assert service["payment"]["crypto_token"] == "BTC"
    assert service["payout"]["model"] == "internal"
    assert service["collector"]["type"] == "manual"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("env", "error"),
    [
        ({}, "Missing required fields: Kryptex account email, Worker name"),
        ({"KRYPTEX_EMAIL": "miner@example.com/rig", "WORKER_NAME": "rig"}, "Invalid value for: Kryptex account email"),
        ({"KRYPTEX_EMAIL": EMAIL, "WORKER_NAME": "rig --url elsewhere"}, "Invalid value for: Worker name"),
        ({"KRYPTEX_EMAIL": EMAIL, "WORKER_NAME": "rig-2"}, None),
    ],
)
async def test_kryptex_deploy_uses_tls_and_one_account_username(monkeypatch, service, env, error):
    class ReachedWorker(Exception):
        """Stop once the UI hands the request to the worker client."""

    worker = {"system_info": json.dumps({"gpu_grants": {SLUG: GPU}})}
    send = AsyncMock(side_effect=ReachedWorker)
    monkeypatch.setattr(main, "_resolve_worker_id", AsyncMock(return_value=1))
    monkeypatch.setattr(main.database, "get_worker", AsyncMock(return_value=worker))
    monkeypatch.setattr(main.database, "get_deployment_spec", AsyncMock(return_value=None))
    monkeypatch.setattr(main, "_reserve_pending_identities", AsyncMock(return_value=[]))
    monkeypatch.setattr(main, "_proxy_worker_deploy", send)

    if error:
        with pytest.raises(HTTPException) as exc:
            await main._deploy(SLUG, main.DeployRequest(env=env), 1)
        assert exc.value.status_code == 400
        assert exc.value.detail == error
        send.assert_not_called()
        return

    with pytest.raises(ReachedWorker):
        await main._deploy(SLUG, main.DeployRequest(env=env), 1)
    worker_id, slug, spec = send.await_args.args
    assert (worker_id, slug) == (1, SLUG)
    assert orchestrator.gpu_grant_for_deploy(SLUG, spec["image"], 1) == GPU
    assert spec["image"] == service["docker"]["image"]
    assert shlex.split(spec["command"]) == [
        "--url",
        "stratum+ssl://prl.kryptex.network:8048",
        "--user",
        f"{EMAIL}/rig-2",
        "--no-rocm",
    ]


def test_kryptex_deploy_card_says_the_balance_stays_on_the_account(service):
    import asyncio
    from unittest.mock import MagicMock, patch

    with patch.object(main, "_require_auth_api", lambda r: None):
        risk = asyncio.run(main.api_deploy_risk(MagicMock(), SLUG))
        xmrig = asyncio.run(main.api_deploy_risk(MagicMock(), "xmrig"))
    assert risk["mining"]["dev_fee_percent"] == 0
    assert risk["mining"]["payout_model"] == "internal"
    assert xmrig["mining"]["payout_model"] == "external"
    assert "payout_model" not in service["mining"]


def test_a_second_kryptex_copy_shares_the_gpu(service):
    result = preflight.assess(service, already_deployed_slugs={SLUG})
    messages = [f["message"] for f in result["findings"]]
    assert any("shares its GPU" in message for message in messages)
    assert not any("shares its CPU" in message for message in messages)


@pytest.mark.parametrize("cpu", [{}, {"cpu_percent": 3.0}])
def test_a_gpu_miner_with_entered_watts_has_a_known_cost(cpu):
    out = test_power.TestNetEndpoint()._call(
        {"power_price_per_kwh": "0.20", "power_currency": "USD", f"power_device_{SLUG}_watts": "200"},
        {},
        [{"slug": SLUG, "status": "running", **cpu}],
    )
    (row,) = out["services"]
    assert (row["platform"], row["watts"], row["watts_source"]) == (SLUG, 200.0, "entered")
    assert row["cost"] == pytest.approx(28.8)
    assert out["cost_known"] is True
    assert "cost_unavailable_reason" not in out
