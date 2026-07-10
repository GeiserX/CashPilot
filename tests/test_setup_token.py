"""Tests for the first-run setup-token gate (app/setup_token.py + app/deps)."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app import deps, setup_token


def _req(host="127.0.0.1", xff=None, query=None, headers=None):
    """A minimal fake Request: real dicts for headers/query_params so .get works."""
    req = MagicMock()
    if host is None:
        req.client = None
    else:
        req.client.host = host
    h = {}
    if xff is not None:
        h["x-forwarded-for"] = xff
    if headers:
        h.update(headers)
    req.headers = h
    req.query_params = query or {}
    return req


class TestSetupTokenModule:
    def test_verify_no_active_allows_anything(self):
        setup_token.clear()
        assert setup_token.verify(None) is True
        assert setup_token.verify("whatever") is True

    def test_verify_active_requires_exact_match(self):
        setup_token.set_active("s3cret")
        assert setup_token.verify("s3cret") is True
        assert setup_token.verify("wrong") is False
        assert setup_token.verify(None) is False
        assert setup_token.verify("") is False

    def test_generate_is_unique_and_long(self):
        a, b = setup_token.generate(), setup_token.generate()
        assert a != b
        assert len(a) >= 20

    def test_set_active_empty_string_deactivates(self):
        setup_token.set_active("")
        assert setup_token.active() is None


class TestClientIp:
    def test_ignores_xff_without_trusted_proxy(self):
        with patch.object(deps, "_TRUST_PROXY", False):
            assert deps.client_ip(_req("10.0.0.1", xff="1.2.3.4")) == "10.0.0.1"

    def test_uses_rightmost_xff_with_trusted_proxy(self):
        # The trusted proxy appends the real peer on the right; a client can only
        # forge entries on the left, so the right-most value is authoritative.
        with patch.object(deps, "_TRUST_PROXY", True):
            req = _req("10.0.0.1", xff="9.9.9.9, 8.8.8.8, 203.0.113.5")
            assert deps.client_ip(req) == "203.0.113.5"

    def test_trusted_proxy_falls_back_to_peer_without_xff(self):
        with patch.object(deps, "_TRUST_PROXY", True):
            assert deps.client_ip(_req("10.0.0.1")) == "10.0.0.1"

    def test_no_client_returns_none(self):
        with patch.object(deps, "_TRUST_PROXY", False):
            assert deps.client_ip(_req(host=None)) is None


class TestRequireFirstRunAccess:
    def test_blocks_when_token_active_and_missing(self):
        setup_token.set_active("tok")
        with patch.object(deps, "_TRUST_PROXY", False), pytest.raises(HTTPException) as ei:
            deps._require_first_run_access(_req("127.0.0.1"))
        assert ei.value.status_code == 403

    def test_allows_with_correct_token_arg(self):
        setup_token.set_active("tok")
        with patch.object(deps, "_TRUST_PROXY", False):
            assert deps._require_first_run_access(_req("127.0.0.1"), "tok") is None

    def test_token_from_query_param(self):
        setup_token.set_active("tok")
        with patch.object(deps, "_TRUST_PROXY", False):
            assert deps._require_first_run_access(_req("127.0.0.1", query={"setup_token": "tok"})) is None

    def test_token_from_header(self):
        setup_token.set_active("tok")
        with patch.object(deps, "_TRUST_PROXY", False):
            assert deps._require_first_run_access(_req("127.0.0.1", headers={"x-setup-token": "tok"})) is None

    def test_public_ip_blocked_even_with_correct_token(self):
        # The network check runs first: a public client is refused regardless of token.
        setup_token.set_active("tok")
        with patch.object(deps, "_TRUST_PROXY", False), pytest.raises(HTTPException) as ei:
            deps._require_first_run_access(_req("8.8.8.8"), "tok")
        assert ei.value.status_code == 403

    def test_no_active_token_falls_back_to_network_only(self):
        # Once the token is retired, first-run access is network-gated only.
        setup_token.clear()
        with patch.object(deps, "_TRUST_PROXY", False):
            assert deps._require_first_run_access(_req("192.168.1.5")) is None
