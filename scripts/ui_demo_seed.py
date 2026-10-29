"""Seed a throwaway CashPilot database with demo data, and optionally serve it.

For UI work: screenshots, design proposals, visual review. Every number, name,
address and credential below is invented. Nothing here talks to a provider.

    # seed only
    uv run python scripts/ui_demo_seed.py /tmp/cp-demo

    # seed, then serve the seeded UI on :8100 and an empty first-run UI on :8101
    uv run python scripts/ui_demo_seed.py /tmp/cp-demo --serve 8100

Login: user ``demo``, password ``demo-password-1`` (owner).

The data dir is wiped first. Expect 8 deployed services on 3 workers (box-a,
box-b, box-c), 60 days of balance history in USD, MYST and GRASS points, two
confirmed payouts, one pending payout prompt, a failing collector and a stopped
container.

``--serve`` runs uvicorn in-process with the network jobs stubbed: earnings
collection, exchange-rate refresh and the release checks become no-ops, rates
are fixed, and the stale-worker job re-stamps the demo workers' heartbeats
instead of marking them offline. Worker URLs point at 127.0.0.1:9, which
refuses at once, so a button that would reach a worker fails fast and locally.
The second instance on port+1 has no users, so /onboarding renders there.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import shutil
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

DEMO_USER = "demo"
DEMO_PASSWORD = "demo-password-1"

# Fixed so every run, and every proposal lane, sees the same numbers.
RATES = {"MYST": 0.172, "ANYONE": 0.61}
FIAT = {"USD": 1.0, "EUR": 0.92, "GBP": 0.79}

# slug -> (currency, earned per day, daily jitter, starting balance)
SERVICES = {
    "honeygain": ("USD", 0.13, 0.04, 14.60),
    "earnapp": ("USD", 0.19, 0.06, 2.10),
    "mysterium": ("MYST", 0.85, 0.30, 1.20),
    "iproyal": ("USD", 0.05, 0.02, 0.80),
    "traffmonetizer": ("USD", 0.08, 0.02, 7.20),
    "repocket": ("USD", 0.06, 0.02, 1.90),
    "packetstream": ("USD", 0.03, 0.01, 0.40),
    "grass": ("GRASS", 420.0, 120.0, 9000.0),
}

# Payouts the history shows: (slug, days ago, amount, method). The balance drops
# by `amount` that day and a confirmed payout row records it.
CONFIRMED_PAYOUTS = [
    ("honeygain", 24, 20.00, "PayPal"),
    ("earnapp", 41, 5.00, "PayPal"),
]
# A drop the user has not answered yet: shows as the pending payout prompt.
PENDING_PAYOUT = ("traffmonetizer", 1, 10.00)

DAYS = 60

WORKERS = {
    "box-a": {
        "client_id": "demo-box-a",
        "system_info": {
            "os": "Linux 6.8.0-45-generic",
            "arch": "x86_64",
            "hostname": "box-a",
            "docker_available": True,
            "features": ["instances", "isolation_check"],
            "version": "demo",
            "egress_ip": "198.51.100.23",
            "egress_network_type": "residential",
            "disk": {"path": "/data", "free_bytes": 412 * 2**30, "total_bytes": 931 * 2**30},
            "gpu": None,
        },
        "containers": [
            ("honeygain", "running", 1.8, 38),
            ("earnapp", "running", 2.4, 61),
            ("mysterium", "running", 4.1, 142),
            ("iproyal", "running", 0.9, 22),
            ("traffmonetizer", "running", 1.2, 31),
        ],
    },
    "box-b": {
        "client_id": "demo-box-b",
        "system_info": {
            "os": "Linux 6.6.51-v8+",
            "arch": "aarch64",
            "hostname": "box-b",
            "docker_available": True,
            "features": ["instances", "isolation_check"],
            "version": "demo",
            "egress_ip": "203.0.113.77",
            "egress_network_type": "residential",
            "disk": {"path": "/data", "free_bytes": 38 * 2**30, "total_bytes": 117 * 2**30},
            "gpu": None,
        },
        "containers": [
            ("honeygain", "running", 2.2, 35),
            ("repocket", "running", 1.1, 44),
            ("packetstream", "running", 0.7, 19),
        ],
    },
    "box-c": {
        "client_id": "demo-box-c",
        "system_info": {
            "os": "Linux 6.1.0-26-amd64",
            "arch": "x86_64",
            "hostname": "box-c",
            "docker_available": True,
            "features": ["instances", "isolation_check"],
            "version": "demo",
            "egress_ip": "192.0.2.140",
            "egress_network_type": "residential",
            "disk": {"path": "/data", "free_bytes": 205 * 2**30, "total_bytes": 468 * 2**30},
            "gpu": None,
        },
        "containers": [
            ("earnapp", "running", 2.0, 58),
            ("traffmonetizer", "running", 1.0, 29),
            # The broken thing on the dashboard: a container that died last night.
            ("iproyal", "exited", 0.0, 0),
        ],
    },
}

# Obviously fake collector credentials, so Settings shows the services as
# configured. Collection is stubbed in --serve, so none of these is ever sent.
CREDENTIALS = {
    "honeygain_email": "demo@example.com",
    "honeygain_password": "not-a-real-password",
    "earnapp_oauth_token": "demo-oauth-token",
    "iproyal_email": "demo@example.com",
    "iproyal_password": "not-a-real-password",
    "mysterium_email": "demo@example.com",
    "mysterium_password": "not-a-real-password",
    "traffmonetizer_token": "demo-token",
    "repocket_email": "demo@example.com",
    "repocket_password": "not-a-real-password",
    "packetstream_auth_token": "demo-token",
    "grass_access_token": "demo-token",
}


def _prepare_env(data_dir: Path) -> None:
    """Point the app at the demo dir. Must run before anything imports app.*."""
    os.environ["CASHPILOT_DATA_DIR"] = str(data_dir)
    os.environ["CASHPILOT_FLEET_DIR"] = str(data_dir / "fleet")
    os.environ.setdefault("CASHPILOT_UPDATE_CHECK", "0")
    os.environ.setdefault("CASHPILOT_SECURE_COOKIE", "false")
    os.environ.setdefault("CASHPILOT_VERSION", "demo")
    # The deployment loop is driven from here, not by the UI, but a stray
    # deploy attempt must not reach a real machine.
    os.environ.setdefault("CASHPILOT_WORKER_URL_POLICY", "permissive")


def _fresh_dir(data_dir: Path) -> None:
    if data_dir.exists():
        shutil.rmtree(data_dir)
    (data_dir / "fleet").mkdir(parents=True)


def _image(slug: str) -> str:
    """The catalog's own image, so the dashboard does not flag every row as outdated."""
    from app import catalog

    return ((catalog.get_service(slug) or {}).get("docker") or {}).get("image") or ""


