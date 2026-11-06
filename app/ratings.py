"""Provider grades, computed from published criteria.

The method lives in ``services/_ratings.yml``: the criteria, what each verdict
is worth, the grade bands and the ceilings. Each service YAML records one
verdict per criterion in its ``rating:`` block, and every verdict rests on a
cited con or pro. This module turns the verdicts into a letter.

Three rules hold the design together:

* **Nobody types a grade.** The rating block has no grade, override, sponsor or
  featured field, and ``validate`` rejects any key it does not know, so the
  only way to move a grade is to change a verdict and cite why.
* **A is the top tier.** It needs 90% of the maximum score; the bands and
  their thresholds are published in the rules file.
* **Missing evidence never reads as good.** ``unknown`` scores the same as
  ``poor``, four unknowns cap the grade, and a service with no block is
  "Not rated yet", never a neutral grade. Same stance as app/disclosure.py.

Pure: no I/O beyond reading the rules file once.
"""

from __future__ import annotations

import datetime as _dt
import functools
from pathlib import Path
from typing import Any

import yaml

RULES_PATH = Path(__file__).resolve().parent.parent / "services" / "_ratings.yml"

#: The keys a rating block may hold. Anything else (grade, override, sponsored,
#: featured, paid, ...) is an error, which is what keeps grades criteria-only.
ALLOWED_KEYS = frozenset({"reviewed_on", "verdicts", "notes", "cons", "pros"})
VERDICTS = ("good", "fair", "poor", "unknown")
#: Best first. A ceiling of D means the grade is D or anything after it.
GRADE_ORDER = ("A", "B", "C", "D", "F")
NOT_RATED = "Not rated yet"


@functools.cache
def load_rules(path: Path | None = None) -> dict[str, Any]:
    """The published method, read once."""
    data = yaml.safe_load((path or RULES_PATH).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path or RULES_PATH}: expected a mapping")
    return data


def criteria_keys(rules: dict[str, Any] | None = None) -> list[str]:
    rules = rules or load_rules()
    return [c["key"] for c in rules["criteria"]]


def _iso_date(value: Any) -> _dt.date | None:
    """An ISO date, from a string or the date YAML makes of an unquoted one."""
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    if isinstance(value, str):
        try:
            return _dt.date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def validate(
    rating: Any,
    service: dict[str, Any] | None = None,
    *,
    rules: dict[str, Any] | None = None,
    today: _dt.date | None = None,
    check_future: bool = True,
) -> list[str]:
    """Every problem with one service's rating block, in plain words. Empty = valid.

    ``check_future=False`` skips the "date is in the future" checks. The running
    app passes it: a box whose clock is behind (a Raspberry Pi before NTP syncs,
    a timezone behind the one the date was written in) would otherwise reject
    every block reviewed today. CI and the tests keep the strict check.
    """
    rules = rules or load_rules()
    today = today or _dt.date.today()
    if not isinstance(rating, dict):
        return [f"rating must be a mapping, not {type(rating).__name__}"]
    errors: list[str] = []

    extra = sorted(set(rating) - ALLOWED_KEYS)
    if extra:
        errors.append(
            f"rating has key(s) {extra} that are not allowed; a grade comes only from the verdicts "
            f"(allowed: {sorted(ALLOWED_KEYS)})"
        )

    if _iso_date(rating.get("reviewed_on")) is None:
        errors.append("rating.reviewed_on must be an ISO date (YYYY-MM-DD)")
    elif check_future and _iso_date(rating.get("reviewed_on")) > today:
        errors.append("rating.reviewed_on is in the future")

    keys = criteria_keys(rules)
    verdicts = rating.get("verdicts")
    if not isinstance(verdicts, dict):
        errors.append("rating.verdicts must be a mapping of criterion to verdict")
        verdicts = {}
    missing = [k for k in keys if k not in verdicts]
    if missing:
        errors.append(f"rating.verdicts is missing {missing}; every criterion needs a verdict")
    unknown_keys = sorted(set(verdicts) - set(keys))
    if unknown_keys:
        errors.append(f"rating.verdicts names unknown criteria {unknown_keys}")
    for key, value in verdicts.items():
        if value not in VERDICTS:
            errors.append(f"rating.verdicts.{key} must be one of {list(VERDICTS)}, got {value!r}")

    notes = rating.get("notes") or {}
    if not isinstance(notes, dict):
        errors.append("rating.notes must be a mapping of criterion to text")
        notes = {}
    for key, value in notes.items():
        if key not in keys:
            errors.append(f"rating.notes names unknown criterion {key!r}")
        elif not isinstance(value, str) or not value.strip():
            errors.append(f"rating.notes.{key} must be text")

    kinds = set(rules.get("kinds") or {})
    tagged: dict[str, set[str]] = {"cons": set(), "pros": set()}
    for section in ("cons", "pros"):
        items = rating.get(section) or []
        if not isinstance(items, list):
            errors.append(f"rating.{section} must be a list")
            continue
        for i, item in enumerate(items):
            where = f"rating.{section}[{i}]"
            if not isinstance(item, dict):
                errors.append(f"{where} must be a mapping")
                continue
            if not isinstance(item.get("text"), str) or not item["text"].strip():
                errors.append(f"{where}.text must be text")
            criterion = item.get("criterion")
            if criterion not in keys:
                errors.append(f"{where}.criterion {criterion!r} is not a published criterion")
            else:
                tagged[section].add(criterion)
            kind = item.get("kind")
            if not isinstance(kind, str) or kind not in kinds:
                errors.append(f"{where}.kind must be one of {sorted(kinds)}, got {item.get('kind')!r}")
            source = item.get("source")
            if not isinstance(source, str) or not source.startswith("https://") or " " in source.strip():
                errors.append(f"{where}.source must be an https:// link")
            checked = _iso_date(item.get("checked_on"))
            if checked is None:
                errors.append(f"{where}.checked_on must be an ISO date (YYYY-MM-DD)")
            elif check_future and checked > today:
                errors.append(f"{where}.checked_on is in the future")

    for key, value in verdicts.items():
        if key not in keys:
            continue
        if value in ("fair", "poor") and key not in tagged["cons"]:
            errors.append(f"rating.verdicts.{key} is {value} but no con cites {key}")
        if value == "good" and key not in tagged["pros"]:
            errors.append(f"rating.verdicts.{key} is good but no pro cites {key}")
        if value == "unknown" and key not in notes:
            errors.append(f"rating.verdicts.{key} is unknown but rating.notes.{key} does not say what was searched")

    reqs = (service or {}).get("requirements")
    if reqs is None:
        reqs = {}
    if not isinstance(reqs, dict):
        errors.append("requirements must be a mapping, so the container rule can be checked")
    elif reqs.get("container_prohibited") and verdicts.get("terms_fit") != "poor":
        errors.append("requirements.container_prohibited is true, so rating.verdicts.terms_fit must be poor")

    return errors


