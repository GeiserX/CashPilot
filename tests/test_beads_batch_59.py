"""The server turned "the phone could not tell" into "stopped".

``app/main.py`` built each Android app's row with::

    "status": "running" if a.get("running") else "stopped"

The Android client now sends ``running: null`` when it cannot determine the
answer — every one of its detection signals degrades to ``false`` when
notification and usage access are denied, so it used to report *every* earning
app as stopped. That was fixed on the phone (CashPilot-android-1oo); this is the
other half, because a falsy ``None`` landed in the same ``else`` branch here and
the fleet page inherited the identical false claim.

The distinction is not cosmetic. **Stopped** means the service should be
reporting and is not — restart it. **Unknown** means the worker could not see —
grant the permission. Collapsing them sends a user to fix the wrong thing.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "app" / "main.py"
CSS = ROOT / "app" / "static" / "css" / "style.css"
APP_JS = ROOT / "app" / "static" / "js" / "app.js"


class TestUnknownIsNotStopped:
    @pytest.mark.parametrize(
        ("running", "expected"),
        [(None, "unknown"), (True, "running"), (False, "stopped")],
        ids=["could-not-tell", "alive", "really-stopped"],
    )
    def test_the_three_answers_stay_three(self, running, expected):
        from app.main import _android_app_status

        assert _android_app_status(running) == expected

    def test_a_real_stopped_is_still_reported(self):
        """The fix is worthless if a genuine negative stops being surfaced."""
        from app.main import _android_app_status

        assert _android_app_status(False) == "stopped"

    def test_no_two_answers_collapse(self):
        from app.main import _android_app_status

        answers = [_android_app_status(v) for v in (None, True, False)]
        assert len(set(answers)) == 3, f"two states share a spelling: {answers}"

    def test_the_old_truthiness_expression_is_gone(self):
        """The old form put ``None`` in the ``else`` branch alongside ``False``.

        Checked against EXECUTABLE lines only. The comment explaining the fix
        necessarily quotes the expression it replaced, and the first version of
        this test matched its own explanation — the fourth time that trap has
        appeared in this project.
        """
        code = [ln for ln in MAIN.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("#")]
        offenders = [ln.strip() for ln in code if 'if a.get("running") else' in ln]
        assert not offenders, offenders

    def test_the_heartbeat_path_uses_the_helper(self):
        """Structural: the row builder must call it, not re-derive the status."""
        tree = ast.parse(MAIN.read_text(encoding="utf-8"))
        calls = {
            node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "_android_app_status" in calls


class TestAggregationPrefersAKnownFact:
    """``best_status`` picks the lowest priority number across instances."""

    def _priority(self) -> dict:
        text = MAIN.read_text(encoding="utf-8")
        line = next(ln for ln in text.splitlines() if "_STATUS_PRIORITY = {" in ln)
        return ast.literal_eval(line.split("=", 1)[1].strip())

    def test_unknown_is_ranked_explicitly(self):
        """Relying on the `.get(cur, 9)` fallback leaves it undeclared."""
        assert "unknown" in self._priority()

    def test_a_known_status_always_beats_unknown(self):
        """Running on one worker and unknown on another must read as running."""
        priority = self._priority()
        unknown = priority["unknown"]
        for status, rank in priority.items():
            if status != "unknown":
                assert rank < unknown, f"{status!r} ranks worse than unknown, so a blind spot would win"

    def test_running_is_still_the_best_answer(self):
        priority = self._priority()
        assert priority["running"] == min(priority.values())


class TestTheUIDistinguishesThem:
    def test_unknown_has_its_own_badge(self):
        assert ".badge-unknown" in CSS.read_text(encoding="utf-8")

    def test_unknown_has_its_own_dot(self):
        assert ".status-dot.unknown" in CSS.read_text(encoding="utf-8")

    def test_unknown_is_not_coloured_like_stopped(self):
        """Same colour is the same claim, whatever the label says."""
        css = CSS.read_text(encoding="utf-8")
        unknown = re.search(r"\.status-dot\.unknown\s*\{([^}]*)\}", css).group(1)
        stopped = re.search(r"\.status-dot\.stopped\s*\{([^}]*)\}", css).group(1)
        assert unknown.strip() != stopped.strip(), "unknown and stopped render identically"

    def test_the_frontend_derives_the_class_from_the_status(self):
        """It builds `badge-${status}`, so a new status needs no JS change —
        only the CSS above. This pins that assumption."""
        js = APP_JS.read_text(encoding="utf-8")
        assert "badge-${statusClass}" in js
        assert "svc.container_status" in js
