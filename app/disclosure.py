"""What a service actually does with your machine (CashPilot-66x).

The most common reaction to software in this space is "is this malware?", and it
is a fair question: the user is being asked to run closed-source third-party
containers that route traffic through their home connection. Answering with an
earnings range and a setup guide does not address it.

The disclosure lives in the service YAML, like everything else service-specific.
This module only reads it and — the part that matters — makes the gaps visible.

**An absent disclosure must never read as a safe one.** A service nobody has
documented is exactly the service a user should be most careful with, so a
missing block reports ``documented: False`` and every unanswered question is
listed by name. Vagueness in the source deserves to be visible rather than
smoothed over, and "we do not know what this provider does with the traffic" is
a legitimate, useful answer.
"""

from __future__ import annotations

import re
from typing import Any

# The questions a user actually has before running one of these. Each is
# answerable in plain words; where it is not, that is itself the answer.
FIELDS: dict[str, str] = {
    "sells": "What is actually being sold — bandwidth, disk, compute, attention?",
    "third_party_traffic": "Do strangers route their traffic through your IP address?",
    "data_collected": "What identifying data leaves your machine?",
    "isp_risk": "What could this mean for your ISP contract?",
    "account_rules": "What are the account and multi-account rules?",
}

UNKNOWN = "unknown"

# Of the five, the one that creates real-world exposure. Tracked separately so a
# service can say "we answered everything except the question that matters".
CRITICAL_FIELD = "third_party_traffic"


def for_service(service: dict[str, Any] | None) -> dict[str, Any]:
    """Return the disclosure for one service, with its gaps named.

    ``answered``/``unanswered`` are what a UI should lead with: a half-filled
    disclosure that looks complete is worse than an obviously empty one.
    """
    if not service:
        return {
            "slug": None,
            "documented": False,
            "answers": {},
            "unanswered": list(FIELDS),
            "unknown": [],
            "answered_count": 0,
            "total_questions": len(FIELDS),
            "routes_third_party_traffic": None,
            "critical_unanswered": True,
            "questions": dict(FIELDS),
            "summary": "No disclosure for this service.",
        }

    slug = service.get("slug")
    raw = _block(service)
    answers: dict[str, str] = {}
    unanswered: list[str] = []
    unknowns: list[str] = []

    for field in FIELDS:
        value = _text(raw.get(field))
        # An explicit "unknown" is a real answer and is kept as one: it says
        # somebody looked and could not find out, which is different from
        # nobody having looked. It is COUNTED separately all the same, because
        # five unknowns is not a documented service.
        if not value:
            unanswered.append(field)
            continue
        answers[field] = value
        if value.lower().startswith(UNKNOWN):
            unknowns.append(field)

    documented = bool(answers)
    return {
        "slug": slug,
        "documented": documented,
        "answers": answers,
        "unanswered": unanswered,
        "unknown": unknowns,
        "answered_count": len(answers),
        "total_questions": len(FIELDS),
        # The one fact worth branching on. Exposed so no consumer has to
        # re-implement the parse and reproduce the bug it was written to avoid.
        "routes_third_party_traffic": routes_third_party_traffic(service),
        # Not all questions weigh the same: a service that answered everything
        # except whether strangers use your IP has not answered the one that
        # matters most.
        "critical_unanswered": CRITICAL_FIELD in unanswered,
        "questions": dict(FIELDS),
        "summary": _summary(service, documented, unanswered, unknowns),
    }


def _text(value: Any) -> str:
    """One answer as displayable text.

    YAML 1.1 coerces an unquoted ``yes``/``no``/``off`` to a bool, which is
    exactly what the schema tells authors to write. Rendering that as the
    literal "True" is worse than useless, so it is normalised back into the
    word the author meant.
    """
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value or "").strip()


