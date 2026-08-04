"""CashPilot-wi7: the LAN-isolation warning named the wrong service, twice.

``app/lan_isolation.py`` raised a ``collector_reachability`` exception when a
service had a ``collector:`` block AND any docker env whose key contained
"URL". Both halves were wrong:

* every one of the 50 catalog YAMLs carries a ``collector:`` block whether or
  not CashPilot has a collector for it, so the first half was always true;
* the second matched proxybase-xyz's ``BACKEND_URL``, which is the PROVIDER'S
  REMOTE endpoint (``https://api.proxybase.xyz`` per the service's own env
  description), not a local dashboard.

So the page told users that ProxyBase Markets — ``collector.type: manual``, slug
absent from ``COLLECTOR_MAP``, no collector at all — needed a network exception,
with the reason "CashPilot reads this service's earnings from its own local
dashboard". Nothing in that sentence was true of it.

And Storj, the one service that genuinely serves its earnings from a local
dashboard on port 14002, got no exception — so a user isolating their containers
lost Storj collection with no warning. The warning was on the service that did
not need it and missing from the one that did.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _exceptions(slug):
    from app import catalog, lan_isolation

    return lan_isolation.assess(catalog.get_service(slug))["exceptions"]


def _kinds(slug):
    return [e["kind"] for e in _exceptions(slug)]


class TestTheWarningGoesToTheServiceThatNeedsIt:
    def test_storj_is_warned(self):
        """It serves earnings from a local dashboard; isolation breaks that."""
        assert "collector_reachability" in _kinds("storj")

    def test_the_reason_names_the_setting_the_user_configures(self):
        detail = next(e["detail"] for e in _exceptions("storj") if e["kind"] == "collector_reachability")
        assert "api_url" in detail

    def test_proxybase_is_not_warned(self):
        """It has no collector, and its BACKEND_URL is the provider's own API."""
        assert "collector_reachability" not in _kinds("proxybase-xyz")

    def test_the_claim_about_a_local_dashboard_is_gone(self):
        """It was said of a remote endpoint, which is what made it false."""
        source = (ROOT / "app" / "lan_isolation.py").read_text(encoding="utf-8")
        code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
        assert "its own local dashboard" not in code


class TestTheGateIsKeyedOnAnActualCollector:
    def test_a_yaml_collector_block_is_not_enough(self):
        """Every catalog entry has one, so it can never distinguish anything."""
        from app import catalog

        with_block = [s for s in catalog.get_services() if (s.get("collector") or {})]
        assert len(with_block) > 40, "the premise changed: not every service declares a collector block"

    def test_the_registry_is_what_decides(self):
        from app.collectors import COLLECTOR_MAP

        assert "storj" in COLLECTOR_MAP
        assert "proxybase-xyz" not in COLLECTOR_MAP

    @pytest.mark.parametrize("slug", ["honeygain", "earnapp", "grass"])
    def test_a_collector_with_no_configurable_url_is_not_warned(self, slug):
        """The exception is about an ADDRESS staying reachable.

        A collector that talks to the provider's own cloud has no local address
        to protect, so warning about it would be the proxybase mistake again.
        """
        assert "collector_reachability" not in _kinds(slug)

    def test_no_service_slug_is_hardcoded_in_the_module(self):
        """The catalog exists so app/ does not branch on individual services."""
        source = (ROOT / "app" / "lan_isolation.py").read_text(encoding="utf-8")
        code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
        for slug in ('"storj"', '"proxybase-xyz"', '"honeygain"'):
            assert slug not in code, f"{slug} is branched on in app/lan_isolation.py"


class TestTheRestOfTheAssessmentIsUnchanged:
    """The control: this must not have removed the exceptions that were right."""

    def test_inbound_port_exceptions_survive(self):
        assert "inbound_port" in _kinds("storj")

    def test_a_service_needing_a_port_still_says_so(self):
        details = [e["detail"] for e in _exceptions("storj") if e["kind"] == "inbound_port"]
        assert details and any("inbound" in d for d in details)

    def test_assess_still_returns_a_verdict(self):
        from app import catalog, lan_isolation

        out = lan_isolation.assess(catalog.get_service("storj"))
        assert out["verdict"]
        assert out["slug"] == "storj"

    def test_an_unknown_service_is_still_handled(self):
        from app import lan_isolation

        assert lan_isolation.assess(None)["verdict"] == lan_isolation.NOT_ISOLATABLE
