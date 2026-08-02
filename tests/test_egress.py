"""Egress-IP conflict detection (CashPilot-5qc).

Providers cap per IP, not per device, and CashPilot's fleet model actively
encourages deploying one service to several machines that may all sit behind one
home connection. The tests that matter are the ones that keep the warning from
being *wrong*, because a warning that cries wolf gets switched off:

* an egress IP we could not detect must never look like a shared one;
* a tailnet or LAN address must never be mistaken for an exit — every worker in
  this project's own reference fleet has one, so the false-conflict blast radius
  is the entire fleet;
* an undocumented per-IP limit must not read as "unlimited"; only 4 of 50
  services declare one today.
"""

from __future__ import annotations

import pytest

from app import egress, preflight


def worker(wid, name, ip=None, network=None, running=(), status="running"):
    info = {"arch": "x86_64"}
    if ip is not None:
        info["egress_ip"] = ip
    if network is not None:
        info["egress_network_type"] = network
    return {
        "id": wid,
        "client_id": f"cid-{wid}",
        "name": name,
        "system_info": info,
        "containers": [{"service": s, "status": status} for s in running],
    }


HOME_A = worker(1, "watchtower", "81.61.1.9", running=["honeygain"])
HOME_B = worker(2, "geiserback", "81.61.1.9")
REMOTE = worker(3, "vps", "95.216.4.7", network="hosting")
UNSEEN = worker(4, "pi")

ONE_PER_IP = {"slug": "honeygain", "name": "Honeygain", "requirements": {"devices_per_ip": 1}}
UNDOCUMENTED = {"slug": "honeygain", "name": "Honeygain", "requirements": {}}
UNLIMITED = {"slug": "honeygain", "name": "Honeygain", "requirements": {"devices_per_ip": 0}}


class TestOnlyRealPublicAddressesCount:
    @pytest.mark.parametrize(
        "addr",
        [
            "192.168.10.100",  # LAN
            "10.0.0.5",
            "172.16.4.1",
            "127.0.0.1",
            "169.254.1.1",  # link-local
            "100.101.102.103",  # CGNAT — and the tailnet range this fleet uses
            "fd00::1",  # unique-local v6
            "::1",
            "224.0.0.1",  # multicast
            "0.0.0.0",
            "",
            "not-an-ip",
            None,
        ],
    )
    def test_a_non_public_address_is_a_detection_failure(self, addr):
        assert egress.public_ip(addr) is None

    def test_a_real_public_address_is_kept(self):
        assert egress.public_ip("81.61.1.9") == "81.61.1.9"
        assert egress.public_ip("2606:4700::1111") == "2606:4700::1111"

    @pytest.mark.parametrize("addr", ["203.0.113.9", "198.51.100.4", "192.0.2.1", "2001:db8:1::1"])
    def test_reserved_documentation_ranges_are_rejected_too(self, addr):
        """Not pedantry: a stub or fixture leaking into production must not group hosts."""
        assert egress.public_ip(addr) is None

    def test_a_tailnet_address_never_groups_the_fleet(self):
        """Every worker here has a 100.x tailnet IP; grouping on it would be catastrophic."""
        tailnet = [worker(i, f"w{i}", f"100.64.0.{i}") for i in range(1, 4)]
        groups = egress.group_by_egress(tailnet)
        assert len(groups) == 1
        assert groups[0]["known"] is False
        assert groups[0]["shared"] is False


class TestUndetectedIsNotShared:
    def test_workers_with_no_ip_are_not_reported_as_sharing_one(self):
        groups = egress.group_by_egress([UNSEEN, worker(5, "other")])
        assert len(groups) == 1
        assert groups[0]["known"] is False
        assert groups[0]["shared"] is False, "two unchecked machines are not a conflict"

    def test_an_unchecked_worker_has_no_known_peers(self):
        assert egress.peers_sharing_egress(UNSEEN, [HOME_A, HOME_B, UNSEEN]) == []

    def test_a_shared_address_is_reported_as_shared(self):
        groups = egress.group_by_egress([HOME_A, HOME_B, REMOTE, UNSEEN])
        shared = [g for g in groups if g["shared"]]
        assert len(shared) == 1
        assert shared[0]["egress_ip"] == "81.61.1.9"
        assert shared[0]["worker_count"] == 2

    def test_groups_are_largest_first_and_unknown_goes_last(self):
        groups = egress.group_by_egress([UNSEEN, REMOTE, HOME_A, HOME_B])
        assert [g["worker_count"] for g in groups] == [2, 1, 1]
        assert groups[-1]["known"] is False

    def test_a_worker_is_not_its_own_peer(self):
        assert [w["id"] for w in egress.peers_sharing_egress(HOME_A, [HOME_A, HOME_B])] == [2]


