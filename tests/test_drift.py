"""A running container that no longer matches what a redeploy would build is reported.

Bitping containers made on 2026-07-31, before the catalog added NET_RAW, ran for
three months with every probe failing ("Operation not permitted ... create new
socket") while CashPilot said nothing. A redeploy fixed them. The dashboard now
lists such a container under "Needs fixing" with the redeploy that fixes it.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app import catalog, drift, main, orchestrator

ROOT = Path(__file__).resolve().parents[1]
BITPING = catalog.get_service("bitping")
EARNAPP = catalog.get_service("earnapp")


def _attrs_from_spec(spec: dict) -> dict:
    """The docker inspect a worker's deploy_raw produces from a spec, on the fields _shape reads."""
    env = {**(spec.get("env") or {})}
    return {
        "Config": {
            "Image": spec["image"],
            # The image's own ENV is there too; a key the catalog does not know is not drift.
            "Env": [f"{k}={v}" for k, v in env.items()] + ["PATH=/usr/bin"],
            "Entrypoint": None,
        },
        "HostConfig": {
            "CapAdd": spec.get("cap_add"),
            "CapDrop": ["ALL"],
            "Privileged": False,
            "NetworkMode": spec.get("network_mode") or "bridge",
            "Devices": [{"PathOnHost": d, "PathInContainer": d} for d in spec.get("devices") or []],
            "PortBindings": {k: [{"HostPort": "1"}] for k in spec.get("ports") or {}},
        },
        "Mounts": [{"Source": h, "Destination": v["bind"]} for h, v in (spec.get("volumes") or {}).items()],
    }


def _shape(spec: dict) -> dict:
    return orchestrator._shape(SimpleNamespace(attrs=_attrs_from_spec(spec)))


def _bitping_spec(**over) -> dict:
    spec = {
        "image": "bitping/bitpingd",
        "env": {"BITPING_EMAIL": "a@b.c", "BITPING_PASSWORD": "pw"},
        "ports": {},
        "volumes": {"bitping-data": {"bind": "/root/.bitping", "mode": "rw"}},
        "network_mode": None,
        "cap_add": ["NET_RAW"],
    }
    spec.update(over)
    return spec


class TestTheBitpingCase:
    def test_a_container_made_without_net_raw_is_flagged(self):
        old = _shape(_bitping_spec(cap_add=None))
        found = drift.container_drift(BITPING, old, _bitping_spec(cap_add=None))
        assert len(found) == 1
        assert "missing NET_RAW" in found[0]

    def test_one_made_with_it_is_not(self):
        assert drift.container_drift(BITPING, _shape(_bitping_spec()), _bitping_spec()) == []

    def test_docker_reporting_cap_prefixed_names_is_the_same_capability(self):
        shape = _shape(_bitping_spec(cap_add=["CAP_NET_RAW"]))
        assert drift.container_drift(BITPING, shape, _bitping_spec()) == []

    def test_the_dashboard_lists_it_per_box_with_a_redeploy(self):
        row = _deployed_row(BITPING, _shape(_bitping_spec(cap_add=None)), recorded=_bitping_spec(cap_add=None))
        inst = row["instance_details"][0]
        assert any("NET_RAW" in d for d in inst["drift"])
        assert inst["drift_has_record"] is True

    def test_a_matching_container_carries_no_drift(self):
        row = _deployed_row(BITPING, _shape(_bitping_spec()), recorded=_bitping_spec())
        assert "drift" not in row["instance_details"][0]

    def test_without_a_record_it_says_so(self):
        row = _deployed_row(BITPING, _shape(_bitping_spec(cap_add=None)), recorded=None)
        inst = row["instance_details"][0]
        assert inst["drift"] and inst["drift_has_record"] is False

    def test_an_older_worker_without_a_shape_is_not_judged(self):
        row = _deployed_row(BITPING, None, recorded=_bitping_spec(cap_add=None))
        assert "drift" not in row["instance_details"][0]


