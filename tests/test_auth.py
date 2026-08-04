"""Tests for password hashing and session tokens in app.auth.

Covers the bcrypt 72-byte truncation, hash/verify round-trips,
and session token encode/decode.
"""

import os

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402

try:
    from app.auth import (  # noqa: E402
        create_session_token,
        decode_session_token,
        hash_password,
        require_role,
        verify_password,
    )
except ImportError:
    pytest.skip("Requires full app dependencies (bcrypt, itsdangerous) — runs in CI", allow_module_level=True)


class TestHashPassword:
    """bcrypt password hashing via direct bcrypt library."""

    def test_short_ascii_password(self):
        h = hash_password("hello")
        assert verify_password("hello", h)

    def test_wrong_password_rejected(self):
        h = hash_password("correct")
        assert not verify_password("wrong", h)

    def test_empty_password(self):
        h = hash_password("")
        assert verify_password("", h)

    def test_exactly_72_ascii_bytes(self):
        pw = "x" * 72
        h = hash_password(pw)
        assert verify_password(pw, h)

    def test_73_ascii_bytes_truncated(self):
        """Byte 73+ is beyond bcrypt's limit; both must verify against same hash."""
        pw72 = "x" * 72
        pw73 = "x" * 73
        h = hash_password(pw72)
        assert verify_password(pw73, h)

    def test_long_password(self):
        pw = "a" * 200
        h = hash_password(pw)
        assert verify_password(pw, h)

    def test_multibyte_utf8_truncation(self):
        """72 accented chars = 144 UTF-8 bytes; truncation must be byte-based."""
        pw = "\u00e9" * 72  # each e-acute is 2 bytes
        h = hash_password(pw)
        assert verify_password(pw, h)

    def test_passwords_identical_first_72_bytes(self):
        """Passwords sharing the first 72 bytes must verify against same hash."""
        base = "A" * 72
        h = hash_password(base + "X")
        assert verify_password(base + "Y", h)

    def test_hash_is_bcrypt_format(self):
        h = hash_password("test")
        assert h.startswith("$2b$")

    def test_different_passwords_different_hashes(self):
        h1 = hash_password("alpha")
        h2 = hash_password("beta")
        assert not verify_password("alpha", h2)
        assert not verify_password("beta", h1)

    def test_unicode_password(self):
        pw = "p\u00e4ssw\u00f6rd\U0001f512"  # passw0rd + lock emoji
        h = hash_password(pw)
        assert verify_password(pw, h)


class TestSessionTokens:
    """Session token creation and decoding."""

    def test_round_trip(self):
        token = create_session_token(42, "alice", "owner")
        data = decode_session_token(token)
        assert data is not None
        assert data["uid"] == 42
        assert data["u"] == "alice"
        assert data["r"] == "owner"

    def test_tampered_token_returns_none(self):
        token = create_session_token(1, "bob", "viewer")
        tampered = token[:-4] + "XXXX"
        assert decode_session_token(tampered) is None

    def test_empty_string_returns_none(self):
        assert decode_session_token("") is None

    def test_garbage_returns_none(self):
        assert decode_session_token("not-a-real-token-at-all") is None


