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


class TestTheDeadCodeDecisionsHold:
    """Two half-alive things in machine_economics, decided rather than ignored.

    `per_service_is_meaningful` was called only by its own tests while the one
    code path that needed it — per-service electricity attribution in
    `api_earnings_net` — did without it. That is not dead code; it is a guard
    that was never connected.

    `DEFAULT_IDLE_WATTS` genuinely was dead, and worse than dead: the same
    number (65.0) with the same meaning as `power.DEFAULT_HOST_TDP_WATTS`,
    which has a real consumer. Two constants for one quantity drift apart
    silently and force the next reader to guess which is authoritative.
    """

    def test_the_guard_is_wired_into_the_path_that_needed_it(self):
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert "machine_economics.per_service_is_meaningful(watts)" in source

    def test_the_duplicate_constant_is_gone(self):
        from app import machine_economics

        assert not hasattr(machine_economics, "DEFAULT_IDLE_WATTS"), (
            "a second source of truth for host draw is back; power.DEFAULT_HOST_TDP_WATTS is the one"
        )

    def test_the_surviving_constant_still_exists_and_is_used(self):
        """Deleting the duplicate must not have removed the real one."""
        from app import power

        assert power.DEFAULT_HOST_TDP_WATTS == 65.0
        assert "power.DEFAULT_HOST_TDP_WATTS" in (ROOT / "app" / "main.py").read_text(encoding="utf-8")

    def test_a_sub_resolution_cost_is_flagged_but_still_counted(self):
        """The host draws the power even when we cannot say which service.

        Dropping the cost would understate what the fleet actually costs, so
        only the ATTRIBUTION is flagged, not the figure.
        """
        from app import machine_economics, power

        rows = [
            {
                "platform": "small",
                "gross": 3.0,
                "watts": 2.0,
                "hours": 720,
                "cost_attributable": machine_economics.per_service_is_meaningful(2.0),
            },
            {
                "platform": "big",
                "gross": 40.0,
                "watts": 120.0,
                "hours": 720,
                "cost_attributable": machine_economics.per_service_is_meaningful(120.0),
            },
        ]
        out = power.summarise(rows, price_per_kwh=0.20, currency="EUR")
        by = {r["platform"]: r for r in out["services"]}
        assert by["small"]["cost_attributable"] is False
        assert by["big"]["cost_attributable"] is True
        assert by["small"]["cost"] > 0, "the cost must still be reported, only its attribution is doubted"
        assert out["total_cost"] == pytest.approx(by["small"]["cost"] + by["big"]["cost"]), (
            "a flagged row must still count toward the fleet total"
        )

    def test_a_caller_that_says_nothing_is_unaffected(self):
        from app import power

        out = power.summarise([{"platform": "x", "gross": 1.0, "watts": 10.0, "hours": 720}], price_per_kwh=0.2)
        assert out["services"][0]["cost_attributable"] is True
