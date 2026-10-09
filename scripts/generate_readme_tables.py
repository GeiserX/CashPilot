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

The same goes for every service COUNT in the README and the docs: a number
written as ``<!-- n:docker -->17<!-- /n -->`` is rewritten from the catalog.
Hand-typed counts drifted the same way the lists did; after one new service the
README still said "50 catalogued" while the guide index said 51.
"""

from __future__ import annotations

import argparse
import re
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

#: Files whose counts are generated. The README also carries the lists above.
COUNTED_FILES = ["README.md", "docs/index.md", "docs/getting-started.md", "docs/comparison.md"]
_COUNT = re.compile(r"<!-- n:(\w+) -->\d*<!-- /n -->")


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


def _live() -> list[dict]:
    return [s for s in catalog.get_services() if str(s.get("status")) in {"active", "beta"}]


def _selected(kind: str) -> list[dict]:
    services = _live()
    if kind == GPU:
        return [s for s in services if s.get("category") == "compute"]
    if kind == DOCKER:
        return [s for s in services if s.get("category") != "compute" and _is_dockerable(s)]
    return [s for s in services if s.get("category") != "compute" and not _is_dockerable(s)]


def _line(kind: str) -> str:
    selected = sorted(_selected(kind), key=lambda s: str(s.get("name", "")).lower())
    return f"**{_LABELS[kind]} ({len(selected)}):** " + ", ".join(_link(s) + _markers(s) for s in selected)


def counts() -> dict[str, int]:
    """Every number the docs state about the catalog, by marker name."""
    from app.collectors import COLLECTOR_MAP

    every = catalog.get_services()
    live = _live()
    status = [str(s.get("status")) for s in every]
    out = {
        "catalogued": len(every),
        "live": len(live),
        "active": status.count("active"),
        "beta": status.count("beta"),
        "retired": sum(st in {"broken", "dead", "dropped"} for st in status),
        "docker": len(_selected(DOCKER)),
        "extension": len(_selected(EXTENSION)),
        "gpu": len(_selected(GPU)),
        "collectors": len(COLLECTOR_MAP),
    }
    out["tracked"] = out["extension"] + out["gpu"]
    for category in ("bandwidth", "depin", "compute", "storage"):
        out[category] = sum(s.get("category") == category for s in live)
    return out


def render_counts(text: str, values: dict[str, int], name: str) -> str:
    def _sub(match: re.Match) -> str:
        key = match.group(1)
        if key not in values:
            raise SystemExit(f"{name}: unknown count marker n:{key}; known: {', '.join(sorted(values))}")
        return f"<!-- n:{key} -->{values[key]}<!-- /n -->"

    return _COUNT.sub(_sub, text)


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
    parser.add_argument("--check", action="store_true", help="fail if the README or docs are out of date")
    args = parser.parse_args()

    values = counts()
    stale = []
    for name in COUNTED_FILES:
        path = ROOT / name
        current = path.read_text(encoding="utf-8")
        updated = render(current) if name == "README.md" else current
        updated = render_counts(updated, values, name)
        if current == updated:
            continue
        stale.append(name)
        if not args.check:
            path.write_text(updated, encoding="utf-8")

    if not stale:
        print("README service lists and doc counts are up to date.")
        return 0
    if args.check:
        print(
            f"Out of date with the catalog: {', '.join(stale)}\nRun: python scripts/generate_readme_tables.py",
            file=sys.stderr,
        )
        return 1
    print(f"Regenerated: {', '.join(stale)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