def _container(slug: str, status: str, cpu: float, mem: int, worker: str, idx: int) -> dict:
    c = {
        "slug": slug,
        "name": f"cashpilot-{slug}",
        "status": status,
        "image": _image(slug),
        "cpu_percent": cpu,
        "memory_mb": mem,
        "net_rx_bytes": (idx + 3) * 917_000_000 if status == "running" else None,
        "net_tx_bytes": (idx + 2) * 1_430_000_000 if status == "running" else None,
        "created": (datetime.now(UTC) - timedelta(days=30 + idx)).isoformat(),
        "container_id": f"{worker[-1]}{idx:011x}",
        "deployed_by": "cashpilot",
        "category": "",
        "instance": 1,
        "restart_policy": "unless-stopped",
    }
    if status != "running":
        c["finished_at"] = (datetime.now(UTC) - timedelta(hours=9)).isoformat()
        c["exit_code"] = 137
    return c


def _balances(rng: random.Random) -> dict[str, list[tuple[str, float]]]:
    """Running balances per day, oldest first, with the payout drops applied."""
    today = datetime.now(UTC).date()
    drops: dict[tuple[str, int], float] = {}
    for slug, ago, amount, _ in CONFIRMED_PAYOUTS:
        drops[(slug, ago)] = amount
    drops[(PENDING_PAYOUT[0], PENDING_PAYOUT[1])] = PENDING_PAYOUT[2]

    out: dict[str, list[tuple[str, float]]] = {}
    for slug, (_cur, per_day, jitter, start) in SERVICES.items():
        bal = start
        rows = []
        for ago in range(DAYS, -1, -1):
            # repocket's collector is the failing one: no reading for 3 days.
            if slug == "repocket" and ago < 3:
                continue
            bal += max(0.0, rng.gauss(per_day, jitter))
            bal -= drops.get((slug, ago), 0.0)
            rows.append(((today - timedelta(days=ago)).isoformat(), round(bal, 4)))
        out[slug] = rows
    return out


