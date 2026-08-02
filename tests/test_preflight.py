"""Pre-deploy reality check (CashPilot-w58).

The catalog shows one generic earnings range per service, so a user cannot tell
before deploying whether it will work in *their* situation — and several will
not. They find out weeks later, when it has earned nothing.

Two properties matter more than the individual verdicts, and both are tested
below: it never blocks a deploy (informed consent, not a nanny), and it never
implies a check that was not run.
"""

from __future__ import annotations

import json

import pytest

from app import catalog, preflight


def _svc(**reqs):
    return {"slug": "demo", "name": "Demo", "requirements": reqs}


class TestVerdicts:
    def test_a_clean_service_looks_fine(self):
        result = preflight.assess(_svc(residential_ip=False, gpu=False))
        assert result["verdict"] == preflight.LOOKS_FINE
        assert result["findings"] == []

    def test_a_duplicate_where_only_one_device_is_allowed_earns_nothing(self):
        result = preflight.assess(_svc(devices_per_ip=1), already_deployed_slugs={"demo"})
        assert result["verdict"] == preflight.EARNS_NOTHING
        assert "forfeit" in result["findings"][0]["message"]

    def test_a_duplicate_without_a_declared_limit_is_only_reduced(self):
        """Absent data must soften the verdict, never invent one."""
        result = preflight.assess(_svc(), already_deployed_slugs={"demo"})
        assert result["verdict"] == preflight.REDUCED

    def test_a_gpu_requirement_is_called_out(self):
        result = preflight.assess(_svc(gpu=True))
        assert result["verdict"] == preflight.CHECK_YOURSELF
        assert "idle" in result["findings"][0]["message"]

    def test_storage_commitment_warns_about_the_held_balance(self):
        """Running a storage node for a month is worse than not running it."""
        result = preflight.assess(_svc(min_storage="550GB"))
        message = result["findings"][0]["message"]
        assert "550GB" in message
        assert "forfeited" in message

    def test_a_residential_only_service_says_so_plainly(self):
        result = preflight.assess(_svc(residential_ip=True, vps_ip=False))
        assert any("residential IP" in f["message"] for f in result["findings"])

    def test_a_catalog_note_is_surfaced(self):
        result = preflight.assess(_svc(note="Nodes on the same subnet share allocation."))
        assert any("same subnet" in f["message"] for f in result["findings"])

    def test_the_worst_verdict_wins(self):
        result = preflight.assess(_svc(devices_per_ip=1, gpu=True), already_deployed_slugs={"demo"})
        assert result["verdict"] == preflight.EARNS_NOTHING

    def test_empty_requirement_strings_are_not_treated_as_requirements(self):
        """Most of the catalog stores '' for unknown, which must stay silent."""
        result = preflight.assess(_svc(min_bandwidth="", min_storage=""))
        assert result["verdict"] == preflight.LOOKS_FINE


class TestItNeverOversteps:
    def test_it_never_blocks_a_deploy(self):
        """Informed consent, not a nanny — even in the worst case."""
        result = preflight.assess(_svc(devices_per_ip=1), already_deployed_slugs={"demo"})
        assert result["blocking"] is False
        assert "anyway" in result["summary"]

    def test_it_declares_what_it_did_not_check(self):
        """A clean result must not read as a guarantee about unexamined things."""
        result = preflight.assess(_svc())
        assert "egress IP type" in result["not_checked"]
        assert "connection speed" in result["not_checked"]

    def test_another_service_running_here_is_not_treated_as_a_duplicate(self):
        result = preflight.assess(_svc(devices_per_ip=1), already_deployed_slugs={"something-else"})
        assert result["verdict"] == preflight.LOOKS_FINE


class TestAgainstTheRealCatalog:
    @pytest.mark.parametrize("slug", ["storj", "honeygain", "mysterium"])
    def test_real_services_produce_a_usable_verdict(self, slug):
        service = catalog.get_service(slug)
        assert service, f"{slug} missing from the catalog"
        result = preflight.assess(service)
        assert result["verdict"] in {
            preflight.LOOKS_FINE,
            preflight.CHECK_YOURSELF,
            preflight.REDUCED,
            preflight.EARNS_NOTHING,
        }
        assert result["summary"]

    def test_storj_warns_about_the_disk_commitment(self):
        result = preflight.assess(catalog.get_service("storj"))
        assert any("forfeited" in f["message"] for f in result["findings"])

    def test_every_catalog_service_can_be_assessed(self):
        """A malformed requirements block must not break the deploy page."""
        for service in catalog.get_services():
            result = preflight.assess(service)
            assert result["verdict"] in _SEEN
            assert isinstance(result["findings"], list)


_SEEN = {
    preflight.LOOKS_FINE,
    preflight.CHECK_YOURSELF,
    preflight.REDUCED,
    preflight.EARNS_NOTHING,
}


