"""Tests for per-service Docker resource limits (worker deploy chain).

Covers:
  * DeploySpec / ResourceSpec validation (valid + invalid mem_limit,
    mem_reservation, oom_score_adj).
  * orchestrator.deploy_raw forwarding mem_limit / mem_reservation /
    oom_score_adj to containers.run() only when set.
  * The worker /deploy endpoint threading resources through to deploy_raw.
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

    def test_omits_resource_kwargs_when_unset(self):
        client = self._mock_client()
        with patch.object(orchestrator, "_get_client", return_value=client):
            orchestrator.deploy_raw(slug="svc", image="img")
        kwargs = client.containers.run.call_args.kwargs
        assert "mem_limit" not in kwargs
        assert "mem_reservation" not in kwargs
        assert "oom_score_adj" not in kwargs


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