async def seed(data_dir: Path) -> None:
    from app import auth, catalog, database

    rng = random.Random(20261029)
    await database.init_db()
    await database.connect_shared()
    catalog.load_services()

    uid = await database.create_first_owner(DEMO_USER, auth.hash_password(DEMO_PASSWORD))
    await database.save_user_preferences(
        uid,
        setup_mode="fresh",
        selected_categories=json.dumps(["bandwidth", "depin"]),
        timezone="Europe/Madrid",
        setup_completed=True,
    )

    # Workers and the containers their last heartbeat reported.
    worker_ids: dict[str, int] = {}
    for name, w in WORKERS.items():
        containers = [_container(s, st, cpu, mem, name, i) for i, (s, st, cpu, mem) in enumerate(w["containers"])]
        wid = await database.upsert_worker(
            w["client_id"],
            name=name,
            url="http://127.0.0.1:9",
            containers=json.dumps(containers),
            system_info=json.dumps(w["system_info"]),
        )
        await database.confirm_worker_key(w["client_id"])
        worker_ids[name] = wid

    # Deployments: one fleet-wide row per service plus a per-worker spec.
    for name, w in WORKERS.items():
        for i, (slug, status, _cpu, _mem) in enumerate(w["containers"]):
            spec = {"image": _image(slug), "environment": {"DEVICE_NAME": f"{name}-{slug}"}}
            await database.save_deployment(
                slug,
                f"{name[-1]}{i:011x}",
                status="running",
                spec=spec,
                worker_id=worker_ids[name],
            )
    # Grass runs as a browser extension, so it has no container anywhere.
    await database.save_deployment("grass", "", status="external")

    await database.set_config_bulk(CREDENTIALS)
    # Credentials entered weeks ago, not this second, so Settings shows real ages.
    cdb = await database._get_db()
    for i, key in enumerate(sorted(CREDENTIALS)):
        when = (datetime.now(UTC) - timedelta(days=9 + 3 * i, hours=i)).strftime("%Y-%m-%d %H:%M:%S")
        await cdb.execute("UPDATE config SET updated_at = ? WHERE key = ?", (when, key))
    await cdb.commit()

    # Earnings history.
    today = datetime.now(UTC).date()
    for slug, rows in _balances(rng).items():
        currency = SERVICES[slug][0]
        for date, bal in rows:
            if currency == "USD":
                fx = 1.0
            elif currency == "MYST":
                # A token moves; store the rate of the day like a collector does.
                ago = (today - datetime.fromisoformat(date).date()).days
                fx = round(RATES["MYST"] * (1 + 0.12 * ((ago % 17) - 8) / 8), 4)
            else:
                fx = None  # GRASS points are unpriced by design.
            await database.upsert_earnings(slug, bal, currency, date=date, fx_rate_usd=fx)

    # Payouts: two confirmed, one waiting for an answer.
    db = await database._get_db()
    for slug, ago, amount, method in CONFIRMED_PAYOUTS:
        pid = await database.record_probable_payout(slug, amount, "USD", 1.0)
        await database.confirm_payout(pid, method)
        when = (datetime.now(UTC) - timedelta(days=ago)).strftime("%Y-%m-%d %H:%M:%S")
        await db.execute("UPDATE payouts SET detected_at = ?, confirmed_at = ? WHERE id = ?", (when, when, pid))
    p_slug, p_ago, p_amount = PENDING_PAYOUT
    pid = await database.record_probable_payout(p_slug, p_amount, "USD", 1.0)
    when = (datetime.now(UTC) - timedelta(days=p_ago)).strftime("%Y-%m-%d %H:%M:%S")
    await db.execute("UPDATE payouts SET detected_at = ? WHERE id = ?", (when, pid))
    await db.commit()
    await database.record_alert(
        "payout",
        p_slug,
        f"Balance fell by ${p_amount:.2f} since the last reading. Was this a payout?",
    )

    # Alerts: one collector that stopped working, one container that died.
    await database.record_alert(
        "collector",
        "repocket",
        "Login rejected (HTTP 401). The saved email or password no longer works.",
        category="auth",
    )
    await database.record_alert(
        "container",
        "iproyal",
        "iproyal on box-c exited with code 137 nine hours ago.",
    )

    # Health checks every 30 minutes for a week; iproyal went down last night.
    now = datetime.now(UTC)
    events = []
    for slug in SERVICES:
        if slug == "grass":
            continue
        for half_hours in range(7 * 48):
            at = now - timedelta(minutes=30 * half_hours)
            down = (slug == "iproyal" and half_hours < 18) or (slug == "packetstream" and 120 <= half_hours < 126)
            events.append((slug, "check_down" if down else "check_ok", "exited" if down else "", at))
    events.append(("mysterium", "restarted", "restarted by worker", now - timedelta(days=3)))
    await db.executemany(
        "INSERT INTO health_events (slug, event, detail, created_at) VALUES (?, ?, ?, ?)",
        [(s, e, d, at.strftime("%Y-%m-%d %H:%M:%S")) for s, e, d, at in events],
    )
    await db.commit()
    await database.close_shared()


