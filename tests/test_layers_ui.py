"""The Fleet page's security layers: what each earner got, and the owner's runtime choice.

The worker reports its runtimes, KVM and env pins (system_info.layers) and each
container's runtime and network. The UI shows per earner whether it is fenced
and which runtime it runs under, locks a choice with the reason (the catalog,
an env pin, a worker that cannot take it), stores the choice per worker, and
sends it with the deploy. An older worker reads as unknown, never as absent.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import database, layer_scripts, layers_ui, main
from app.routers import layers as layers_router

GVISOR_RUNTIMES = [
    {"name": "runc", "gvisor": False, "hostnet": False, "net_raw": False},
    {"name": "runsc-hostnet", "gvisor": True, "hostnet": True, "net_raw": False},
    {"name": "runsc-hostnet-raw", "gvisor": True, "hostnet": True, "net_raw": True},
]


def _worker(
    layers=None, containers=(), features=("runtime_choice", "gvisor_check"), os="Linux 6.8.0", iso=None, **info
):
    system_info = {
        "os": os,
        "features": list(features),
        "isolation": iso or {"mode": "on", "network": "cashpilot-isolated", "fence": {"state": "ok"}},
        **info,
    }
    if layers is not None:
        system_info["layers"] = layers
    return {
        "id": 7,
        "client_id": "c7",
        "name": "box",
        "system_info": json.dumps(system_info),
        "containers": json.dumps(list(containers)),
    }


def _layers(runtimes=GVISOR_RUNTIMES, pins=None, **extra):
    return {
        "runtimes": runtimes,
        "default_runtime": "runc",
        "kvm": True,
        "pins": pins or {"default": None, "overrides": {}},
        "proxy_runtimes": ["runc", "runsc", "runsc-hostnet", "runsc-hostnet-raw"],
        "gvisor_check": None,
        **extra,
    }


NONE = {"default": None, "earners": {}}


class TestTheView:
    def test_each_earner_shows_its_fence_and_runtime(self):
        w = _worker(
            _layers(),
            [
                {"slug": "honeygain", "status": "running", "runtime": "runsc-hostnet", "network": "cashpilot-isolated"},
                {"slug": "earnapp", "status": "running", "runtime": "runc", "network": "bridge"},
            ],
        )
        view = layers_ui.worker_view(w, NONE)
        by = {e["slug"]: e for e in view["earners"]}
        assert by["honeygain"]["runtime"] == "gvisor" and by["honeygain"]["fence"] is True
        assert by["earnapp"]["runtime"] == "runc" and by["earnapp"]["fence"] is False
        assert view["gvisor"]["state"] == "installed"
        assert view["kvm"] is True

    def test_an_older_worker_is_unknown_not_absent(self):
        w = _worker(None, [{"slug": "honeygain", "status": "running"}], features=())
        view = layers_ui.worker_view(w, NONE)
        assert view["known"] is False
        assert view["gvisor"]["state"] == "unknown"
        assert view["kvm"] is None
        earner = view["earners"][0]
        assert earner["runtime"] is None and earner["fence"] is None
        assert "older" in earner["locked"]

    def test_a_runc_binary_under_a_gvisor_name_shows_runc(self):
        fake = [{"name": "runsc-hostnet", "gvisor": False, "hostnet": False, "net_raw": False}]
        w = _worker(_layers(fake), [{"slug": "honeygain", "runtime": "runsc-hostnet", "network": "cashpilot-isolated"}])
        view = layers_ui.worker_view(w, NONE)
        assert view["earners"][0]["runtime"] == "runc"
        assert view["gvisor"]["state"] == "missing"

    def test_isolation_off_is_not_fenced(self):
        iso = {"mode": "off", "fence": {"state": "reduced"}}
        w = _worker(_layers(), [{"slug": "honeygain", "runtime": "runc", "network": "cashpilot-isolated"}], iso=iso)
        assert layers_ui.worker_view(w, NONE)["earners"][0]["fence"] is False

    def test_unraid_says_why_and_offers_no_install(self):
        w = _worker(_layers([]), os="Linux 6.12.24-Unraid")
        state = layers_ui.worker_view(w, NONE)["gvisor"]
        assert state["state"] == "unsupported"
        assert "VM" in state["why"]


class TestLocks:
    def test_mysterium_is_locked_with_its_catalog_reason(self):
        w = _worker(_layers(), [{"slug": "mysterium", "runtime": "runc", "network": "cashpilot-isolated"}])
        why = layers_ui.worker_view(w, NONE)["earners"][0]["locked"]
        assert "kernel WireGuard" in why

    def test_an_env_override_locks_and_names_the_variable(self):
        pins = {"default": None, "overrides": {"honeygain": "runsc-hostnet"}}
        w = _worker(
            _layers(pins=pins), [{"slug": "honeygain", "runtime": "runsc-hostnet", "network": "cashpilot-isolated"}]
        )
        why = layers_ui.worker_view(w, NONE)["earners"][0]["locked"]
        assert "CASHPILOT_CONTAINER_RUNTIME_OVERRIDES" in why and "honeygain=runsc-hostnet" in why

    def test_an_env_override_does_not_lock_a_host_networked_earner(self):
        # The worker applies the variables to bridge networking only.
        pins = {"default": "runsc-hostnet", "overrides": {"hostie": "runc"}}
        w = _worker(_layers(pins=pins), [{"slug": "hostie", "runtime": "runc", "network": "host"}])
        svc = {"name": "Hostie", "docker": {"network_mode": "host"}}
        with patch.object(layers_ui.catalog, "get_service", return_value=svc):
            assert layers_ui.worker_view(w, NONE)["earners"][0]["locked"] is None

    def test_the_env_default_locks_the_worker_default(self):
        pins = {"default": "runsc-hostnet", "overrides": {}}
        view = layers_ui.worker_view(_worker(_layers(pins=pins)), NONE)
        assert "CASHPILOT_CONTAINER_RUNTIME" in view["default_locked"]

    def test_gvisor_without_the_runtime_asks_to_install(self):
        w = _worker(
            _layers(GVISOR_RUNTIMES[:1]), [{"slug": "honeygain", "runtime": "runc", "network": "cashpilot-isolated"}]
        )
        why = layers_ui.worker_view(w, NONE)["earners"][0]["locked"]
        assert "Install gVisor" in why

    def test_back_to_runc_is_never_locked_by_a_missing_gvisor(self):
        info = json.loads(_worker(_layers(GVISOR_RUNTIMES[:1]))["system_info"])
        assert layers_ui.locked("honeygain", info, "runc") is None


def _run(coro):
    return asyncio.run(coro)


class TestStorage:
    def _store(self):
        store: dict[str, str] = {}

        async def get(key=None):
            return store.get(key)

        async def put(key, value):
            store[key] = value

        return (
            store,
            patch.object(database, "get_config", side_effect=get),
            patch.object(database, "set_config", side_effect=put),
        )

    def test_the_default_applies_to_new_earners_only(self):
        store, g, s = self._store()
        w = _worker(_layers(), [{"slug": "earnapp", "runtime": "runc", "network": "cashpilot-isolated"}])
        with g, s:
            _run(layers_ui.set_default(w, "gvisor"))
            # Already here: keeps what it runs under, on every redeploy.
            assert _run(layers_ui.for_new_deploy(w, "earnapp")) == "runc"
            # New: takes the default, and keeps it after.
            assert _run(layers_ui.for_new_deploy(w, "honeygain")) == "gvisor"
            assert json.loads(store["worker_c7_runtime_choice"])["earners"]["honeygain"] == "gvisor"

    def test_a_default_that_does_not_fit_leaves_dockers_default(self):
        _store, g, s = self._store()
        w = _worker(_layers())
        with g, s:
            _run(layers_ui.set_default(w, "gvisor"))
            assert _run(layers_ui.for_new_deploy(w, "mysterium")) is None

    def test_no_choice_sends_nothing(self):
        _store, g, s = self._store()
        with g, s:
            assert _run(layers_ui.for_new_deploy(_worker(_layers()), "honeygain")) is None


class TestTheRoutes:
    def _client(self, worker):
        return (
            patch.object(database, "list_workers", AsyncMock(return_value=[worker])),
            patch.object(database, "get_config", AsyncMock(return_value=None)),
            patch.object(database, "set_config", AsyncMock()),
            patch.object(layers_router.deps, "_require_owner", return_value={"r": "owner"}),
            patch.object(layers_router.deps, "_require_reader", return_value={"r": "owner"}),
        )

    def test_a_locked_choice_is_a_409_with_the_reason(self):
        w = _worker(_layers(), [{"slug": "mysterium", "runtime": "runc", "network": "cashpilot-isolated"}])
        patches = self._client(w)
        with patches[0], patches[1], patches[2] as put, patches[3], patches[4]:
            resp = TestClient(main.app).post(
                "/api/workers/7/runtime-choice", json={"slug": "mysterium", "choice": "gvisor"}
            )
        assert resp.status_code == 409, resp.text
        assert "WireGuard" in resp.json()["detail"]
        put.assert_not_called()

    def test_a_choice_is_saved(self):
        w = _worker(_layers(), [{"slug": "honeygain", "runtime": "runc", "network": "cashpilot-isolated"}])
        patches = self._client(w)
        with patches[0], patches[1], patches[2] as put, patches[3], patches[4]:
            resp = TestClient(main.app).post(
                "/api/workers/7/runtime-choice", json={"slug": "honeygain", "choice": "gvisor"}
            )
        assert resp.status_code == 200, resp.text
        assert json.loads(put.call_args.args[1])["earners"] == {"honeygain": "gvisor"}

    def test_an_unknown_choice_is_a_400(self):
        patches = self._client(_worker(_layers()))
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            resp = TestClient(main.app).post("/api/workers/7/runtime-choice", json={"choice": "kata"})
        assert resp.status_code == 400

    def test_the_view_lists_each_worker(self):
        patches = self._client(_worker(_layers()))
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            resp = TestClient(main.app).get("/api/layers")
        assert resp.status_code == 200
        assert resp.json()["workers"]["7"]["gvisor"]["state"] == "installed"

    def test_choosing_needs_the_owner(self):
        with patch.object(
            layers_router.deps, "_require_owner", side_effect=HTTPException(status_code=403, detail="Owner only")
        ):
            resp = TestClient(main.app).post("/api/workers/7/runtime-choice", json={"choice": "runc"})
        assert resp.status_code == 403


@pytest.mark.real_runtime_choice
class TestTheDeploySendsTheChoice:
    def test_a_stored_choice_rides_the_deploy(self):
        w = _worker(_layers())
        with (
            patch.object(database, "get_worker", AsyncMock(return_value=w)),
            patch.object(layers_ui, "for_new_deploy", AsyncMock(return_value="gvisor")),
        ):
            assert _run(main._runtime_choice_for(7, "honeygain")) == "gvisor"

    def test_an_old_worker_with_a_stored_choice_is_refused(self):
        w = _worker(_layers(), features=())
        with (
            patch.object(database, "get_worker", AsyncMock(return_value=w)),
            patch.object(layers_ui, "for_new_deploy", AsyncMock(return_value="gvisor")),
            pytest.raises(HTTPException) as err,
        ):
            _run(main._runtime_choice_for(7, "honeygain"))
        assert err.value.status_code == 409
        assert "Nothing was deployed" in err.value.detail

    def test_the_choice_reaches_the_worker_in_the_deploy_body(self):
        sent = {}

        async def hop(worker_id, method, path, *, json=None, **kwargs):
            sent.update(json or {})
            return {"container_id": "abc123"}

        with (
            patch.object(main, "_runtime_choice_for", AsyncMock(return_value="gvisor")),
            patch.object(main, "_proxy_to_worker", side_effect=hop),
        ):
            _run(main._send_worker_deploy(7, "honeygain", {"image": "honeygain/honeygain"}))
        assert sent["runtime_choice"] == "gvisor"

    def test_a_proxied_copy_sends_no_choice(self):
        choice = AsyncMock(return_value="gvisor")
        with (
            patch.object(main, "_runtime_choice_for", choice),
            patch.object(main, "_proxy_worker_call", AsyncMock(return_value={"container_id": "abc123"})) as call,
        ):
            _run(main._send_worker_deploy(7, "honeygain", {"image": "honeygain/honeygain"}, proxy_id=3))
        choice.assert_not_called()
        assert "runtime_choice" not in call.call_args.kwargs["json"]

    def test_desktop_gets_none(self):
        w = _worker(_layers(), device_type="desktop")
        with patch.object(database, "get_worker", AsyncMock(return_value=w)):
            assert _run(main._runtime_choice_for(7, "honeygain")) is None


class TestTheCommand:
    def test_it_is_pinned_to_the_tag_and_the_shipped_files_sha256(self):
        with patch.object(layer_scripts.version, "current", return_value="3.1.0"):
            cmd = layer_scripts.command("cashpilot-gvisor", "install")
        assert "/GeiserX/CashPilot/v3.1.0/scripts/cashpilot-gvisor" in cmd
        assert layer_scripts.sha256("cashpilot-gvisor") in cmd
        assert "sha256sum -c -" in cmd and cmd.endswith('sudo bash "$d/cashpilot-gvisor" install')

    def test_the_sha256_check_runs_before_sudo(self):
        with patch.object(layer_scripts.version, "current", return_value="3.1.0"):
            cmd = layer_scripts.command("cashpilot-gvisor", "undo")
        assert cmd.index("sha256sum -c") < cmd.index("sudo")
        assert " && " in cmd  # a failed check stops the line

    def test_arguments_are_quoted(self):
        with patch.object(layer_scripts.version, "current", return_value="3.1.0"):
            cmd = layer_scripts.command("cashpilot-gvisor", "install", ["--ui", "http://x; rm -rf /"])
        assert "'http://x; rm -rf /'" in cmd

    def test_a_dev_build_says_why_there_is_none(self):
        with patch.object(layer_scripts.version, "current", return_value="dev"):
            out = layers_ui.commands()
        assert "development build" in out["error"]


class TestTheDashboardRow:
    def test_each_copy_carries_the_layers_it_got(self):
        w = _worker(
            _layers(),
            [
                {"slug": "honeygain", "runtime": "runsc-hostnet", "network": "cashpilot-isolated"},
                {"slug": "earnapp", "runtime": "runc", "network": "bridge"},
                {"slug": "repocket"},
            ],
        )
        w["status"] = "online"
        rows = {r["slug"]: r["_layers"] for r in _run(main._get_all_worker_containers([w]))}
        assert rows["honeygain"] == {"fence": True, "runtime": "gvisor"}
        assert rows["earnapp"] == {"fence": False, "runtime": "runc"}
        # An older worker reports neither: unknown, never "not fenced".
        assert rows["repocket"] == {"fence": None, "runtime": None}
