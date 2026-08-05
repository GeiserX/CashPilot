"""CashPilot-dw1: two container inventories that disagreed, with the cache deciding.

``get_status`` and ``get_status_light`` are the same two-phase discovery — label
-filtered containers first, then image-matched externals. ``get_status_cached``
serves whichever is current for the cache age.

They did not agree. ``get_status_light`` kept a ``seen_slugs`` set and emitted at
most **one** image-matched external per slug; ``get_status`` had no such set and
returned every match. So a host running a CashPilot-managed honeygain alongside
a hand-started one reported two containers or one depending purely on how warm
the cache was — and nothing in the code said so.

Reporting both is the correct side of that disagreement:

* the container IDs differ, so these are genuinely separate containers, and
  ``seen_ids`` already prevents counting one of them twice;
* the UI's per-instance rows exist precisely to show each one;
* two instances of one service on a single host is exactly what a user needs to
  see, because most providers pay per IP — hiding the second is hiding the
  reason their earnings are not doubling.

The related claim that ``get_status_light`` omits ``net_rx_bytes``/``net_tx_bytes``
where ``get_status`` emits them is real but harmless, and deliberately not
"fixed" here: ``net_activity.totals`` reads them with ``.get`` and returns None
when both are absent, so an omitted key and an explicit None are the same answer
— *unavailable*. The light path skips ``stats()`` on purpose because it is slow,
so it genuinely cannot know them, and writing 0.0 would be the lie this codebase
exists to avoid.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
ORCH = ROOT / "app" / "orchestrator.py"


def _container(*, cid, name, slug=None, image=None, status="running"):
    c = MagicMock()
    c.id = cid
    c.short_id = cid[:12]
    c.name = name
    c.status = status
    # Keyed off the real constants, never off literals. The label is
    # "cashpilot.deployed-by" with a HYPHEN; spelling it with an underscore made
    # the labeled path fall back to "unknown" and the fixture silently
    # unrealistic.
    from app.constants import LABEL_DEPLOYED_BY, LABEL_SERVICE

    c.labels = {LABEL_SERVICE: slug, LABEL_DEPLOYED_BY: "worker"} if slug else {}
    c.image.tags = [image] if image else []
    c.image.short_id = "sha256:abc"
    c.attrs = {"Created": "2026-08-05T00:00:00Z"}
    return c


class TestNeitherPathDropsARunningContainer:
    """The bead: the answer must not depend on which function was called."""

    IMAGE = "honeygain/desktop:latest"

    def _both_paths(self):
        """Same fixture through both functions, returning (full, light)."""
        out = []
        for fn in ("get_status", "get_status_light"):
            from app import orchestrator

            managed = _container(cid="managed-id", name="cashpilot-honeygain", slug="honeygain")
            external = _container(cid="external-id", name="my-own-honeygain", image=self.IMAGE)
            client = MagicMock()
            client.containers.list.side_effect = [[managed], [managed, external]]
            with (
                patch.object(orchestrator, "_get_client", return_value=client),
                patch.object(orchestrator, "_build_image_slug_map", return_value={self.IMAGE: "honeygain"}),
                patch.object(orchestrator, "_collect_stats_bulk", return_value={}),
            ):
                out.append(getattr(orchestrator, fn)())
        return out

    def test_the_two_paths_report_the_same_containers(self):
        """The whole defect, stated as one assertion."""
        full, light = self._both_paths()
        assert {c["container_id"] for c in full} == {c["container_id"] for c in light}, (
            "the inventory still depends on which function ran, so it depends on cache age"
        )

    def test_both_report_the_second_instance(self):
        full, light = self._both_paths()
        assert len(full) == 2
        assert len(light) == 2, "the light path is dropping a running container again"

    def test_both_keep_the_managed_and_the_external_apart(self):
        full, light = self._both_paths()
        for results in (full, light):
            assert {c["deployed_by"] for c in results} == {"worker", "external"}


class TestTheDedupeThatMustStay:
    def test_the_same_container_is_never_counted_twice(self):
        """Both scans can surface one container; ID dedupe is what stops that."""
        from app import orchestrator

        both = _container(cid="same-id", name="cashpilot-honeygain", slug="honeygain", image="honeygain/desktop:latest")
        client = MagicMock()
        client.containers.list.side_effect = [[both], [both]]
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "_build_image_slug_map", return_value={"honeygain/desktop:latest": "honeygain"}),
            patch.object(orchestrator, "_collect_stats_bulk", return_value={}),
        ):
            assert len(orchestrator.get_status_light()) == 1

    def test_the_id_set_is_still_consulted(self):
        """Structural: removing the slug set must not take the ID one with it."""
        tree = ast.parse(ORCH.read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "get_status_light")
        names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        assert "seen_ids" in names


class TestTheSlugSetIsGoneEntirely:
    def test_no_function_keeps_a_slug_dedupe_set(self):
        """Left in place but unread, it invites the next author to use it again."""
        assert "seen_slugs" not in ORCH.read_text(encoding="utf-8")

    def test_neither_function_declares_a_variable_nothing_reads(self):
        """A write-only set is how this divergence looked right up close."""
        tree = ast.parse(ORCH.read_text(encoding="utf-8"))
        for name in ("get_status", "get_status_light"):
            fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
            assigned = {t.id for n in ast.walk(fn) if isinstance(n, ast.AnnAssign | ast.Assign) for t in _targets(n)}
            loaded = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
            # Attribute calls like seen_ids.add() count as a load of seen_ids.
            unread = {v for v in assigned if v not in loaded and not v.startswith("_")}
            assert not unread, f"{name} declares {unread}, which nothing reads"


def _targets(node):
    if isinstance(node, ast.AnnAssign):
        return [node.target] if isinstance(node.target, ast.Name) else []
    return [t for t in node.targets if isinstance(t, ast.Name)]


class TestTheNetByteAsymmetryIsHarmless:
    """Checked rather than assumed, and deliberately left alone."""

    def test_totals_reads_the_keys_defensively(self):
        from app import net_activity

        assert net_activity.totals({}) is None
        assert net_activity.totals({"net_rx_bytes": None, "net_tx_bytes": None}) is None

    def test_an_omitted_key_and_an_explicit_none_agree(self):
        from app import net_activity

        assert net_activity.totals({}) == net_activity.totals({"net_rx_bytes": None})

    def test_the_light_path_does_not_invent_a_zero(self):
        """0.0 would read as "no traffic" for a counter it never sampled."""
        source = ORCH.read_text(encoding="utf-8")
        start = source.index("def get_status_light(")
        body = source[start : source.index("\ndef ", start + 10)]
        assert '"net_rx_bytes": 0' not in body
        assert '"net_tx_bytes": 0' not in body
