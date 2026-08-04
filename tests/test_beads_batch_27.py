"""CashPilot-3hf: the credential checker was correct, complete, and dead.

``app/credential_test.py`` exists to end the "paste a token, wait up to an hour,
learn from the notification bell" loop. It classifies outcomes and produces
genuinely actionable sentences:

    Honeygain rejected these credentials. If they are a browser cookie or
    token, they have most likely expired — copy a fresh one and try again.

``/api/services/{slug}/test-credentials`` serves that. **No UI ever called it.**

What a user with a mistyped password actually got was the next scheduled run's
alert, rendered verbatim in the bell:

    Client error '401 Unauthorized' for url
    'https://dashboard.honeygain.com/api/v1/users/tokens' For more information
    check: https://developer.mozilla.org/…

Up to an hour later, and pointing at MDN.

The Save button on the credential modal now calls it and reports the verdict.
The endpoint deliberately returns no field that could carry a secret, so its
message is safe to show as-is.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "static" / "js" / "app.js"


def without_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in text.splitlines())


def js():
    return without_comments(APP_JS.read_text(encoding="utf-8"))


class TestTheCheckerIsReachableFromTheUI:
    def test_something_calls_the_endpoint(self):
        assert "/test-credentials" in js(), "the credential checker still has no caller"

    def test_the_save_button_passes_its_slug(self):
        """Without the slug the caller cannot name a service to test."""
        source = js()
        assert 'data-action="saveCredentialModal" data-a1="${escapeHtml(slug)}"' in source

    def test_the_handler_accepts_it(self):
        assert "async function saveCredentialModal(slug)" in js()

    def test_the_slug_is_url_encoded(self):
        """Slugs are catalog-controlled, but building a path by concatenation is
        the habit that eventually meets a value that needs escaping."""
        assert "encodeURIComponent(slug)" in js()

    def test_the_verdict_message_is_shown(self):
        source = js()
        assert "verdict.message" in source

    def test_success_and_failure_are_styled_differently(self):
        """A red toast for a working credential would be worse than silence."""
        assert "verdict.ok ? 'success' : 'error'" in js()


class TestAFailedCheckIsNotAFailedCredential:
    """The distinction that keeps this honest.

    If the CHECK itself cannot run — the app is unreachable, the provider times
    out, the endpoint 500s — saying "rejected" sends someone to re-copy a token
    that was fine. The two are reported differently.
    """

    def test_a_check_that_errors_says_so(self):
        source = js()
        assert "could not check them right now" in source

    def test_it_is_not_reported_as_an_error(self):
        source = js()
        i = source.index("could not check them right now")
        assert "'warning'" in source[i : i + 200], "an unavailable check is being reported as a rejection"

    def test_the_credentials_are_still_saved(self):
        """The save already succeeded; a failed check must not imply otherwise."""
        source = js()
        i = source.index("could not check them right now")
        assert "Saved, but" in source[i - 60 : i + 40]


class TestTheEndpointItCallsStillBehaves:
    """The UI is only worth wiring if what it calls is still correct."""

    def test_the_route_exists(self):
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert '@app.post("/api/services/{slug}/test-credentials")' in source

    def test_the_response_carries_a_message(self):
        from app import credential_test

        out = credential_test.result(credential_test.OK, "Honeygain", balance=3.5, currency="USD")
        assert out["ok"] is True
        assert out["message"]

    def test_a_rejection_is_actionable(self):
        """The sentence this whole bead is about."""
        from app import credential_test

        outcome = credential_test.classify("Client error '401 Unauthorized' for url 'https://x/api'")
        message = credential_test.message(outcome, "Honeygain", None, "")
        assert "Honeygain" in message
        assert "expired" in message.lower() or "reject" in message.lower()

    def test_the_response_cannot_carry_a_secret(self):
        """Deliberate, and worth pinning now that the message reaches a toast."""
        from app import credential_test

        out = credential_test.result(credential_test.OK, "Honeygain", balance=1.0, currency="USD", password="hunter2")
        assert "password" not in out
        assert "hunter2" not in str(out)

    @pytest.mark.parametrize("raw", ["", "connection timed out", "Client error '403 Forbidden' for url 'https://x'"])
    def test_classification_never_raises(self, raw):
        """It is now on the interactive path; a crash here is a broken Save."""
        from app import credential_test

        outcome = credential_test.classify(raw)
        assert credential_test.message(outcome, "Honeygain", None, "")
