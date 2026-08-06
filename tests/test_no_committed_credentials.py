"""No tracked file may state a credential literally.

WHY THIS EXISTS WHEN GITGUARDIAN IS ALREADY INSTALLED
-----------------------------------------------------
On 2026-08-06 the Android repository's release keystore password was found in a
tracked ``CLAUDE.md``, in a PUBLIC repository, where it had sat since
2026-05-25. GitGuardian ran on every pull request throughout and passed.

That is not a GitGuardian failure. Secret scanners look for high-entropy tokens
and recognisable formats -- an AWS key, a JWT, a PEM block. What was committed
was a short memorable phrase in a sentence after the word "password:". To an
entropy detector, that is a sentence.

So this test does the opposite job on purpose: it looks for the SHAPE a person
writes when documenting a credential, and does not care whether the value looks
random. Between them the two halves are covered.

Nothing was found in this repository when the sweep was run -- it is preventive
here, not remedial. The Android repo carries the same check as a shell script in
CI (scripts/check-no-committed-credentials.sh); this is the same rule expressed
where this repository already keeps its guards.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: Match "<name> is/:/= <value>", then judge the VALUE separately. Doing it in
#: two steps rather than one clever regex is what makes this maintainable: the
#: first pass is deliberately loose, and every decision about what counts as a
#: credential lives in one readable function below.
_NAME = r"(password|passwd|passphrase|secret|api[_-]?key|auth[_-]?token)"
ASSIGNMENT = re.compile(rf"{_NAME}\s*(?:is|:|=)\s*([\"'`]?)([A-Za-z0-9_@.+-]{{6,}})\2", re.I)

#: Phrases that mean the line is talking ABOUT a credential rather than stating
#: one. Case-insensitive, and deliberately generous.
ALLOW = re.compile(
    r"example|placeholder|your-|<[a-z]|\$\{|\$\(|getenv|os\.environ|environment|"
    r"NOT recorded|the (password|secret|token|key)|a (password|secret|token|key)|"
    r"app signing key|upload key|document\.|getElementById",
    re.I,
)

#: Env-var NAMES are all-caps by convention, and a line naming one is
#: documentation, not disclosure. Matched case-SENSITIVELY on purpose: an
#: earlier version allowed "_KEY" case-insensitively, which silently suppressed
#: every line containing "api_key" -- including the ones it was meant to catch.
ENV_VAR_NAME = re.compile(r"[A-Z][A-Z0-9]*_(KEY|PASSWORD|TOKEN|SECRET|PASSPHRASE)")


def _looks_like_a_secret(value: str) -> bool:
    """Whether a value is plausibly a real credential rather than a word.

    A credential has structure a English word does not: a digit, or several
    separators. That single rule removes the whole false-positive class this
    check kept tripping on --

        MODE_PASSPHRASE = "passphrase"   the value IS the word
        passphrase=body.passphrase       attribute access
        const password = document...     a DOM lookup

    -- while still catching every real shape:

        cashpilot-release-2026   digits and hyphens
        sk-live-0123456789       digits and hyphens
        aaaa-bbbb-cccc-dddd      no digits, but three separators
    """
    if any(ch.isdigit() for ch in value):
        return True
    return sum(value.count(c) for c in "-@_") >= 2


#: Tests are excluded. Fixtures are SUPPOSED to look like credentials, and
#: scanning them produces noise that gets the whole check switched off.
#:
#: The tradeoff, stated rather than hidden: a real secret pasted into a test
#: would not be caught here. That is a narrower risk than documentation -- a
#: fixture is written to be fake, a doc line is written to be true -- but it is
#: a real gap, and GitGuardian remains the backstop for the high-entropy case.
EXCLUDED = ("tests/",)


def _tracked_files() -> list[Path]:
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True, check=False, timeout=30)
    if out.returncode != 0:
        pytest.skip("not a git checkout; nothing to sweep")
    return [ROOT / line for line in out.stdout.splitlines() if line and not line.startswith(EXCLUDED)]


def _offences(text: str) -> list[str]:
    hits = []
    for line in text.splitlines():
        if ALLOW.search(line) or ENV_VAR_NAME.search(line):
            continue
        for match in ASSIGNMENT.finditer(line):
            value = match.group(3)
            # A value equal to its own key name is a label, not a secret:
            # MODE_PASSPHRASE = "passphrase".
            if value.lower() == match.group(1).lower().replace("_", "").replace("-", ""):
                continue
            if _looks_like_a_secret(value):
                hits.append(line.strip()[:120])
                break
    return hits


def test_no_tracked_file_states_a_credential():
    offenders: dict[str, list[str]] = {}
    for path in _tracked_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # binary or unreadable: not prose, not our business
        found = _offences(text)
        if found:
            offenders[str(path.relative_to(ROOT))] = found

    assert not offenders, (
        "A tracked file appears to state a credential literally. This repository is "
        f"PUBLIC:\n{offenders}\n\nIf it is real: remove it, rotate it, and remember that "
        "redacting HEAD does not clear the history. If it is a false positive, widen ALLOW."
    )


class TestTheCheckCanActuallyFire:
    """Controls. A guard that cannot fail is worse than none — it gets cited as
    coverage. Both of these caught real bugs in the Android version of this
    rule: one pattern matched a variable assignment, and one ALLOW term
    ("signing key") silently suppressed the very line being guarded
    ("Signing keystore")."""

    def test_it_catches_the_exact_line_that_started_this(self):
        line = "- **Signing keystore:** password: `cashpilot-release-2026`"
        assert _offences(line), "the real-world line that prompted this check is not caught"

    @pytest.mark.parametrize(
        "line",
        [
            'password = "hunter2-abcdef"',
            "api_key: `sk-live-0123456789`",
            "auth_token is aaaa-bbbb-cccc-dddd",
        ],
    )
    def test_it_catches_other_literal_shapes(self, line):
        assert _offences(line), line

    @pytest.mark.parametrize(
        "line",
        [
            "self.password = password",  # a variable, not a value
            "apiKey = localKey",
            'password = os.getenv("CASHPILOT_PASSWORD")',
            "password: your-password-here",  # a placeholder
            "| `CASHPILOT_ADMIN_API_KEY` | unset | Bearer auth. |",
            "the password is not recorded here",
        ],
    )
    def test_it_stays_quiet_on_things_that_are_not_credentials(self, line):
        assert not _offences(line), line

    def test_the_sweep_actually_reads_files(self):
        """Without this, an empty file list would make the main test pass while
        checking nothing at all."""
        files = _tracked_files()
        assert len(files) > 50, f"only {len(files)} tracked files swept; the sweep is not working"