class TestImages:
    def test_a_provider_image_on_another_tag_is_not_drift(self):
        """Provider images follow their default tag on purpose."""
        shape = _shape(_bitping_spec(image="bitping/bitpingd:26.8.17-1"))
        assert drift.container_drift(BITPING, shape, _bitping_spec()) == []

    def test_our_own_image_on_another_tag_is_drift(self):
        catalog_image = EARNAPP["docker"]["image"]
        repo = catalog_image.rsplit(":", 1)[0]
        assert repo.startswith(drift.OWN_IMAGE_PREFIX)
        found = drift.container_drift(EARNAPP, _earnapp(f"{repo}:0.0.1-r1"), None)
        assert found == [f"runs {repo}:0.0.1-r1; the catalog now pins {catalog_image.rsplit(':', 1)[1]}"]

    def test_our_own_image_on_the_pinned_tag_is_not(self):
        shape = _earnapp(EARNAPP["docker"]["image"])
        assert drift.container_drift(EARNAPP, shape, None) == []

    def test_a_custom_image_the_operator_chose_is_not_drift(self):
        repo = EARNAPP["docker"]["image"].rsplit(":", 1)[0]
        shape = _earnapp(f"{repo}:0.0.1-r1")
        assert drift.container_drift(EARNAPP, shape, None, custom_image=f"{repo}:0.0.1-r1") == []


def _earnapp(image: str) -> dict:
    """An earnapp container as the catalog would make it, on ``image``."""
    d = EARNAPP["docker"]
    return {
        "image": image,
        "env_keys": [v["key"] for v in d.get("env") or []],
        "cap_add": list(d.get("cap_add") or []),
        "devices": [drift._device_target(x) for x in d.get("devices") or []],
        "mounts": sorted(drift._volume_targets(d.get("volumes"))),
        "ports": sorted(drift._catalog_port_keys(d)),
        "network_mode": d.get("network_mode") or "bridge",
    }


class TestOtherFields:
    SVC = {
        "slug": "demo",
        "docker": {
            "image": "demo/demo",
            "env": [
                {"key": "TOKEN", "required": True},
                {"key": "OPTIONAL", "default": ""},
                {"key": "MODE", "default": "fast"},
                {"key": "REGION", "default": "eu"},
            ],
            "ports": ["9000:9000"],
            "volumes": ["${DATA}:/data"],
            "devices": ["/dev/net/tun"],
            "command": "run --token ${TOKEN} --mode ${MODE}",
        },
    }

    def _spec(self, **over):
        spec = {
            "image": "demo/demo",
            "env": {"TOKEN": "t", "OPTIONAL": "", "MODE": "fast", "REGION": "eu"},
            "ports": {"9000/tcp": 9000},
            "volumes": {"/mnt/d": {"bind": "/data", "mode": "rw"}},
            "devices": ["/dev/net/tun"],
            "command": "run --token t --mode fast",
        }
        spec.update(over)
        return spec

    def test_a_container_built_from_the_spec_matches(self):
        assert drift.container_drift(self.SVC, _shape(self._spec()), self._spec()) == []

    def test_a_missing_device_mount_port_and_env_key_are_each_named(self):
        shape = _shape(self._spec(devices=[], volumes={}, ports={}, env={"TOKEN": "t"}))
        found = " | ".join(drift.container_drift(self.SVC, shape, self._spec()))
        assert "/dev/net/tun" in found
        assert "/data" in found
        assert "9000/tcp" in found
        assert "REGION" in found
        # An optional key with no default is not set to anything by a redeploy.
        assert "OPTIONAL" not in found
        # Keys the command carries reach the service on the command line, not the env
        # (IPRoyal's credentials, renamed in the catalog after its containers were made).
        assert "TOKEN" not in found and "MODE" not in found

    def test_a_command_the_catalog_has_changed_since_is_drift(self):
        recorded = self._spec(command="run --token t")
        found = drift.container_drift(self.SVC, _shape(recorded), recorded)
        assert found == ["runs an older command; the catalog has changed it since"]
        # The command carries credentials and is never in what the worker reports.
        assert "command" not in _shape(recorded) and "cmd" not in json.dumps(_shape(recorded)).lower()

    def test_host_networking_hides_no_port_difference(self):
        svc = {"docker": {**self.SVC["docker"], "network_mode": "host"}}
        shape = _shape(self._spec(network_mode="host", ports={}))
        assert drift.container_drift(svc, shape, self._spec(network_mode="host")) == []
        bridge = _shape(self._spec())
        assert drift.container_drift(svc, bridge, None) == ["uses its own network, but should share the host's"]

    def test_a_device_the_catalog_dropped_is_drift(self):
        svc = {"docker": {**self.SVC["docker"], "devices": []}}
        assert drift.container_drift(svc, _shape(self._spec()), self._spec()) == [
            "still has device /dev/net/tun, which the catalog no longer passes in"
        ]

    def test_an_unreadable_record_still_judges_the_catalog(self):
        """A failed record read must not hide what the catalog alone shows."""
        with patch("app.main.database.get_deployment_spec", AsyncMock(side_effect=RuntimeError("db"))):
            found, has_record = asyncio.run(
                main._instance_drift(
                    BITPING, "bitping", {"_worker_id": 1, "shape": _shape(_bitping_spec(cap_add=None))}, None, {}
                )
            )
        assert any("NET_RAW" in f for f in found) and has_record is False

    def test_a_capability_the_catalog_dropped_is_drift(self):
        found = drift.container_drift(self.SVC, _shape(self._spec(cap_add=["NET_ADMIN"])), self._spec())
        assert found == ["still has NET_ADMIN, which the catalog no longer grants"]