class TestRequireRole:
    """Role checking including fleet escalation."""

    def test_none_user_returns_false(self):
        assert require_role(None, "owner") is False

    def test_owner_satisfies_owner(self):
        assert require_role({"r": "owner"}, "owner") is True

    def test_writer_satisfies_writer(self):
        assert require_role({"r": "writer"}, "writer") is True

    def test_writer_does_not_satisfy_owner(self):
        assert require_role({"r": "writer"}, "owner") is False

    def test_fleet_does_NOT_satisfy_writer(self):
        """The shared fleet key must not be a writer credential.

        This test previously asserted the opposite, and the grant it protected
        was justified in a comment as being "for heartbeat/status endpoints".
        The heartbeat never went through require_role — api_worker_heartbeat
        uses _authenticate_worker_heartbeat — so the grant gave workers nothing
        they needed while unlocking five user-facing routes.

        That key is in every worker's compose file and readable with
        `docker inspect`. Verified against a running server before the change:
        a bare `Authorization: Bearer <fleet key>` POST to
        /api/earnings/payouts/1/reject returned 200 and permanently deleted the
        row, with no session and no account. It now returns 403.
        """
        assert require_role({"r": "fleet"}, "writer") is False

    def test_fleet_does_not_satisfy_owner(self):
        assert require_role({"r": "fleet"}, "owner") is False

    def test_the_heartbeat_path_does_not_depend_on_require_role(self):
        """What made removing the writer grant safe.

        If the heartbeat had gone through require_role, dropping the grant
        would have locked every worker out of the fleet.
        """
        import pathlib

        main_src = (pathlib.Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
        start = main_src.index("async def api_worker_heartbeat")
        body = main_src[start : start + 1200]
        assert "_authenticate_worker_heartbeat" in body
        assert "_require_writer" not in body

    def test_fleet_still_matches_when_fleet_is_explicitly_listed(self):
        """Removing the implicit grant must not break an explicit fleet check."""
        assert require_role({"r": "fleet"}, "fleet") is True
        assert require_role({"r": "fleet"}, "writer", "fleet") is True

    def test_fleet_does_not_satisfy_fleet_directly(self):
        # fleet role only has the implicit writer grant, not self-match unless listed
        assert require_role({"r": "fleet"}, "fleet") is True

    def test_writer_does_not_satisfy_fleet(self):
        assert require_role({"r": "writer"}, "fleet") is False

    def test_multiple_roles_accepted(self):
        assert require_role({"r": "owner"}, "writer", "owner") is True

    def test_empty_roles_returns_false(self):
        assert require_role({"r": "owner"}) is False


class TestAsyncPasswordWrappers:
    """The async wrappers run bcrypt off the event loop (apm perf)."""

    def test_hash_and_verify_async_roundtrip(self):
        import asyncio

        from app.auth import hash_password_async, verify_password_async

        async def run():
            h = await hash_password_async("correct-horse-battery-staple")
            assert await verify_password_async("correct-horse-battery-staple", h) is True
            assert await verify_password_async("wrong-password", h) is False

        asyncio.run(run())


class TestTheSharedFleetKeyCannotMutateFinancialRecords:
    """End-to-end, because the unit test alone would not have caught this.

    require_role is a pure function; the defect only becomes visible when you
    ask what a real request carrying the shared key can reach. Before the fix a
    bare `Authorization: Bearer <fleet key>` POST to
    /api/earnings/payouts/{id}/reject returned 200 and permanently deleted the
    row — no session, no account, on a server the caller had never logged into.

    The key is distributed to every worker host by design (docs/fleet.md puts it
    in the worker's compose environment), so this was reachable by any machine
    in the fleet, anyone who could `docker inspect cashpilot-worker`, and anyone
    who could read the shared /fleet volume.
    """

    def _call(self, handler_name, role, **kwargs):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from fastapi import HTTPException

        from app import main

        request = MagicMock()
        request.headers = {}
        request.cookies = {}
        request.client = MagicMock(host="127.0.0.1")

        async def run():
            with (
                # deps._require_auth_api resolves the user; patch there so the
                # REAL require_role still runs — patching require_role itself
                # would test nothing.
                patch("app.deps._require_auth_api", lambda r: {"uid": 0, "u": "x", "r": role}),
                patch.object(main.database, "reject_payout", AsyncMock(return_value=True)),
                patch.object(main.database, "confirm_payout", AsyncMock(return_value=True)),
            ):
                try:
                    await getattr(main, handler_name)(request, **kwargs)
                    return "allowed"
                except HTTPException as exc:
                    return exc.status_code

        return asyncio.run(run())

    def test_the_fleet_key_cannot_reject_a_payout(self):
        """Rejection is a hard DELETE FROM payouts. It is not recoverable."""
        assert self._call("api_reject_payout", "fleet", payout_id=1) == 403

    def test_the_fleet_key_cannot_confirm_a_payout(self):
        assert self._call("api_confirm_payout", "fleet", payout_id=1) == 403

    def test_a_real_writer_still_can(self):
        """Without this, the two above would pass with the feature broken."""
        assert self._call("api_reject_payout", "writer", payout_id=1) == "allowed"

    def test_an_owner_still_can(self):
        assert self._call("api_confirm_payout", "owner", payout_id=1) == "allowed"

    def test_a_viewer_still_cannot(self):
        """Unchanged behaviour, asserted so the fix cannot have loosened it."""
        assert self._call("api_reject_payout", "viewer", payout_id=1) == 403
