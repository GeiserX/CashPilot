"""Generate the README service tables from the catalog (CashPilot-9q1).

"YAML is the single source of truth" is the rule this project is built on, and
the README service tables were the one place it was violated: hand-maintained,
so they drifted. That is not hypothetical — the README kept publishing a per-IP
device limit for weeks after the catalog dropped it for being unsourced, which
is the same wrong number in the more visible place.

Adding a service should be one file plus an optional collector. Every extra
place a contributor has to remember is a place a first-time contributor gets it
wrong, gets a review comment, and does not come back.

Run with --check in CI to fail on drift; run with no arguments to rewrite.

Only the regions between the markers are touched, so the surrounding prose,
footnotes and hand-written notes are preserved.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import catalog  # noqa: E402

BEGIN = "<!-- BEGIN GENERATED: {name} -->"
END = "<!-- END GENERATED: {name} -->"

# Services shown in each table. Anything broken, dead or dropped is excluded
# from the catalog loader already.
DOCKER = "docker-services"
EXTENSION = "extension-services"
GPU = "gpu-services"


def _yes_no(value: object) -> str:
    """Three-valued, because absent is not false.

    The hand-maintained table used ✅/❌ only, so a service that simply never
    declared the field rendered as a definite "no". That is the same
    absent-versus-false confusion that has bitten this catalog repeatedly.
    """
    if value is None:
        return "?"
    return "✅" if value else "❌"


def _vps_allowed(reqs: dict) -> object:
    """Whether a VPS is permitted, applying the schema's documented default.

    services/_schema.yml states vps_ip defaults to the opposite of
    residential_ip. Using a DOCUMENTED default is not a guess; ignoring it and
    printing "?" for two thirds of the catalog would be less informative and
    less true.
    """
    if reqs.get("vps_ip") is not None:
        return reqs["vps_ip"]
    residential = reqs.get("residential_ip")
    return None if residential is None else not residential


def _devices(value: object) -> str:
    """Render a device limit, keeping absent distinct from a documented number.

    ``?`` is not decoration: an undocumented limit is genuinely unknown, and
    printing ``1`` for it — which is what the hand-maintained table did for
    roughly thirty services — asserts something no provider ever said.
    """
    if value is None:
        return "? \\*\\*\\*"
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "? \\*\\*\\*"
    return "Unlimited" if number == 0 else str(number)


def _link(service: dict) -> str:
    url = (service.get("referral") or {}).get("signup_url") or service.get("website") or ""
    return f"[{service.get('name', service.get('slug'))}]({url})"


def _guide(service: dict) -> str:
    return f"[Guide](docs/guides/{service['slug']}.md)"


_METHOD_NAMES = {
    "paypal": "PayPal",
    "bank": "Bank Transfer",
    "giftcard": "Gift Cards",
    "amazon_giftcard": "Amazon Gift Card",
    "wise": "Wise",
    "revolut": "Revolut",
    "payeer": "Payeer",
}


def _payout(service: dict) -> str:
    payment = service.get("payment") or {}
    token = payment.get("crypto_token") or ""
    rendered = []
    for method in payment.get("methods") or []:
        if method == "crypto":
            rendered.append(f"Crypto ({token})" if token else "Crypto")
        else:
            rendered.append(_METHOD_NAMES.get(method, method.replace("_", " ").title()))
    return ", ".join(rendered) or "--"


def _markers(service: dict) -> str:
    """Footnote markers, DERIVED from the catalog rather than hand-placed.

    A hand-placed marker is lost the first time the table is regenerated, which
    would silently delete the warning that EarnApp forbids the way CashPilot
    runs it — the most consequential sentence in this file.
    """
    if (service.get("requirements") or {}).get("container_prohibited"):
        return " \\*\\*\\*\\*"
    return ""


def _row(service: dict, kind: str) -> str:
    reqs = service.get("requirements") or {}
    cells = [_link(service) + _markers(service), _guide(service)]
    if kind == GPU:
        cells += [
            _yes_no(reqs.get("residential_ip")),
            _yes_no(reqs.get("gpu")),
            str(reqs.get("min_storage") or "N/A"),
            _payout(service),
            str(service.get("status", "")).title(),
        ]
    else:
        cells += [
            _yes_no(reqs.get("residential_ip")),
            _yes_no(_vps_allowed(reqs)),
            _devices(reqs.get("devices_per_account")),
            _devices(reqs.get("devices_per_ip")),
            _payout(service),
        ]
        if kind == EXTENSION:
            cells.append(str(service.get("status", "")).title())
    return "| " + " | ".join(cells) + " |"


def _is_dockerable(service: dict) -> bool:
    return bool((service.get("docker") or {}).get("image"))


def _table(kind: str) -> str:
    services = [s for s in catalog.get_services() if str(s.get("status")) in {"active", "beta"}]
    if kind == GPU:
        selected = [s for s in services if s.get("category") == "compute"]
        header = "| Service | Guide | Residential IP required | GPU | Min Storage | Payout | Status |"
        divider = "|---------|-------|:-:|:-:|:-:|--------|--------|"
    elif kind == DOCKER:
        selected = [s for s in services if s.get("category") != "compute" and _is_dockerable(s)]
        header = "| Service | Guide | Residential IP required | VPS allowed | Devices / Acct | Devices / IP | Payout |"
        divider = "|---------|-------|:-:|:-:|:-:|:-:|--------|"
    else:
        selected = [s for s in services if s.get("category") != "compute" and not _is_dockerable(s)]
        header = "| Service | Guide | Residential IP required | VPS allowed | Devices / Acct | Devices / IP | Payout | Status |"
        divider = "|---------|-------|:-:|:-:|:-:|:-:|--------|--------|"

    selected.sort(key=lambda s: str(s.get("name", "")).lower())
    return "\n".join([header, divider, *(_row(s, kind) for s in selected)])


def render(readme: str) -> str:
    """Replace every generated region, leaving all other text untouched."""
    for kind in (DOCKER, EXTENSION, GPU):
        begin, end = BEGIN.format(name=kind), END.format(name=kind)
        if begin not in readme or end not in readme:
            raise SystemExit(
                f"README is missing the {kind} markers. Add:\n  {begin}\n  {end}\n"
                "around the table so it can be generated."
            )
        head, rest = readme.split(begin, 1)
        _stale, tail = rest.split(end, 1)
        readme = f"{head}{begin}\n{_table(kind)}\n{end}{tail}"
    return readme


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the README is out of date")
    args = parser.parse_args()

    path = ROOT / "README.md"
    current = path.read_text(encoding="utf-8")
    updated = render(current)

    if current == updated:
        print("README service tables are up to date.")
        return 0
    if args.check:
        print(
            "README service tables are out of date with the catalog.\nRun: python scripts/generate_readme_tables.py",
            file=sys.stderr,
        )
        return 1
    path.write_text(updated, encoding="utf-8")
    print("README service tables regenerated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
