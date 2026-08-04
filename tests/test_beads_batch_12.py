"""Batch 12: two claims the app could not support.

One told users a stored setting was in force when nothing read it back. The
other told 21 services' users they could cash out any amount, because
"undocumented" had been written into the catalog as "no minimum".
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "static" / "js" / "app.js"
SERVICES = ROOT / "services"


def without_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in text.splitlines())


def catalog_entries():
    out = {}
    for path in sorted(SERVICES.rglob("*.yml")):
        if path.name.startswith("_"):
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        out[data.get("slug", path.stem)] = data
    return out


class TestAnUndocumentedMinimumIsNotZero:
    """CashPilot-x26: 21 services encoded "we don't know" as "no minimum".

    payouts.min_payout is explicitly three-valued — positive is a real minimum,
    0.0 is a documented "cash out any amount", None is undocumented. Twenty-one
    services carried ``min_amount: 0`` with an EMPTY ``payment.minimum_payout``,
    so the catalog asserted a fact nobody had established.

    Two consequences. api_earnings_breakdown reported the user eligible to cash
    out any balance above zero, sending them to a withdrawal page that would
    refuse them. And payouts.looks_like_payout returns False on a falsy
    threshold, so payout detection was silently disabled for all 21.
    """

    def test_no_service_claims_zero_without_documenting_it(self):
        offenders = []
        for slug, data in catalog_entries().items():
            cashout = data.get("cashout") or {}
            payment = data.get("payment") or {}
            if cashout.get("min_amount") == 0 and not str(payment.get("minimum_payout") or "").strip():
                offenders.append(slug)
        assert not offenders, (
            f"these claim 'no minimum' with nothing documenting it: {offenders}. "
            "Use null for undocumented; 0 means the provider genuinely has no minimum."
        )

    def test_a_documented_zero_would_still_be_allowed(self):
        """The contract keeps three values; this fix must not collapse it to two."""
        from app import payouts

        assert payouts.min_payout({"cashout": {"min_amount": 0}}) == 0.0
        assert payouts.min_payout({"cashout": {"min_amount": None}}) is None
        assert payouts.min_payout({"cashout": {"min_amount": 4.0}}) == 4.0

    def test_the_catalog_still_has_real_minimums(self):
        """Guards against this passing because every minimum was nulled."""
        real = [
            slug
            for slug, d in catalog_entries().items()
            if isinstance((d.get("cashout") or {}).get("min_amount"), (int, float))
            and (d.get("cashout") or {}).get("min_amount")
        ]
        assert len(real) >= 5, f"only {len(real)} services have a positive minimum: {real}"


class TestEligibilityDistinguishesItsThreeCases:
    """Reuses the existing harness in tests/test_eligibility.py.

    Rebuilding it here produced a service dict missing `name`, which the handler
    requires — a second harness for one endpoint is a second thing to get wrong.
    """

    def _eligible(self, cashout, balance=100.0):
        from tests.test_eligibility import _call_breakdown, _earnings_row, _service

        rows = [_earnings_row("svc", balance=balance)]
        svcs = {"svc": _service("svc", cashout=cashout)}
        return _call_breakdown(rows, svcs)[0]["cashout"]["eligible"]

    def test_no_cashout_route_is_a_definite_no(self):
        """Not unknown — there is no withdrawal route at all."""
        assert self._eligible(None) is False

    def test_an_unknown_minimum_is_unknown(self):
        """Claiming eligibility here sends the user to a page that refuses them."""
        assert self._eligible({"min_amount": None}) is None

    def test_a_documented_no_minimum_is_eligible(self):
        assert self._eligible({"min_amount": 0}, balance=5.0) is True

    def test_an_unparseable_minimum_is_unknown_not_a_crash(self):
        """A catalog typo must not 500 the dashboard.

        min_amount comes from YAML a human edits, so "4.00 USD" or an empty
        string are realistic. float() raises on both; treating that as unknown
        matches how every other unparseable value in this codebase is handled,
        and is the branch codecov flagged as untested.
        """
        assert self._eligible({"min_amount": "not a number"}) is None

    def test_a_numeric_string_still_parses(self):
        """YAML quoting is common and should not silently disable a threshold."""
        assert self._eligible({"min_amount": "20"}, balance=25.0) is True
        assert self._eligible({"min_amount": "20"}, balance=5.0) is False

    def test_a_real_threshold_is_compared(self):
        assert self._eligible({"min_amount": 20.0}, balance=5.0) is False
        assert self._eligible({"min_amount": 20.0}, balance=25.0) is True


class TestTheSettingsPageDoesNotClaimStoredValuesApply:
    """CashPilot-73o: the page asserted a stored value was in force.

    Every variable it offers is resolved once from the environment at import —
    main.py:639-640, auth.py, fleet_key.py — so a value written to the config
    table can never take effect. The UI showed a green "Variables saved" toast
    and a "DB" badge meaning "the database value is in use", and collection
    carried on at the old interval.

    Several of them cannot change at runtime at all, which is why the fix is to
    stop claiming they can rather than to wire them up: the session key signs
    logins already in use, the data directory is where the open database lives,
    and the fleet key is what enrolled workers already hold.
    """

    def test_the_db_badge_no_longer_asserts_the_value_is_in_use(self):
        source = without_comments(APP_JS.read_text(encoding="utf-8"))
        assert 'badge-category" style="font-size:0.7rem;margin-left:8px;">DB<' not in source

    def test_a_stored_value_is_labelled_as_not_applied(self):
        source = without_comments(APP_JS.read_text(encoding="utf-8"))
        assert "Stored, not applied" in source

    def test_the_page_says_a_restart_is_required(self):
        source = without_comments(APP_JS.read_text(encoding="utf-8"))
        assert "does not take effect" in source
        assert "restart the container" in source

    def test_the_template_copy_matches(self):
        html = (ROOT / "app" / "templates" / "settings.html").read_text(encoding="utf-8")
        assert "saved to the database." not in html
        assert "does not take effect" in html

    @pytest.mark.parametrize(
        "key,module",
        [
            ("CASHPILOT_HOSTNAME_PREFIX", "app/main.py"),
            ("CASHPILOT_COLLECT_INTERVAL", "app/main.py"),
            ("CASHPILOT_SECRET_KEY", "app/auth.py"),
        ],
    )
    def test_these_really_are_import_time_reads(self, key, module):
        """The premise of the fix. If one ever becomes live, revisit the copy."""
        source = (ROOT / module).read_text(encoding="utf-8")
        assert f'os.getenv("{key}"' in source
