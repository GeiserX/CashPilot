"""Extended tests for individual collector classes.

Each collector follows the same pattern: authenticate + fetch balance via httpx.
We mock httpx.AsyncClient to test collect() logic without network calls.
"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest

from app.collectors.base import BaseCollector

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(status_code=200, json_data=None, text="", url="https://example.com"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    resp.url = url
    resp.headers = {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        import httpx as _httpx
        resp.raise_for_status.side_effect = _httpx.HTTPStatusError(
            f"HTTP {status_code}", request=MagicMock(), response=resp
        )
    return resp


def _make_async_client():
    """Create a base mock AsyncClient with proper async context manager."""
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


# ---------------------------------------------------------------------------
# BaseCollector
# ---------------------------------------------------------------------------


class TestBaseCollector:
    def test_base_raises_not_implemented(self):
        c = BaseCollector()
        with pytest.raises(NotImplementedError):
            asyncio.run(c.collect())


# ---------------------------------------------------------------------------
# Honeygain
# ---------------------------------------------------------------------------


class TestHoneygainCollector:
    def test_collect_success(self):
        from app.collectors.honeygain import HoneygainCollector

        login_resp = _mock_response(200, {"data": {"access_token": "jwt-token"}})
        balance_resp = _mock_response(200, {"data": {"payout": {"usd_cents": 550}}})
        client = _make_async_client()
        client.post.return_value = login_resp
        client.get.return_value = balance_resp

        with patch("app.collectors.honeygain.httpx.AsyncClient", return_value=client):
            c = HoneygainCollector(email="test@test.com", password="pass")
            result = asyncio.run(c.collect())
        assert result.balance == 5.50
        assert result.error is None

    def test_collect_auth_failure(self):
        from app.collectors.honeygain import HoneygainCollector

        client = _make_async_client()
        client.post.side_effect = Exception("Auth failed")

        with patch("app.collectors.honeygain.httpx.AsyncClient", return_value=client):
            c = HoneygainCollector(email="bad", password="bad")
            result = asyncio.run(c.collect())
        assert result.error is not None
        assert result.balance == 0.0

    def test_collect_token_refresh(self):
        from app.collectors.honeygain import HoneygainCollector

        login_resp = _mock_response(200, {"data": {"access_token": "new-jwt"}})
        expired_resp = MagicMock()
        expired_resp.status_code = 401
        ok_resp = _mock_response(200, {"data": {"payout": {"usd_cents": 100}}})

        client = _make_async_client()
        client.post.return_value = login_resp
        client.get.side_effect = [expired_resp, ok_resp]

        with patch("app.collectors.honeygain.httpx.AsyncClient", return_value=client):
            c = HoneygainCollector(email="test@test.com", password="pass")
            result = asyncio.run(c.collect())
        assert result.balance == 1.0
        assert result.error is None


# ---------------------------------------------------------------------------
# EarnApp — uses client.cookies internally, test error path reliably
# ---------------------------------------------------------------------------


class TestEarnAppCollector:
    def test_collect_error(self):
        from app.collectors.earnapp import EarnAppCollector

        client = _make_async_client()
        client.get.side_effect = Exception("Network error")

        with patch("app.collectors.earnapp.httpx.AsyncClient", return_value=client):
            c = EarnAppCollector(oauth_token="bad-token")
            result = asyncio.run(c.collect())
        assert result.error is not None
        assert result.balance == 0.0

    def test_collect_403(self):
        """Test authentication failure path."""
        from app.collectors.earnapp import EarnAppCollector

        xsrf_resp = _mock_response(200)
        forbidden_resp = _mock_response(403)
        forbidden_resp.raise_for_status = MagicMock()  # 403 is handled, not raised

        client = _make_async_client()
        # cookies.items() is called after the first GET
        client.cookies = httpx_cookies_mock({})
        client.get.side_effect = [xsrf_resp, forbidden_resp]

        with patch("app.collectors.earnapp.httpx.AsyncClient", return_value=client):
            c = EarnAppCollector(oauth_token="expired")
            result = asyncio.run(c.collect())
        assert result.error is not None
        assert "Authentication" in result.error


def httpx_cookies_mock(cookie_dict):
    """Create a mock that behaves like httpx.Cookies for .items() iteration."""
    mock = MagicMock()
    mock.items.return_value = list(cookie_dict.items())
    return mock


# ---------------------------------------------------------------------------
# IPRoyal
# ---------------------------------------------------------------------------


class TestIPRoyalCollector:
    def test_collect_success(self):
        from app.collectors.iproyal import IPRoyalCollector

        login_resp = _mock_response(200, {"access_token": "tok"})
        balance_resp = _mock_response(200, {"balance": 4.50})

        client = _make_async_client()
        client.post.return_value = login_resp
        client.get.return_value = balance_resp

        with patch("app.collectors.iproyal.httpx.AsyncClient", return_value=client):
            c = IPRoyalCollector(email="test@test.com", password="pass")
            result = asyncio.run(c.collect())
        assert result.error is None
        assert result.balance == 4.50

    def test_collect_login_failure(self):
        from app.collectors.iproyal import IPRoyalCollector

        login_resp = _mock_response(422)
        login_resp.raise_for_status = MagicMock()  # 422 is handled inline

        client = _make_async_client()
        client.post.return_value = login_resp

        with patch("app.collectors.iproyal.httpx.AsyncClient", return_value=client):
            c = IPRoyalCollector(email="bad", password="bad")
            result = asyncio.run(c.collect())
        assert result.error is not None

    def test_collect_network_error(self):
        from app.collectors.iproyal import IPRoyalCollector

        client = _make_async_client()
        client.post.side_effect = Exception("Network error")

        with patch("app.collectors.iproyal.httpx.AsyncClient", return_value=client):
            c = IPRoyalCollector(email="x", password="x")
            result = asyncio.run(c.collect())
        assert result.error is not None


# ---------------------------------------------------------------------------
# Traffmonetizer
# ---------------------------------------------------------------------------


class TestTraffmonetizerCollector:
    def test_collect_success_with_token(self):
        from app.collectors.traffmonetizer import TraffmonetizerCollector

        balance_resp = _mock_response(200, {"data": {"balance": 2.75}})
        client = _make_async_client()
        client.get.return_value = balance_resp

        with patch("app.collectors.traffmonetizer.httpx.AsyncClient", return_value=client):
            c = TraffmonetizerCollector(token="jwt-token")
            result = asyncio.run(c.collect())
        assert result.error is None
        assert result.balance == 2.75

    def test_collect_no_token_no_creds(self):
        from app.collectors.traffmonetizer import TraffmonetizerCollector

        client = _make_async_client()
        with patch("app.collectors.traffmonetizer.httpx.AsyncClient", return_value=client):
            c = TraffmonetizerCollector()
            result = asyncio.run(c.collect())
        assert result.error is not None
        assert "No token" in result.error

    def test_collect_error(self):
        from app.collectors.traffmonetizer import TraffmonetizerCollector

        client = _make_async_client()
        client.get.side_effect = Exception("Network error")

        with patch("app.collectors.traffmonetizer.httpx.AsyncClient", return_value=client):
            c = TraffmonetizerCollector(token="bad-token")
            result = asyncio.run(c.collect())
        assert result.error is not None


# ---------------------------------------------------------------------------
# Repocket
# ---------------------------------------------------------------------------


class TestRepocketCollector:
    def test_collect_success(self):
        from app.collectors.repocket import RepocketCollector

        login_resp = _mock_response(200, {"idToken": "id-tok", "refreshToken": "ref-tok"})
        balance_resp = _mock_response(200, {"centsCredited": 150})

        client = _make_async_client()
        client.post.return_value = login_resp
        client.get.return_value = balance_resp

        with patch("app.collectors.repocket.httpx.AsyncClient", return_value=client):
            c = RepocketCollector(email="test@test.com", password="pass")
            result = asyncio.run(c.collect())
        assert result.error is None
        assert result.balance == 1.50

    def test_collect_error(self):
        from app.collectors.repocket import RepocketCollector

        client = _make_async_client()
        client.post.side_effect = Exception("Login failed")

        with patch("app.collectors.repocket.httpx.AsyncClient", return_value=client):
            c = RepocketCollector(email="bad", password="bad")
            result = asyncio.run(c.collect())
        assert result.error is not None


# ---------------------------------------------------------------------------
# ProxyRack — uses POST for balance
# ---------------------------------------------------------------------------


class TestProxyRackCollector:
    def test_collect_success(self):
        from app.collectors.proxyrack import ProxyRackCollector

        balance_resp = _mock_response(200, {"data": {"balance": "$0.85"}})
        client = _make_async_client()
        client.post.return_value = balance_resp

        with patch("app.collectors.proxyrack.httpx.AsyncClient", return_value=client):
            c = ProxyRackCollector(api_key="test-api-key")
            result = asyncio.run(c.collect())
        assert result.error is None
        assert result.balance == 0.85

    def test_collect_auth_failure(self):
        from app.collectors.proxyrack import ProxyRackCollector

        resp = _mock_response(401)
        resp.raise_for_status = MagicMock()  # 401 handled inline
        client = _make_async_client()
        client.post.return_value = resp

        with patch("app.collectors.proxyrack.httpx.AsyncClient", return_value=client):
            c = ProxyRackCollector(api_key="bad-key")
            result = asyncio.run(c.collect())
        assert result.error is not None
        assert "Authentication" in result.error

    def test_collect_error(self):
        from app.collectors.proxyrack import ProxyRackCollector

        client = _make_async_client()
        client.post.side_effect = Exception("API error")

        with patch("app.collectors.proxyrack.httpx.AsyncClient", return_value=client):
            c = ProxyRackCollector(api_key="bad-key")
            result = asyncio.run(c.collect())
        assert result.error is not None


# ---------------------------------------------------------------------------
# Bitping — uses client.cookies like EarnApp, test error path
# ---------------------------------------------------------------------------


class TestBitpingCollector:
    def test_collect_error(self):
        from app.collectors.bitping import BitpingCollector

        client = _make_async_client()
        client.post.side_effect = Exception("Auth error")

        with patch("app.collectors.bitping.httpx.AsyncClient", return_value=client):
            c = BitpingCollector(email="bad", password="bad")
            result = asyncio.run(c.collect())
        assert result.error is not None
        assert result.balance == 0.0

    def test_collect_success(self):
        from app.collectors.bitping import BitpingCollector

        login_resp = _mock_response(200, {"token": "tok123"})
        balance_resp = _mock_response(200, {"usdEarnings": 0.15})

        client = _make_async_client()
        # Bitping checks client.cookies for "token" cookie after login
        client.cookies = httpx_cookies_mock({"token": "tok123"})
        client.post.return_value = login_resp
        client.get.return_value = balance_resp

        with patch("app.collectors.bitping.httpx.AsyncClient", return_value=client):
            c = BitpingCollector(email="test@test.com", password="pass")
            result = asyncio.run(c.collect())
        assert result.error is None
        assert result.balance == 0.15


# ---------------------------------------------------------------------------
# EarnFM
# ---------------------------------------------------------------------------


class TestEarnFMCollector:
    def test_collect_success(self):
        from app.collectors.earnfm import EarnFMCollector

        login_resp = _mock_response(200, {"access_token": "auth-tok", "refresh_token": "ref-tok"})
        balance_resp = _mock_response(200, {"data": {"totalBalance": 0.50}})

        client = _make_async_client()
        client.post.return_value = login_resp
        client.get.return_value = balance_resp

        with patch("app.collectors.earnfm.httpx.AsyncClient", return_value=client):
            c = EarnFMCollector(email="test@test.com", password="pass")
            result = asyncio.run(c.collect())
        assert result.error is None
        assert result.balance == 0.50

    def test_collect_error(self):
        from app.collectors.earnfm import EarnFMCollector

        client = _make_async_client()
        client.post.side_effect = Exception("Failed")

        with patch("app.collectors.earnfm.httpx.AsyncClient", return_value=client):
            c = EarnFMCollector(email="bad", password="bad")
            result = asyncio.run(c.collect())
        assert result.error is not None


# ---------------------------------------------------------------------------
# PacketStream — scrapes HTML
# ---------------------------------------------------------------------------


class TestPacketStreamCollector:
    def test_collect_success_html_pattern(self):
        from app.collectors.packetstream import PacketStreamCollector

        html = '<h3>Balance</h3><div><h2 class="x">$1.25</h2></div>'
        resp = _mock_response(200, text=html, url="https://app.packetstream.io/dashboard")
        resp.text = html
        client = _make_async_client()
        client.get.return_value = resp

        with patch("app.collectors.packetstream.httpx.AsyncClient", return_value=client):
            c = PacketStreamCollector(auth_token="jwt-token")
            result = asyncio.run(c.collect())
        assert result.error is None
        assert result.balance == 1.25

    def test_collect_auth_failure(self):
        from app.collectors.packetstream import PacketStreamCollector

        resp = _mock_response(200, url="https://app.packetstream.io/login")
        resp.raise_for_status = MagicMock()
        client = _make_async_client()
        client.get.return_value = resp

        with patch("app.collectors.packetstream.httpx.AsyncClient", return_value=client):
            c = PacketStreamCollector(auth_token="expired")
            result = asyncio.run(c.collect())
        assert result.error is not None
        assert "Authentication" in result.error

    def test_collect_error(self):
        from app.collectors.packetstream import PacketStreamCollector

        client = _make_async_client()
        client.get.side_effect = Exception("Error")

        with patch("app.collectors.packetstream.httpx.AsyncClient", return_value=client):
            c = PacketStreamCollector(auth_token="bad")
            result = asyncio.run(c.collect())
        assert result.error is not None


# ---------------------------------------------------------------------------
# Grass — complex multi-endpoint
# ---------------------------------------------------------------------------


class TestGrassCollector:
    def test_collect_settled_points(self):
        from app.collectors.grass import GrassCollector

        resp = _mock_response(200, {"result": {"data": {"totalPoints": 250.0}}})
        client = _make_async_client()
        client.get.return_value = resp

        with patch("app.collectors.grass.httpx.AsyncClient", return_value=client):
            c = GrassCollector(access_token="test-token")
            result = asyncio.run(c.collect())
        assert result.error is None
        assert result.balance == 250.0
        assert result.currency == "GRASS"

    def test_collect_auth_failure(self):
        from app.collectors.grass import GrassCollector

        resp = _mock_response(401)
        resp.raise_for_status = MagicMock()
        client = _make_async_client()
        client.get.return_value = resp

        with patch("app.collectors.grass.httpx.AsyncClient", return_value=client):
            c = GrassCollector(access_token="expired")
            result = asyncio.run(c.collect())
        assert result.error is not None
        assert "Token expired" in result.error

    def test_collect_error(self):
        from app.collectors.grass import GrassCollector

        client = _make_async_client()
        client.get.side_effect = Exception("Error")

        with patch("app.collectors.grass.httpx.AsyncClient", return_value=client):
            c = GrassCollector(access_token="bad")
            result = asyncio.run(c.collect())
        assert result.error is not None


# ---------------------------------------------------------------------------
# Bytelixir — session cookie scraper
# ---------------------------------------------------------------------------


class TestBytelixirCollector:
    def test_collect_session_expired(self):
        from app.collectors.bytelixir import BytelixirCollector

        resp = _mock_response(200, url="https://dash.bytelixir.com/login")
        client = _make_async_client()
        client.get.return_value = resp

        with patch.object(BytelixirCollector, "_make_client", return_value=client):
            c = BytelixirCollector(session_cookie="expired")
            result = asyncio.run(c.collect())
        assert result.error is not None
        assert "expired" in result.error.lower()

    def test_collect_html_scrape_success(self):
        from app.collectors.bytelixir import BytelixirCollector

        html = '<span>$</span>0.04<span class="text-2xs">025</span>'
        resp = _mock_response(200, text=html, url="https://dash.bytelixir.com/en")
        resp.text = html
        client = _make_async_client()
        client.get.return_value = resp

        with patch.object(BytelixirCollector, "_make_client", return_value=client):
            c = BytelixirCollector(session_cookie="valid-sess")
            result = asyncio.run(c.collect())
        assert result.error is None
        assert result.balance == pytest.approx(0.0403, abs=0.001)

    def test_collect_error(self):
        from app.collectors.bytelixir import BytelixirCollector

        client = _make_async_client()
        client.get.side_effect = Exception("Error")

        with patch.object(BytelixirCollector, "_make_client", return_value=client):
            c = BytelixirCollector(session_cookie="bad")
            result = asyncio.run(c.collect())
        assert result.error is not None

    def test_parse_balance_from_html(self):
        from app.collectors.bytelixir import BytelixirCollector

        html = '<span>$</span>1.23<span class="text-2xs">456</span>'
        assert BytelixirCollector._parse_balance_from_html(html) == 1.23456

    def test_parse_balance_no_match(self):
        from app.collectors.bytelixir import BytelixirCollector

        assert BytelixirCollector._parse_balance_from_html("<p>nothing</p>") is None


# ---------------------------------------------------------------------------
# Salad
# ---------------------------------------------------------------------------


class TestSaladCollector:
    def test_collect_success(self):
        from app.collectors.salad import SaladCollector

        balance_resp = _mock_response(200, {"currentBalance": 1.10})
        client = _make_async_client()
        client.get.return_value = balance_resp

        with patch("app.collectors.salad.httpx.AsyncClient", return_value=client):
            c = SaladCollector(auth_cookie="auth-cookie")
            result = asyncio.run(c.collect())
        assert result.error is None
        assert result.balance == 1.10

    def test_collect_auth_expired(self):
        from app.collectors.salad import SaladCollector

        resp = _mock_response(401)
        resp.raise_for_status = MagicMock()  # 401 handled inline
        client = _make_async_client()
        client.get.return_value = resp

        with patch("app.collectors.salad.httpx.AsyncClient", return_value=client):
            c = SaladCollector(auth_cookie="expired")
            result = asyncio.run(c.collect())
        assert result.error is not None
        assert "expired" in result.error.lower()

    def test_collect_error(self):
        from app.collectors.salad import SaladCollector

        client = _make_async_client()
        client.get.side_effect = Exception("Error")

        with patch("app.collectors.salad.httpx.AsyncClient", return_value=client):
            c = SaladCollector(auth_cookie="bad")
            result = asyncio.run(c.collect())
        assert result.error is not None


# ---------------------------------------------------------------------------
# Storj
# ---------------------------------------------------------------------------


class TestStorjCollector:
    def test_collect_success_current_month(self):
        from app.collectors.storj import StorjCollector

        data = {
            "currentMonth": {
                "egressBandwidthPayout": 150,
                "egressRepairAuditPayout": 50,
                "diskSpacePayout": 100,
            }
        }
        resp = _mock_response(200, data)
        client = _make_async_client()
        client.get.return_value = resp

        with patch("app.collectors.storj.httpx.AsyncClient", return_value=client):
            c = StorjCollector(api_url="http://localhost:14002")
            result = asyncio.run(c.collect())
        assert result.error is None
        assert result.balance == 3.0  # (150+50+100)/100

    def test_collect_connect_error(self):
        import httpx as _httpx

        from app.collectors.storj import StorjCollector

        client = _make_async_client()
        client.get.side_effect = _httpx.ConnectError("Connection refused")

        with patch("app.collectors.storj.httpx.AsyncClient", return_value=client):
            c = StorjCollector()
            result = asyncio.run(c.collect())
        assert result.error is not None
        assert "not reachable" in result.error

    def test_collect_generic_error(self):
        from app.collectors.storj import StorjCollector

        client = _make_async_client()
        client.get.side_effect = Exception("Error")

        with patch("app.collectors.storj.httpx.AsyncClient", return_value=client):
            c = StorjCollector()
            result = asyncio.run(c.collect())
        assert result.error is not None


# ---------------------------------------------------------------------------
# MystNodes
# ---------------------------------------------------------------------------


class TestMystNodesCollector:
    def test_collect_error(self):
        from app.collectors.mystnodes import MystNodesCollector

        client = _make_async_client()
        client.post.side_effect = Exception("Auth error")

        with patch("app.collectors.mystnodes.httpx.AsyncClient", return_value=client):
            c = MystNodesCollector(email="bad", password="bad")
            result = asyncio.run(c.collect())
        assert result.error is not None
        assert result.balance == 0.0