class TestNetworkType:
    @pytest.mark.parametrize(
        "vendor",
        ["DigitalOcean", "Amazon EC2", "Hetzner", "  vultr  ", "Google Compute Engine", "OVH SAS"],
    )
    def test_hosting_vendors_are_recognised(self, vendor):
        assert egress.classify_vendor(vendor) == egress.HOSTING

    @pytest.mark.parametrize("vendor", ["QEMU", "VMware, Inc.", "ASUSTeK COMPUTER INC.", "", None, "Innotek GmbH"])
    def test_a_home_lab_hypervisor_is_not_hosting(self, vendor):
        """A VM on a home server is a residential connection — the common case here."""
        assert egress.classify_vendor(vendor) == egress.UNKNOWN

    def test_unrecognised_values_normalise_to_unknown(self):
        assert egress.normalise_network_type("datacenter") == egress.UNKNOWN
        assert egress.normalise_network_type(None) == egress.UNKNOWN
        assert egress.normalise_network_type("HOSTING") == egress.HOSTING

    def test_a_group_with_disagreeing_members_claims_nothing(self):
        a = worker(1, "a", "81.61.1.9", network="hosting")
        b = worker(2, "b", "81.61.1.9", network="residential")
        assert egress.group_by_egress([a, b])[0]["network_type"] == egress.UNKNOWN

    def test_a_group_agrees_when_its_members_do(self):
        a = worker(1, "a", "81.61.1.9", network="hosting")
        b = worker(2, "b", "81.61.1.9")
        assert egress.group_by_egress([a, b])[0]["network_type"] == egress.HOSTING

    def test_malformed_system_info_does_not_raise(self):
        assert egress.egress_of({"system_info": "not-a-dict"}) is None
        assert egress.network_type_of({"system_info": None}) == egress.UNKNOWN
        assert egress.egress_of(None) is None


class TestDevicesPerIpLimit:
    def test_absent_means_undocumented_not_unlimited(self):
        assert egress.devices_per_ip_limit({"requirements": {}}) is None
        assert egress.devices_per_ip_limit({}) is None
        assert egress.devices_per_ip_limit(None) is None

    def test_zero_means_documented_as_unlimited(self):
        assert egress.devices_per_ip_limit(UNLIMITED) == 0

    def test_a_real_limit_is_read(self):
        assert egress.devices_per_ip_limit(ONE_PER_IP) == 1

    def test_garbage_is_undocumented_rather_than_guessed(self):
        assert egress.devices_per_ip_limit({"requirements": {"devices_per_ip": "one"}}) is None
        assert egress.devices_per_ip_limit({"requirements": {"devices_per_ip": -3}}) is None


class TestRunningSlugs:
    def test_only_running_containers_count(self):
        w = {"containers": [{"service": "a", "status": "running"}, {"service": "b", "status": "exited"}]}
        assert egress.running_slugs(w) == {"a"}

    def test_malformed_container_lists_are_ignored(self):
        assert egress.running_slugs({"containers": "[]"}) == set()
        assert egress.running_slugs({"containers": ["x", {"status": "running"}]}) == set()
        assert egress.running_slugs(None) == set()


