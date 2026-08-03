"""No service-specific knowledge in ``app/`` outside the collectors.

The repo states the rule plainly: "YAML is the source of truth. Every service
lives in ``services/{category}/{slug}.yml``. The web UI, container deployment,
earnings collection, and documentation ALL derive from these files. Never
hardcode service-specific logic in ``app/``."

A rule with no test is a preference. This one had already drifted twice:

* 13 per-service credential hints — prose about where to find a token in a
  provider's own UI — lived in a dict inside ``api_collectors_meta``, out of
  reach of anyone editing the service they describe.
* ``api_per_node_earnings`` branched on ``slug == "mysterium"`` and imported
  that collector class by name, so a second service reporting per-node figures
  meant editing a route handler.

``app/collectors/`` is exempt by design — the architecture is explicitly one
collector module per service.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "services"


def catalogued_slugs() -> set[str]:
    return {p.stem for p in SERVICES.rglob("*.yml") if not p.name.startswith("_")}


#: Literals that match a slug but are not one. Each needs a reason, because an
#: allowlist that grows without justification is how the rule dies quietly.
ALLOWED = {
    # A CoinGecko coin id that happens to equal the slug. It identifies a coin
    # on a third-party price API, not a CashPilot service, and the mapping it
    # lives in is keyed by CURRENCY code.
    ("app/exchange_rates.py", "mysterium"),
}


def slug_literals() -> list[tuple[str, int, str]]:
    slugs = catalogued_slugs()
    found: list[tuple[str, int, str]] = []
    for path in sorted((ROOT / "app").rglob("*.py")):
        if "collectors" in path.parts:
            continue
        rel = str(path.relative_to(ROOT))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in slugs:
                if (rel, node.value) in ALLOWED:
                    continue
                found.append((rel, node.lineno, node.value))
    return found


class TestNoServiceIsNamedInApplicationCode:
    def test_no_slug_literal_survives_outside_the_collectors(self):
        offenders = slug_literals()
        assert not offenders, (
            "service-specific literals in app/: "
            + ", ".join(f"{f}:{n} -> {s!r}" for f, n, s in offenders)
            + ". Declare the behaviour in the service YAML and read it from the catalog."
        )

    def test_the_scan_is_not_vacuous(self):
        """A broken parser or an empty slug set would pass the test above."""
        slugs = catalogued_slugs()
        assert len(slugs) >= 40, f"only {len(slugs)} slugs found — the catalog scan is wrong"
        assert {"honeygain", "mysterium", "storj"} <= slugs

    def test_the_detector_would_catch_a_new_hardcode(self):
        """Proved against a planted literal rather than assumed."""
        import tempfile

        slugs = catalogued_slugs()
        with tempfile.TemporaryDirectory() as tmp:
            planted = Path(tmp) / "planted.py"
            planted.write_text('if slug == "honeygain":\n    pass\n', encoding="utf-8")
            tree = ast.parse(planted.read_text(encoding="utf-8"))
            hits = [
                n.value
                for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in slugs
            ]
        assert hits == ["honeygain"], "the detector cannot see a hardcoded slug"

    def test_every_allowlist_entry_still_exists(self):
        """A stale exemption silently widens the rule."""
        for rel, value in ALLOWED:
            source = (ROOT / rel).read_text(encoding="utf-8")
            assert value in source, f"{rel} no longer contains {value!r} — drop the exemption"


class TestCredentialHintsLiveInTheCatalog:
    def test_the_hardcoded_dict_is_gone(self):
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert "press F12" not in source, "credential hints are back in app/"
        assert "hints: dict[str, str]" not in source

    def test_the_endpoint_reads_them_from_the_service(self):
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert 'get("credential_hint")' in source

    def test_the_hints_survived_the_move(self):
        """13 services carried one; losing any is a silent loss of help text."""
        with_hint = [
            p.stem
            for p in SERVICES.rglob("*.yml")
            if not p.name.startswith("_")
            and ((yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("collector") or {}).get("credential_hint")
        ]
        assert len(with_hint) == 13, (
            f"expected 13 services with a credential hint, found {len(with_hint)}: {sorted(with_hint)}"
        )

    @pytest.mark.parametrize("slug", ["bytelixir", "earnapp", "grass", "packetstream", "proxyrack"])
    def test_the_ones_that_explain_a_browser_dance_are_all_present(self, slug):
        """These are the hints a user genuinely cannot proceed without."""
        path = next(SERVICES.rglob(f"{slug}.yml"))
        hint = (yaml.safe_load(path.read_text(encoding="utf-8")).get("collector") or {}).get("credential_hint")
        assert hint and len(hint) > 50, f"{slug} lost its credential hint"


class TestPerNodeEarningsIsDeclaredNotBranchedOn:
    def test_the_handler_no_longer_names_a_service(self):
        """Checked as CODE, not as text.

        The text version of this test failed on the comment that explains what
        was removed — grepping source for `slug == "mysterium"` matched the
        prose describing the deleted branch. A guard that reads comments is a
        guard that punishes documenting the fix, and it is the third time this
        session that a text-matching check has fired on its own explanation.
        The AST sees code and nothing else.
        """
        tree = ast.parse((ROOT / "app" / "main.py").read_text(encoding="utf-8"))
        handler = next(
            n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "api_per_node_earnings"
        )
        compared = {
            c.value
            for node in ast.walk(handler)
            if isinstance(node, ast.Compare)
            for c in node.comparators
            if isinstance(c, ast.Constant) and isinstance(c.value, str)
        }
        assert not (compared & catalogued_slugs()), f"handler still compares against {compared & catalogued_slugs()}"

        imported = {
            node.module
            for node in ast.walk(handler)
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app.collectors.")
        }
        assert not imported, f"handler imports a specific collector: {imported}"

    def test_the_capability_is_declared_in_yaml(self):
        path = next(SERVICES.rglob("mysterium.yml"))
        collector = yaml.safe_load(path.read_text(encoding="utf-8")).get("collector") or {}
        assert collector.get("per_node_earnings") is True

    def test_exactly_one_service_claims_it_today(self):
        """If a second appears, it should be because someone added the line."""
        claiming = [
            p.stem
            for p in SERVICES.rglob("*.yml")
            if not p.name.startswith("_")
            and ((yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("collector") or {}).get("per_node_earnings")
        ]
        assert claiming == ["mysterium"], claiming

    def test_the_schema_documents_both_new_fields(self):
        schema = (SERVICES / "_schema.yml").read_text(encoding="utf-8")
        assert "credential_hint" in schema
        assert "per_node_earnings" in schema