def _band(percent: float, rules: dict[str, Any]) -> str:
    for band in rules["bands"]:
        if percent >= band["min_percent"]:
            return band["grade"]
    return GRADE_ORDER[-1]


def _worse(a: str, b: str) -> str:
    return a if GRADE_ORDER.index(a) >= GRADE_ORDER.index(b) else b


def _cap_holds(cap: dict[str, Any], service: dict[str, Any], verdicts: dict[str, str], unknowns: int) -> bool:
    key = cap["key"]
    if key == "container_prohibited":
        reqs = service.get("requirements") or {}
        return isinstance(reqs, dict) and bool(reqs.get("container_prohibited"))
    if key == "poor_payout_or_safety":
        return verdicts.get("payout_record") == "poor" or verdicts.get("account_safety") == "poor"
    if key == "thin_evidence":
        return unknowns >= cap["min_unknown"]
    raise ValueError(f"unknown cap {key!r} in the ratings rules")


def for_service(service: dict[str, Any] | None, *, rules: dict[str, Any] | None = None) -> dict[str, Any]:
    """The grade of one service, with everything that explains it."""
    rules = rules or load_rules()
    rating = (service or {}).get("rating")
    if not isinstance(rating, dict) or not isinstance(rating.get("verdicts"), dict):
        return {"rated": False, "grade": None, "summary": NOT_RATED}

    points = rules["points"]
    raw = rating["verdicts"]
    titles = {c["key"]: c["title"] for c in rules["criteria"]}
    verdicts = {key: raw.get(key, "unknown") for key in titles}
    score = sum(points.get(v, 0) for v in verdicts.values())
    maximum = max(points.values()) * len(verdicts)
    exact = 100 * score / maximum if maximum else 0.0
    # Rounded for display only: a band compares the exact share, so 89.96%
    # never rounds up into A.
    percent = round(exact, 1)
    unknowns = sum(1 for v in verdicts.values() if v == "unknown")

    band = _band(exact, rules)
    grade = band
    applied: list[dict[str, str]] = []
    for cap in rules["caps"]:
        if not _cap_holds(cap, service or {}, verdicts, unknowns):
            continue
        # A ceiling is reported only when it lowers the grade the score earned.
        if GRADE_ORDER.index(cap["max_grade"]) > GRADE_ORDER.index(band):
            applied.append({"key": cap["key"], "max_grade": cap["max_grade"], "reason": cap["reason"]})
            grade = _worse(grade, cap["max_grade"])

    cons = list(rating.get("cons") or [])
    return {
        "rated": True,
        "grade": grade,
        "band_grade": band,
        "score": score,
        "max": maximum,
        "percent": percent,
        "caps": applied,
        "unknown_count": unknowns,
        "thin_evidence": unknowns >= _thin_threshold(rules),
        "reviewed_on": str(rating.get("reviewed_on") or ""),
        "verdicts": [{"key": k, "title": titles[k], "verdict": verdicts[k]} for k in titles],
        "notes": dict(rating.get("notes") or {}),
        "cons": cons,
        "pros": list(rating.get("pros") or []),
        "top_cons": cons[:3],
        "summary": f"{grade}, {score} of {maximum}"
        + (
            f", thin evidence: {unknowns} of {len(verdicts)} criteria unchecked"
            if unknowns >= _thin_threshold(rules)
            else ""
        ),
    }


def _thin_threshold(rules: dict[str, Any]) -> int:
    for cap in rules["caps"]:
        if cap["key"] == "thin_evidence":
            return int(cap["min_unknown"])
    return len(rules["criteria"]) + 1
