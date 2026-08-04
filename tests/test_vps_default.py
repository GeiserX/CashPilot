"""CashPilot-0yf: one catalog fact, two readers, opposite answers.

``services/_schema.yml`` documents that ``vps_ip`` defaults to the opposite of
``residential_ip``. Two consumers read that field:

* ``scripts/generate_readme_tables.py`` applied the default, so the catalog page
  tells the user "VPS not allowed" for a residential-only service;
* ``app/preflight.py`` tested ``reqs.get("vps_ip") is False`` — the literal
  boolean — so an absent key never entered the branch.

The result: 21 services the documentation describes as residential-only got no
warning at all before being deployed onto a hosting worker, where they earn
nothing or get the account banned. Five services warned; twenty-six should.

Both now read through ``app.catalog.vps_allowed``, so they cannot drift apart.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "services"


class TestTheDocumentedDefaultIsApplied:
    def test_an_explicit_value_always_wins(self):
        from app.catalog import vps_allowed

        assert vps_allowed({"vps_ip": True, "residential_ip": True}) is True
        assert vps_allowed({"vps_ip": False, "residential_ip": False}) is False

    def test_residential_only_means_no_vps(self):
        """The documented default, and the case the whole bead is about."""
        from app.catalog import vps_allowed

        assert vps_allowed({"residential_ip": True}) is False

    def test_not_residential_means_vps_is_fine(self):
        from app.catalog import vps_allowed

        assert vps_allowed({"residential_ip": False}) is True

    def test_nothing_declared_is_unknown_not_permitted(self):
        """Absent is not 'allowed'. Returning True here would invent a licence."""
        from app.catalog import vps_allowed

        assert vps_allowed({}) is None
        assert vps_allowed(None) is None


class TestPreflightUsesIt:
    def test_preflight_no_longer_demands_the_literal_boolean(self):
        source = (ROOT / "app" / "preflight.py").read_text(encoding="utf-8")
        assert 'reqs.get("vps_ip") is False' not in source
        assert "catalog.vps_allowed(reqs) is False" in source

    def test_the_readme_generator_delegates_rather_than_reimplementing(self):
        """Two implementations of one rule is how they diverged the first time."""
        source = (ROOT / "scripts" / "generate_readme_tables.py").read_text(encoding="utf-8")
        assert "from app.catalog import vps_allowed" in source
        assert "return None if residential is None else not residential" not in source


class TestTheCatalogAgreesWithItself:
    def _requirements(self):
        out = {}
        for path in sorted(SERVICES.rglob("*.yml")):
            if path.name.startswith("_"):
                continue
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            out[data.get("slug", path.stem)] = data.get("requirements") or {}
        return out

    def test_the_warning_covers_every_residential_only_service(self):
        """5 services fired before this change; 26 should.

        The count is asserted loosely — the point is that it is far more than
        the handful that declared vps_ip explicitly, not a specific number that
        breaks whenever a service is added.
        """
        from app.catalog import vps_allowed

        reqs = self._requirements()
        residential_only = [s for s, r in reqs.items() if r.get("residential_ip") and vps_allowed(r) is False]
        explicit = [s for s, r in reqs.items() if r.get("residential_ip") and r.get("vps_ip") is False]
        assert len(residential_only) > len(explicit), "the documented default is not being applied"
        assert len(residential_only) >= 20, f"only {len(residential_only)} residential-only services resolved"

    @pytest.mark.parametrize("slug", ["packetstream", "honeygain"])
    def test_known_residential_services_resolve_to_no_vps(self, slug):
        """packetstream declares no vps_ip; honeygain declares it explicitly.

        Both must reach the same answer, which is the whole point of the shared
        helper.
        """
        from app.catalog import vps_allowed

        assert vps_allowed(self._requirements()[slug]) is False

    def test_declaring_both_is_explicit_and_rare(self):
        """residential_ip AND vps_ip both true is allowed, but should be deliberate.

        My first version of this test called it a contradiction. It is not: an
        EXPLICIT vps_ip is the catalog author stating the provider accepts a
        VPS, and that outranks any inference from residential_ip. The schema
        only defines vps_ip's DEFAULT in terms of residential_ip; it says
        nothing about the two being mutually exclusive.

        What is worth catching is the combination appearing by accident, so the
        set is pinned. earnfm is the one service that says both today.
        """
        both = {
            slug
            for slug, r in self._requirements().items()
            if r.get("residential_ip") is True and r.get("vps_ip") is True
        }
        assert both == {"earnfm"}, (
            f"services declaring residential_ip AND vps_ip changed: {sorted(both)}. "
            "If that is deliberate, add it here; if not, the catalog entry is wrong."
        )

    def test_the_default_never_produces_that_combination(self):
        """It can only ever arise from an explicit vps_ip, never by inference."""
        from app.catalog import vps_allowed

        inferred = [
            slug
            for slug, r in self._requirements().items()
            if r.get("residential_ip") is True and r.get("vps_ip") is None and vps_allowed(r) is not False
        ]
        assert not inferred, f"the documented default resolved these to VPS-allowed: {inferred}"
