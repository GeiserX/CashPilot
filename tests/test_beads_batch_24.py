"""CashPilot-eat / CashPilot-izt: the one credential needing a shell command had no hint.

``app/main.py`` reads credential guidance from ``collector.credential_hint``, and
``services/_schema.yml`` documents exactly that field. Thirteen services use it.
anyone-protocol alone carried its guidance in ``collector.credentials`` — a list
of ``{key, label, hint, type}`` dicts that nothing in the codebase reads.

That is the worst possible service to lose a hint on. Every other credential is
findable in a provider's web dashboard; this one is a relay fingerprint that
exists only on the operator's own machine and needs

    docker exec cashpilot-anyone-protocol anon --list-fingerprint

So the single credential that genuinely cannot be guessed was the single
credential with nothing on screen explaining where to get it. The input rendered
(``_COLLECTOR_ARGS["anyone-protocol"] = ["fingerprints"]``) with no hint beside
it — the user saw an empty box labelled "fingerprints".

Two beads, one cause: -eat filed the missing hint, -izt filed the unread field.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "services"

# Every key services/_schema.yml defines under `collector:`. A key outside this
# set is not a schema violation the app rejects — it is worse, because it is
# silently ignored, which is exactly how the anyone-protocol hint disappeared.
DOCUMENTED_COLLECTOR_KEYS = {
    "type",
    "notes",
    "per_node_earnings",
    "credential_hint",
    "credential_lifetime",
    "durable_alternative",
}


def catalog():
    out = {}
    for path in sorted(SERVICES.rglob("*.yml")):
        if path.name.startswith("_"):
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        out[data.get("slug", path.stem)] = data
    return out


class TestTheHintReachesTheFieldTheUIReads:
    def test_anyone_protocol_has_a_hint_at_all(self):
        collector = catalog()["anyone-protocol"]["collector"]
        assert collector.get("credential_hint"), "the fingerprint credential still has no guidance"

    def test_the_hint_still_carries_the_command(self):
        """The whole value of this hint: the credential is not in any dashboard."""
        hint = catalog()["anyone-protocol"]["collector"]["credential_hint"]
        assert "anon --list-fingerprint" in hint
        assert "docker exec" in hint

    def test_the_unread_field_is_gone(self):
        collector = catalog()["anyone-protocol"]["collector"]
        assert "credentials" not in collector, "guidance is back in a field nothing reads"

    def test_the_handler_reads_the_field_this_now_uses(self):
        """The premise. If main.py ever reads something else, this hint dies again."""
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert '.get("credential_hint")' in source

    def test_the_credential_input_is_still_declared(self):
        """A hint with no input beside it would be equally useless."""
        from app.collectors import _COLLECTOR_ARGS

        assert _COLLECTOR_ARGS["anyone-protocol"] == ["fingerprints"]


class TestNoServiceHidesGuidanceInAFieldNothingReads:
    """The general rule. Two beads were filed for one instance of it.

    An undocumented key under `collector:` is not rejected anywhere — it is
    silently ignored, so the author sees their YAML accepted and the user sees
    nothing. That is the failure mode worth a test.
    """

    def test_every_collector_key_is_one_the_schema_defines(self):
        offenders = []
        for slug, data in catalog().items():
            collector = data.get("collector") or {}
            unknown = set(collector) - DOCUMENTED_COLLECTOR_KEYS
            if unknown:
                offenders.append((slug, sorted(unknown)))
        assert not offenders, (
            f"these declare collector keys nothing reads: {offenders}. "
            "Undocumented keys are silently ignored — put user-facing guidance in "
            "credential_hint (see services/_schema.yml)."
        )

    def test_the_allowlist_matches_what_the_schema_documents(self):
        """Guards the guard: an allowlist that drifts from the schema proves nothing."""
        schema = (SERVICES / "_schema.yml").read_text(encoding="utf-8")
        start = schema.index("# collector:")
        block = schema[start : start + 2000]
        for key in ("type", "notes", "credential_hint", "per_node_earnings"):
            assert f"#   {key}:" in block, f"{key} is in the allowlist but not documented in _schema.yml"

    def test_the_documented_field_is_actually_used(self):
        """Guards against this passing because every hint was deleted."""
        with_hint = [slug for slug, d in catalog().items() if (d.get("collector") or {}).get("credential_hint")]
        assert len(with_hint) >= 10, f"only {len(with_hint)} services carry a credential hint"

    @pytest.mark.parametrize("slug", ["honeygain", "earnapp", "anyone-protocol"])
    def test_named_services_keep_their_hint(self, slug):
        assert (catalog()[slug].get("collector") or {}).get("credential_hint")


class TestTheHintSurvivesTheSanitiser:
    """A hint is inserted as markup, and the sanitiser strips what it does not keep.

    A previous fix found that a `rel` written into a hint is removed on its way
    to the DOM. The tags used here have to be ones that survive, or the guidance
    renders as stripped text with the command mangled.
    """

    def test_it_uses_only_tags_the_sanitiser_keeps(self):
        import re

        hint = catalog()["anyone-protocol"]["collector"]["credential_hint"]
        tags = {t.lower() for t in re.findall(r"<\s*([a-zA-Z]+)", hint)}
        allowed = {"a", "b", "code", "br", "i", "strong", "em"}
        assert tags <= allowed, f"hint uses tags the sanitiser will strip: {sorted(tags - allowed)}"

    def test_the_command_is_not_inside_a_link(self):
        """A shell command rendered as an anchor invites clicking, not copying."""
        hint = catalog()["anyone-protocol"]["collector"]["credential_hint"]
        anchor_start = hint.find("<a ")
        assert anchor_start == -1 or "anon --list-fingerprint" not in hint[anchor_start:]
