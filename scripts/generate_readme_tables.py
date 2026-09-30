"""Generate the README service lists from the catalog (CashPilot-9q1).

"YAML is the single source of truth" is the rule this project is built on, and
the README service lists were the one place it was violated: hand-maintained,
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

# Services shown in each list. Anything broken, dead or dropped is excluded
# from the catalog loader already.
DOCKER = "docker-services"
EXTENSION = "extension-services"
GPU = "gpu-services"


def _link(service: dict) -> str:
    url = (service.get("referral") or {}).get("signup_url") or service.get("website") or ""
    return f"[{service.get('name', service.get('slug'))}]({url})"


def _markers(service: dict) -> str:
    """Footnote markers, DERIVED from the catalog rather than hand-placed.

    A hand-placed marker is lost the first time the list is regenerated, which
    would silently delete the warning that EarnApp forbids the way CashPilot
    runs it — the most consequential sentence in this file.
    """
    if (service.get("requirements") or {}).get("container_prohibited"):
        return " \\*"
    return ""


def _is_dockerable(service: dict) -> bool:
    return bool((service.get("docker") or {}).get("image"))


_LABELS = {
    DOCKER: "Run in Docker by CashPilot",
    EXTENSION: "Browser extension or desktop app, tracked",
    GPU: "GPU compute, tracked",
}


def _line(kind: str) -> str:
    services = [s for s in catalog.get_services() if str(s.get("status")) in {"active", "beta"}]
    if kind == GPU:
        selected = [s for s in services if s.get("category") == "compute"]
    elif kind == DOCKER:
        selected = [s for s in services if s.get("category") != "compute" and _is_dockerable(s)]
    else:
        selected = [s for s in services if s.get("category") != "compute" and not _is_dockerable(s)]
    selected.sort(key=lambda s: str(s.get("name", "")).lower())
    return f"**{_LABELS[kind]} ({len(selected)}):** " + ", ".join(_link(s) + _markers(s) for s in selected)


def render(readme: str) -> str:
    """Replace every generated region, leaving all other text untouched."""
    for kind in (DOCKER, EXTENSION, GPU):
        begin, end = BEGIN.format(name=kind), END.format(name=kind)
        if begin not in readme or end not in readme:
            raise SystemExit(
                f"README is missing the {kind} markers. Add:\n  {begin}\n  {end}\n"
                "around the list so it can be generated."
            )
        head, rest = readme.split(begin, 1)
        _stale, tail = rest.split(end, 1)
        readme = f"{head}{begin}\n{_line(kind)}\n{end}{tail}"
    return readme


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the README is out of date")
    args = parser.parse_args()

    path = ROOT / "README.md"
    current = path.read_text(encoding="utf-8")
    updated = render(current)

    if current == updated:
        print("README service lists are up to date.")
        return 0
    if args.check:
        print(
            "README service lists are out of date with the catalog.\nRun: python scripts/generate_readme_tables.py",
            file=sys.stderr,
        )
        return 1
    path.write_text(updated, encoding="utf-8")
    print("README service lists regenerated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
