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
            "summary": "No disclosure for this service.",
        }

    slug = service.get("slug")
    raw = service.get("disclosure") or {}
    answers: dict[str, str] = {}
    unanswered: list[str] = []

    for field in FIELDS:
        value = str(raw.get(field) or "").strip()
        # An explicit "unknown" is a real answer and is kept as one: it says
        # somebody looked and could not find out, which is different from
        # nobody having looked.
        if not value:
            unanswered.append(field)
        else:
            answers[field] = value

    documented = bool(answers)
    return {
        "slug": slug,
        "documented": documented,
        "answers": answers,
        "unanswered": unanswered,
        "questions": FIELDS,
        "summary": _summary(service, documented, unanswered),
    }


def _summary(service: dict[str, Any], documented: bool, unanswered: list[str]) -> str:
    name = service.get("name") or service.get("slug") or "This service"
    if not documented:
        return (
            f"{name} has not been documented yet. That is not a statement that it is safe — "
            "it means nobody has written down what it does with your machine."
        )
    if unanswered:
        return f"{name} is partly documented. {len(unanswered)} question(s) below are still unanswered."
    return f"{name} is fully documented below."


def routes_third_party_traffic(service: dict[str, Any] | None) -> bool | None:
    """Whether strangers use the user's IP. None when it is not documented.

    Deliberately three-valued. This is the single most consequential fact about
    most services in this catalog — it is what creates ISP and law-enforcement
    exposure — so "not documented" must not collapse into "no".
    """
    if not service:
        return None
    value = str((service.get("disclosure") or {}).get("third_party_traffic") or "").strip().lower()
    if not value or value.startswith(UNKNOWN):
        return None
    if value.startswith(("yes", "true")):
        return True
    if value.startswith(("no", "false")):
        return False
    return None


def coverage(services: list[dict[str, Any]]) -> dict[str, Any]:
    """How much of the catalog is documented, and which services are not.

    Kept honest on purpose: a partially documented catalog should be able to
    say so rather than presenting the documented subset as if it were all.
    """
    documented = [s for s in services if (s.get("disclosure") or {})]
    missing = sorted(s.get("slug") for s in services if not (s.get("disclosure") or {}))
    return {
        "total": len(services),
        "documented": len(documented),
        "undocumented": len(missing),
        "undocumented_slugs": missing,
    }
