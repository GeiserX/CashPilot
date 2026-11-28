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
        "isolation": iso or {"mode": "on", "network": "cashpilot-isolated", "fence": {"state": "applied"}},
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

    @pytest.mark.parametrize(
        ("state", "fenced"), [("applied", True), ("reduced", False), ("failed", False), ("n/a", None)]
    )
    def test_fenced_only_once_the_filter_is_applied(self, state, fenced):
        iso = {"mode": "on", "network": "cashpilot-isolated", "fence": {"state": state}}
        w = _worker(_layers(), [{"slug": "honeygain", "runtime": "runc", "network": "cashpilot-isolated"}], iso=iso)
        assert layers_ui.worker_view(w, NONE)["earners"][0]["fence"] is fenced

    def test_isolation_off_is_not_fenced(self):
        iso = {"mode": "off", "fence": {"state": "reduced"}}
        w = _worker(_layers(), [{"slug": "honeygain", "runtime": "runc", "network": "cashpilot-isolated"}], iso=iso)
        assert layers_ui.worker_view(w, NONE)["earners"][0]["fence"] is False

    def test_a_worker_that_does_not_say_its_isolation_mode_is_unknown_not_off(self):
        w = _worker(
            _layers(), [{"slug": "honeygain", "runtime": "runc", "network": "cashpilot-isolated"}], iso={"x": 1}
        )
        assert layers_ui.worker_view(w, NONE)["earners"][0]["fence"] is None

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

    def test_the_catalog_reason_is_shown_in_the_owner_s_language(self, tmp_path, monkeypatch):
        from app import catalog, i18n

        english = catalog.get_service("mysterium")["docker"]["runtime_reason"]
        d = tmp_path / "_i18n"
        d.mkdir()
        (d / "es.yml").write_text(
            f'mysterium.docker.runtime_reason:\n  text: "gVisor no le da WireGuard."\n'
            f'  source: "{catalog.i18n_source_hash(english)}"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(catalog, "I18N_DIR", d)
        catalog._i18n_tables.clear()
        token = i18n._current.set("es")
        try:
            w = _worker(_layers(), [{"slug": "mysterium", "runtime": "runc", "network": "cashpilot-isolated"}])
            why = layers_ui.worker_view(w, NONE)["earners"][0]["locked"]
        finally:
            i18n._current.reset(token)
            catalog._i18n_tables.clear()
        assert "gVisor no le da WireGuard." in why and "kernel WireGuard" not in why

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
        assert "CASHPILOT_CONTAINER_RUNTIME" in view["default_locks"]["gvisor"]
        # A stored gVisor default under that pin: runc is locked too, as the POST refuses it.
        view = layers_ui.worker_view(_worker(_layers(pins=pins)), {"default": "gvisor", "earners": {}})
        assert view["default_locks"]["gvisor"] is None
        assert "CASHPILOT_CONTAINER_RUNTIME" in view["default_locks"]["runc"]

    def test_gvisor_without_the_runtime_asks_to_install(self):
        w = _worker(
            _layers(GVISOR_RUNTIMES[:1]), [{"slug": "honeygain", "runtime": "runc", "network": "cashpilot-isolated"}]
        )
        why = layers_ui.worker_view(w, NONE)["earners"][0]["locked"]
        assert "Install gVisor" in why

    def test_bitping_needs_the_net_raw_variant(self):
        info = json.loads(_worker(_layers(GVISOR_RUNTIMES[:2]))["system_info"])
        why = layers_ui.locked("bitping", info, "gvisor")
        assert why and "--net-raw" in why
        # Any other earner still takes the plain passthrough runtime.
        assert layers_ui.locked("honeygain", info, "gvisor") is None
        # With the raw variant registered, Bitping can choose gVisor.
        assert layers_ui.locked("bitping", json.loads(_worker(_layers())["system_info"]), "gvisor") is None

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
            # New: takes the default, recorded as its own only once the worker took it.
            assert _run(layers_ui.for_new_deploy(w, "honeygain")) == "gvisor"
            assert "honeygain" not in json.loads(store["worker_c7_runtime_choice"])["earners"]
            _run(layers_ui.remember(w, "honeygain", "gvisor"))
            assert json.loads(store["worker_c7_runtime_choice"])["earners"]["honeygain"] == "gvisor"
            # A later default leaves it there.
            _run(layers_ui.set_default(w, "runc"))
            assert _run(layers_ui.for_new_deploy(w, "honeygain")) == "gvisor"

    def test_a_refused_first_deploy_keeps_no_inherited_choice(self):
        """The default changes after a failed first deploy: the retry takes the new default."""
        store, g, s = self._store()
        w = _worker(_layers())
        with g, s:
            _run(layers_ui.set_default(w, "gvisor"))
            assert _run(layers_ui.for_new_deploy(w, "honeygain")) == "gvisor"
            # No remember: the worker never took it.
            _run(layers_ui.set_default(w, "runc"))
            assert _run(layers_ui.for_new_deploy(w, "honeygain")) == "runc"

    def test_remember_never_replaces_a_choice_already_there(self):
        store, g, s = self._store()
        store["worker_c7_runtime_choice"] = json.dumps({"default": "gvisor", "earners": {"honeygain": "runc"}})
        with g, s:
            _run(layers_ui.remember(_worker(_layers()), "honeygain", "gvisor"))
        assert json.loads(store["worker_c7_runtime_choice"])["earners"]["honeygain"] == "runc"

    def test_an_earner_already_there_with_an_unreported_runtime_keeps_dockers_default(self):
        store, g, s = self._store()
        w = _worker(_layers(), [{"slug": "earnapp", "network": "cashpilot-isolated"}])
        with g, s:
            _run(layers_ui.set_default(w, "gvisor"))
            assert json.loads(store["worker_c7_runtime_choice"])["earners"] == {"earnapp": None}
            assert _run(layers_ui.for_new_deploy(w, "earnapp")) is None

    def test_a_reset_earner_keeps_dockers_default_under_a_gvisor_default(self):
        store, g, s = self._store()
        store["worker_c7_runtime_choice"] = json.dumps({"default": "gvisor", "earners": {"honeygain": "runc"}})
        w = _worker(_layers())
        with g, s:
            _run(layers_ui.set_earner(w, "honeygain", None))
            assert _run(layers_ui.for_new_deploy(w, "honeygain")) is None
            # A later default change does not touch it either.
            _run(layers_ui.set_default(w, "runc"))
            assert json.loads(store["worker_c7_runtime_choice"])["earners"] == {"honeygain": None}

    def test_the_default_ignores_external_containers(self):
        """An external honeygain is not deployed from here, so it must not pin the managed one to runc."""
        store, g, s = self._store()
        external = {"slug": "honeygain", "runtime": "runc", "network": "bridge", "deployed_by": "external"}
        w = _worker(_layers(), [external])
        with g, s:
            _run(layers_ui.set_default(w, "gvisor"))
            assert "honeygain" not in json.loads(store["worker_c7_runtime_choice"])["earners"]
            assert _run(layers_ui.for_new_deploy(w, "honeygain")) == "gvisor"

    def test_a_stored_choice_an_env_pin_now_overrules_is_not_sent(self):
        store, g, s = self._store()
        pins = {"default": None, "overrides": {"honeygain": "runc"}}
        store["worker_c7_runtime_choice"] = json.dumps({"default": None, "earners": {"honeygain": "gvisor"}})
        with g, s:
            assert _run(layers_ui.for_new_deploy(_worker(_layers(pins=pins)), "honeygain")) is None
            # Without the pin the same stored choice rides the deploy again.
            assert _run(layers_ui.for_new_deploy(_worker(_layers()), "honeygain")) == "gvisor"

    def test_two_new_earners_at_once_both_keep_their_choice(self):
        store: dict[str, str] = {}

        async def get(key=None):
            await asyncio.sleep(0)
            return store.get(key)

        async def put(key, value):
            await asyncio.sleep(0)
            store[key] = value

        async def both(w):
            await layers_ui.set_default(w, "gvisor")
            await asyncio.gather(
                layers_ui.remember(w, "honeygain", "gvisor"), layers_ui.remember(w, "earnapp", "gvisor")
            )

        with (
            patch.object(database, "get_config", side_effect=get),
            patch.object(database, "set_config", side_effect=put),
        ):
            _run(both(_worker(_layers())))
        assert json.loads(store["worker_c7_runtime_choice"])["earners"] == {"honeygain": "gvisor", "earnapp": "gvisor"}

    def test_a_default_that_does_not_fit_leaves_dockers_default(self):
        _store, g, s = self._store()
        w = _worker(_layers())
        with g, s:
            _run(layers_ui.set_default(w, "gvisor"))
            assert _run(layers_ui.for_new_deploy(w, "mysterium")) is None

    def test_a_gvisor_default_on_a_worker_whose_gvisor_is_gone_is_sent_not_recorded(self):
        """The deploy refuses it and says why, instead of running the earner without gVisor."""
        store, g, s = self._store()
        store["worker_c7_runtime_choice"] = json.dumps({"default": "gvisor", "earners": {}})
        with g, s:
            assert _run(layers_ui.for_new_deploy(_worker(_layers(runtimes=["runc"])), "honeygain")) == "gvisor"
            assert json.loads(store["worker_c7_runtime_choice"])["earners"] == {}

    def test_a_stored_value_that_is_not_an_object_reads_as_no_choice(self):
        store, g, s = self._store()
        for raw in ("[]", '"gvisor"', "3", "null"):
            store["worker_c7_runtime_choice"] = raw
            with g, s:
                assert _run(layers_ui.choices(_worker(_layers()))) == {"default": None, "earners": {}}

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

    @pytest.mark.parametrize("body", [{}, {"slug": "honeygain"}])
    def test_a_request_without_a_choice_resets_nothing(self, body):
        w = _worker(_layers(), [{"slug": "honeygain", "runtime": "runc", "network": "cashpilot-isolated"}])
        patches = self._client(w)
        with patches[0], patches[1], patches[2] as put, patches[3], patches[4]:
            resp = TestClient(main.app).post("/api/workers/7/runtime-choice", json=body)
        assert resp.status_code == 422, resp.text
        put.assert_not_called()

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

    def test_a_stored_gvisor_choice_without_gvisor_is_refused_before_anything_moves(self):
        # Caught here, before a deploy that leaves a route removes the routed copy.
        w = _worker(_layers(runtimes=["runc"]))
        with (
            patch.object(database, "get_worker", AsyncMock(return_value=w)),
            patch.object(layers_ui, "for_new_deploy", AsyncMock(return_value="gvisor")),
            pytest.raises(HTTPException) as err,
        ):
            _run(main._runtime_choice_for(7, "honeygain"))
        assert err.value.status_code == 409
        assert "Nothing was deployed" in err.value.detail

    def test_a_routed_copy_of_an_earner_set_to_gvisor_is_refused_before_the_worker_is_asked(self):
        w = _worker(_layers())
        stored = {"default": None, "earners": {"honeygain": "gvisor"}}
        call = AsyncMock(return_value={"status": "deployed"})
        with (
            patch.object(database, "get_worker", AsyncMock(return_value=w)),
            patch.object(layers_ui, "choices", AsyncMock(return_value=stored)),
            patch.object(main, "_proxy_worker_call", call),
            pytest.raises(HTTPException) as err,
        ):
            _run(main._send_worker_deploy(7, "honeygain", {"earner": {}}, proxy_id=3, definition={}))
        assert err.value.status_code == 409 and "Nothing was deployed" in err.value.detail
        call.assert_not_called()

    @pytest.mark.parametrize("stored", [{"honeygain": "runc"}, {}])
    def test_a_routed_copy_without_a_gvisor_choice_takes_no_choice(self, stored):
        # A gVisor default alone does not block a route: it covers direct deploys.
        w = _worker(_layers())
        with (
            patch.object(database, "get_worker", AsyncMock(return_value=w)),
            patch.object(layers_ui, "choices", AsyncMock(return_value={"default": "gvisor", "earners": stored})),
        ):
            assert _run(main._runtime_choice_for(7, "honeygain", routed=True)) is None

    def test_a_stored_runc_choice_without_gvisor_still_deploys(self):
        w = _worker(_layers(runtimes=["runc"]))
        with (
            patch.object(database, "get_worker", AsyncMock(return_value=w)),
            patch.object(layers_ui, "for_new_deploy", AsyncMock(return_value="runc")),
        ):
            assert _run(main._runtime_choice_for(7, "honeygain")) == "runc"

    def test_the_choice_reaches_the_worker_in_the_deploy_body(self):
        sent = {}

        async def hop(worker_id, method, path, *, json=None, **kwargs):
            sent.update(json or {})
            return {"container_id": "abc123"}

        with (
            patch.object(main, "_runtime_choice_for", AsyncMock(return_value="gvisor")),
            patch.object(main, "_remember_runtime_choice", AsyncMock()),
            patch.object(main, "_proxy_to_worker", side_effect=hop),
        ):
            _run(main._send_worker_deploy(7, "honeygain", {"image": "honeygain/honeygain"}))
        assert sent["runtime_choice"] == "gvisor"

    def test_the_choice_is_remembered_only_once_the_worker_took_the_deploy(self):
        remember = AsyncMock()
        with (
            patch.object(main, "_runtime_choice_for", AsyncMock(return_value="gvisor")),
            patch.object(main, "_remember_runtime_choice", remember),
            patch.object(main, "_proxy_to_worker", AsyncMock(return_value={"container_id": "abc123"})),
        ):
            _run(main._send_worker_deploy(7, "honeygain", {"image": "honeygain/honeygain"}))
        remember.assert_awaited_once_with(7, "honeygain", "gvisor")

        remember.reset_mock()
        with (
            patch.object(main, "_runtime_choice_for", AsyncMock(return_value="gvisor")),
            patch.object(main, "_remember_runtime_choice", remember),
            patch.object(main, "_proxy_to_worker", AsyncMock(side_effect=HTTPException(status_code=502))),
            pytest.raises(HTTPException),
        ):
            _run(main._send_worker_deploy(7, "honeygain", {"image": "honeygain/honeygain"}))
        remember.assert_not_called()

    def test_a_routed_copy_of_an_earner_whose_gvisor_choice_a_pin_overrules_is_not_refused(self):
        pins = {"default": None, "overrides": {"honeygain": "runc"}}
        w = _worker(_layers(pins=pins))
        stored = {"default": None, "earners": {"honeygain": "gvisor"}}
        with (
            patch.object(database, "get_worker", AsyncMock(return_value=w)),
            patch.object(layers_ui, "choices", AsyncMock(return_value=stored)),
        ):
            assert _run(main._runtime_choice_for(7, "honeygain", routed=True)) is None

    def test_a_proxied_copy_sends_no_choice(self):
        choice = AsyncMock(return_value="gvisor")
        with (
            patch.object(main, "_runtime_choice_for", choice),
            patch.object(main, "_proxy_worker_call", AsyncMock(return_value={"container_id": "abc123"})) as call,
        ):
            _run(main._send_worker_deploy(7, "honeygain", {"image": "honeygain/honeygain"}, proxy_id=3))
        # Asked only whether the copy may be routed; whatever it answers is never sent.
        choice.assert_awaited_once_with(7, "honeygain", routed=True)
        assert "runtime_choice" not in call.call_args.kwargs["json"]

    def test_a_restore_keeps_the_runtime_choice(self):
        sent = {}

        async def hop(worker_id, method, path, *, json=None, **kwargs):
            sent.update(json or {})
            return {"state_id": 1}

        restore = {"sha256": "ab" * 32, "bundle_b64": "eA==", "passphrase": "p"}
        with (
            patch.object(main, "_runtime_choice_for", AsyncMock(return_value="gvisor")),
            patch.object(main, "_image_for_worker", AsyncMock(side_effect=lambda w, s, spec: spec)),
            patch.object(database, "get_worker", AsyncMock(return_value={"client_id": "c7"})),
            patch.object(main, "_confirmed_worker_key", AsyncMock(return_value="k" * 32)),
            patch.object(main, "_remember_runtime_choice", AsyncMock()) as remember,
            patch.object(main, "_proxy_to_worker", side_effect=hop),
        ):
            _run(main._proxy_worker_restore(7, "honeygain", {"image": "honeygain/honeygain"}, restore))
        assert sent["runtime_choice"] == "gvisor"
        remember.assert_awaited_once_with(7, "honeygain", "gvisor")

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


class TestTheSecureVm:
    NOW = 1_800_000_000

    def _info(self, fence, features=("runtime_choice", "secure_vm")):
        return {"features": list(features), "secure_vm": {"host": "big-box", "fence": fence}}

    def test_a_fresh_ok_is_ok(self):
        vm = layers_ui.secure_vm(self._info({"state": "ok", "checked_at": self.NOW - 60}), now=self.NOW)
        assert vm == {"host": "big-box", "state": "ok", "reason": ""}

    def test_an_old_ok_is_stale_never_ok(self):
        vm = layers_ui.secure_vm(self._info({"state": "ok", "checked_at": self.NOW - 3600}), now=self.NOW)
        assert vm["state"] == "stale"

    def test_a_check_from_the_future_is_unknown_never_ok(self):
        vm = layers_ui.secure_vm(self._info({"state": "ok", "checked_at": self.NOW + 600}), now=self.NOW)
        assert vm["state"] == "unknown"

    def test_no_state_yet_is_unknown_never_ok(self):
        assert layers_ui.secure_vm(self._info(None), now=self.NOW)["state"] == "unknown"

    def test_a_failed_fence_says_why(self):
        fence = {"state": "failed", "checked_at": self.NOW, "reason": "the guard found a route to the LAN"}
        vm = layers_ui.secure_vm(self._info(fence), now=self.NOW)
        assert vm["state"] == "failed" and "route to the LAN" in vm["reason"]

    def test_a_worker_without_the_feature_has_no_vm(self):
        info = self._info({"state": "ok", "checked_at": self.NOW}, features=("runtime_choice",))
        assert layers_ui.secure_vm(info, now=self.NOW) is None

    def test_each_earner_carries_the_vm_fence(self):
        w = _worker(
            _layers(),
            [{"slug": "honeygain", "runtime": "runc", "network": "cashpilot-isolated"}],
            features=("runtime_choice", "secure_vm"),
            secure_vm={"host": "big-box", "fence": {"state": "failed", "checked_at": 1, "reason": "x"}},
        )
        view = layers_ui.worker_view(w, NONE)
        assert view["secure_vm"]["state"] == "failed"
        assert view["earners"][0]["vm"] is False
        # A worker that is not in a VM shows no VM fence per earner.
        plain = layers_ui.worker_view(_worker(_layers(), [{"slug": "honeygain", "runtime": "runc"}]), NONE)
        assert plain["secure_vm"] is None and plain["earners"][0]["vm"] is None
