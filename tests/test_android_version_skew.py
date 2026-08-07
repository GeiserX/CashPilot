"""An Android client is judged against Android releases, not against the server.

Reported from the live fleet: every phone showed "v0.3.0 != UI v1.24.1",
permanently. That was never skew. The Android client ships on its own release
track and its versions will never match the server's, so the comparison could
only ever be false -- and a warning that is always on is a warning that teaches
the operator to ignore the one that matters.

The rule these tests pin: compare a phone to the newest CashPilot-android
release, compare everything else to the UI, and when the reference is unknown
say NOTHING. That last one is the important one -- an unreachable GitHub must
make the warning disappear, never make every phone look out of date.
"""

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

from app import update_check, version  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_cache():
    update_check._reset_for_tests()
    yield
    update_check._reset_for_tests()


def _reference(system_info: dict, ui_version: str) -> str | None:
    """The reference main.py picks. Mirrors the enrichment, without a DB."""
    is_android = str(system_info.get("os") or "").strip().lower() == "android"
    return update_check.android_latest() if is_android else ui_version


class TestThePhoneIsNotComparedToTheServer:
    def test_a_current_phone_is_not_skewed_against_a_1x_ui(self):
        """The reported bug, stated as the app actually saw it."""
        update_check._android_tag = "v0.3.0"
        si = {"os": "Android", "version": "0.3.0"}
        ref = _reference(si, "1.24.1")
        assert ref == "v0.3.0"
        assert version.skewed(ref, si["version"]) is False

    def test_the_old_behaviour_WOULD_have_flagged_it(self):
        """Control. If comparing to the UI did not flag it, this test proves
        nothing about the fix -- the bug has to be reproducible."""
        assert version.skewed("1.24.1", "0.3.0") is True

    def test_a_genuinely_old_phone_IS_still_flagged(self):
        """The fix must not silence real skew, only the fabricated kind."""
        update_check._android_tag = "v0.5.0"
        si = {"os": "Android", "version": "0.3.0"}
        assert version.skewed(_reference(si, "1.24.1"), si["version"]) is True

    def test_a_patch_behind_is_not_skew(self):
        """Skew is judged on major.minor; patches inside a series interoperate."""
        update_check._android_tag = "v0.3.9"
        si = {"os": "Android", "version": "0.3.0"}
        assert version.skewed(_reference(si, "1.24.1"), si["version"]) is False


class TestUnknownReferenceSaysNothing:
    """The failure mode that must never produce a warning."""

    def test_unreachable_github_means_no_warning(self):
        update_check._android_tag = None  # never fetched, or every fetch failed
        si = {"os": "Android", "version": "0.3.0"}
        assert _reference(si, "1.24.1") is None
        assert version.skewed(None, si["version"]) is False

    @pytest.mark.parametrize("flag", ["0", "off", "false", "no"])
    @pytest.mark.asyncio
    async def test_disabled_check_fetches_nothing_and_warns_about_nothing(self, flag):
        with patch.dict(os.environ, {"CASHPILOT_UPDATE_CHECK": flag}):
            assert await update_check.refresh_android() is None
            assert update_check.android_latest() is None
            assert version.skewed(update_check.android_latest(), "0.3.0") is False


class TestNonAndroidIsUnaffected:
    def test_a_linux_worker_is_still_compared_to_the_ui(self):
        update_check._android_tag = "v0.3.0"
        si = {"os": "Linux", "version": "1.13.0"}
        assert _reference(si, "1.24.1") == "1.24.1"
        assert version.skewed(_reference(si, "1.24.1"), si["version"]) is True

    def test_a_matching_linux_worker_is_not_skewed(self):
        si = {"os": "Linux", "version": "1.24.1"}
        assert version.skewed(_reference(si, "1.24.1"), si["version"]) is False

    def test_os_detection_is_case_insensitive_and_whitespace_tolerant(self):
        update_check._android_tag = "v0.3.0"
        for spelling in ("Android", "android", "ANDROID", "  Android  "):
            assert _reference({"os": spelling, "version": "0.3.0"}, "1.24.1") == "v0.3.0"

    def test_a_worker_with_no_os_falls_back_to_the_ui(self):
        """Absent is not Android. An unknown OS must not silently get the
        Android yardstick, or a container would be judged against a phone."""
        update_check._android_tag = "v0.3.0"
        assert _reference({"version": "1.13.0"}, "1.24.1") == "1.24.1"


class TestTheFetchNeverRaises:
    @pytest.mark.asyncio
    async def test_a_broken_response_lands_on_unknown(self):
        class _Boom:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **k):
                raise RuntimeError("no network")

        with patch("app.update_check.httpx.AsyncClient", lambda **k: _Boom()):
            assert await update_check.refresh_android(force=True) is None
        assert update_check.android_latest() is None

    @pytest.mark.asyncio
    async def test_a_tag_that_is_not_a_version_is_rejected(self):
        """Third-party JSON. A tag like 'nightly' must not be shown as a release."""
        assert update_check._parse_tag({"tag_name": "nightly"}) is None
        assert update_check._parse_tag({"tag_name": "v0.3.0"}) == "v0.3.0"