class TestPreflightEndpoint:
    def _call(self, slug, worker_id=None, worker=None, deployments=None):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from app import main

        async def run():
            with (
                patch.object(main, "_require_auth_api", lambda r: None),
                patch.object(main.database, "get_deployments", AsyncMock(return_value=deployments or [])),
                patch.object(main.database, "list_workers", AsyncMock(return_value=[worker] if worker else [])),
            ):
                return await main.api_service_preflight(MagicMock(), slug, worker_id=worker_id)

        return asyncio.run(run())

    def test_an_unknown_service_is_a_404(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            self._call("no-such-service")
        assert exc.value.status_code == 404

    def test_it_returns_a_verdict_for_a_real_service(self):
        result = self._call("storj")
        assert result["slug"] == "storj"
        assert result["verdict"] in _SEEN
        assert result["blocking"] is False

    def test_a_duplicate_on_the_named_worker_is_detected(self):
        """Scoped to that worker: a per-IP limit is about ONE machine.

        The worker row is built the way SQLite actually returns one — JSON TEXT
        columns, and the container keyed by ``slug`` as the heartbeat emits it.
        Fixtures that used dicts and ``service`` are why a 500 and a
        never-matching filter both shipped green.
        """
        worker = {
            "id": 1,
            "client_id": "cid-1",
            "containers": json.dumps([{"slug": "honeygain", "status": "running"}]),
            "system_info": json.dumps({"arch": "x86_64"}),
        }
        result = self._call("honeygain", worker_id=1, worker=worker)
        assert result["verdict"] in {preflight.REDUCED, preflight.EARNS_NOTHING}
        assert result["worker_arch"] == "x86_64"

    def test_without_a_worker_it_falls_back_to_all_deployments(self):
        result = self._call("honeygain", deployments=[{"slug": "honeygain"}])
        assert result["verdict"] in {preflight.REDUCED, preflight.EARNS_NOTHING}


class TestProviderForbidsWhatCashPilotDoes:
    """The strongest verdict: the tool causes the breach on the user's behalf.

    EarnApp's own help centre forbids "Virtual Machines (VMs), Docker
    containers, ... personal or home servers" and states the penalty as
    termination without notice plus cancellation of pending payments. CashPilot
    deploys every service as a Docker container, so shipping EarnApp silently
    would make the tool the cause of the ban.
    """

    def test_it_is_reported_and_says_what_actually_happens(self):
        svc = {"slug": "x", "name": "X", "requirements": {"container_prohibited": True}}
        out = preflight.assess(svc)
        assert out["verdict"] == preflight.EARNS_NOTHING
        message = " ".join(f["message"] for f in out["findings"])
        assert "Docker containers" in message
        assert "termination without notice" in message.lower() or "without notice" in message

    def test_it_still_does_not_block_the_deploy(self):
        """Informed consent: the user may accept the risk knowingly."""
        svc = {"slug": "x", "requirements": {"container_prohibited": True}}
        assert preflight.assess(svc)["blocking"] is False

    def test_a_service_without_the_flag_is_unaffected(self):
        out = preflight.assess({"slug": "x", "requirements": {}})
        assert not any("Docker containers" in f["message"] for f in out["findings"])

    def test_the_real_catalog_flags_earnapp(self):
        from app import catalog

        assert preflight.assess(catalog.get_service("earnapp"))["verdict"] == preflight.EARNS_NOTHING

    def test_the_flag_is_not_set_on_services_merely_wanting_a_residential_ip(self):
        """It requires a first-party source, never an inference from residential_ip."""
        from app import catalog

        allowed = {"earnapp"}
        for svc in catalog.get_services():
            if (svc.get("requirements") or {}).get("container_prohibited"):
                assert svc["slug"] in allowed, (
                    f"{svc['slug']} declares container_prohibited — confirm a first-party source "
                    "and add it to docs/research/per-ip-device-limits.md before allowing it here"
                )


class TestSourcedPerIpLimits:
    """Values must trace to a provider statement; see docs/research/per-ip-device-limits.md."""

    @pytest.mark.parametrize("slug", ["honeygain", "iproyal", "earnfm", "ebesucher"])
    def test_the_four_documented_services_declare_one_per_ip(self, slug):
        from app import catalog

        assert (catalog.get_service(slug)["requirements"] or {}).get("devices_per_ip") == 1

    @pytest.mark.parametrize("slug", ["repocket", "proxyrack", "packetstream", "bitping", "urnetwork"])
    def test_services_with_no_provider_source_stay_absent(self, slug):
        """A widely-repeated review-site number is not a source.

        repocket previously declared devices_per_ip: 2 on exactly that basis.
        """
        from app import catalog

        assert "devices_per_ip" not in (catalog.get_service(slug)["requirements"] or {})

    def test_a_second_device_behind_one_ip_now_gets_the_strongest_verdict(self):
        """The point of the bead: the verdict was weak exactly where the
        mistake is most likely, because the limit was never recorded."""
        from app import catalog

        out = preflight.assess(catalog.get_service("honeygain"), already_deployed_slugs={"honeygain"})
        assert out["verdict"] == preflight.EARNS_NOTHING
        assert "one device per IP" in " ".join(f["message"] for f in out["findings"])