class TestPreflightSeesTheRestOfTheFleet:
    """The differentiator: a single-host tool cannot see any of this."""

    def test_a_one_per_ip_service_on_a_sibling_behind_one_ip_earns_nothing(self):
        out = preflight.assess(ONE_PER_IP, worker=HOME_B, fleet_workers=[HOME_A, HOME_B])
        assert out["verdict"] == preflight.EARNS_NOTHING
        joined = " ".join(f["message"] for f in out["findings"])
        assert "watchtower" in joined, "the user has to know WHICH machine"
        assert "81.61.1.9" in joined

    def test_an_undocumented_limit_says_it_does_not_know(self):
        out = preflight.assess(UNDOCUMENTED, worker=HOME_B, fleet_workers=[HOME_A, HOME_B])
        assert out["verdict"] == preflight.CHECK_YOURSELF
        assert "documented" in " ".join(f["message"] for f in out["findings"])

    def test_a_documented_unlimited_service_is_only_reduced(self):
        out = preflight.assess(UNLIMITED, worker=HOME_B, fleet_workers=[HOME_A, HOME_B])
        assert out["verdict"] == preflight.REDUCED

    def test_a_documented_multi_device_limit_counts_the_instances(self):
        three = {"slug": "honeygain", "name": "Honeygain", "requirements": {"devices_per_ip": 3}}
        out = preflight.assess(three, worker=HOME_B, fleet_workers=[HOME_A, HOME_B])
        assert out["verdict"] == preflight.REDUCED

        crowded = [worker(i, f"w{i}", "81.61.1.9", running=["honeygain"]) for i in range(10, 13)]
        out = preflight.assess(three, worker=HOME_B, fleet_workers=[*crowded, HOME_B])
        assert out["verdict"] == preflight.EARNS_NOTHING

    def test_a_different_public_ip_is_not_a_conflict(self):
        out = preflight.assess(ONE_PER_IP, worker=REMOTE, fleet_workers=[HOME_A, REMOTE])
        assert out["verdict"] != preflight.EARNS_NOTHING

    def test_an_undetected_ip_produces_no_fleet_finding_at_all(self):
        """Better silent than inventing a conflict we did not observe."""
        out = preflight.assess(ONE_PER_IP, worker=UNSEEN, fleet_workers=[HOME_A, UNSEEN])
        assert out["findings"] == []
        assert "egress IP type" in out["not_checked"]

    def test_a_sibling_not_running_the_service_is_not_a_conflict(self):
        out = preflight.assess(ONE_PER_IP, worker=HOME_A, fleet_workers=[HOME_A, worker(9, "idle", "81.61.1.9")])
        assert out["findings"] == []

    def test_a_stopped_sibling_container_is_not_a_conflict(self):
        stopped = worker(9, "stopped", "81.61.1.9", running=["honeygain"], status="exited")
        out = preflight.assess(ONE_PER_IP, worker=HOME_B, fleet_workers=[stopped, HOME_B])
        assert out["findings"] == []

    def test_a_known_egress_ip_stops_advertising_it_as_unchecked(self):
        out = preflight.assess(UNLIMITED, worker=HOME_B, fleet_workers=[HOME_B])
        assert "egress IP type" not in out["not_checked"]
        assert "connection speed" in out["not_checked"]

    def test_it_still_never_blocks(self):
        out = preflight.assess(ONE_PER_IP, worker=HOME_B, fleet_workers=[HOME_A, HOME_B])
        assert out["blocking"] is False

    def test_no_fleet_context_degrades_to_the_old_behaviour(self):
        out = preflight.assess(ONE_PER_IP)
        assert out["verdict"] == preflight.LOOKS_FINE
        assert "egress IP type" in out["not_checked"]


class TestResidentialOnlyOnAHostedMachine:
    RESI = {
        "slug": "honeygain",
        "name": "Honeygain",
        "requirements": {"residential_ip": True, "vps_ip": False},
    }

    def test_a_hosted_worker_turns_the_precondition_into_a_verdict(self):
        out = preflight.assess(self.RESI, worker=REMOTE, fleet_workers=[REMOTE], system_info=REMOTE["system_info"])
        assert out["verdict"] == preflight.EARNS_NOTHING
        assert "hosted/VPS" in " ".join(f["message"] for f in out["findings"])

    def test_an_unknown_connection_stays_the_users_problem_not_a_false_pass(self):
        out = preflight.assess(self.RESI, worker=HOME_B, fleet_workers=[HOME_B], system_info=HOME_B["system_info"])
        assert out["verdict"] == preflight.CHECK_YOURSELF
        assert "cannot check" in " ".join(f["message"] for f in out["findings"])

    def test_it_is_stated_once_not_twice(self):
        out = preflight.assess(self.RESI, worker=REMOTE, fleet_workers=[REMOTE], system_info=REMOTE["system_info"])
        assert len([f for f in out["findings"] if "residential" in f["message"].lower()]) == 1


