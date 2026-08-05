"""The version this image was built as.

Both apps hardcoded ``version="0.1.0"`` while releases are tag-driven and had
reached 1.11.x, so neither image knew or reported what it was. That made UI /
worker skew completely undetectable: an Unraid user updating the CashPilot app
but not the CashPilot Worker app — two separate Community Applications entries,
each on ``:latest`` — ends up running a 1.11 UI against a 1.4 worker, and
nothing in the fleet page, the workers table, the heartbeat or any log says so.
The symptoms surface as unexplained missing data (a worker that never reports an
egress IP, a button that 404s) with no way for the user or a support thread to
identify the cause.

The value is baked in at build time from the release tag. ``dev`` is the honest
answer anywhere else — a checkout, a local ``docker build``, the test suite —
because claiming a release number there would be worse than admitting ignorance.
"""

from __future__ import annotations

import os

#: What an image reports when it was not built from a release tag.
UNKNOWN = "dev"


def current() -> str:
    """The running version, or ``dev`` outside a release build."""
    return (os.getenv("CASHPILOT_VERSION") or "").strip() or UNKNOWN


def display() -> str:
    """How the running version should be shown to a person.

    A real release reads ``v1.11.34``; anything else reads ``dev``. The ``v`` is
    added HERE rather than in a template so no caller has to remember it, and so
    a dev build cannot end up rendered as ``vdev``.

    Exists because the sidebar printed a hardcoded ``CashPilot v0.2.49`` for
    roughly 150 releases while the correct value sat unread in CASHPILOT_VERSION.
    Never fabricate a number: a build that does not know its version says so.
    """
    value = current()
    # `series()` is the strict check: it requires MAJOR.MINOR of digits, so an
    # arbitrary string gets shown as-is rather than dressed up. is_release()
    # alone was too permissive -- it accepts anything not on its exclusion list,
    # so CASHPILOT_VERSION=not-a-release rendered as "vnot-a-release", which is
    # exactly the fabrication this function exists to prevent.
    return f"v{value}" if series(value) else value


def is_release(value: str | None = None) -> bool:
    """Whether a version string names an actual release rather than ``dev``."""
    return (value if value is not None else current()) not in ("", UNKNOWN, "latest", None)


def series(value: str | None) -> str | None:
    """The MAJOR.MINOR of a version, which is what skew is judged on.

    Patch releases inside a series are meant to interoperate; a difference in
    major or minor is the one worth telling somebody about.
    """
    text = (value or "").strip().lstrip("v")
    if not is_release(text):
        return None
    parts = text.split(".")
    if len(parts) < 2 or not all(p.isdigit() for p in parts[:2]):
        return None
    return f"{parts[0]}.{parts[1]}"


def skewed(ui: str | None, worker: str | None) -> bool:
    """True only when both sides are known releases AND their series differ.

    Deliberately conservative. An unknown version on either side is not
    evidence of skew — an older worker that predates version reporting sends
    nothing at all, and calling that "skewed" would light a warning on every
    fleet during the upgrade that introduces this.
    """
    ui_series, worker_series = series(ui), series(worker)
    if ui_series is None or worker_series is None:
        return False
    return ui_series != worker_series
