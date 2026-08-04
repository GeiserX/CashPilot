"""CashPilot-3tr: ticking two boxes behind one connection warned about nothing.

The wizard invites you to tick every node at once. Tick two workers behind the
same home connection, deploy Honeygain (``devices_per_ip: 1``), and you got no
question and no warning — just "Deployed to 2 node(s)" in green.

Per the project's own note the second instance normally earns nothing, and some
providers forfeit the account balance. The warning appeared only the NEXT time
you deployed, after the damage was done.

The cause is that the cross-machine check counts peers ALREADY RUNNING the
service:

    conflicting = [w for w in peers if slug in egress.running_slugs(w)]

Two workers receiving it in the same action are not running it yet, so neither
counted against the other. Each was assessed as though the other were not
getting it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "static" / "js" / "app.js"

SERVICE = {
    "slug": "honeygain",
    "name": "Honeygain",
    "requirements": {"devices_per_ip": 1, "residential_ip": True},
}


# Routable addresses on purpose. 203.0.113.x and 198.51.100.x are RFC 5737
# DOCUMENTATION ranges, and egress.public_ip correctly refuses to treat a
# reserved address as an exit — so a fixture using them produces no peers at
# all and every assertion here would pass or fail for the wrong reason.
def _worker(worker_id, egress_ip="88.12.34.56", containers=None):
    return {
        "id": worker_id,
        "client_id": f"cid-{worker_id}",
        "name": f"node{worker_id}",
        "status": "online",
        "containers": containers or [],
        "system_info": {"egress_ip": egress_ip, "docker_available": True},
    }


def _findings(worker, fleet, planned=None):
    from app import preflight

    out = preflight.assess(
        SERVICE,
        already_deployed_slugs=set(),
        system_info=worker.get("system_info") or {},
        worker=worker,
        fleet_workers=fleet,
        also_deploying_to=planned,
    )
    return out["findings"], out


class TestASimultaneousDeployIsSeen:
    def test_two_nodes_behind_one_ip_now_warn(self):
        a, b = _worker(1), _worker(2)
        findings, _ = _findings(a, [a, b], planned={2})
        assert any(f["verdict"] == "will_earn_nothing" for f in findings), (
            f"a second instance behind the same IP raised nothing: {findings}"
        )

    def test_without_the_planned_set_it_is_silent(self):
        """The bug, stated as a test. Neither worker is running it yet."""
        a, b = _worker(1), _worker(2)
        findings, _ = _findings(a, [a, b], planned=None)
        assert not any(f["verdict"] == "will_earn_nothing" for f in findings)

    def test_a_single_node_deploy_is_unaffected(self):
        """The control: one machine behind one IP is exactly the normal case."""
        a, b = _worker(1), _worker(2)
        findings, _ = _findings(a, [a, b], planned=set())
        assert not any(f["verdict"] == "will_earn_nothing" for f in findings)

    def test_the_worker_itself_does_not_count(self):
        """Passing its own id must not make a machine conflict with itself."""
        a = _worker(1)
        findings, _ = _findings(a, [a], planned={1})
        assert not any(f["verdict"] == "will_earn_nothing" for f in findings)

    def test_different_egress_ips_do_not_conflict(self):
        """The limit is per IP; two separate connections are two customers."""
        a, b = _worker(1, "88.12.34.56"), _worker(2, "81.61.1.9")
        findings, _ = _findings(a, [a, b], planned={2})
        assert not any(f["verdict"] == "will_earn_nothing" for f in findings)

    def test_an_already_running_peer_still_conflicts(self):
        """The control: the pre-existing behaviour must survive."""
        a = _worker(1)
        b = _worker(2, containers=[{"slug": "honeygain", "status": "running"}])
        findings, _ = _findings(a, [a, b], planned=None)
        assert any(f["verdict"] == "will_earn_nothing" for f in findings)


class TestTheEndpointAcceptsIt:
    def test_it_takes_a_planned_parameter(self):
        import inspect

        from app import main

        assert "planned" in inspect.signature(main.api_service_preflight).parameters

    def test_it_ignores_junk(self):
        """The value comes from a query string; it must not be trusted."""
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        i = source.index("async def api_service_preflight")
        block = source[i : i + 3000]
        assert "part.isdigit()" in block

    def test_it_drops_the_worker_being_assessed(self):
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        i = source.index("async def api_service_preflight")
        assert "planned_ids.discard(worker_id)" in source[i : i + 3000]


class TestTheWizardSendsIt:
    def _js(self):
        text = APP_JS.read_text(encoding="utf-8")
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in text.splitlines())

    def test_the_preflight_call_includes_the_selection(self):
        assert "planned=${encodeURIComponent(planned)}" in self._js()

    def test_it_sends_every_selected_worker(self):
        assert "workerIds.join(',')" in self._js()

    def test_the_confirmation_still_interrupts_on_that_verdict(self):
        """The control: raising the finding is useless if nothing acts on it."""
        assert "will_earn_nothing" in self._js()


class TestTheCatalogStillDeclaresTheLimit:
    """If honeygain stops declaring devices_per_ip, none of this fires."""

    def test_honeygain_caps_at_one_device_per_ip(self):
        import yaml

        for path in ROOT.joinpath("services").rglob("honeygain.yml"):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            assert (data.get("requirements") or {}).get("devices_per_ip") == 1
            return
        pytest.fail("honeygain.yml not found")

    def test_the_limit_is_read_from_the_catalog(self):
        from app import egress

        assert egress.devices_per_ip_limit(SERVICE) == 1
        assert egress.devices_per_ip_limit({"slug": "x", "requirements": {}}) is None


def test_the_finding_says_what_is_at_stake():
    """ "Will earn nothing" understates it: some providers forfeit the balance."""
    a, b = _worker(1), _worker(2)
    findings, _ = _findings(a, [a, b], planned={2})
    message = " ".join(f.get("message", "") for f in findings)
    assert "88.12.34.56" in message or "node2" in message, f"the finding names neither the IP nor the peer: {findings}"
    assert json.dumps(findings)  # serialisable: it crosses the API boundary


class TestAReservedAddressIsNotAnExit:
    """Why this file uses routable IPs, pinned so the fixture is not "tidied".

    A documentation or private address means detection failed — we are looking
    at an interface, not an exit. Grouping on one would invent conflicts across
    unrelated machines, which is the opposite of what this module promises.
    """

    @pytest.mark.parametrize("value", ["203.0.113.5", "198.51.100.9", "192.168.1.10", "100.64.0.1", "127.0.0.1"])
    def test_it_is_refused(self, value):
        from app import egress

        assert egress.public_ip(value) is None

    @pytest.mark.parametrize("value", ["88.12.34.56", "81.61.1.9"])
    def test_a_routable_address_is_accepted(self, value):
        from app import egress

        assert egress.public_ip(value) == value

    def test_two_undetected_workers_do_not_conflict(self):
        """Undetected is not shared — an invariant the module states outright."""
        a, b = _worker(1, "192.168.1.10"), _worker(2, "192.168.1.11")
        findings, _ = _findings(a, [a, b], planned={2})
        assert not any(f["verdict"] == "will_earn_nothing" for f in findings)


class TestTheEndpointActuallyForwardsIt:
    """Driven end to end, because parsing it and dropping it looks identical.

    A control that removed `also_deploying_to=planned_ids` from the call left
    every other test passing: they exercise preflight.assess directly and check
    the endpoint only by reading its source. An endpoint that accepts the
    parameter, validates it, and then never passes it on is exactly the wiring
    failure that would make this whole change inert.
    """

    async def _call(self, planned):
        from unittest.mock import AsyncMock, MagicMock, patch

        from app import main

        workers = [_worker(1), _worker(2)]
        with (
            patch.object(main, "_require_auth_api", lambda r: None),
            patch.object(main.catalog, "get_service", lambda slug: SERVICE),
            patch.object(main.database, "list_workers", AsyncMock(return_value=workers)),
            patch.object(main, "_decoded_worker", lambda w: w),
        ):
            return await main.api_service_preflight(MagicMock(), "honeygain", worker_id=1, planned=planned)

    @pytest.mark.asyncio
    async def test_the_simultaneous_deploy_is_reported(self):
        out = await self._call("1,2")
        assert any(f["verdict"] == "will_earn_nothing" for f in out["findings"]), (
            f"the endpoint parsed the planned set but did not act on it: {out}"
        )

    @pytest.mark.asyncio
    async def test_a_single_node_deploy_is_quiet(self):
        """The control: one selected node must not warn about itself."""
        out = await self._call("1")
        assert not any(f["verdict"] == "will_earn_nothing" for f in out["findings"])

    @pytest.mark.asyncio
    async def test_no_parameter_behaves_as_before(self):
        out = await self._call(None)
        assert not any(f["verdict"] == "will_earn_nothing" for f in out["findings"])

    @pytest.mark.asyncio
    async def test_junk_is_ignored_rather_than_crashing(self):
        """It arrives on a query string, so it is untrusted input."""
        out = await self._call("1,../etc/passwd,,abc,2")
        assert any(f["verdict"] == "will_earn_nothing" for f in out["findings"]), (
            "the valid ids in a messy value were discarded"
        )

    @pytest.mark.asyncio
    async def test_entirely_junk_does_not_warn(self):
        out = await self._call("abc,,,;drop table")
        assert not any(f["verdict"] == "will_earn_nothing" for f in out["findings"])
