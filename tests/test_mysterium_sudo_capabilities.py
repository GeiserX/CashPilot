"""Mysterium ran for months looking healthy and completing no session.

The node runs as root and still configures its VPN interface and firewall
through ``sudo ip ...`` / ``sudo iptables ...``. sudo switches uid and gid on
the way, and every container is deployed with ``cap_drop ALL``. The catalog
declared NET_ADMIN alone, so sudo died with

    sudo: PERM_SUDOERS: setresuid(-1, 1, -1): Operation not permitted

at startup and on every session, while the node kept registering and
advertising itself. Measured on three hosts and three Docker versions:
``cap_drop ALL`` + NET_ADMIN fails identically with and without
no-new-privileges, and adding SETUID + SETGID makes it succeed with
no-new-privileges still on. So the hardening stays universal and the catalog
declares the two capabilities.

Declaring them was not enough on its own: a redeploy reproduced ``cap_add``
from the record of the first deploy, so no existing node could ever receive
the fix. Capabilities now come from the catalog, like the image.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app import catalog, orchestrator, worker_api
from app import producer_state as ps
from app.main import _merge_recorded_spec
from app.worker_api import DeploySpec, _validate_deploy_spec

#: Verbatim from a production node (Sep 2026), colour codes removed.
REAL_FAILURE_LOG = (
    "2026-09-19T10:37:48.604 WRN ../../nat/service_iptables.go:105 > Failed to prepare iptables setup "
    'error="failed to create MYST iptables chain: error calling IPTables: '
    '\\"/usr/sbin/iptables --new MYST --table nat\\": exit status 1 output: '
    "sudo: PERM_SUDOERS: setresuid(-1, 1, -1): Operation not permitted\\n"
    'sudo: unable to open /etc/sudoers: Operation not permitted"'
)
HEALTHY_LOG = "2026-09-19T10:37:48.604 INF ../../services/wireguard/service/service.go:150 > Wireguard: started"


@pytest.fixture
def mysterium():
    svc = catalog.get_service("mysterium")
    assert svc, "mysterium is missing from the catalog"
    return svc


@pytest.fixture
def real_catalog(monkeypatch):
    monkeypatch.setattr(worker_api, "_catalog_get_services", catalog.get_services)


def _run_kwargs(**deploy_kwargs):
    container = MagicMock()
    container.id = "cid"
    container.short_id = "short"
    client = MagicMock()
    client.containers.get.side_effect = orchestrator.NotFound("nope")
    client.containers.run.return_value = container
    with patch.object(orchestrator, "_get_client", return_value=client):
        orchestrator.deploy_raw(**deploy_kwargs)
    return client.containers.run.call_args.kwargs


class TestTheNodeCanRunSudo:
    def test_the_catalog_declares_what_sudo_needs(self, mysterium):
        caps = {str(c).upper() for c in mysterium["docker"]["cap_add"]}
        assert {"NET_ADMIN", "SETUID", "SETGID"} <= caps

    def test_the_worker_accepts_the_catalog_entry_it_ships(self, mysterium, real_catalog):
        docker = mysterium["docker"]
        _validate_deploy_spec(
            DeploySpec(
                image=docker["image"],
                cap_add=docker["cap_add"],
                devices=docker["devices"],
                network_mode=docker["network_mode"],
            ),
            "mysterium",
        )

    @pytest.mark.parametrize("cap", ["SETUID", "SETGID"])
    def test_the_capabilities_are_granted_to_mysterium_alone(self, cap, real_catalog):
        with pytest.raises(HTTPException) as refused:
            _validate_deploy_spec(DeploySpec(image="x", cap_add=[cap]), "honeygain")
        assert refused.value.status_code == 403

    def test_they_reach_docker_with_the_hardening_still_on(self, mysterium):
        kwargs = _run_kwargs(slug="mysterium", image="img", cap_add=mysterium["docker"]["cap_add"])
        assert kwargs["cap_drop"] == ["ALL"]
        assert set(kwargs["cap_add"]) == {"NET_ADMIN", "SETUID", "SETGID"}
        assert kwargs["security_opt"] == ["no-new-privileges:true"]
        assert kwargs["privileged"] is False


class TestARedeployDeliversTheFix:
    def test_capabilities_come_from_the_catalog_not_the_first_deploy(self):
        merged, divergence = _merge_recorded_spec(
            {"image": "i", "env": {}, "cap_add": ["NET_ADMIN", "SETUID", "SETGID"]},
            {"image": "i", "env": {}, "cap_add": ["NET_ADMIN"]},
            user_env={},
        )
        assert merged["cap_add"] == ["NET_ADMIN", "SETUID", "SETGID"]
        assert any("cap_add" in d for d in divergence), "the operator is told the capabilities changed"

    def test_a_capability_the_catalog_dropped_does_not_come_back(self):
        """The worker would refuse it: it only accepts what its catalog declares."""
        merged, _ = _merge_recorded_spec(
            {"image": "i", "env": {}, "cap_add": None},
            {"image": "i", "env": {}, "cap_add": ["NET_RAW"]},
            user_env={},
        )
        assert not merged.get("cap_add")

    def test_unchanged_capabilities_are_not_reported(self):
        _, divergence = _merge_recorded_spec(
            {"image": "i", "env": {}, "cap_add": ["NET_ADMIN"]},
            {"image": "i", "env": {}, "cap_add": ["NET_ADMIN"]},
            user_env={},
        )
        assert not any("cap_add" in d for d in divergence)

    def test_the_same_capabilities_in_another_order_are_not_a_change(self):
        _, divergence = _merge_recorded_spec(
            {"image": "i", "env": {}, "cap_add": ["NET_ADMIN", "SETUID"]},
            {"image": "i", "env": {}, "cap_add": ["setuid", "NET_ADMIN"]},
            user_env={},
        )
        assert not any("cap_add" in d for d in divergence)

    def test_the_command_is_still_reproduced(self):
        """Control: the rest of the runtime shape keeps following the record."""
        merged, divergence = _merge_recorded_spec(
            {"image": "i", "env": {}, "command": "new"},
            {"image": "i", "env": {}, "command": "deployed"},
            user_env={},
        )
        assert merged["command"] == "deployed"
        assert any("command" in d for d in divergence)


class TestTheFailureIsNamed:
    def test_the_real_log_line_reads_as_failing(self, mysterium):
        hits = ps.match_log_signals(REAL_FAILURE_LOG, ps.signals_for(mysterium))
        assert [h["state"] for h in hits] == ["failing"]
        assert "redeploy" in hits[0]["means"].lower()

    def test_a_healthy_log_does_not(self, mysterium):
        assert ps.match_log_signals(HEALTHY_LOG, ps.signals_for(mysterium)) == []