class TestTheRedeployClearsIt:
    """A redeploy from the record builds a container the check is satisfied with."""

    def test_after_a_redeploy_the_drift_is_gone(self):
        old_record = _bitping_spec(cap_add=None)
        before = _shape(old_record)
        assert drift.container_drift(BITPING, before, old_record)

        captured: dict = {}

        async def _capture(worker_id, slug, spec):
            captured["spec"] = dict(spec)
            return {"container_id": "abc"}

        saved = AsyncMock()
        body = main.DeployRequest(env={})

        async def run():
            with (
                patch.object(main.catalog, "get_service", return_value=BITPING),
                patch.object(main, "_resolve_worker_id", AsyncMock(return_value=1)),
                patch.object(main, "_proxy_worker_deploy", _capture),
                patch.object(main.database, "get_deployment_spec", AsyncMock(return_value=old_record)),
                patch.object(main.database, "save_deployment", saved),
                patch.object(main.database, "record_health_event", AsyncMock()),
                patch.object(main, "_spawn", lambda coro: coro.close()),
                patch.object(main.metrics, "record_container_lifecycle", lambda *a: None),
            ):
                await main.api_deploy(MagicMock(), "bitping", body, worker_id=1, _auth={})

        asyncio.run(run())
        after = _shape(captured["spec"])
        assert drift.container_drift(BITPING, after, saved.call_args.kwargs["spec"]) == []


class TestTheDashboard:
    def test_the_row_has_a_redeploy_handler(self):
        js = (ROOT / "app" / "static" / "js" / "app.js").read_text()
        assert 'data-action="redeployOnWorker"' in js
        assert "\n    redeployOnWorker,\n" in js
        assert "tag: 'Needs fixing'" in js


def _deployed_row(svc, shape, recorded, deployed_by="worker", config=None):
    from fastapi.testclient import TestClient

    container = {
        "slug": svc["slug"],
        "name": f"cashpilot-{svc['slug']}",
        "status": "running",
        "image": "x",
        "deployed_by": deployed_by,
    }
    if shape is not None:
        container["shape"] = shape
    worker = {
        "id": 1,
        "name": "w1",
        "status": "online",
        "system_info": json.dumps({"docker_available": True, "arch": "x86_64"}),
        "containers": json.dumps([container]),
        "apps": "[]",
    }
    owner = {"uid": 1, "u": "owner", "r": "owner"}

    @asynccontextmanager
    async def _noop_lifespan(app):
        yield

    with (
        patch.object(main.app.router, "lifespan_context", _noop_lifespan),
        patch("app.main.auth.get_current_user", return_value=owner),
        patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
        patch("app.main.database.get_earnings_summary", new_callable=AsyncMock, return_value=[]),
        patch("app.main.database.get_health_scores", new_callable=AsyncMock, return_value=[]),
        patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[]),
        patch("app.main.database.get_deployment_spec", new_callable=AsyncMock, return_value=recorded),
        patch("app.main.database.get_config", new_callable=AsyncMock, return_value=config or {}),
        patch("app.main.catalog.get_service", return_value=svc),
        TestClient(main.app, raise_server_exceptions=False) as client,
    ):
        resp = client.get("/api/services/deployed")
    assert resp.status_code == 200, resp.text
    return resp.json()[0]


def _container(labels, attrs=None):
    return SimpleNamespace(labels=labels, attrs=attrs or _attrs_from_spec(_bitping_spec(cap_add=None)))


