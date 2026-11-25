"""The dashboard writes coin amounts in full, run in node.

toFixed(2) turned a 0.01599128 BTC payout into "0.02", and the services
table's toFixed(4) turned 0.000613902892 XMR into "0.0006". formatAmount is the
one helper every payout and balance figure in its own unit goes through.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "app/static/js/app.js"

_HARNESS = r"""
const src = require('fs').readFileSync(process.argv[process.argv.length - 2], 'utf8');
const from = src.indexOf('  function formatCurrency(val, nativeCurrency, digits) {');
const to = src.indexOf('  function setTextContent(id, text) {');
if (from < 0 || to <= from) { console.log(JSON.stringify({ error: 'block moved' })); process.exit(0); }
const _exchangeRates = { fiat: { USD: 1, EUR: 0.92 }, crypto_usd: {} };
const fns = new Function('_exchangeRates', '_displayCurrency', `${src.slice(from, to)}; return { formatAmount, formatNative, formatCurrency };`)(_exchangeRates, 'USD');
const cases = JSON.parse(process.argv[process.argv.length - 1]);
console.log(JSON.stringify(cases.map(([fn, args]) => fns[fn](...args))));
"""


def _run(*cases):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    out = subprocess.run(
        [node, "-e", _HARNESS, str(APP_JS), json.dumps(cases)],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    result = json.loads(out.stdout)
    assert not isinstance(result, dict), result
    return result


@pytest.mark.parametrize(
    ("value", "currency", "text"),
    [
        (0.01599128, "BTC", "0.01599128"),
        (0.00012345, "BTC", "0.00012345"),
        (0.000613902892, "XMR", "0.00061390289"),
        (0.000000004, "XMR", "0.000000004"),
        (1.23456789, "BTC", "1.23456789"),
        (1.5, "BTC", "1.50"),
        (123, "GRASS", "123.00"),
        (24.9, "USD", "24.90"),
        (12.3456, "EUR", "12.35"),
        (12.3456, None, "12.35"),
    ],
)
def test_format_amount_matches_the_server(value, currency, text):
    from app import payouts

    (shown,) = _run(["formatAmount", [value, currency]])
    assert shown == text
    # One rule on both sides, so the bell and the dashboard agree.
    assert payouts.format_amount(value, currency) == text


def test_the_services_table_keeps_a_monero_balance_in_full():
    usd, xmr = _run(["formatNative", [5, "USD"]], ["formatNative", [0.000613902892, "XMR"]])
    assert usd is None
    assert xmr == "0.00061390289 XMR"


def test_an_unpriced_coin_keeps_its_small_units():
    """With no price for XMR the services table shows formatCurrency, not formatNative."""
    xmr, delta = _run(["formatCurrency", [0.000613902892, "XMR"]], ["formatCurrency", [0.00001, "BTC"]])
    assert xmr == "0.00061390289 XMR"
    assert delta == "0.00001 BTC"


@pytest.mark.parametrize(
    "site",
    [
        "const native = `${formatAmount(p.amount, nativeCurrency)} ${nativeCurrency}`;",
        "${formatAmount(item.balance, cur)} ${cur}",
        "const money = value => (unit ? `${formatAmount(value, unit)} ${unit}` : formatCurrency(value));",
        "${escapeHtml(formatAmount(p.amount, p.currency))} ${escapeHtml(p.currency || '')}",
    ],
)
def test_every_payout_figure_goes_through_the_helper(site):
    """The pending payout, cash-out reminder, payout card and cash-out list."""
    assert site in APP_JS.read_text(encoding="utf-8")
