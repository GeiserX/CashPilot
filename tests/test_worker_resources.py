"""Tests for per-service Docker resource limits (worker deploy chain).

Covers:
  * DeploySpec / ResourceSpec validation (valid + invalid mem_limit,
    mem_reservation, oom_score_adj, cpu_shares).
  * orchestrator.deploy_raw forwarding mem_limit / mem_reservation /
    oom_score_adj / cpu_shares to containers.run() only when set.
  * The worker /deploy endpoint threading resources through to deploy_raw.
  * Every catalog YAML's docker.resources block validating against the same
    rules the worker enforces, with only documented keys.
"""

import os
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402

try:
    from fastapi import HTTPException  # noqa: E402
    from fastapi.testclient import TestClient  # noqa: E402

    from app import orchestrator, worker_api  # noqa: E402
    from app.worker_api import (  # noqa: E402
        DeploySpec,
        ResourceSpec,
        _validate_deploy_spec,
        _validate_resources,
    )
except ImportError:
    pytest.skip(
        "Requires full app dependencies (fastapi, docker, etc.) — runs in CI",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# ResourceSpec / DeploySpec validation
# ---------------------------------------------------------------------------


class TestResourceValidation:
    def test_valid_resources_pass(self):
        spec = DeploySpec(image="x", resources=ResourceSpec(mem_limit="256m", oom_score_adj=200))
        _validate_deploy_spec(spec)  # must not raise

    def test_none_resources_pass(self):
        _validate_deploy_spec(DeploySpec(image="x"))
        _validate_resources(None)

    @pytest.mark.parametrize("good", ["128", "256m", "2g", "512M", "1024k", "999b", "1536m", "2G"])
    def test_valid_mem_forms_accepted(self, good):
        _validate_resources(ResourceSpec(mem_limit=good, mem_reservation=good))

    @pytest.mark.parametrize("bad", ["", "abc", "-5m", "256 m", "12tb", "2gb", "1.5g", "m"])
    def test_invalid_mem_limit_rejected(self, bad):
        with pytest.raises(HTTPException) as ei:
            _validate_resources(ResourceSpec(mem_limit=bad))
        assert ei.value.status_code == 400

    def test_invalid_mem_reservation_rejected(self):
        with pytest.raises(HTTPException) as ei:
            _validate_resources(ResourceSpec(mem_reservation="lots"))
        assert ei.value.status_code == 400

    @pytest.mark.parametrize("bad", [-1001, 1001, 5000, -5000])
    def test_oom_out_of_range_rejected(self, bad):
        with pytest.raises(HTTPException) as ei:
            _validate_resources(ResourceSpec(oom_score_adj=bad))
        assert ei.value.status_code == 400

    @pytest.mark.parametrize("good", [2, 1024, 2048, 262144])
    def test_valid_cpu_shares_accepted(self, good):
        _validate_resources(ResourceSpec(cpu_shares=good))

    @pytest.mark.parametrize("bad", [0, 1, -1, -1024, 262145])
    def test_cpu_shares_out_of_range_rejected(self, bad):
        # 0 and 1 are rejected deliberately: Docker reads 0 as "default" and
        # refuses 1 outright, so accepting either would silently not apply the
        # weight the operator asked for.
        with pytest.raises(HTTPException) as ei:
            _validate_resources(ResourceSpec(cpu_shares=bad))
        assert ei.value.status_code == 400

    @pytest.mark.parametrize("good", [-1000, -100, 0, 200, 300, 1000])
    def test_oom_in_range_accepted(self, good):
        _validate_resources(ResourceSpec(oom_score_adj=good))

    def test_invalid_resources_rejected_via_deploy_spec(self):
        spec = DeploySpec(image="x", resources=ResourceSpec(oom_score_adj=5000))
        with pytest.raises(HTTPException) as ei:
            _validate_deploy_spec(spec)
        assert ei.value.status_code == 400


# ---------------------------------------------------------------------------
# orchestrator.deploy_raw -> containers.run() kwargs
# ---------------------------------------------------------------------------


class TestDeployRawResources:
    def _mock_client(self):
        container = MagicMock()
        container.id = "cid"
        container.short_id = "short"
        client = MagicMock()
        # No pre-existing container: get() raises NotFound so deploy proceeds.
        client.containers.get.side_effect = orchestrator.NotFound("nope")
        client.containers.run.return_value = container
        return client

    def test_forwards_resources_from_pydantic_model(self):
        client = self._mock_client()
        with patch.object(orchestrator, "_get_client", return_value=client):
            orchestrator.deploy_raw(
                slug="storj",
                image="img",
                resources=ResourceSpec(mem_limit="2g", oom_score_adj=-100),
            )
        kwargs = client.containers.run.call_args.kwargs
        assert kwargs["mem_limit"] == "2g"
        assert kwargs["oom_score_adj"] == -100
        assert "mem_reservation" not in kwargs

    def test_forwards_resources_from_dict_with_reservation(self):
        client = self._mock_client()
        with patch.object(orchestrator, "_get_client", return_value=client):
            orchestrator.deploy_raw(
                slug="svc",
                image="img",
                resources={"mem_limit": "768m", "mem_reservation": "512m", "oom_score_adj": None},
            )
        kwargs = client.containers.run.call_args.kwargs
        assert kwargs["mem_limit"] == "768m"
        assert kwargs["mem_reservation"] == "512m"
        # None-valued fields are dropped, never forwarded as None.
        assert "oom_score_adj" not in kwargs

    def test_forwards_cpu_shares(self):
        client = self._mock_client()
        with patch.object(orchestrator, "_get_client", return_value=client):
            orchestrator.deploy_raw(
                slug="storj",
                image="img",
                resources=ResourceSpec(mem_limit="2g", oom_score_adj=-100, cpu_shares=2048),
            )
        kwargs = client.containers.run.call_args.kwargs
        assert kwargs["cpu_shares"] == 2048
        assert kwargs["mem_limit"] == "2g"

    def test_forwards_cpu_shares_from_catalog_dict(self):
        # No production caller passes a dict today (the worker always builds a
        # ResourceSpec), but _normalize_resources deliberately accepts one, so
        # pin that tolerance. NOTE: the dict path skips _validate_resources —
        # any future caller taking this shortcut must validate first.
        client = self._mock_client()
        with patch.object(orchestrator, "_get_client", return_value=client):
            orchestrator.deploy_raw(slug="storj", image="img", resources={"cpu_shares": 2048})
        assert client.containers.run.call_args.kwargs["cpu_shares"] == 2048

    def test_omits_resource_kwargs_when_unset(self):
        client = self._mock_client()
        with patch.object(orchestrator, "_get_client", return_value=client):
            orchestrator.deploy_raw(slug="svc", image="img")
        kwargs = client.containers.run.call_args.kwargs
        assert "mem_limit" not in kwargs
        assert "mem_reservation" not in kwargs
        assert "cpu_shares" not in kwargs
        assert "oom_score_adj" not in kwargs

    def test_forwards_container_spec(self):
        client = self._mock_client()
        with patch.object(orchestrator, "_get_client", return_value=client):
            orchestrator.deploy_raw(
                slug="svc",
                image="img",
                env={"ID": "tok", "NAME": "dev"},
                ports={"8081/tcp": 9000},
                volumes={"/host": {"bind": "/data", "mode": "rw"}},
                cap_add=["NET_ADMIN"],
                command="run",
                hostname="myhost",
            )
        kwargs = client.containers.run.call_args.kwargs
        assert kwargs["environment"] == {"ID": "tok", "NAME": "dev"}
        assert kwargs["ports"] == {"8081/tcp": 9000}
        assert kwargs["volumes"] == {"/host": {"bind": "/data", "mode": "rw"}}
        assert kwargs["cap_add"] == ["NET_ADMIN"]
        assert kwargs["command"] == "run"
        assert kwargs["hostname"] == "myhost"

    def test_ports_suppressed_in_host_network(self):
        client = self._mock_client()
        with patch.object(orchestrator, "_get_client", return_value=client):
            orchestrator.deploy_raw(
                slug="mysterium",
                image="img",
                ports={"4449/tcp": 4449},
                network_mode="host",
            )
        kwargs = client.containers.run.call_args.kwargs
        # Host networking ignores published ports; deploy_raw must not pass them.
        assert kwargs["ports"] is None
        assert kwargs["network_mode"] == "host"


class TestDeployRawHardening:
    """Third-party images must get the minimum kernel surface (CashPilot-a5p)."""

    def _mock_client(self):
        container = MagicMock()
        container.id = "cid"
        container.short_id = "short"
        client = MagicMock()
        client.containers.get.side_effect = orchestrator.NotFound("nope")
        client.containers.run.return_value = container
        return client

    def _run_kwargs(self, **deploy_kwargs):
        client = self._mock_client()
        with patch.object(orchestrator, "_get_client", return_value=client):
            orchestrator.deploy_raw(**deploy_kwargs)
        return client.containers.run.call_args.kwargs

    def test_hardening_flags_always_applied(self):
        kwargs = self._run_kwargs(slug="honeygain", image="img")
        assert kwargs["cap_drop"] == ["ALL"]
        assert kwargs["security_opt"] == ["no-new-privileges:true"]
        assert kwargs["privileged"] is False
        assert kwargs["pids_limit"] == orchestrator._PIDS_LIMIT
        # Nothing declared any capability, so none is added back.
        assert kwargs["cap_add"] is None

    def test_catalog_declared_capability_is_added_back(self):
        # mysterium is the only catalog service declaring a cap; dropping ALL must not
        # break it — NET_ADMIN is re-added on top of the drop.
        kwargs = self._run_kwargs(slug="mysterium", image="img", cap_add=["NET_ADMIN"])
        assert kwargs["cap_drop"] == ["ALL"]
        assert kwargs["cap_add"] == ["NET_ADMIN"]

    def test_privileged_is_not_an_accepted_argument(self):
        # The dangerous state is unrepresentable, not merely refused upstream.
        with pytest.raises(TypeError):
            orchestrator.deploy_raw(slug="x", image="i", privileged=True)


# ---------------------------------------------------------------------------
# Worker /deploy endpoint (spec -> deploy_raw)
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _noop_lifespan(a):
    yield


class TestWorkerDeployEndpoint:
    def _client(self):
        # Disable the heartbeat lifespan so the TestClient stays isolated.
        worker_api.app.router.lifespan_context = _noop_lifespan
        return TestClient(worker_api.app, raise_server_exceptions=False)

    def _auth(self):
        return {"Authorization": f"Bearer {worker_api.API_KEY}"}

    def test_endpoint_threads_resources_to_deploy_raw(self):
        captured: dict = {}

        def _fake_deploy(**kwargs):
            captured.update(kwargs)
            return "container-id-123"

        with patch("app.worker_api.orchestrator.deploy_raw", side_effect=_fake_deploy):
            resp = self._client().post(
                "/api/containers/storj/deploy",
                json={"image": "img", "resources": {"mem_limit": "2g", "oom_score_adj": -100}},
                headers=self._auth(),
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "deployed"
        res = captured["resources"]
        assert res.mem_limit == "2g"
        assert res.oom_score_adj == -100

    def test_endpoint_deploys_without_resources(self):
        captured: dict = {}

        def _fake_deploy(**kwargs):
            captured.update(kwargs)
            return "container-id-123"

        with patch("app.worker_api.orchestrator.deploy_raw", side_effect=_fake_deploy):
            resp = self._client().post(
                "/api/containers/honeygain/deploy",
                json={"image": "img"},
                headers=self._auth(),
            )
        assert resp.status_code == 200, resp.text
        assert captured["resources"] is None

    def test_endpoint_rejects_invalid_oom_score_adj(self):
        resp = self._client().post(
            "/api/containers/storj/deploy",
            json={"image": "img", "resources": {"oom_score_adj": 5000}},
            headers=self._auth(),
        )
        assert resp.status_code == 400

    def test_endpoint_rejects_invalid_mem_limit(self):
        resp = self._client().post(
            "/api/containers/storj/deploy",
            json={"image": "img", "resources": {"mem_limit": "loads"}},
            headers=self._auth(),
        )
        assert resp.status_code == 400

    def test_endpoint_rejects_invalid_cpu_shares(self):
        # Proves the shared validator is actually reached on the wire for the
        # new key, like the oom/mem siblings above — not just at unit level.
        resp = self._client().post(
            "/api/containers/storj/deploy",
            json={"image": "img", "resources": {"cpu_shares": 1}},
            headers=self._auth(),
        )
        assert resp.status_code == 400


class TestCatalogResourceBlocksAreValid:
    """Every docker.resources block in the real catalog must be deployable.

    Nothing else validates these at load time: an undocumented key (a typo like
    `cpushares`) is silently ignored by Pydantic's default extra="ignore", so
    the YAML looks correct, CI stays green, and the limit the author asked for
    never reaches Docker. Same failure mode — and same guard pattern — as the
    collector-key allowlist in test_beads_batch_24.py.
    """

    # Derived, not hardcoded: ResourceSpec is what actually decides whether a
    # key is honored, so a hand-copied set here could drift and prove nothing.
    # The schema-agreement test below covers the documentation side.
    DOCUMENTED_RESOURCE_KEYS = frozenset(ResourceSpec.model_fields)

    @staticmethod
    def _resource_blocks():
        # The production loader, not a reimplemented walk: it reads both .yml
        # and .yaml, so a service added under either extension stays guarded.
        from app.catalog import load_services

        return {
            svc.get("slug"): resources
            for svc in load_services()
            if (resources := (svc.get("docker") or {}).get("resources"))
        }

    def test_the_catalog_carries_resource_blocks_at_all(self):
        # Negative control for the two tests below: if the loader breaks and
        # returns nothing, they would pass vacuously while checking nothing.
        assert self._resource_blocks(), "no docker.resources block found in any service YAML"

    def test_every_resource_key_is_one_the_schema_documents(self):
        offenders = {
            slug: sorted(set(res) - self.DOCUMENTED_RESOURCE_KEYS)
            for slug, res in self._resource_blocks().items()
            if set(res) - self.DOCUMENTED_RESOURCE_KEYS
        }
        assert not offenders, f"undocumented resource keys are silently ignored, never applied: {offenders}"

    def test_every_resource_block_passes_worker_validation(self):
        # The worker 400s an out-of-range value at deploy time; a catalog that
        # ships one turns every operator's first deploy into that 400.
        for slug, res in self._resource_blocks().items():
            try:
                _validate_resources(ResourceSpec(**res))
            except HTTPException as exc:
                pytest.fail(f"{slug}: catalog resources would be rejected at deploy: {exc.detail}")

    def test_every_honored_key_is_documented_in_the_schema(self):
        # Guards the guard from the other side: the allowlist above is derived
        # from ResourceSpec (what the worker honors), and this ties each of
        # those keys back to _schema.yml (what authors read). If they disagree,
        # either the schema teaches a key nothing applies, or the worker
        # honors a key nobody can discover.
        import pathlib

        schema = (pathlib.Path(__file__).resolve().parents[1] / "services" / "_schema.yml").read_text(encoding="utf-8")
        for key in self.DOCUMENTED_RESOURCE_KEYS:
            assert key in schema, f"{key} is honored by ResourceSpec but undocumented in services/_schema.yml"


class TestPidsLimitParsing:
    """CASHPILOT_PIDS_LIMIT is read at import time — a typo must not kill the worker."""

    @pytest.mark.parametrize("raw", ["512m", "", "abc", "1.5", "0", "-1"])
    def test_bad_values_fall_back_to_default(self, raw, monkeypatch):
        from app import orchestrator

        monkeypatch.setenv("CASHPILOT_PIDS_LIMIT", raw)
        assert orchestrator._read_pids_limit() == orchestrator._PIDS_LIMIT_DEFAULT

    def test_unset_uses_default(self, monkeypatch):
        from app import orchestrator

        monkeypatch.delenv("CASHPILOT_PIDS_LIMIT", raising=False)
        assert orchestrator._read_pids_limit() == orchestrator._PIDS_LIMIT_DEFAULT

    def test_valid_override_is_honoured(self, monkeypatch):
        from app import orchestrator

        monkeypatch.setenv("CASHPILOT_PIDS_LIMIT", "2048")
        assert orchestrator._read_pids_limit() == 2048


class TestCapabilitiesArePerSlug:
    """One service declaring a capability must not grant it to every other slug."""

    def test_bitping_may_request_net_raw(self):
        from app import worker_api

        assert "NET_RAW" in worker_api._catalog_allowed_capabilities("bitping")

    def test_another_slug_may_not_request_net_raw(self):
        from app import worker_api

        assert "NET_RAW" not in worker_api._catalog_allowed_capabilities("honeygain")

    def test_unknown_slug_gets_nothing(self):
        from app import worker_api

        assert worker_api._catalog_allowed_capabilities("not-a-real-service") == set()

    def test_deploy_spec_rejects_borrowed_capability(self):
        from fastapi import HTTPException

        from app import worker_api

        spec = worker_api.DeploySpec(image="x", cap_add=["NET_RAW"])
        # honeygain does not declare NET_RAW; borrowing bitping's must be refused.
        with pytest.raises(HTTPException) as exc:
            worker_api._validate_deploy_spec(spec, slug="honeygain")
        assert exc.value.status_code == 403
        # ...while bitping's own declaration is accepted.
        worker_api._validate_deploy_spec(spec, slug="bitping")
