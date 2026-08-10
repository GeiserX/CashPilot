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


def worker(wid, name, ip=None, network=None, running=(), status="running", worker_status="online"):
    info = {"arch": "x86_64"}
    if ip is not None:
        info["egress_ip"] = ip
    if network is not None:
        info["egress_network_type"] = network
    return {
        "id": wid,
        "client_id": f"cid-{wid}",
        "name": name,
        "status": worker_status,
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

    def test_knowing_the_address_does_not_mean_knowing_the_type(self):
        """The label is about the connection TYPE. An IP says nothing about it.

        Dropping it because the address was found produced a response that
        claimed the type was checked while a finding beside it said it could not
        be — the exact self-contradiction the module forbids.
        """
        out = preflight.assess(UNLIMITED, worker=HOME_B, fleet_workers=[HOME_B])
        assert "egress IP type" in out["not_checked"]

    def test_a_known_connection_type_stops_advertising_it_as_unchecked(self):
        out = preflight.assess(UNLIMITED, worker=REMOTE, fleet_workers=[REMOTE])
        assert "egress IP type" not in out["not_checked"]
        assert "connection speed" in out["not_checked"]

    def test_the_local_instance_counts_towards_a_documented_limit(self):
        """Peers + the one already here + the new one. Omitting the local one
        under-warns in exactly the situation this feature exists for."""
        two = {"slug": "honeygain", "name": "Honeygain", "requirements": {"devices_per_ip": 2}}
        here = worker(7, "here", "81.61.1.9", running=["honeygain"])
        out = preflight.assess(
            two,
            already_deployed_slugs=egress.running_slugs(here),
            worker=here,
            fleet_workers=[here, HOME_A],
        )
        assert out["verdict"] == preflight.EARNS_NOTHING

    def test_two_unnamed_peers_do_not_render_as_a_repeated_phrase(self):
        anon = [
            {
                "id": i,
                "system_info": {"egress_ip": "81.61.1.9"},
                "containers": [{"slug": "honeygain", "status": "running"}],
            }
            for i in (20, 21)
        ]
        out = preflight.assess(ONE_PER_IP, worker=HOME_B, fleet_workers=[*anon, HOME_B])
        joined = " ".join(f["message"] for f in out["findings"])
        assert "machine 20" in joined and "machine 21" in joined

    def test_it_still_never_blocks(self):
        out = preflight.assess(ONE_PER_IP, worker=HOME_B, fleet_workers=[HOME_A, HOME_B])
        assert out["blocking"] is False

    def test_no_fleet_context_degrades_to_the_old_behaviour(self):
        out = preflight.assess(ONE_PER_IP)
        assert out["verdict"] == preflight.LOOKS_FINE
        assert "egress IP type" in out["not_checked"]


class TestOneFactOneSource:
    """The hosting verdict must not depend on a redundant kwarg."""

    RESI = {"slug": "honeygain", "name": "Honeygain", "requirements": {"residential_ip": True, "vps_ip": False}}

    def test_the_verdict_is_the_same_with_and_without_system_info(self):
        with_kwarg = preflight.assess(
            self.RESI, worker=REMOTE, fleet_workers=[REMOTE], system_info=REMOTE["system_info"]
        )
        without = preflight.assess(self.RESI, worker=REMOTE, fleet_workers=[REMOTE])
        assert with_kwarg["verdict"] == without["verdict"] == preflight.EARNS_NOTHING

    def test_an_explicit_system_info_still_wins(self):
        out = preflight.assess(self.RESI, worker=REMOTE, fleet_workers=[REMOTE], system_info={})
        assert out["verdict"] == preflight.CHECK_YOURSELF

    def test_a_malformed_system_info_does_not_raise(self):
        assert preflight.assess(self.RESI, worker={"system_info": "junk"})["blocking"] is False


class TestAndroidWorkersAreCounted:
    """A phone on the home WiFi plus a server is two devices on ONE public IP."""

    PHONE = {
        "id": 30,
        "client_id": "cid-30",
        "name": "phone",
        "system_info": {"egress_ip": "81.61.1.9", "device_type": "android"},
        "containers": [],
        "apps": [{"slug": "honeygain", "running": True}, {"slug": "grass", "running": False}],
    }

    def test_a_running_android_app_counts_as_a_device(self):
        assert egress.running_slugs(self.PHONE) == {"honeygain"}

    def test_a_phone_behind_the_same_ip_is_a_conflict(self):
        out = preflight.assess(ONE_PER_IP, worker=HOME_B, fleet_workers=[self.PHONE, HOME_B])
        assert out["verdict"] == preflight.EARNS_NOTHING
        assert "phone" in " ".join(f["message"] for f in out["findings"])


class TestSelfExclusion:
    def test_two_legacy_rows_with_no_client_id_do_not_cancel_each_other(self):
        """`None != None` is False, so keying on client_id hid real conflicts."""
        a = {
            "id": 40,
            "client_id": None,
            "name": "a",
            "system_info": {"egress_ip": "81.61.1.9"},
            "containers": [{"slug": "honeygain", "status": "running"}],
        }
        b = {"id": 41, "client_id": None, "name": "b", "system_info": {"egress_ip": "81.61.1.9"}, "containers": []}
        assert [w["id"] for w in egress.peers_sharing_egress(b, [a, b])] == [40]


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


class _FakeStream:
    """Stands in for httpx's streaming response so no test touches the network."""

    def __init__(self, body=b"", status=200, exc=None):
        self.body, self.status_code, self.exc = body, status, exc

    async def __aenter__(self):
        if self.exc:
            raise self.exc
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_bytes(self):
        yield self.body


class _FakeClient:
    def __init__(self, resp, seen):
        self._resp, self._seen = resp, seen

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, method, url):
        self._seen.append(url)
        return self._resp


