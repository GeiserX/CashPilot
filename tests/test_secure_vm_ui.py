"""The Fleet page's Secure VM: the commands that add, check and remove one.

A Secure VM (scripts/cashpilot-vm) is installed as root on its host, so the UI
only shows the owner a command, pinned to the release tag and the script's
sha256. A host without a Secure VM gets the install command with this UI's
address and the host's own name; a host with one gets status, verify and
remove. A phone, a Desktop and a Secure VM itself are not hosts for one.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import database, layer_scripts, main
from app.routers import secure_vm

ROOT = Path(__file__).resolve().parents[1]


def _worker(wid, name, **info):
    return {"id": wid, "name": name, "system_info": json.dumps({"os": "Linux 6.12", **info}), "containers": "[]"}


def _vm_of(host, wid=9):
    return _worker(
        wid,
        f"{host}-secure-vm",
        features=["secure_vm"],
        secure_vm={"host": host, "fence": {"state": "ok", "checked_at": 1}},
    )


def _get(workers, wid=7, ui_url="http://ui.lan:8080"):
    with (
        patch.object(database, "list_workers", AsyncMock(return_value=workers)),
        patch.object(secure_vm.deps, "_require_owner", return_value={"r": "owner"}),
        patch.object(layer_scripts.version, "current", return_value="3.1.0"),
    ):
        return TestClient(main.app).get(f"/api/workers/{wid}/secure-vm/commands", params={"ui_url": ui_url})


class TestTheCommands:
    def test_a_host_without_one_gets_the_install_command(self):
        resp = _get([_worker(7, "box")])
        assert resp.status_code == 200, resp.text
        cmd = resp.json()["install"]
        assert "/GeiserX/CashPilot/v3.1.0/scripts/cashpilot-vm" in cmd
        assert layer_scripts.sha256("cashpilot-vm") in cmd
        # --ref: the guest's compose file comes from the same release as the script.
        assert cmd.endswith(
            'sudo bash "$d/cashpilot-vm" install --ui http://ui.lan:8080 --host-worker box --ref v3.1.0'
        )

    def test_the_fleet_key_is_never_in_the_command(self):
        with patch.dict("os.environ", {"CASHPILOT_API_KEY": "fleet-key-must-not-leak"}):
            resp = _get([_worker(7, "box")])
        assert "fleet-key-must-not-leak" not in resp.text

    def test_a_host_with_one_gets_status_verify_and_remove(self):
        resp = _get([_worker(7, "box"), _vm_of("box")])
        assert resp.status_code == 200, resp.text
        out = resp.json()
        assert set(out) == {"status", "verify", "remove"}
        assert out["remove"].endswith('sudo bash "$d/cashpilot-vm" remove')

    def test_another_hosts_vm_does_not_count(self):
        resp = _get([_worker(7, "box"), _vm_of("other")])
        assert set(resp.json()) == {"install"}

    def test_the_host_name_is_quoted(self):
        # The installer allows spaces; anything a shell would read never gets this far.
        resp = _get([_worker(7, "my box")])
        assert "--host-worker 'my box'" in resp.json()["install"]

    def test_only_the_ui_address_is_kept(self):
        resp = _get([_worker(7, "box")], ui_url="https://ui.example/fleet?x=1#y")
        assert resp.json()["install"].endswith("--ui https://ui.example --host-worker box --ref v3.1.0")

    @pytest.mark.parametrize(
        "bad",
        [
            "ftp://ui.example",
            "http://",
            "http://user:pw@ui.example",
            "http://ui.example/ x",
            "javascript:alert(1)",
            "http://" + "a" * 300,
        ],
    )
    def test_a_bad_ui_address_is_a_400(self, bad):
        assert _get([_worker(7, "box")], ui_url=bad).status_code == 400

    @pytest.mark.parametrize(
        "worker",
        [
            _worker(7, "phone", os="Android", device_type="android"),
            _worker(7, "laptop", device_type="desktop"),
            _vm_of("box", wid=7),
        ],
    )
    def test_a_phone_a_desktop_or_a_vm_is_not_a_host(self, worker):
        assert _get([worker]).status_code == 400

    def test_an_unknown_worker_is_a_404(self):
        assert _get([_worker(7, "box")], wid=8).status_code == 404

    def test_a_dev_build_says_why_there_is_none(self):
        with patch.object(layer_scripts.version, "current", return_value="dev"):
            out = secure_vm.commands("box", "http://ui", False)
        assert "development build" in out["error"]

    def test_it_needs_the_owner(self):
        with patch.object(
            secure_vm.deps, "_require_owner", side_effect=HTTPException(status_code=403, detail="Owner only")
        ):
            resp = TestClient(main.app).get("/api/workers/7/secure-vm/commands", params={"ui_url": "http://ui"})
        assert resp.status_code == 403


class TestTheShippedFiles:
    def test_the_ui_image_ships_the_script(self):
        assert "scripts/cashpilot-vm" in (ROOT / "Dockerfile").read_text()
        assert "!scripts/cashpilot-vm" in (ROOT / ".dockerignore").read_text().splitlines()

    def test_the_fleet_page_loads_the_hooks_before_its_own_script(self):
        page = (ROOT / "app/templates/fleet.html").read_text()
        assert page.index('{% include "_secure_vm.html" %}') < page.index("globalThis.CPSecureVM ?")

    def test_every_string_the_panel_uses_is_in_english(self):
        source = json.loads((ROOT / "app/i18n/en.json").read_text(encoding="utf-8"))
        panel = (ROOT / "app/templates/_secure_vm.html").read_text()
        keys = set(re.findall(r"\bt\('([a-z0-9_.]+)'", panel))
        assert keys, "the check found no keys"
        assert keys <= set(source), sorted(keys - set(source))
        # The fence states come in through a template string.
        assert {f"layers.vm.fence_{s}" for s in ("ok", "stale", "failed", "unknown")} <= set(source)


class TestTwoWorkersWithOneName:
    # A Secure VM names its host by worker name. When two workers share it
    # (an old offline one and its replacement), the VM belongs to neither.

    def test_the_commands_are_refused_until_one_is_renamed(self):
        resp = _get([_worker(7, "box"), _worker(8, "box"), _vm_of("box")])
        assert resp.status_code == 409
        assert "Two workers are called box" in resp.json()["detail"]

    def test_vm_host_picks_only_a_unique_name(self):
        workers = [_worker(7, "box"), _worker(8, "nas"), _vm_of("box")]
        vm = secure_vm.placement.system_info(workers[2])
        assert secure_vm.vm_host(vm, workers)["id"] == 7
        assert secure_vm.vm_host(vm, [*workers, _worker(10, "box")]) is None
        # The VM itself never counts as its own host.
        assert secure_vm.vm_host(vm, [_vm_of("box")]) is None

    def test_the_fleet_page_matches_the_same_way(self):
        js = (ROOT / "app/templates/_secure_vm.html").read_text()
        assert "hosts.length === 1 ? hosts[0] : null" in js


class TestWhatTheInstallerWouldRefuse:
    @pytest.mark.parametrize("url", ["http://[::1", "http://["])
    def test_an_unparseable_ui_address_is_a_400(self, url):
        assert _get([_worker(7, "box")], ui_url=url).status_code == 400

    def test_a_public_http_ui_is_refused_before_the_install(self):
        # The guest's worker never sends its key over http to a public host.
        resp = _get([_worker(7, "box")], ui_url="http://203.0.113.9:8080")
        assert resp.status_code == 400
        assert "https" in resp.json()["detail"]
        assert _get([_worker(7, "box")], ui_url="http://192.168.1.5:8080").status_code == 200
        assert _get([_worker(7, "box")], ui_url="https://cashpilot.example.com").status_code == 200

    def test_a_public_http_ui_still_gets_the_commands_for_an_existing_vm(self):
        # status, verify and remove never use the UI address.
        resp = _get([_worker(7, "box"), _vm_of("box")], ui_url="http://203.0.113.9:8080")
        assert resp.status_code == 200, resp.text
        assert set(resp.json()) == {"status", "verify", "remove"}

    @pytest.mark.parametrize("name", ["box$(id)", "b" * 65, "café"])
    def test_a_host_name_the_installer_refuses_gets_no_command(self, name):
        resp = _get([_worker(7, name)])
        assert resp.status_code == 200
        assert "install" not in resp.json()
        assert "Rename the worker" in resp.json()["error"]
