"""Generate the provider ratings section of docs/ratings.md from the catalog.

The method comes from services/_ratings.yml and the evidence from each service
YAML's ``rating:`` block; app/ratings.py computes the grades. Only the region
between the markers is rewritten, so the hand-written explanation above it is
kept. Run with --check in CI to fail when the page is out of date.

The page carries no signup links: it links each provider's guide instead, so a
grade never sits next to a sign-up button.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import catalog, ratings  # noqa: E402

PAGE = ROOT / "docs" / "ratings.md"
BEGIN = "<!-- BEGIN GENERATED: ratings -->"
END = "<!-- END GENERATED: ratings -->"
STALE_DAYS = 365
_VERDICT_LABEL = {"good": "Good", "fair": "Fair", "poor": "Poor", "unknown": "Unknown"}


def _cell(text: object) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def _live() -> list[dict]:
    return [s for s in catalog.get_services() if s.get("status") in ("active", "beta")]


def _cited(item: dict) -> str:
    return f"{_cell(item['text'])} [Source]({item['source']}), checked {item['checked_on']}."


def _method(rules: dict) -> list[str]:
    out = [
        "## The criteria",
        "",
        "| Criterion | The question | Good | Fair | Poor |",
        "|---|---|---|---|---|",
    ]
    for c in rules["criteria"]:
        out.append(
            f"| {_cell(c['title'])} | {_cell(c['question'])} | {_cell(c['good'])} | {_cell(c['fair'])} | {_cell(c['poor'])} |"
        )
    pts = rules["points"]
    out += [
        "",
        f"Each verdict scores points: good {pts['good']}, fair {pts['fair']}, poor {pts['poor']}, "
        f"unknown {pts['unknown']}. Unknown scores the same as poor, so a provider we could not check "
        "is graded as cautiously as one with bad evidence.",
        "",
        "| Grade | Share of the maximum score |",
        "|---|---|",
    ]
    for band in rules["bands"]:
        out.append(f"| {band['grade']} | {band['min_percent']}% or more |")
    out += ["", "Ceilings, applied whatever the score:", ""]
    for cap in rules["caps"]:
        out.append(f"- **Capped at {cap['max_grade']}.** {_cell(cap['reason'])}")
    out += ["", "What a cited con or pro may rest on:", ""]
    for kind, meaning in rules["kinds"].items():
        out.append(f"- `{kind}`: {_cell(meaning)}")
    return out


def _summary(rows: list[tuple[dict, dict]]) -> list[str]:
    out = [
        "## All providers",
        "",
        "| Provider | Grade | Score | Unchecked | Reviewed | Worst con |",
        "|---|:---:|:---:|:---:|---|---|",
    ]
    for svc, r in rows:
        worst = r["cons"][0]["text"] if r["cons"] else "None found"
        out.append(
            f'| <a href="#{svc["slug"]}">{_cell(svc["name"])}</a> | {r["grade"]} | {r["score"]} of {r["max"]} '
            f"| {r['unknown_count']} | {r['reviewed_on']} | {_cell(worst)} |"
        )
    return out


def _provider(svc: dict, r: dict) -> list[str]:
    out = [
        f'<a id="{svc["slug"]}"></a>',
        "",
        f"### {svc['name']}",
        "",
        f"**Grade {r['grade']}**, {r['score']} of {r['max']} points, {r['unknown_count']} of {len(r['verdicts'])} "
        f"criteria unchecked, reviewed {r['reviewed_on']}. "
        f"Setup guide: [{svc['name']}](guides/{svc['slug']}.md).",
        "",
    ]
    for cap in r["caps"]:
        out += [f"- Capped at {cap['max_grade']}: {_cell(cap['reason'])}"]
    if r["caps"]:
        out.append("")
    out += ["| Criterion | Verdict | Note |", "|---|---|---|"]
    for v in r["verdicts"]:
        note = r["notes"].get(v["key"], "")
        out.append(f"| {_cell(v['title'])} | {_VERDICT_LABEL[v['verdict']]} | {_cell(note)} |")
    out += ["", "**Cons**", ""]
    out += [f"- {_cited(c)}" for c in r["cons"]] or ["- None found."]
    out += ["", "**Pros**", ""]
    out += [f"- {_cited(p)}" for p in r["pros"]] or ["- None found."]
    out.append("")
    return out


def _order(row: tuple[dict, dict]) -> tuple:
    svc, r = row
    return (ratings.GRADE_ORDER.index(r["grade"]), -r["score"], str(svc["name"]).lower())


def render_section() -> str:
    rules = ratings.load_rules()
    rows = []
    for svc in _live():
        r = ratings.for_service(svc)
        if r["rated"]:
            rows.append((svc, r))
    rows.sort(key=_order)
    lines = [BEGIN, "", *_method(rules), "", *_summary(rows), "", "## Provider details", ""]
    for svc, r in rows:
        lines += _provider(svc, r)
    lines.append(END)
    return "\n".join(lines)


def render_file(text: str) -> str:
    start, end = text.find(BEGIN), text.find(END)
    if start < 0 or end < start:
        raise SystemExit(f"{PAGE}: the {BEGIN} / {END} markers are missing")
    return text[:start] + render_section() + text[end + len(END) :]


def stale(today: dt.date | None = None) -> list[str]:
    today = today or dt.date.today()
    out = []
    for svc in _live():
        reviewed = ratings._iso_date((svc.get("rating") or {}).get("reviewed_on"))
        if reviewed and (today - reviewed).days > STALE_DAYS:
            out.append(f"{svc['slug']} (reviewed {reviewed})")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if docs/ratings.md is out of date")
    args = parser.parse_args()

    unrated = [s["slug"] for s in _live() if not ratings.for_service(s)["rated"]]
    if unrated:
        print(f"Not rated yet: {', '.join(unrated)}")
    for line in stale():
        print(f"Review is over {STALE_DAYS} days old: {line}")

    current = PAGE.read_text(encoding="utf-8")
    wanted = render_file(current)
    if args.check:
        if current != wanted:
            print("docs/ratings.md is out of date. Run: python scripts/generate_ratings_page.py")
            return 1
        print("docs/ratings.md matches the catalog.")
        return 0
    if current != wanted:
        PAGE.write_text(wanted, encoding="utf-8")
        print("docs/ratings.md updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