class TestWorkerSideDetection:
    def test_an_explicit_declaration_beats_the_hardware_guess(self, monkeypatch):
        from app import worker_api

        monkeypatch.setenv("CASHPILOT_WORKER_NETWORK", "residential")
        assert worker_api._detect_network_type() == egress.RESIDENTIAL

    def test_a_bad_declaration_falls_through_to_unknown(self, monkeypatch):
        from app import worker_api

        monkeypatch.setenv("CASHPILOT_WORKER_NETWORK", "datacenter")
        monkeypatch.setattr(worker_api, "_DMI_PATHS", ())
        assert worker_api._detect_network_type() == egress.UNKNOWN

    def test_a_hosting_vendor_in_dmi_is_detected(self, monkeypatch, tmp_path):
        from app import worker_api

        monkeypatch.delenv("CASHPILOT_WORKER_NETWORK", raising=False)
        vendor = tmp_path / "sys_vendor"
        vendor.write_text("DigitalOcean\n")
        monkeypatch.setattr(worker_api, "_DMI_PATHS", (str(tmp_path / "missing"), str(vendor)))
        assert worker_api._detect_network_type() == egress.HOSTING

    @pytest.mark.asyncio
    async def test_detection_can_be_switched_off(self, monkeypatch):
        from app import worker_api

        monkeypatch.setenv("CASHPILOT_EGRESS_DETECT", "off")
        assert await worker_api._detect_egress_ip() is None

    @pytest.mark.asyncio
    async def test_an_override_is_honoured_and_still_validated(self, monkeypatch):
        from app import worker_api

        monkeypatch.delenv("CASHPILOT_EGRESS_DETECT", raising=False)
        monkeypatch.setattr(worker_api, "_egress_cache", (None, 0.0))
        monkeypatch.setenv("CASHPILOT_EGRESS_IP", "81.61.1.9")
        assert await worker_api._detect_egress_ip() == "81.61.1.9"

        monkeypatch.setattr(worker_api, "_egress_cache", (None, 0.0))
        monkeypatch.setenv("CASHPILOT_EGRESS_IP", "192.168.1.5")
        assert await worker_api._detect_egress_ip() is None, "a LAN override is still a LAN address"

    @pytest.mark.asyncio
    async def test_every_endpoint_failing_yields_none_not_a_guess(self, monkeypatch):
        from app import worker_api

        for var in ("CASHPILOT_EGRESS_DETECT", "CASHPILOT_EGRESS_IP", "CASHPILOT_EGRESS_IP_URL"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr(worker_api, "_egress_cache", (None, 0.0))

        class Boom:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url):
                raise OSError("no network")

        monkeypatch.setattr(worker_api.httpx, "AsyncClient", lambda **kw: Boom())
        assert await worker_api._detect_egress_ip() is None

    @pytest.mark.asyncio
    async def test_a_lookup_response_is_validated_before_it_is_trusted(self, monkeypatch):
        from app import worker_api

        for var in ("CASHPILOT_EGRESS_DETECT", "CASHPILOT_EGRESS_IP", "CASHPILOT_EGRESS_IP_URL"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr(worker_api, "_egress_cache", (None, 0.0))

        class Resp:
            status_code = 200
            text = "<html>error page</html>"

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url):
                return Resp()

        monkeypatch.setattr(worker_api.httpx, "AsyncClient", lambda **kw: Client())
        assert await worker_api._detect_egress_ip() is None


class TestEndpoints:
    """Including the regression: worker rows arrive as JSON TEXT, not dicts."""

    def _call(self, fn, *args, workers=None):
        import asyncio
        import json
        from unittest.mock import AsyncMock, MagicMock, patch

        from app import main

        # Rows exactly as SQLite hands them back: containers/system_info are strings.
        rows = [
            {**w, "containers": json.dumps(w["containers"]), "system_info": json.dumps(w["system_info"])}
            for w in (workers or [])
        ]

        async def run():
            with (
                patch.object(main, "_require_auth_api", lambda r: None),
                patch.object(main.database, "list_workers", AsyncMock(return_value=rows)),
                patch.object(main.database, "get_deployments", AsyncMock(return_value=[])),
                patch.object(main.catalog, "get_service", return_value=ONE_PER_IP),
            ):
                return await fn(MagicMock(), *args)

        return asyncio.run(run())

    def test_preflight_with_a_worker_id_does_not_500_on_raw_json_columns(self):
        """Shipped code passed the raw TEXT column to code expecting a mapping."""
        out = self._call(main_preflight(), "honeygain", 2, workers=[HOME_A, HOME_B])
        assert out["verdict"] == "will_earn_nothing"
        assert "watchtower" in " ".join(f["message"] for f in out["findings"])

    def test_preflight_for_an_unknown_worker_is_a_404(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            self._call(main_preflight(), "honeygain", 99, workers=[HOME_A])
        assert exc.value.status_code == 404

    def test_preflight_without_a_worker_id_still_works(self):
        out = self._call(main_preflight(), "honeygain", None, workers=[HOME_A])
        assert out["blocking"] is False

    def test_egress_groups_reports_sharing_and_the_undetermined_separately(self):
        out = self._call(main_groups(), workers=[HOME_A, HOME_B, REMOTE, UNSEEN])
        assert out["shared_groups"] == 1
        assert out["undetermined"] == 1
        shared = next(g for g in out["groups"] if g["shared"])
        assert shared["egress_ip"] == "81.61.1.9"
        assert {w["name"] for w in shared["workers"]} == {"watchtower", "geiserback"}

    def test_egress_groups_on_an_empty_fleet_is_empty_not_an_error(self):
        out = self._call(main_groups(), workers=[])
        assert out == {"groups": [], "shared_groups": 0, "undetermined": 0}


def main_preflight():
    from app import main

    return main.api_service_preflight


def main_groups():
    from app import main

    return main.api_fleet_egress_groups
