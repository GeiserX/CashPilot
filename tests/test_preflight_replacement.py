"""A deploy that replaces a running copy is not a second device on the IP.

Since Mysterium declares one node per public IP, every ordinary redeploy of a
running node, an imported draft deployed onto a worker that already runs it,
and the deploy form's redeploy all asked preflight about the node they were
about to replace and were told it "will most likely earn nothing". A real
second copy, another instance on the same worker or a node on another worker
behind the same public IP, still warns.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import catalog, main, preflight, proxies

ROOT = Path(__file__).resolve().parent.parent
EXIT = "93.184.215.14"


def _worker(worker_id, *, running=0, egress_ip="88.12.34.56", slug="mysterium"):
    containers = [
        {"slug": slug, "name": f"cashpilot-{slug}" + (f"-{i}" if i > 1 else ""), "status": "running", "instance": i}
        for i in range(1, running + 1)
    ]
    return {
        "id": worker_id,
        "client_id": f"cid-{worker_id}",
        "name": f"node{worker_id}",
        "status": "online",
        "containers": containers,
        "system_info": {"egress_ip": egress_ip, "docker_available": True},
    }


async def _preflight(workers, *, instances=None, worker_id=1, recorded=None):
    with (
        patch.object(main, "_require_auth_api", lambda r: None),
        patch.object(main.database, "get_deployment_spec", AsyncMock(return_value=recorded)),
        patch.object(main.database, "list_workers", AsyncMock(return_value=workers)),
        patch.object(main, "_decoded_worker", lambda w: w),
    ):
        return await main.api_service_preflight(
            MagicMock(), "mysterium", worker_id=worker_id, planned=None, instances=instances
        )


def _per_ip(out):
    return [f for f in out["findings"] if "already running" in f["message"]]


class TestAReplacementIsNotASecondCopy:
    @pytest.mark.asyncio
    async def test_a_plain_redeploy_of_a_running_node_does_not_warn(self):
        # No instances: the deploy keeps the recorded count (redeploy, imported draft).
        out = await _preflight([_worker(1, running=1)])
        assert _per_ip(out) == []
        assert out["verdict"] != preflight.EARNS_NOTHING

    @pytest.mark.asyncio
    async def test_a_redeploy_at_its_recorded_count_does_not_warn(self):
        out = await _preflight([_worker(1, running=1)], recorded={"instances": 1})
        assert _per_ip(out) == []

    @pytest.mark.asyncio
    async def test_a_record_of_more_copies_than_run_starts_another_one(self):
        # No count asked: the deploy takes the recorded two, and one is not running.
        out = await _preflight([_worker(1, running=1)], recorded={"instances": 2})
        assert [f["verdict"] for f in _per_ip(out)] == [preflight.EARNS_NOTHING]

    @pytest.mark.asyncio
    async def test_the_deploy_forms_redeploy_at_the_same_count_does_not_warn(self):
        out = await _preflight([_worker(1, running=1)], instances=1)
        assert _per_ip(out) == []

    @pytest.mark.asyncio
    async def test_asking_for_another_copy_on_the_same_worker_still_warns(self):
        out = await _preflight([_worker(1, running=1)], instances=2)
        assert [f["verdict"] for f in _per_ip(out)] == [preflight.EARNS_NOTHING]
        assert "already running on this machine" in _per_ip(out)[0]["message"]

    @pytest.mark.asyncio
    async def test_a_node_on_another_worker_behind_the_same_ip_still_warns(self):
        out = await _preflight([_worker(1, running=1), _worker(2, running=1)])
        found = _per_ip(out)
        assert [f["verdict"] for f in found] == [preflight.EARNS_NOTHING]
        assert "already running on node2" in found[0]["message"]

    @pytest.mark.asyncio
    async def test_control_another_worker_on_its_own_ip_is_no_peer(self):
        out = await _preflight([_worker(1, running=1), _worker(2, running=1, egress_ip="81.2.3.4")])
        assert _per_ip(out) == []

    @pytest.mark.asyncio
    async def test_a_stopped_copy_is_not_one_the_deploy_replaces(self):
        # Copy 1 runs, copy 2 is stopped: asking for two starts a second device.
        workers = [_worker(1, running=2)]
        workers[0]["containers"][1]["status"] = "exited"
        out = await _preflight(workers, instances=2)
        assert [f["verdict"] for f in _per_ip(out)] == [preflight.EARNS_NOTHING]

    @pytest.mark.asyncio
    async def test_an_app_running_on_the_worker_is_nothing_a_deploy_replaces(self):
        # Android workers report apps, not containers: still a device on this IP.
        workers = [_worker(1)]
        workers[0]["apps"] = [{"slug": "mysterium", "running": True}]
        out = await _preflight(workers)
        assert [f["verdict"] for f in _per_ip(out)] == [preflight.EARNS_NOTHING]


class TestTheCountAcrossTheFleet:
    """With a limit above one, the replaced copy is the deploy itself, not one more."""

    SVC = {"slug": "demo", "name": "Demo", "requirements": {"devices_per_ip": 2}}

    def _assess(self, replacing):
        here = _worker(1, running=1, slug="demo")
        peer = _worker(2, running=1, slug="demo")
        return preflight.assess(
            self.SVC,
            already_deployed_slugs={"demo"},
            worker=here,
            fleet_workers=[here, peer],
            replacing=replacing,
        )

    def test_a_replacement_is_number_two(self):
        out = self._assess(True)
        found = _per_ip(out)
        assert [f["verdict"] for f in found] == [preflight.REDUCED]
        assert "this would be number 2" in found[0]["message"]

    def test_control_an_added_copy_is_number_three(self):
        found = _per_ip(self._assess(False))
        assert any(f["verdict"] == preflight.EARNS_NOTHING and "number 3" in f["message"] for f in found)


class TestEveryPathAsksTheRightQuestion:
    def _js(self, name):
        text = (ROOT / name).read_text(encoding="utf-8")
        return re.sub(r"(^|\s)//.*$", "", re.sub(r"/\*.*?\*/", "", text, flags=re.S), flags=re.M)

    def test_the_deploy_form_sends_the_copies_it_asks_for(self):
        js = self._js("app/static/js/app.js")
        body = js[js.index("async function _confirmPreflight") : js.index("async function _deployToWorkers")]
        assert "_instancesFor(slug, id)" in body and "&instances=${encodeURIComponent(n)}" in body
        # Left out when the form has no count, so the server reads it as a replacement.
        assert "n === undefined ? ''" in body

    def test_an_imported_draft_asks_without_a_count(self):
        # import.js has no instance inputs: _instancesFor finds none, so the
        # server sees no count and a worker already running the slug is replaced.
        imp = self._js("app/static/js/import.js")
        assert "CP.confirmPreflight(slug, ids)" in imp
        assert "instances-input" not in imp

    def test_the_fleet_move_and_the_redeploy_button_never_ask_preflight(self):
        fleet = self._js("app/templates/fleet.html")
        assert "/preflight" not in fleet and "confirmPreflight" not in fleet
        js = self._js("app/static/js/app.js")
        body = js[js.index("async function redeployOnWorker") : js.index("async function redeployWithImage")]
        assert "preflight" not in body.lower()


class TestTheProxiedCopy:
    def _workers(self):
        def copy(proxy_id):
            return {"slug": "mysterium", "status": "running", "proxy_id": proxy_id, "exit_ip": EXIT}

        two = _worker(2, running=1)
        two["system_info"]["proxied"] = [copy(7)]
        three = _worker(3)
        three["system_info"]["proxied"] = [copy(8)]
        return two, three

    def test_redeploying_a_copy_does_not_list_itself(self):
        two, _ = self._workers()
        assert proxies.same_exit_copies([two], "mysterium", EXIT, itself=(2, 7)) == []

    def test_another_copy_through_the_same_exit_is_listed(self):
        two, three = self._workers()
        assert proxies.same_exit_copies([two, three], "mysterium", EXIT, itself=(2, 7)) == ["node3 (through proxy 8)"]

    def test_the_endpoint_passes_the_copy_being_checked(self):
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert "proxies.same_exit_copies(workers, slug, exit_ip, itself=(worker_id, proxy_id))" in source


def test_mysterium_still_declares_one_node_per_ip():
    """The case that made this visible; if the limit goes, these tests prove less."""
    assert (catalog.get_service("mysterium").get("requirements") or {}).get("devices_per_ip") == 1
