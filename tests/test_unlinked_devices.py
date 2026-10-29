"""A deployed device missing from the provider account is reported.

A node whose id is not on the user's account runs, looks healthy and earns for
nobody. Where the collector already holds the account credentials it asks the
provider for the account's devices, and the collection loop turns any deployed
id missing from that list into a notice on the service row and in the bell.
A lookup that fails must never claim a node is unlinked.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.collectors.base import EarningsResult
from app.collectors.earnapp import EarnAppCollector
from app.main import _unlinked_devices_warning

LINKED = "sdk-node-" + "a" * 32
UNLINKED = "sdk-node-" + "b" * 32


def _resp(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


def _collect(device_ids, devices_resp):
    client = AsyncMock()
    client.cookies = MagicMock()
    client.cookies.items.return_value = [("xsrf-token", "x")]
    client.get.side_effect = [_resp({}), _resp({"balance": 1.5}), devices_resp]
    with patch("app.collectors.earnapp.httpx.AsyncClient", return_value=client):
        c = EarnAppCollector(oauth_token="t")
        c.device_ids = set(device_ids)
        return asyncio.run(c.collect()), client


def test_a_deployed_uuid_missing_from_the_account_is_reported():
    result, client = _collect({LINKED, UNLINKED}, _resp([{"uuid": LINKED, "title": "box"}]))
    assert result.error is None and result.balance == 1.5
    assert result.unlinked_devices == [UNLINKED]
    assert client.get.call_args_list[2].args[0].endswith("/dashboard/api/devices")


def test_every_uuid_on_the_account_reports_nothing():
    result, _ = _collect({LINKED}, _resp([{"uuid": LINKED}]))
    assert result.unlinked_devices == []


def test_an_unreadable_device_list_claims_nothing():
    for bad in (_resp({"error": "nope"}), _resp([{"id": 1}]), _resp([], status_code=500)):
        if bad.status_code == 500:
            bad.raise_for_status.side_effect = RuntimeError("500")
        result, _ = _collect({LINKED}, bad)
        assert result.error is None and result.balance == 1.5
        assert result.unlinked_devices is None


def test_no_deployed_ids_means_no_extra_request():
    client = AsyncMock()
    client.cookies = MagicMock()
    client.cookies.items.return_value = []
    client.get.side_effect = [_resp({}), _resp({"balance": 1.5})]
    with patch("app.collectors.earnapp.httpx.AsyncClient", return_value=client):
        result = asyncio.run(EarnAppCollector(oauth_token="t").collect())
    assert result.unlinked_devices is None
    assert client.get.call_count == 2


def test_the_notice_names_the_device_and_its_link():
    text = _unlinked_devices_warning(EarningsResult(platform="earnapp", balance=1.0, unlinked_devices=[UNLINKED]))
    assert "not on your EarnApp account" in text
    assert f"https://earnapp.com/r/{UNLINKED}" in text
    assert _unlinked_devices_warning(EarningsResult(platform="earnapp", balance=1.0, unlinked_devices=[])) == ""


def test_the_collection_loop_hands_collectors_the_deployed_ids_and_raises_a_notice():
    from app import main

    collector = EarnAppCollector(oauth_token="t")
    collector.collect = AsyncMock(
        return_value=EarningsResult(platform="earnapp", balance=1.0, unlinked_devices=[UNLINKED])
    )
    with (
        patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[{"slug": "earnapp"}]),
        patch("app.main.database.get_config", new_callable=AsyncMock, return_value={}),
        patch("app.collectors.make_collectors", return_value=[collector]),
        patch("app.collectors._close_stale", new_callable=AsyncMock),
        patch("app.main.database.get_deployed_env_values", new_callable=AsyncMock, return_value={UNLINKED}) as lookup,
        patch("app.main.database.record_alert", new_callable=AsyncMock, return_value=None),
        patch("app.main.database.clear_alerts", new_callable=AsyncMock),
        patch("app.main.database.upsert_earnings", new_callable=AsyncMock),
        patch("app.main._detect_payout", new_callable=AsyncMock, return_value=None),
        patch("app.main._pending_payout_alerts", new_callable=AsyncMock, return_value=[]),
        patch("app.main._flatline_check", new_callable=AsyncMock, return_value=[]),
        patch("app.main._offline_worker_alerts", new_callable=AsyncMock, return_value=[]),
    ):
        asyncio.run(main._run_collection())
    lookup.assert_awaited_with("earnapp", "EARNAPP_UUID")
    assert collector.device_ids == {UNLINKED}
    notices = [a for a in main._collector_alerts if a.get("kind") == "notice" and a["platform"] == "earnapp"]
    assert notices and UNLINKED in notices[0]["error"]


# ProxyRack answers per device. Both bodies are what /api/device/status
# returned on 2026-10-29 for an unknown id and for one of our online devices.
PR_LINKED = "c" * 64
PR_UNLINKED = "d" * 64
PR_INVALID = {
    "status": "error",
    "error": "Invalid request parameters",
    "details": {"device_id": "The selected device id is invalid."},
}


def _pr_collect(device_ids, status_for):
    from app.collectors.proxyrack import ProxyRackCollector

    async def post(url, headers=None, json=None):
        if url.endswith("/balance"):
            return _resp({"data": {"balance": "$2.00"}})
        return status_for(json["device_id"])

    client = AsyncMock()
    client.is_closed = False
    client.post.side_effect = post
    with patch("app.collectors.proxyrack.httpx.AsyncClient", return_value=client):
        c = ProxyRackCollector(api_key="k")
        c.device_ids = set(device_ids)
        return asyncio.run(c.collect())


def test_a_proxyrack_device_the_account_refuses_is_reported():
    def status(device_id):
        if device_id == PR_LINKED:
            return _resp({"status": "success", "data": {"device_id": device_id, "status": "Online: 192.0.2.1"}})
        return _resp(PR_INVALID, status_code=400)

    result = _pr_collect({PR_LINKED, PR_UNLINKED}, status)
    assert result.error is None and result.balance == 2.0
    assert result.unlinked_devices == [PR_UNLINKED]


def test_a_proxyrack_lookup_that_fails_claims_nothing():
    def status(device_id):
        raise RuntimeError("timeout")

    result = _pr_collect({PR_UNLINKED}, status)
    assert result.error is None and result.balance == 2.0
    assert result.unlinked_devices is None


def test_a_rate_limited_proxyrack_check_is_unknown_not_unlinked_or_linked():
    limited = {"status": "error", "error": "Requests limit exceeded (5 per minute)."}

    def status(device_id):
        if device_id == PR_UNLINKED:
            return _resp(PR_INVALID, status_code=400)
        return _resp(limited, status_code=400)

    result = _pr_collect({PR_LINKED, PR_UNLINKED}, status)
    assert result.error is None and result.balance == 2.0
    assert result.unlinked_devices is None


def _run_loop(results_by_call, lookup=None, previous=None):
    """Run _run_collection with one EarnApp collector; return the alerts it leaves."""
    from app import main

    collector = EarnAppCollector(oauth_token="t")
    collector.collect = AsyncMock(return_value=results_by_call)
    with (
        patch("app.main._collector_alerts", list(previous or [])),
        patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[{"slug": "earnapp"}]),
        patch("app.main.database.get_config", new_callable=AsyncMock, return_value={}),
        patch("app.collectors.make_collectors", return_value=[collector]),
        patch("app.collectors._close_stale", new_callable=AsyncMock),
        patch(
            "app.main.database.get_deployed_env_values",
            new_callable=AsyncMock,
            **(lookup or {"return_value": {UNLINKED}}),
        ),
        patch("app.main.database.record_alert", new_callable=AsyncMock, return_value=None),
        patch("app.main.database.clear_alerts", new_callable=AsyncMock) as clear,
        patch("app.main.database.upsert_earnings", new_callable=AsyncMock) as upsert,
        patch("app.main._detect_payout", new_callable=AsyncMock, return_value=None),
        patch("app.main._pending_payout_alerts", new_callable=AsyncMock, return_value=[]),
        patch("app.main._flatline_check", new_callable=AsyncMock, return_value=[]),
        patch("app.main._offline_worker_alerts", new_callable=AsyncMock, return_value=[]),
    ):
        asyncio.run(main._run_collection())
        return list(main._collector_alerts), clear, upsert


def test_an_unfinished_device_check_keeps_the_notice_instead_of_clearing_it():
    notice = {"kind": "notice", "platform": "earnapp", "error": f"A deployed device is not on your account: {UNLINKED}"}
    alerts, clear, _ = _run_loop(EarningsResult(platform="earnapp", balance=1.0), previous=[notice])
    assert notice in alerts
    assert ("notice", "earnapp") not in [c.args for c in clear.await_args_list]


def test_a_finished_check_with_nothing_unlinked_clears_the_notice():
    notice = {"kind": "notice", "platform": "earnapp", "error": "old"}
    alerts, clear, _ = _run_loop(
        EarningsResult(platform="earnapp", balance=1.0, unlinked_devices=[]), previous=[notice]
    )
    assert notice not in alerts
    clear.assert_any_await("notice", "earnapp")


def test_a_failed_device_id_lookup_still_collects_the_balance():
    _, _, upsert = _run_loop(
        EarningsResult(platform="earnapp", balance=1.0), lookup={"side_effect": RuntimeError("db locked")}
    )
    upsert.assert_awaited()
