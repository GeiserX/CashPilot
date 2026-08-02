"""Optional container runtime passthrough (CashPilot-54q).

The research verdict this implements is a REFUSAL: do not adopt gVisor as a
default or as a supported "hardened profile". The escape path it defends is
already closed by the deploy-spec validation (privileged refused, capabilities
and network_mode allowlisted, host bind mounts blocked), and there is no
documented case of a mainstream proxyware image escaping its container. The
risks that actually occur here are IP attribution and lateral movement, which
gVisor does not address — while costing roughly 1.7x network throughput on a
workload that is pure network I/O.

So what ships is the cheap concession: an advanced user who has already
installed a runtime can opt one service into it and own the outcome. Nothing
defaults to it, and nothing recommends it.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app import orchestrator, worker_api


def spec(**kwargs):
    return worker_api.DeploySpec(image="example/image:1.0", **kwargs)


class TestNothingIsEverDefaulted:
    def test_the_default_spec_selects_no_runtime(self):
        assert spec().runtime is None

    def test_a_spec_without_a_runtime_passes_validation_untouched(self):
        with patch.object(orchestrator, "available_runtimes", return_value=set()) as available:
            worker_api._validate_runtime(None)
        available.assert_not_called(), "an absent runtime must not even query the daemon"

    def test_deploy_passes_none_through_so_docker_uses_its_default(self):
        captured = {}

        def fake_run(**kwargs):
            captured.update(kwargs)
            return MagicMock(short_id="abc123")

        client = MagicMock()
        client.containers.run.side_effect = fake_run
        client.containers.get.side_effect = orchestrator.NotFound("nope")

        with patch.object(orchestrator, "_get_client", return_value=client):
            orchestrator.deploy_raw(slug="demo", image="img:1")
        assert captured["runtime"] is None


class TestTheAllowlistComesFromTheDaemon:
    def test_a_runtime_this_host_provides_is_accepted(self):
        with patch.object(orchestrator, "available_runtimes", return_value={"runc", "runsc"}):
            worker_api._validate_runtime("runsc")

    def test_a_runtime_this_host_does_not_provide_is_refused(self):
        """Otherwise it fails at create time with a Docker error nobody can act on."""
        with (
            patch.object(orchestrator, "available_runtimes", return_value={"runc"}),
            pytest.raises(HTTPException) as exc,
        ):
            worker_api._validate_runtime("runsc")
        assert exc.value.status_code == 400
        assert "runsc" in exc.value.detail
        assert "runc" in exc.value.detail, "the error should say what IS available"

    def test_a_host_reporting_no_runtimes_refuses_everything_but_the_default(self):
        with (
            patch.object(orchestrator, "available_runtimes", return_value=set()),
            pytest.raises(HTTPException),
        ):
            worker_api._validate_runtime("runsc")

    def test_the_allowlist_is_not_hardcoded(self):
        """A hardcoded list would offer runtimes the host has never installed."""
        import ast
        import pathlib

        source = pathlib.Path(worker_api.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name == "_validate_runtime"
        )
        literals = {n.value for n in ast.walk(fn) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        assert "runsc" not in literals, "the validator must not carry a hardcoded runtime name"


class TestReadingTheDaemon:
    def test_it_returns_what_docker_reports(self):
        client = MagicMock()
        client.info.return_value = {"Runtimes": {"runc": {}, "runsc": {}}}
        with patch.object(orchestrator, "_get_client", return_value=client):
            assert orchestrator.available_runtimes() == {"runc", "runsc"}

    def test_a_daemon_that_cannot_be_reached_reports_none_rather_than_raising(self):
        with patch.object(orchestrator, "_get_client", side_effect=RuntimeError("no docker")):
            assert orchestrator.available_runtimes() == set()

    def test_a_malformed_info_response_reports_none(self):
        client = MagicMock()
        client.info.return_value = {"Runtimes": "runc"}
        with patch.object(orchestrator, "_get_client", return_value=client):
            assert orchestrator.available_runtimes() == set()


class TestTheSpecStillRefusesEverythingElse:
    """The runtime field must not become a way around the existing guards."""

    def test_privileged_is_still_refused_even_with_a_valid_runtime(self):
        with (
            patch.object(orchestrator, "available_runtimes", return_value={"runsc"}),
            pytest.raises(HTTPException) as exc,
        ):
            worker_api._validate_deploy_spec(spec(runtime="runsc", privileged=True))
        assert exc.value.status_code == 403

    def test_the_runtime_is_validated_before_anything_is_deployed(self):
        with (
            patch.object(orchestrator, "available_runtimes", return_value=set()),
            pytest.raises(HTTPException) as exc,
        ):
            worker_api._validate_deploy_spec(spec(runtime="runsc"))
        assert exc.value.status_code == 400


class TestTheEndpointDoesNotRecommendIt:
    def _call(self):
        import asyncio

        with patch.object(worker_api, "_verify_api_key", lambda r: None):
            return asyncio.run(worker_api.api_runtimes(MagicMock()))

    def test_it_lists_what_the_host_provides(self):
        with patch.object(orchestrator, "available_runtimes", return_value={"runc", "runsc"}):
            out = self._call()
        assert out["available"] == ["runc", "runsc"]

    def test_it_selects_nothing_and_says_it_is_unsupported(self):
        with patch.object(orchestrator, "available_runtimes", return_value={"runc"}):
            out = self._call()
        assert out["default"] is None
        assert out["supported"] is False
        assert "not a hardening recommendation" in out["note"]
