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

    def test_fleet_satisfies_writer(self):
        assert require_role({"r": "fleet"}, "writer") is True

    def test_fleet_does_not_satisfy_owner(self):
        assert require_role({"r": "fleet"}, "owner") is False

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
