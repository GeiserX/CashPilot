"""Earners that run but do not earn must not read as healthy.

Seen live in Nov 2026, each with a healthy container: a PacketStream copy
refused as non-residential for days, ProxyBase retrying its relay for days
on two boxes, and EarnApp crashing on a handshake timeout every 100
seconds for four days. The lines below are the ones those copies logged.
"""

from __future__ import annotations

import pytest

from app import catalog, producer_state


def _signal(slug: str, needle: str) -> dict:
    signals = producer_state.signals_for(catalog.get_service(slug))
    [found] = [s for s in signals if needle in s["pattern"]]
    assert producer_state.is_windowed(found)
    return found


def _ps(msg: str) -> str:
    return f'time="2026-11-12T12:42:43Z" level=info msg="Status: {msg}"'


PS_NONRES = _ps("Error: Non-residential IPs are currently unsupported")
PS_ONE_CLIENT = _ps("Error: PacketStream allows packeting from 1 client per IP address.")
PS_RUNNING = _ps("PacketStream is running")
PB_RETRY = [
    "Wed Nov 11 07:44:42 2026: [connection] [INFO] Failed to connect to ",
    "203.0.113.7:2931, retrying in 5 seconds.",
]
PB_BALANCE = "Thu Nov 12 13:38:58 2026: [packet_handler] [INFO] Balance: $0.0103"
EA_CRASH = [
    "✔ EarnApp is active (making money in the background)",
    "        reject(new Error(client.reason || 'connection failed'));",
    "Error: Handshake timeout",
]


@pytest.mark.parametrize(
    ("slug", "needle", "broken", "healthy"),
    [
        ("packetstream", "Non-residential", [PS_NONRES] * 24, [PS_NONRES] * 24 + [PS_RUNNING]),
        ("packetstream", "1 client per IP", [PS_ONE_CLIENT] * 24, [PS_ONE_CLIENT] * 24 + [PS_RUNNING]),
        ("proxybase", "retrying", PB_RETRY * 240, PB_RETRY * 240 + [PB_BALANCE]),
        ("earnapp", "Handshake", EA_CRASH * 35, EA_CRASH * 2),
    ],
)
def test_the_logged_failure_is_flagged_and_a_recovery_is_not(slug, needle, broken, healthy):
    signal = _signal(slug, needle)
    assert producer_state.windowed_hit("\n".join(broken), signal)
    assert not producer_state.windowed_hit("\n".join(healthy), signal)


def test_the_worker_filter_returns_both_halves_of_the_proxybase_verdict():
    """The worker filters the window with one regex; the balance line must survive it."""
    import re

    signal = _signal("proxybase", "retrying")
    rx = re.compile(producer_state.window_filter(signal))
    assert rx.search(PB_RETRY[1])
    assert rx.search(PB_BALANCE)


def test_the_catalog_accepts_the_new_signals():
    for slug in ("packetstream", "proxybase", "earnapp"):
        svc = catalog.get_service(slug)
        assert catalog._validate(svc, __import__("pathlib").Path(f"{slug}.yml")) == []


def test_every_windowed_signal_declares_the_state_the_dashboard_shows():
    """The dashboard shows every windowed hint as failing, whatever the YAML says.

    A windowed signal that declares another state would read one way in the
    catalog and another on the dashboard.
    """
    wrong = [
        (svc["slug"], s["pattern"], s.get("state"))
        for svc in catalog.get_services()
        for s in producer_state.signals_for(svc)
        if producer_state.is_windowed(s) and s.get("state", producer_state.FAILING) != producer_state.FAILING
    ]
    assert wrong == []