@pytest.fixture
def no_network(monkeypatch):
    """Fail loudly if anything here would really reach the internet."""
    from app import worker_api

    for var in (
        "CASHPILOT_EGRESS_DETECT",
        "CASHPILOT_EGRESS_IP",
        "CASHPILOT_EGRESS_IP_URL",
        "CASHPILOT_WORKER_NETWORK",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(worker_api, "_egress_cache", (None, 0.0))
    seen: list[str] = []

    def install(resp):
        monkeypatch.setattr(worker_api.httpx, "AsyncClient", lambda **kw: _FakeClient(resp, seen))
        return seen

    install(_FakeStream(exc=AssertionError("a test tried to reach the network")))
    return install, seen


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

    def test_a_home_server_vendor_is_not_flagged_as_hosting(self, monkeypatch, tmp_path):
        """Verified against the real reference fleet, which reports this string."""
        from app import worker_api

        monkeypatch.delenv("CASHPILOT_WORKER_NETWORK", raising=False)
        vendor = tmp_path / "sys_vendor"
        vendor.write_text("ASUSTeK COMPUTER INC.\n")
        monkeypatch.setattr(worker_api, "_DMI_PATHS", (str(vendor),))
        assert worker_api._detect_network_type() == egress.UNKNOWN

    @pytest.mark.asyncio
    async def test_detection_can_be_switched_off(self, monkeypatch, no_network):
        from app import worker_api

        monkeypatch.setenv("CASHPILOT_EGRESS_DETECT", "off")
        assert await worker_api._detect_egress_ip() is None

    @pytest.mark.asyncio
    async def test_a_valid_override_skips_the_lookup_entirely(self, monkeypatch, no_network):
        from app import worker_api

        monkeypatch.setenv("CASHPILOT_EGRESS_IP", "81.61.1.9")
        assert await worker_api._detect_egress_ip() == "81.61.1.9"
        assert no_network[1] == [], "an override must not cause any request"

    @pytest.mark.asyncio
    async def test_an_invalid_override_warns_and_falls_back_to_lookup(self, monkeypatch, no_network, caplog):
        """192.168.x is what most people would call 'my IP'; silence is cruel."""
        from app import worker_api

        install, seen = no_network
        install(_FakeStream(b"81.61.1.9\n"))
        monkeypatch.setenv("CASHPILOT_EGRESS_IP", "192.168.1.5")
        with caplog.at_level("WARNING"):
            assert await worker_api._detect_egress_ip() == "81.61.1.9"
        assert "not a public address" in caplog.text
        assert seen, "it should still look the address up"

    @pytest.mark.asyncio
    async def test_a_custom_endpoint_is_used_alone_and_never_falls_back(self, monkeypatch, no_network):
        """Naming your own endpoint IS the opt-out; a quiet fallback undoes it."""
        from app import worker_api

        install, seen = no_network
        install(_FakeStream(b"not-an-ip"))
        monkeypatch.setenv("CASHPILOT_EGRESS_IP_URL", "https://my-own.example/ip")
        assert await worker_api._detect_egress_ip() is None
        assert seen == ["https://my-own.example/ip"], f"leaked to a third party: {seen}"

    @pytest.mark.asyncio
    async def test_a_response_is_validated_before_it_is_trusted(self, monkeypatch, no_network):
        from app import worker_api

        install, _ = no_network
        install(_FakeStream(b"<html>error page</html>"))
        assert await worker_api._detect_egress_ip() is None

    @pytest.mark.asyncio
    async def test_a_non_200_is_not_parsed(self, monkeypatch, no_network):
        from app import worker_api

        install, _ = no_network
        install(_FakeStream(b"81.61.1.9", status=503))
        assert await worker_api._detect_egress_ip() is None

    @pytest.mark.asyncio
    async def test_an_oversized_body_cannot_exhaust_memory(self, monkeypatch, no_network):
        from app import worker_api

        install, _ = no_network
        install(_FakeStream(b"81.61.1.9" + b"x" * 10_000_000))
        assert await worker_api._detect_egress_ip() is None, "truncated garbage is not an IP"

    @pytest.mark.asyncio
    async def test_a_stalled_endpoint_cannot_hang_the_heartbeat(self, monkeypatch, no_network):
        """A serial heartbeat loop means a hung lookup takes the worker offline."""
        import asyncio

        from app import worker_api

        async def never_returns(url):
            await asyncio.sleep(3600)

        monkeypatch.setattr(worker_api, "_fetch_egress_ip", never_returns)
        monkeypatch.setattr(worker_api, "_EGRESS_TOTAL_TIMEOUT", 0.05)
        assert await worker_api._detect_egress_ip() is None

    @pytest.mark.asyncio
    async def test_a_successful_lookup_is_cached(self, monkeypatch, no_network):
        from app import worker_api

        install, seen = no_network
        install(_FakeStream(b"81.61.1.9"))
        assert await worker_api._detect_egress_ip() == "81.61.1.9"
        assert await worker_api._detect_egress_ip() == "81.61.1.9"
        assert len(seen) == 1, "the second call must come from cache"

    @pytest.mark.asyncio
    async def test_a_failure_is_cached_too_so_a_blackhole_is_not_retried_every_minute(self, monkeypatch, no_network):
        from app import worker_api

        install, seen = no_network
        install(_FakeStream(b"nope"))
        assert await worker_api._detect_egress_ip() is None
        tried = len(seen)
        assert tried == len(worker_api._EGRESS_ENDPOINTS), "the first attempt should try each fallback"
        assert await worker_api._detect_egress_ip() is None
        assert len(seen) == tried, "a DROPped network would otherwise cost the timeout every heartbeat"

    @pytest.mark.asyncio
    async def test_the_cache_expires(self, monkeypatch, no_network):
        from app import worker_api

        install, seen = no_network
        install(_FakeStream(b"81.61.1.9"))
        assert await worker_api._detect_egress_ip() == "81.61.1.9"
        monkeypatch.setattr(worker_api, "_EGRESS_TTL_SECONDS", -1.0)
        assert await worker_api._detect_egress_ip() == "81.61.1.9"
        assert len(seen) == 2


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


class TestARetiredMachineMustNotFabricateAConflict:
    """An enrolled worker's row survives being switched off, forever.

    The stale-worker purge deliberately spares enrolled rows, and the last
    heartbeat it left behind still lists every container as running with its
    last-known egress IP. Counting those as peers would invent a conflict
    against a live machine — the opposite of this module's stated failure
    direction, which is to miss a conflict and never to invent one.
    """

    OFFLINE_PEER = worker(50, "old-server", "81.61.1.9", running=["honeygain"], worker_status="offline")
    LIVE = worker(51, "survivor", "81.61.1.9")

    def _preflight(self, workers, worker_id):
        import asyncio
        import json
        from unittest.mock import AsyncMock, MagicMock, patch

        from app import main

        rows = [
            {**w, "containers": json.dumps(w["containers"]), "system_info": json.dumps(w["system_info"])}
            for w in workers
        ]

        async def run():
            with (
                patch.object(main, "_require_auth_api", lambda r: None),
                patch.object(main.database, "list_workers", AsyncMock(return_value=rows)),
                patch.object(main.database, "get_deployments", AsyncMock(return_value=[])),
                patch.object(main.catalog, "get_service", return_value=ONE_PER_IP),
            ):
                return await main.api_service_preflight(MagicMock(), "honeygain", worker_id)

        return asyncio.run(run())

    def test_an_offline_peer_raises_no_conflict(self):
        out = self._preflight([self.OFFLINE_PEER, self.LIVE], 51)
        assert out["findings"] == [], "a machine that is switched off is not competing for the IP"

    def test_the_same_peer_online_does_raise_one(self):
        online = {**self.OFFLINE_PEER, "status": "online"}
        out = self._preflight([online, self.LIVE], 51)
        assert out["verdict"] == "will_earn_nothing"

    def test_an_offline_worker_can_still_be_assessed_itself(self):
        """A worker that just restarted must not 404 while its status catches up."""
        out = self._preflight([self.OFFLINE_PEER, self.LIVE], 50)
        assert out["blocking"] is False


class TestTheInstanceCountUsesMachinesNotNames:
    def test_two_distinct_peers_sharing_a_hostname_both_count(self):
        """WORKER_NAME defaults to the hostname; duplicate hostnames are ordinary."""
        two = {"slug": "honeygain", "name": "Honeygain", "requirements": {"devices_per_ip": 2}}
        me = worker(60, "me", "81.61.1.9")
        peers = [
            worker(61, "raspberrypi", "81.61.1.9", running=["honeygain"]),
            worker(62, "raspberrypi", "81.61.1.9", running=["honeygain"]),
        ]
        out = preflight.assess(two, worker=me, fleet_workers=[me, *peers])
        assert out["verdict"] == preflight.EARNS_NOTHING, "3 instances against a limit of 2"

    def test_the_message_still_names_each_machine_once(self):
        me = worker(63, "me", "81.61.1.9")
        peers = [
            worker(64, "pi", "81.61.1.9", running=["honeygain"]),
            worker(65, "pi", "81.61.1.9", running=["honeygain"]),
        ]
        out = preflight.assess(ONE_PER_IP, worker=me, fleet_workers=[me, *peers])
        message = " ".join(f["message"] for f in out["findings"])
        assert "pi, pi" not in message, "the display list should collapse duplicate names"


class TestAddressFormsThatCarrySomeoneElsesAddress:
    @pytest.mark.parametrize(
        "addr", ["::192.168.1.5", "::10.0.0.1", "fec0::1", "2002:c0a8:101::1", "64:ff9b::c0a8:101"]
    )
    def test_they_are_all_rejected(self, addr):
        assert egress.public_ip(addr) is None

    def test_the_compatible_form_of_a_public_address_matches_itself(self):
        """Grouping is string equality, so both forms must reduce to one key."""
        assert egress.public_ip("::81.61.1.9") == egress.public_ip("81.61.1.9") == "81.61.1.9"


class TestTheHeartbeatSurvivesABadCycle:
    @pytest.mark.asyncio
    async def test_one_failing_cycle_does_not_end_the_loop(self, monkeypatch):
        """A dead task means offline until someone restarts the container."""
        import asyncio

        from app import worker_api

        calls = []

        async def flaky():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("docker_available blew up")

        monkeypatch.setattr(worker_api, "_send_heartbeat", flaky)
        monkeypatch.setattr(worker_api, "HEARTBEAT_INTERVAL", 0)
        task = asyncio.create_task(worker_api._heartbeat_loop())
        for _ in range(20):
            await asyncio.sleep(0)
            if len(calls) >= 3:
                break
        task.cancel()
        assert len(calls) >= 3, "the loop stopped after the first exception"


class TestAdvertisedHost:
    """Parsing the host out of an advertised dial-back address."""

    @pytest.mark.parametrize(
        ("raw", "host"),
        [
            ("84.54.25.89:28967", "84.54.25.89"),
            ("mynode.ddns.net:28967", "mynode.ddns.net"),
            ("mynode.ddns.net", "mynode.ddns.net"),
            ("[2001:db8::1]:28967", "2001:db8::1"),
            ("2001:db8::1", "2001:db8::1"),
            ("  host:1  ", "host"),
        ],
    )
    def test_host_is_extracted(self, raw, host):
        assert egress.advertised_host(raw) == host

    @pytest.mark.parametrize("raw", ["", "   ", None, "[]:28967"])
    def test_nothing_usable_is_none(self, raw):
        assert egress.advertised_host(raw) is None


class TestAdvertisedAddressVerdict:
    """The Aug 2026 storj incident, as a decision table.

    The node advertised a stale literal IP after a silent ISP re-provision;
    satellites dialled a dead address for days while the container looked
    healthy. The verdict's job is to catch exactly that — and its NO-CLAIM
    rows matter as much as its findings, because a wrong "your address is
    stale" sends the operator to fix DNS that is fine.
    """

    EGRESS = "213.217.28.154"

    def test_the_incident_a_stale_literal_ip_is_a_finding(self):
        reason = egress.advertised_address_verdict("84.54.25.89:28967", self.EGRESS, None)
        assert reason and "84.54.25.89" in reason and self.EGRESS in reason

    def test_a_literal_matching_the_egress_is_no_finding(self):
        assert egress.advertised_address_verdict(f"{self.EGRESS}:28967", self.EGRESS, None) is None

    def test_a_private_literal_is_a_finding_without_any_egress_comparison(self):
        reason = egress.advertised_address_verdict("192.168.10.100:28967", self.EGRESS, None)
        assert reason and "private" in reason

    def test_a_hostname_resolving_to_the_egress_is_no_finding(self):
        assert egress.advertised_address_verdict("node.example.org:28967", self.EGRESS, {self.EGRESS}) is None

    def test_a_hostname_resolving_elsewhere_is_a_finding(self):
        reason = egress.advertised_address_verdict("node.example.org:28967", self.EGRESS, {"84.54.25.89"})
        assert reason and "node.example.org" in reason and "84.54.25.89" in reason

    def test_a_name_that_definitively_does_not_resolve_is_a_finding(self):
        reason = egress.advertised_address_verdict("gone.example.org:28967", self.EGRESS, set())
        assert reason and "does not resolve" in reason

    # -- the no-claim rows: silence must mean "cannot tell", never "fine" -----

    def test_transient_resolution_failure_is_no_claim(self):
        assert egress.advertised_address_verdict("node.example.org:28967", self.EGRESS, None) is None

    def test_undetected_egress_is_no_claim_even_for_a_wrong_literal(self):
        # Negative control: the strongest possible finding input must still be
        # silent when the machine's own egress is unknown.
        assert egress.advertised_address_verdict("84.54.25.89:28967", None, None) is None

    def test_no_advertised_address_is_no_claim(self):
        assert egress.advertised_address_verdict(None, self.EGRESS, {"1.2.3.4"}) is None
        assert egress.advertised_address_verdict("", self.EGRESS, {"1.2.3.4"}) is None


class TestAdvertisedAddressCatalog:
    """The schema key is only useful if it names an env var that exists."""

    def test_storj_declares_its_dial_back_env(self):
        from app.catalog import load_services

        storj = next(s for s in load_services() if s.get("slug") == "storj")
        assert (storj.get("docker") or {}).get("advertised_address_env") == "ADDRESS"

    def test_every_declared_address_env_exists_in_that_services_env_list(self):
        # A typo here would make the worker look up an env var that is never
        # set, silently reporting nothing — the same failure mode this whole
        # feature exists to end.
        from app.catalog import load_services

        for svc in load_services():
            docker = svc.get("docker") or {}
            var = docker.get("advertised_address_env")
            if not var:
                continue
            keys = {e.get("key") for e in (docker.get("env") or [])}
            assert var in keys, f"{svc.get('slug')}: advertised_address_env={var!r} names no declared env var"