class TestOnlyWhatCashPilotDeployed:
    """A container the user runs by hand is theirs: never judged, even with CashPilot's labels."""

    def test_the_worker_reports_settings_only_for_its_own_containers(self):
        assert "shape" in orchestrator._shape_entry(_container({"cashpilot.deployed-by": "worker"}))
        # An exported compose file carries the labels too, and the user runs it by hand.
        assert orchestrator._shape_entry(_container({"cashpilot.deployed-by": "compose"})) == {}
        assert orchestrator._shape_entry(_container({})) == {}

    def test_a_hand_made_container_is_not_flagged_on_the_dashboard(self):
        shape = _shape(_bitping_spec(cap_add=None))
        for who in ("external", "compose", "unknown"):
            row = _deployed_row(BITPING, shape, recorded=None, deployed_by=who)
            assert "drift" not in row["instance_details"][0], who
        # The control: the same container made by the worker is flagged.
        assert _deployed_row(BITPING, shape, recorded=None)["instance_details"][0]["drift"]


class TestTheSwitch:
    def test_off_on_the_worker_reports_nothing(self, monkeypatch):
        own = _container({"cashpilot.deployed-by": "worker"})
        monkeypatch.setenv("CASHPILOT_DRIFT_WARNINGS", "false")
        assert orchestrator._shape_entry(own) == {}
        monkeypatch.setenv("CASHPILOT_DRIFT_WARNINGS", "true")
        assert "shape" in orchestrator._shape_entry(own)

    def test_off_on_the_ui_flags_nothing(self, monkeypatch):
        shape = _shape(_bitping_spec(cap_add=None))
        monkeypatch.setenv("CASHPILOT_DRIFT_WARNINGS", "off")
        assert "drift" not in _deployed_row(BITPING, shape, recorded=None)["instance_details"][0]
        monkeypatch.delenv("CASHPILOT_DRIFT_WARNINGS")
        assert _deployed_row(BITPING, shape, recorded=None)["instance_details"][0]["drift"]

    def test_it_is_documented_and_in_the_compose_example(self):
        assert "CASHPILOT_DRIFT_WARNINGS" in (ROOT / "docs" / "configuration.md").read_text()
        assert (ROOT / "docker-compose.yml").read_text().count("CASHPILOT_DRIFT_WARNINGS=") == 2


class TestIgnore:
    def _ignore(self, svc, stored=None):
        saved = AsyncMock()

        async def run():
            with (
                patch.object(main.catalog, "get_service", return_value=svc),
                patch.object(main.database, "get_config", AsyncMock(return_value=stored or {})),
                patch.object(main.database, "set_config", saved),
            ):
                await main.api_drift_ignore(MagicMock(), svc["slug"], worker_id=1, _auth={})

        asyncio.run(run())
        key, value = saved.call_args.args
        return {key: value}

    def test_ignore_mutes_that_box_until_the_catalog_changes(self):
        shape = _shape(_bitping_spec(cap_add=None))
        config = self._ignore(BITPING)
        assert "drift" not in _deployed_row(BITPING, shape, recorded=None, config=config)["instance_details"][0]

        # A later catalog fix to this service shows again.
        changed = {**BITPING, "docker": {**BITPING["docker"], "devices": ["/dev/net/tun"]}}
        row = _deployed_row(changed, shape, recorded=None, config=config)
        assert row["instance_details"][0]["drift"]

    def test_a_text_edit_in_the_catalog_keeps_it_muted(self):
        reworded = {**BITPING, "docker": {**BITPING["docker"], "notes": "reworded"}}
        assert drift.catalog_fingerprint(reworded) == drift.catalog_fingerprint(BITPING)

    def test_ignore_is_per_box(self):
        shape = _shape(_bitping_spec(cap_add=None))
        other_box = {"drift_ignored": json.dumps({"bitping|2": drift.catalog_fingerprint(BITPING)})}
        assert _deployed_row(BITPING, shape, recorded=None, config=other_box)["instance_details"][0]["drift"]

    def test_earlier_mutes_are_kept(self):
        stored = {"drift_ignored": json.dumps({"earnapp|3": "abc"})}
        config = self._ignore(BITPING, stored)
        assert json.loads(config["drift_ignored"]) == {
            "earnapp|3": "abc",
            "bitping|1": drift.catalog_fingerprint(BITPING),
        }

    def test_the_row_has_an_ignore_handler(self):
        js = (ROOT / "app" / "static" / "js" / "app.js").read_text()
        assert 'data-action="ignoreDrift"' in js
        assert "\n    ignoreDrift,\n" in js
