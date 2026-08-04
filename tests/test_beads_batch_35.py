"""CashPilot-3fr: two rows, one name, no way to tell them apart.

A worker redeployed with a new or empty ``/data`` — the appdata path changed,
the volume was recreated — registers under a fresh random ``client_id``. The old
row stays in the fleet list forever: offline, with its last-known container
pills, inflating the worker count.

Both rows carry the same display name, and the page rendered no id at all. So
the operator picked one to Remove by guesswork, and removing the LIVE one takes
that host out of the fleet.

The automatic purge cannot help here and should not be widened to. It only
deletes rows with no ``api_key_enc``, and the first heartbeat of every worker
sets that — so no row that ever heartbeated is eligible. The reason is written
into ``_check_stale_workers``: a host persists its key locally and re-presents
it, so deleting an enrolled row leaves no match for that key. Auto-deleting
enrolled rows trades a cosmetic duplicate for an outage.

What was actually missing is the information needed to choose correctly, so the
fix is to show it: the id on every card, a flag when a name is duplicated, and
the id in the removal prompt.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FLEET = ROOT / "app" / "templates" / "fleet.html"


def fleet_html() -> str:
    return FLEET.read_text(encoding="utf-8")


def without_comments(text: str) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in text.splitlines())


class TestTheIdIsVisible:
    """Asserted on the DISPLAYED element, not on the expression.

    The first version looked for `w.client_id ||` anywhere in the file. That
    expression also appears six times in the per-machine power inputs
    (CashPilot-jm6), which are data attributes the user never reads — so
    deleting the visible id left the test passing. What matters here is that
    something RENDERS it.
    """

    def _id_element(self) -> str:
        source = without_comments(fleet_html())
        marker = '<code style="font-size:0.68rem'
        assert marker in source, "no element renders the worker id on the card"
        start = source.index(marker)
        return source[start : source.index("</code>", start)]

    def test_every_card_renders_the_client_id(self):
        assert "w.client_id" in self._id_element()

    def test_it_falls_back_to_the_row_id(self):
        """A worker from before client_id existed still needs to be identifiable."""
        assert "'#' + w.id" in self._id_element()

    def test_the_id_is_escaped(self):
        """It reaches the DOM through innerHTML like everything else here."""
        assert "esc(" in self._id_element()

    def test_it_says_what_the_id_is_for(self):
        """A bare hex string with no explanation is not usable information."""
        assert "how to tell which is which" in fleet_html()


class TestDuplicateNamesAreFlagged:
    def test_the_page_counts_names(self):
        source = without_comments(fleet_html())
        assert "nameCounts" in source

    def test_it_marks_a_duplicated_name(self):
        source = without_comments(fleet_html())
        assert "duplicate name" in source

    def test_the_flag_explains_the_cause(self):
        """ "Duplicate" without the reason invites deleting the wrong row."""
        source = fleet_html()
        assert "redeployed with a new or empty /data" in source

    def test_it_tells_the_operator_what_to_compare(self):
        source = fleet_html()
        assert "Compare the ids and the last-seen times" in source

    def test_a_unique_name_is_not_flagged(self):
        """The control: the badge is conditional, not always rendered."""
        source = without_comments(fleet_html())
        assert "> 1 ?" in source, "the duplicate badge is not gated on a count"


class TestTheRemovalPromptNamesWhichOne:
    def test_it_takes_the_client_id(self):
        source = without_comments(fleet_html())
        assert "function removeWorker(workerId, name, clientId)" in source

    def test_the_handler_passes_it(self):
        source = without_comments(fleet_html())
        assert "removeWorker(id, name, btn.dataset.workerClient)" in source

    def test_the_button_carries_it(self):
        source = without_comments(fleet_html())
        assert "data-worker-client=" in source

    def test_the_prompt_shows_it(self):
        source = without_comments(fleet_html())
        assert "Id: ${clientId}" in source

    def test_the_existing_warning_survives(self):
        """The control: the re-enrolment explanation must not be lost."""
        source = fleet_html()
        assert "delete /data/.worker_key on that host" in source


class TestTheAutomaticPurgeIsDeliberatelyUnchanged:
    """Widening it would trade a cosmetic duplicate for a real outage."""

    def test_enrolled_rows_are_still_never_auto_deleted(self):
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert 'not w.get("api_key_enc")' in source, (
            "the purge now deletes enrolled workers; a host that persists its key would be dropped"
        )

    def test_the_reason_is_still_recorded(self):
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert "permanent fleet lockout" in source
