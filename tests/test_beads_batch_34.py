"""CashPilot-jm6: the running-costs feature had no way to configure it.

Every key the feature reads — the electricity price, its currency, the
per-machine wattage, the dedicated flag — was read by app/main.py and written by
nothing. No field, no documentation, no route short of hand-crafting a
POST /api/config with key names that appear nowhere the user can see.

So a user who only uses the app saw the card hidden, or saw "Without your
electricity price CashPilot cannot say whether that covers the electricity",
forever. machine_economics returns UNKNOWN for every machine when the price and
the watts are unset, and both were unsettable.

The card was also hidden until a tariff existed, which made the one control that
could set a tariff unreachable — so it is now shown as soon as there are
machines to talk about.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FLEET = ROOT / "app" / "templates" / "fleet.html"


def fleet_html() -> str:
    return FLEET.read_text(encoding="utf-8")


def without_comments(text: str) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in text.splitlines())


class TestTheTariffCanBeEntered:
    def test_there_is_a_price_field(self):
        assert 'id="power-price"' in fleet_html()

    def test_there_is_a_currency_field(self):
        """Reading the price without its unit is how the EUR/USD mixing began."""
        assert 'id="power-currency"' in fleet_html()

    def test_it_writes_the_key_main_py_reads(self):
        """Asserted together with the CONTROL that triggers the write.

        Checking only for the key names left this passing when the inputs and
        the save button were removed — the handler still mentioned them. A key
        name in a function nobody can reach is the bug, not the fix.
        """
        source = without_comments(fleet_html())
        assert "power_price_per_kwh" in source
        assert "power_currency" in source
        assert 'id="power-save"' in source, "the key is written by a control the user cannot reach"
        assert "getElementById('power-save').addEventListener" in source, "the save button is not wired up"

    def test_main_py_still_reads_that_key(self):
        """The premise. A field writing a key nobody reads is the same bug."""
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert "power_price_per_kwh" in source

    def test_the_legacy_key_is_honoured_when_loading(self):
        """main.py accepts electricity_price_per_kwh; an existing setting must
        show in the field rather than looking unset and being overwritten."""
        assert "electricity_price_per_kwh" in without_comments(fleet_html())

    def test_a_blank_price_is_refused_rather_than_stored(self):
        source = without_comments(fleet_html())
        assert "Enter your price per kWh first" in source

    def test_a_nonsense_price_is_refused(self):
        source = without_comments(fleet_html())
        assert "Number.isFinite" in source


class TestPerMachinePowerCanBeEntered:
    def test_there_is_a_watts_field(self):
        assert "power-watts" in fleet_html()

    def test_there_is_a_dedicated_toggle(self):
        assert "power-dedicated" in fleet_html()

    def test_it_writes_the_keys_main_py_reads(self):
        source = without_comments(fleet_html())
        assert "_watts`]" in source or "_watts`" in source
        assert "_dedicated`" in source

    def test_it_keys_on_client_id_not_the_row_id(self):
        """The row id does not survive re-enrolment; main.py keys on client_id.

        Writing under the row id would orphan the setting the moment a host is
        removed and comes back, which is the exact trap _worker_config_key
        exists to document.
        """
        source = without_comments(fleet_html())
        assert "clientId" in source
        assert "worker_${id}_watts" in source

    def test_the_endpoint_returns_the_current_values(self):
        """An empty box that silently overwrites what is stored is worse than
        no box, so the field has to be able to show what is set."""
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert 'w["watts"]' in source
        assert 'w["dedicated"]' in source

    def test_it_reads_them_the_same_way_the_economics_endpoint_does(self):
        """Two readers of one setting is how they drift apart."""
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert source.count("_worker_config_key(") >= 2
        assert '_worker_flag(config, w, "dedicated")' in source


class TestTheCardIsReachable:
    def test_it_is_shown_once_there_are_machines(self):
        """It was hidden until a tariff existed, which hid the tariff control."""
        source = without_comments(fleet_html())
        i = source.index("if (!machines.length)")
        assert "card.style.display = ''" in source[i : i + 400]

    def test_an_empty_fleet_still_hides_it(self):
        """The control: it must not appear on an install with no workers."""
        source = without_comments(fleet_html())
        assert "if (!machines.length) { card.style.display = 'none'; return; }" in source


class TestTheBackendStillNeedsBoth:
    """The reason both inputs exist rather than just the tariff."""

    @pytest.mark.parametrize(
        ("watts", "price", "known"),
        [(65.0, 0.30, True), (None, 0.30, False), (65.0, None, False), (None, None, False)],
    )
    def test_a_cost_needs_a_wattage_and_a_tariff(self, watts, price, known):
        from app import machine_economics

        out = machine_economics.assess_machine(
            name="watchtower", monthly_gross=5.0, watts=watts, price_per_kwh=price, dedicated=True
        )
        assert (out["monthly_cost"] is not None) is known

    def test_the_unknown_verdict_is_what_the_user_was_stuck_on(self):
        from app import machine_economics

        out = machine_economics.assess_machine(
            name="watchtower", monthly_gross=5.0, watts=None, price_per_kwh=None, dedicated=True
        )
        assert out["verdict"] == machine_economics.UNKNOWN
