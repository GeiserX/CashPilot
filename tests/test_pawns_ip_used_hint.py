"""A Pawns copy that Pawns refuses for its IP says so on the dashboard.

Seen live in Nov 2026 on two boxes for hours: the container was Up, but Pawns
saw another live device on the same IP and never let it share. pawns-cli
logged ``ip_used`` every 1 to 10 minutes, and the dashboard still showed the
copy as running with nothing wrong. The lines below are the ones it logged.
The catalog's windowed signal turns them into a "Needs fixing" hint; the copy
stays ``running`` and is not called account_disabled.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest
from fastapi.testclient import TestClient

from app import catalog, main, orchestrator, producer_state


def _event(at: str, name: str, parameters: str = "{}") -> str:
    return f'{{"happened_at":"{at}","name":"{name}","parameters":{parameters}}}'


STARTING = _event("2026-11-27T17:08:09Z", "starting")
BALANCE = _event("2026-11-27T17:08:10Z", "balance_ready", '{"balance":"7.614 USD","traffic":"38.0747 GB"}')
IP_USED = _event(
    "2026-11-27T17:09:23Z",
    "not_running",
    '{"error":"ip_used","message":"getting free port failed (ip has alive peer)"}',
)
SHARING = _event("2026-11-27T19:30:00Z", "running")

BLOCKED = "\n".join([STARTING, BALANCE, *[IP_USED] * 24])

WORKER = {"id": 7, "name": "nas", "status": "online", "url": "http://192.168.50.100:8081"}
RUNNING = {"slug": "iproyal", "status": "running", "instance": 1, "_worker_id": 7}


def _signal() -> dict:
    signals = producer_state.signals_for(catalog.get_service("iproyal"))
    [found] = [s for s in signals if producer_state.is_windowed(s)]
    return found


def _sweep(logs: str) -> list[str]:
    """One run of the scheduled windowed-signal sweep, with the worker answering ``logs``."""

    async def _proxy(wid, method, path, params=None, **kw):
        assert path == "/api/containers/iproyal/logs"
        # What the worker does: keep only the lines the filter matches.
        rx = re.compile(params["match"])
        return {"logs": "\n".join(line for line in logs.splitlines() if rx.search(line)), "filtered": True}

    with (
        patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[]),
        patch("app.main._get_all_worker_containers", new_callable=AsyncMock, return_value=[RUNNING]),
        patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=WORKER),
        patch("app.main.database.get_deployment_spec", new_callable=AsyncMock, return_value=None),
        patch("app.main._proxy_to_worker", side_effect=_proxy),
    ):
        asyncio.run(main._check_windowed_signals())
    return main._windowed_hints.get(("iproyal", 7, 1), [])


def _deployed_row() -> dict:
    worker = {
        **WORKER,
        "system_info": json.dumps({"docker_available": True}),
        "containers": json.dumps([{"slug": "iproyal", "name": "cashpilot-iproyal", "status": "running"}]),
        "apps": "[]",
    }

    @asynccontextmanager
    async def _noop_lifespan(app):
        yield

    with (
        patch.object(main.app.router, "lifespan_context", _noop_lifespan),
        patch("app.main.auth.get_current_user", return_value={"uid": 1, "u": "owner", "r": "owner"}),
        patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
        patch("app.main.database.get_earnings_summary", new_callable=AsyncMock, return_value=[]),
        patch("app.main.database.get_health_scores", new_callable=AsyncMock, return_value=[]),
        patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[]),
        patch("app.main.database.get_custom_images", new_callable=AsyncMock, return_value={}),
        TestClient(main.app, raise_server_exceptions=False) as client,
    ):
        resp = client.get("/api/services/deployed")
    assert resp.status_code == 200, resp.text
    return next(r for r in resp.json() if r["slug"] == "iproyal")


@pytest.fixture(autouse=True)
def _clean_state():
    main._windowed_hints = {}
    main._signal_hints = {}
    main._account_disabled.pop("iproyal", None)
    yield
    main._windowed_hints = {}
    main._signal_hints = {}


def test_a_blocked_copy_shows_as_running_with_a_hint_on_the_dashboard():
    hints = _sweep(BLOCKED)
    assert len(hints) == 1
    assert "another live device on this IP address" in hints[0]
    assert "Stop any other Pawns app on this IP" in hints[0]
    assert "ask Pawns support to release it" in hints[0]
    row = _deployed_row()
    assert row["container_status"] == "running"
    assert row["account_disabled"] is False
    assert row["instance_details"][0]["hints"] == hints
    print(
        json.dumps(
            {k: row[k] for k in ("slug", "container_status", "account_disabled")}
            | {"hints": row["instance_details"][0]["hints"]},
            indent=2,
        )
    )


def test_the_hint_clears_once_the_copy_starts_sharing():
    assert _sweep(BLOCKED)
    assert _sweep("\n".join([BLOCKED, SHARING])) == []
    assert _deployed_row()["instance_details"][0]["hints"] == []


def test_the_hint_clears_when_the_window_holds_no_refusal():
    assert _sweep(BLOCKED)
    assert _sweep("\n".join([STARTING, BALANCE, SHARING, BALANCE])) == []
    assert _sweep("") == []


def test_a_few_refusals_while_it_starts_are_not_yet_a_hint():
    assert _sweep("\n".join([STARTING, BALANCE, *[IP_USED] * 4])) == []


def test_not_running_is_not_read_as_running():
    """``"name":"not_running"`` must not satisfy the ``unless`` that cancels the hint."""
    unless = re.compile(_signal()["unless"], re.IGNORECASE)
    assert unless.search(SHARING)
    assert not unless.search(IP_USED)


def test_the_disabled_account_path_is_unchanged():
    signals = producer_state.signals_for(catalog.get_service("iproyal"))
    # The refusal never reads as a disabled account, on the tail or on a stopped copy.
    assert orchestrator.match_fatal(BLOCKED, signals) is None
    assert producer_state.match_log_signals(BLOCKED, signals) == []
    # And "user is disabled" still does.
    assert orchestrator.match_fatal("user is disabled" * 40, signals) == "account_disabled"


def test_the_catalog_entry_validates():
    svc = catalog.get_service("iproyal")
    assert catalog._validate(svc, __import__("pathlib").Path("iproyal.yml")) == []
