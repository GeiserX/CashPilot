"""CashPilot-ljx: a container you started yourself got live buttons that 404.

The worker's image matcher already answers this. ``app/orchestrator.py`` sets
``"deployed_by": "external"`` for a container matched by IMAGE rather than by
CashPilot's own label — one the user started themselves with ``docker run``.

``_get_all_worker_containers`` then rebuilt each container dict from scratch and
hardcoded ``"deployed_by": worker_name``, so the worker's answer was read
nowhere. ``grep -rn deployed_by app/`` showed the only readers were the two
writers in orchestrator.py and these two overwrites.

The result: that container appeared as an ordinary managed service — "Running"
badge, instance count, CPU/memory, and enabled Restart / Stop / Logs. Clicking
any of them returned ``404 Container for honeygain not found``, which reads as a
CashPilot bug on a service the same screen had just called Running.

The node name was never lost by preserving the flag: ``_node`` already carries
it, and is what the UI uses for per-instance labels.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "static" / "js" / "app.js"


def without_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in text.splitlines())


def _worker(containers, name="watchtower"):
    return {
        "id": 1,
        "client_id": f"cid-{name}",
        "name": name,
        "status": "online",
        "containers": json.dumps(containers),
        "apps": "[]",
        "system_info": json.dumps({"docker_available": True}),
    }


async def _containers(rows):
    from app import main

    with patch.object(main.database, "list_workers", AsyncMock(return_value=rows)):
        return await main._get_all_worker_containers()


MANAGED = {"slug": "honeygain", "name": "cashpilot-honeygain", "status": "running", "deployed_by": "watchtower"}
EXTERNAL = {"slug": "honeygain", "name": "honeygain", "status": "running", "deployed_by": "external"}


class TestTheWorkersAnswerSurvives:
    @pytest.mark.asyncio
    async def test_an_externally_started_container_stays_external(self):
        out = await _containers([_worker([EXTERNAL])])
        assert out[0]["deployed_by"] == "external", "the worker's answer is still being overwritten"

    @pytest.mark.asyncio
    async def test_a_managed_container_is_unaffected(self):
        """The control: this must not mark everything external."""
        out = await _containers([_worker([MANAGED])])
        assert out[0]["deployed_by"] != "external"

    @pytest.mark.asyncio
    async def test_a_container_with_no_answer_falls_back_to_the_node(self):
        """An older worker sends no deployed_by; the previous value is the sane default."""
        row = {"slug": "honeygain", "name": "x", "status": "running"}
        out = await _containers([_worker([row], name="geiserback")])
        assert out[0]["deployed_by"] == "geiserback"

    @pytest.mark.asyncio
    async def test_the_node_name_is_still_carried(self):
        """_node is what the UI labels instances with; it must not be collateral."""
        out = await _containers([_worker([EXTERNAL], name="geiserback")])
        assert out[0]["_node"] == "geiserback"


class TestTheEndpointReportsIt:
    async def _deployed(self, containers):
        from app import main

        with (
            patch.object(main, "_require_auth_api", lambda r: None),
            patch.object(main, "_require_reader", lambda r: None),
            patch.object(main, "_get_all_worker_containers", AsyncMock(return_value=containers)),
            patch.object(main.database, "get_deployments", AsyncMock(return_value=[])),
            patch.object(main.database, "get_earnings_summary", AsyncMock(return_value=[])),
            patch.object(main.database, "get_config", AsyncMock(return_value={})),
            patch.object(main.database, "get_health_scores", AsyncMock(return_value={})),
            patch.object(main.catalog, "get_service", lambda slug: {"name": "Honeygain", "slug": slug}),
        ):
            from unittest.mock import MagicMock

            return await main.api_services_deployed(MagicMock())

    def _instance(self, deployed_by):
        return {
            "slug": "honeygain",
            "name": "honeygain",
            "status": "running",
            "cpu_percent": 0,
            "memory_mb": 0,
            "deployed_by": deployed_by,
            "_node": "watchtower",
            "_worker_id": 1,
            "_has_docker": True,
            "_is_android": False,
        }

    @pytest.mark.asyncio
    async def test_an_external_only_service_is_flagged(self):
        rows = await self._deployed([self._instance("external")])
        assert rows[0]["unmanaged"] is True

    @pytest.mark.asyncio
    async def test_a_managed_service_is_not(self):
        rows = await self._deployed([self._instance("watchtower")])
        assert rows[0]["unmanaged"] is False

    @pytest.mark.asyncio
    async def test_a_mixed_service_keeps_its_buttons(self):
        """One managed instance can still be controlled.

        Flagging the whole row would remove the buttons that DO work; the
        per-instance flag marks the odd one out instead.
        """
        rows = await self._deployed([self._instance("external"), self._instance("watchtower")])
        assert rows[0]["unmanaged"] is False
        flags = [i["unmanaged"] for i in rows[0]["instance_details"]]
        assert sorted(flags) == [False, True]

    @pytest.mark.asyncio
    async def test_each_instance_carries_the_flag(self):
        rows = await self._deployed([self._instance("external")])
        assert rows[0]["instance_details"][0]["unmanaged"] is True


class TestTheUIStopsOfferingButtonsThatCannotWork:
    def _js(self):
        return without_comments(APP_JS.read_text(encoding="utf-8"))

    def test_the_row_reads_the_flag(self):
        assert "inst.unmanaged || svc.unmanaged" in self._js()

    def test_the_buttons_are_disabled(self):
        source = self._js()
        assert "Started outside CashPilot" in source
        i = source.index("const unmanaged = inst.unmanaged")
        assert "disabled" in source[i : i + 400]

    def test_the_reason_is_stated_rather_than_left_blank(self):
        """A dead button with no explanation reads as a broken app."""
        assert "manage it where you started it" in self._js()

    def test_the_row_is_labelled(self):
        source = self._js()
        assert "unmanagedLabel" in source
        assert ">Unmanaged<" in source

    def test_the_no_docker_case_still_has_its_own_message(self):
        """The control: this must not swallow the pre-existing disable reason."""
        assert 'title="No Docker access"' in self._js()


class TestTheWorkerStillComputesIt:
    """The premise. If orchestrator stops setting it, everything above is inert."""

    def test_the_image_matcher_marks_external_containers(self):
        source = (ROOT / "app" / "orchestrator.py").read_text(encoding="utf-8")
        assert source.count('"deployed_by": "external"') >= 2

    def test_labelled_containers_report_their_label(self):
        source = (ROOT / "app" / "orchestrator.py").read_text(encoding="utf-8")
        assert 'c.labels.get(LABEL_DEPLOYED_BY, "unknown")' in source


class TestTheMixedServiceSubRowsHonourTheFlag:
    """CodeRabbit, PR #212: the case this change was designed around was unfixed.

    A row with one managed and one external instance deliberately KEEPS its
    buttons, because the managed instance can still be controlled — and the
    per-instance flag was supposed to mark the odd one out. The sub-row renderer
    never read that flag, so the external instance inside a mixed service still
    offered Restart / Stop / Logs, and every one still answered 404.

    Marking a thing in the payload and ignoring it at the one place it matters
    leaves the bug exactly where it was.
    """

    def _js(self):
        return without_comments(APP_JS.read_text(encoding="utf-8"))

    def test_the_sub_row_reads_the_per_instance_flag(self):
        """Declared AND used — declaring it alone changes no behaviour."""
        source = self._js()
        assert "const iUnmanaged = inst.unmanaged || svc.unmanaged;" in source
        i = source.index("const iUnmanaged")
        assert "iUnmanaged" in source[i + 20 : i + 300], "the flag is declared but never read"

    def test_the_sub_row_disables_on_it(self):
        source = self._js()
        i = source.index("const iUnmanaged")
        block = source[i : i + 300]
        assert "disabled" in block
        assert "Started outside CashPilot" in block

    def test_the_sub_rows_no_docker_reason_survives(self):
        """The control: the pre-existing disable must not be swallowed."""
        source = self._js()
        i = source.index("const iUnmanaged")
        assert "iNoDocker ? ' disabled title=\"No Docker access\"'" in source[i : i + 400]

    def test_both_render_paths_now_check_it(self):
        """Single-instance and multi-instance are separate code paths.

        Fixing one and not the other is exactly what happened the first time.

        Asserted on the USE, not the declaration. The first version counted
        `unmanaged || svc.unmanaged` occurrences, which a revert that deleted
        only the disabledAttr ternary still satisfied — the variable stayed,
        unused, and the test passed against the broken state. Every
        disabledAttr assignment must mention the reason.
        """
        source = self._js()
        assignments = [line for line in source.splitlines() if "const disabledAttr" in line]
        assert len(assignments) >= 2, f"expected both render paths to build disabledAttr, found {assignments}"
        # The ternary wraps, so check the block after each assignment.
        for line in assignments:
            i = source.index(line)
            assert "Started outside CashPilot" in source[i : i + 300], (
                f"a render path builds disabledAttr without the unmanaged reason: {line.strip()}"
            )