def serve(port: int, data_dir: Path) -> None:
    """Run the seeded UI with every outbound job stubbed (see module docstring)."""
    import uvicorn

    from app import database, exchange_rates, main, update_check

    async def _noop(*_a, **_kw) -> None:
        return None

    async def _fixed_rates() -> None:
        exchange_rates._crypto_usd.update(RATES)
        exchange_rates._fiat_rates.update(FIAT)
        stamp = time.time()
        exchange_rates._crypto_last_fetch = stamp
        exchange_rates._fiat_last_fetch = stamp
        exchange_rates._last_fetch = stamp

    async def _keep_workers_fresh() -> None:
        db = await database._get_db()
        await db.execute("UPDATE workers SET status = 'online', last_heartbeat = datetime('now')")
        await db.commit()

    exchange_rates.refresh = _fixed_rates
    update_check.refresh = _noop
    update_check.refresh_android = _noop
    main._run_collection = _noop
    main._check_stale_workers = _keep_workers_fresh

    uvicorn.run(main.app, host="127.0.0.1", port=port, log_level="warning")


def main_cli() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data_dir", type=Path)
    ap.add_argument("--serve", type=int, metavar="PORT", help="serve the seeded UI on PORT, first-run UI on PORT+1")
    ap.add_argument("--fresh", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    data_dir = args.data_dir.resolve()
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    if args.fresh:
        # Internal: the empty first-run instance, its own process and data dir.
        _fresh_dir(data_dir)
        _prepare_env(data_dir)
        serve(args.serve, data_dir)
        return

    _fresh_dir(data_dir)
    _prepare_env(data_dir)
    asyncio.run(seed(data_dir))
    print(f"Seeded {data_dir}. Login: {DEMO_USER} / {DEMO_PASSWORD}")
    if args.serve:
        import subprocess

        fresh = subprocess.Popen(
            [sys.executable, __file__, str(data_dir) + "-fresh", "--serve", str(args.serve + 1), "--fresh"]
        )
        try:
            print(f"Seeded UI http://127.0.0.1:{args.serve}  first-run UI http://127.0.0.1:{args.serve + 1}")
            serve(args.serve, data_dir)
        finally:
            fresh.terminate()
            fresh.wait(timeout=10)


if __name__ == "__main__":
    main_cli()