def _block(service: dict[str, Any] | None) -> dict[str, Any]:
    """The service's disclosure mapping, or an empty one.

    A YAML author writing `disclosure: TODO` produced a string here, and calling
    .get() on it was a 500 at request time that the catalog loader does not
    catch.
    """
    raw = (service or {}).get("disclosure")
    return raw if isinstance(raw, dict) else {}


def _summary(service: dict[str, Any], documented: bool, unanswered: list[str], unknowns: list[str]) -> str:
    name = service.get("name") or service.get("slug") or "This service"
    if not documented:
        return (
            f"{name} has not been documented yet. That is not a statement that it is safe — "
            "it means nobody has written down what it does with your machine."
        )
    if not unanswered and len(unknowns) == len(FIELDS):
        # Every question was researched and none could be answered. Calling that
        # "fully documented" would be the most misleading string in the module.
        return (
            f"All {len(FIELDS)} questions about {name} were researched and NONE could be "
            "answered — the provider does not say. Treat that as a reason for caution, "
            "not as reassurance."
        )
    parts = []
    if unanswered:
        parts.append(f"{len(unanswered)} question(s) below are still unanswered")
    if unknowns:
        parts.append(f"{len(unknowns)} could not be answered by the provider")
    if not parts:
        return f"{name} is fully documented below."
    return f"{name} is partly documented: " + ", and ".join(parts) + "."


# The answer must OPEN with a STANDALONE yes/no/unknown — the word used as a
# verdict, then punctuation or the end of the string.
#
# A word boundary is not enough. "No longer — since v2 they route traffic"
# passes \b and means the opposite of what it parses as, which is the single
# most dangerous wrong answer this module can produce. A prefix match was worse
# still: it read "notably, strangers DO use your IP" as "no".
#
# So anything we cannot parse with confidence becomes None. That is the safe
# direction, and the catalog test below makes an unparseable answer fail CI
# rather than quietly becoming a verdict.
# A dash must be a separator, not part of a word: "TRUE-ish" is not a verdict,
# while "Yes - buyers proxy through you" is.
_VERDICT_RE = re.compile(r"^(yes|no|unknown|true|false)\s*(?:[.,:;!?]|[—–-]\s|$)", re.IGNORECASE)


def parse_verdict(value: Any) -> bool | None:
    """yes/no/unknown at the START of an answer, as a tri-state."""
    if isinstance(value, bool):
        # YAML 1.1 turns an unquoted `yes`/`no` into a real boolean before we
        # ever see it, so the schema's own advice produces this type.
        return value
    match = _VERDICT_RE.match(str(value or "").strip())
    if not match:
        return None
    word = match.group(1).lower()
    if word in {"yes", "true"}:
        return True
    if word in {"no", "false"}:
        return False
    return None


def routes_third_party_traffic(service: dict[str, Any] | None) -> bool | None:
    """Whether strangers use the user's IP. None when it is not documented.

    Deliberately three-valued. This is the single most consequential fact about
    most services in this catalog — it is what creates ISP and law-enforcement
    exposure — so neither "not documented" nor prose we failed to parse may
    collapse into "no".
    """
    if not service:
        return None
    return parse_verdict(_block(service).get("third_party_traffic"))


def coverage(services: list[dict[str, Any]]) -> dict[str, Any]:
    """How much of the catalog is documented, and which services are not.

    Kept honest on purpose: a partially documented catalog should be able to
    say so rather than presenting the documented subset as if it were all.
    """
    # Delegates rather than re-testing dict truthiness: a disclosure of
    # {"sells": "   "} or {"typo_field": "x"} is truthy but answers nothing, so
    # a second definition here overstated coverage in the one function whose
    # whole job is to be honest about the gap.
    flags = [(s.get("slug"), for_service(s)["documented"]) for s in services]
    documented = [slug for slug, ok in flags if ok]
    missing = sorted({str(slug or "") for slug, ok in flags if not ok})
    return {
        "total": len(services),
        "documented": len(documented),
        "undocumented": len(missing),
        "undocumented_slugs": missing,
    }
