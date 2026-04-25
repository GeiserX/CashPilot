"""Deep collector tests covering auth refresh paths, specific response parsing,
and edge cases that the basic tests didn't cover."""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")



def _make_async_client():
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


def _mock_response(status_code=200, json_data=None, text="", url="https://example.com"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    resp.url = url
    resp.headers = {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        import httpx
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}", request=MagicMock(), response=resp
        )
    return resp


# ---------------------------------------------------------------------------
# MystNodes — comprehensive
# ---------------------------------------------------------------------------


class TestMystNodesCollectorDeep:
    def test_collect_success(self):
        from app.collectors.mystnodes import MystNodesCollector

        login_resp = _mock_response(200, {"accessToken": "at", "refreshToken": "rt"})
        earnings_resp = _mock_response(200, {"earningsTotal": 12.5})

        client = _make_async_client()
        client.post.return_value = login_resp
        client.get.return_value = earnings_resp

        with patch("app.collectors.mystnodes.httpx.AsyncClient", return_value=client):
            c = MystNodesCollector(email="test@test.com", password="pass")
            result = asyncio.run(c.collect())
        assert result.error is None
        assert result.balance == 12.5
        assert result.currency == "MYST"

    def test_collect_no_credentials(self):
        from app.collectors.mystnodes import MystNodesCollector

        c = MystNodesCollector(email="", password="")
        result = asyncio.run(c.collect())
        assert result.error is not None
        assert "not configured" in result.error

    def test_collect_with_token_refresh(self):
        from app.collectors.mystnodes import MystNodesCollector

        login_resp = _mock_response(200, {"accessToken": "at", "refreshToken": "rt"})
        expired_resp = MagicMock()
        expired_resp.status_code = 401
        ok_resp = _mock_response(200, {"earningsTotal": 5.0})

        refresh_resp = _mock_response(200, {"accessToken": "new-at", "refreshToken": "new-rt"})

        client = _make_async_client()
        client.post.side_effect = [login_resp, refresh_resp]
        client.get.side_effect = [expired_resp, ok_resp]

        with patch("app.collectors.mystnodes.httpx.AsyncClient", return_value=client):
            c = MystNodesCollector(email="test@test.com", password="pass")
            result = asyncio.run(c.collect())
        assert result.error is None
        assert result.balance == 5.0

    def test_get_per_node_earnings(self):
        from app.collectors.mystnodes import MystNodesCollector

        login_resp = _mock_response(200, {"accessToken": "at", "refreshToken": "rt"})
        nodes_resp = _mock_response(200, {
            "nodes": [
                {
                    "identity": "0xabc123",
                    "name": "node-1",
                    "localIp": "192.168.1.10",
                    "nodeStatus": {"online": True},
                    "country": {"code": "US"},
                    "version": "1.0.0",
                    "earnings": [{"etherAmount": 0.5}, {"etherAmount": 0.3}],
                    "lifetimeEarnings": {
                        "totalEther": 10.0,
                        "settledEther": 8.0,
                        "unsettledEther": 2.0,
                    },
                }
            ]
        })

        client = _make_async_client()
        client.post.return_value = login_resp
        client.get.return_value = nodes_resp

        with patch("app.collectors.mystnodes.httpx.AsyncClient", return_value=client):
            c = MystNodesCollector(email="test@test.com", password="pass")
            result = asyncio.run(c.get_per_node_earnings())
        assert len(result) == 1
        assert result[0]["identity"] == "0xabc123"
        assert result[0]["earnings_myst"] == 0.8
        assert result[0]["online"] is True

    def test_get_per_node_no_creds(self):
        from app.collectors.mystnodes import MystNodesCollector

        c = MystNodesCollector(email="", password="")
        result = asyncio.run(c.get_per_node_earnings())
        assert result == []

    def test_get_per_node_error(self):
        from app.collectors.mystnodes import MystNodesCollector

        client = _make_async_client()
        client.post.side_effect = Exception("Auth failed")

        with patch("app.collectors.mystnodes.httpx.AsyncClient", return_value=client):
            c = MystNodesCollector(email="test@test.com", password="pass")
            result = asyncio.run(c.get_per_node_earnings())
        assert result == []


# ---------------------------------------------------------------------------
# Traffmonetizer — auth path
# ---------------------------------------------------------------------------


class TestTraffmonetizerDeep:
    def test_collect_with_email_auth(self):
        from app.collectors.traffmonetizer import TraffmonetizerCollector

        login_resp = _mock_response(200, {"data": {"token": "jwt-tok"}})
        balance_resp = _mock_response(200, {"data": {"balance": 1.50}})

        client = _make_async_client()
        client.post.return_value = login_resp
        client.get.return_value = balance_resp

        with patch("app.collectors.traffmonetizer.httpx.AsyncClient", return_value=client):
            c = TraffmonetizerCollector(email="test@test.com", password="pass")
            result = asyncio.run(c.collect())
        assert result.error is None
        assert result.balance == 1.50

    def test_collect_token_refresh_on_401(self):
        from app.collectors.traffmonetizer import TraffmonetizerCollector

        expired_resp = MagicMock()
        expired_resp.status_code = 401
        login_resp = _mock_response(200, {"data": {"token": "new-tok"}})
        ok_resp = _mock_response(200, {"data": {"balance": 0.75}})

        client = _make_async_client()
        client.post.return_value = login_resp
        client.get.side_effect = [expired_resp, ok_resp]

        with patch("app.collectors.traffmonetizer.httpx.AsyncClient", return_value=client):
            c = TraffmonetizerCollector(email="test@test.com", password="pass", token="old-tok")
            result = asyncio.run(c.collect())
        assert result.error is None
        assert result.balance == 0.75

    def test_collect_auth_permanently_failed(self):
        from app.collectors.traffmonetizer import TraffmonetizerCollector

        resp_401 = MagicMock()
        resp_401.status_code = 401

        client = _make_async_client()
        client.get.return_value = resp_401
        # No email set, so no re-auth possible
        with patch("app.collectors.traffmonetizer.httpx.AsyncClient", return_value=client):
            c = TraffmonetizerCollector(token="expired-tok")
            result = asyncio.run(c.collect())
        assert result.error is not None
        assert "Authentication" in result.error


# ---------------------------------------------------------------------------
# EarnFM — auth refresh path
# ---------------------------------------------------------------------------


class TestEarnFMDeep:
    def test_collect_with_token_refresh(self):
        from app.collectors.earnfm import EarnFMCollector

        login_resp = _mock_response(200, {"access_token": "at", "refresh_token": "rt"})
        expired_resp = MagicMock()
        expired_resp.status_code = 401
        refresh_resp = _mock_response(200, {"access_token": "new-at", "refresh_token": "new-rt"})
        ok_resp = _mock_response(200, {"data": {"totalBalance": 1.25}})

        client = _make_async_client()
        client.post.side_effect = [login_resp, refresh_resp]
        client.get.side_effect = [expired_resp, ok_resp]

        with patch("app.collectors.earnfm.httpx.AsyncClient", return_value=client):
            c = EarnFMCollector(email="test@test.com", password="pass")
            result = asyncio.run(c.collect())
        assert result.error is None
        assert result.balance == 1.25


# ---------------------------------------------------------------------------
# Repocket — auth refresh path
# ---------------------------------------------------------------------------


class TestRepocketDeep:
    def test_collect_with_token_refresh(self):
        from app.collectors.repocket import RepocketCollector

        login_resp = _mock_response(200, {"idToken": "id-tok", "refreshToken": "ref-tok"})
        expired_resp = MagicMock()
        expired_resp.status_code = 401
        refresh_resp = _mock_response(200, {"id_token": "new-id", "refresh_token": "new-ref"})
        ok_resp = _mock_response(200, {"centsCredited": 200})

        client = _make_async_client()
        client.post.side_effect = [login_resp, refresh_resp]
        client.get.side_effect = [expired_resp, ok_resp]

        with patch("app.collectors.repocket.httpx.AsyncClient", return_value=client):
            c = RepocketCollector(email="test@test.com", password="pass")
            result = asyncio.run(c.collect())
        assert result.error is None
        assert result.balance == 2.0


# ---------------------------------------------------------------------------
# Grass — active devices estimation
# ---------------------------------------------------------------------------


class TestGrassDeep:
    def test_collect_active_devices_estimation(self):
        from app.collectors.grass import GrassCollector

        # First call: settled points = 0 (active epoch)
        user_resp = _mock_response(200, {"result": {"data": {"totalPoints": 0}}})
        # Second call: active devices
        devices_resp = _mock_response(200, {
            "result": {"data": [
                {"aggUptime": 3600, "ipScore": 80, "multiplier": 1.0, "ipAddress": "1.2.3.4"},
            ]}
        })

        client = _make_async_client()
        client.get.side_effect = [user_resp, devices_resp]

        with patch("app.collectors.grass.httpx.AsyncClient", return_value=client):
            c = GrassCollector(access_token="test-token")
            result = asyncio.run(c.collect())
        assert result.error is None
        # 1 hour * 50 base * (80/100) * 1.0 = 40 points
        assert result.balance == 40.0

    def test_collect_rate_limited(self):
        from app.collectors.grass import GrassCollector

        rate_resp = MagicMock()
        rate_resp.status_code = 429
        rate_resp.headers = {"Retry-After": "1"}

        client = _make_async_client()
        client.get.return_value = rate_resp

        with patch("app.collectors.grass.httpx.AsyncClient", return_value=client):
            c = GrassCollector(access_token="test-token")
            result = asyncio.run(c.collect())
        assert result.error is not None
        assert "rate limit" in result.error.lower()

    def test_collect_active_devices_rate_limited(self):
        from app.collectors.grass import GrassCollector

        user_resp = _mock_response(200, {"result": {"data": {"totalPoints": 0}}})
        rate_resp = MagicMock()
        rate_resp.status_code = 429
        rate_resp.headers = {"Retry-After": "1"}

        client = _make_async_client()
        client.get.side_effect = [user_resp, rate_resp]

        with patch("app.collectors.grass.httpx.AsyncClient", return_value=client):
            c = GrassCollector(access_token="test-token")
            result = asyncio.run(c.collect())
        assert result.error is not None


# ---------------------------------------------------------------------------
# PacketStream — alternative parsing
# ---------------------------------------------------------------------------


class TestPacketStreamDeep:
    def test_collect_json_pattern(self):
        from app.collectors.packetstream import PacketStreamCollector

        html = 'window.userData = {"balance": 2.50}'
        resp = _mock_response(200, url="https://app.packetstream.io/dashboard")
        resp.text = html
        client = _make_async_client()
        client.get.return_value = resp

        with patch("app.collectors.packetstream.httpx.AsyncClient", return_value=client):
            c = PacketStreamCollector(auth_token="jwt")
            result = asyncio.run(c.collect())
        assert result.error is None
        assert result.balance == 2.50

    def test_collect_bare_json_pattern(self):
        from app.collectors.packetstream import PacketStreamCollector

        html = '{"something": true, "balance": 1.75, "more": false}'
        resp = _mock_response(200, url="https://app.packetstream.io/dashboard")
        resp.text = html
        client = _make_async_client()
        client.get.return_value = resp

        with patch("app.collectors.packetstream.httpx.AsyncClient", return_value=client):
            c = PacketStreamCollector(auth_token="jwt")
            result = asyncio.run(c.collect())
        assert result.error is None
        assert result.balance == 1.75

    def test_collect_unparseable_html(self):
        from app.collectors.packetstream import PacketStreamCollector

        html = "<html><body>No balance here</body></html>"
        resp = _mock_response(200, url="https://app.packetstream.io/dashboard")
        resp.text = html
        client = _make_async_client()
        client.get.return_value = resp

        with patch("app.collectors.packetstream.httpx.AsyncClient", return_value=client):
            c = PacketStreamCollector(auth_token="jwt")
            result = asyncio.run(c.collect())
        assert result.error is not None
        assert "parse" in result.error.lower()


# ---------------------------------------------------------------------------
# Storj — alternative response formats
# ---------------------------------------------------------------------------


class TestStorjDeep:
    def test_collect_estimated_payout_field(self):
        from app.collectors.storj import StorjCollector

        resp = _mock_response(200, {"estimatedPayout": 250})
        client = _make_async_client()
        client.get.return_value = resp

        with patch("app.collectors.storj.httpx.AsyncClient", return_value=client):
            c = StorjCollector()
            result = asyncio.run(c.collect())
        assert result.error is None
        assert result.balance == 2.50

    def test_collect_fallback_to_sno_on_404(self):
        from app.collectors.storj import StorjCollector

        not_found = MagicMock()
        not_found.status_code = 404
        sno_resp = _mock_response(200, {"currentMonthExpectations": 150})

        client = _make_async_client()
        client.get.side_effect = [not_found, sno_resp]

        with patch("app.collectors.storj.httpx.AsyncClient", return_value=client):
            c = StorjCollector()
            result = asyncio.run(c.collect())
        assert result.error is None
        assert result.balance == 1.50


# ---------------------------------------------------------------------------
# Bytelixir — API fallback path
# ---------------------------------------------------------------------------


class TestBytelixirDeep:
    def test_collect_api_fallback(self):
        from app.collectors.bytelixir import BytelixirCollector

        # HTML scrape fails (no balance pattern)
        html_resp = _mock_response(200, text="<p>no balance</p>", url="https://dash.bytelixir.com/en")
        html_resp.text = "<p>no balance</p>"
        # API fallback succeeds
        api_resp = _mock_response(200, {"data": {"balance": "0.5000000000"}})

        client = _make_async_client()
        client.get.side_effect = [html_resp, api_resp]

        with patch.object(BytelixirCollector, "_make_client", return_value=client):
            c = BytelixirCollector(session_cookie="valid")
            result = asyncio.run(c.collect())
        assert result.balance == 0.50

    def test_collect_api_401(self):
        from app.collectors.bytelixir import BytelixirCollector

        html_resp = _mock_response(200, text="<p>no balance</p>", url="https://dash.bytelixir.com/en")
        html_resp.text = "<p>no balance</p>"
        api_resp = _mock_response(401)
        api_resp.raise_for_status = MagicMock()  # 401 handled inline

        client = _make_async_client()
        client.get.side_effect = [html_resp, api_resp]

        with patch.object(BytelixirCollector, "_make_client", return_value=client):
            c = BytelixirCollector(session_cookie="expired")
            result = asyncio.run(c.collect())
        assert result.error is not None
        assert "expired" in result.error.lower()


# ---------------------------------------------------------------------------
# EarnApp — success with cookies mock
# ---------------------------------------------------------------------------


class TestEarnAppDeep:
    def test_collect_success(self):
        from app.collectors.earnapp import EarnAppCollector

        xsrf_resp = _mock_response(200)
        balance_resp = _mock_response(200, {"balance": 3.25})

        client = _make_async_client()
        client.cookies = MagicMock()
        client.cookies.items.return_value = [("xsrf-token", "xsrf-val")]
        client.get.side_effect = [xsrf_resp, balance_resp]

        with patch("app.collectors.earnapp.httpx.AsyncClient", return_value=client):
            c = EarnAppCollector(oauth_token="test-token")
            result = asyncio.run(c.collect())
        assert result.error is None
        assert result.balance == 3.25

    def test_collect_error_in_response(self):
        from app.collectors.earnapp import EarnAppCollector

        xsrf_resp = _mock_response(200)
        error_resp = _mock_response(200, {"error": "Session expired"})

        client = _make_async_client()
        client.cookies = MagicMock()
        client.cookies.items.return_value = []
        client.get.side_effect = [xsrf_resp, error_resp]

        with patch("app.collectors.earnapp.httpx.AsyncClient", return_value=client):
            c = EarnAppCollector(oauth_token="test-token")
            result = asyncio.run(c.collect())
        assert result.error == "Session expired"


# ---------------------------------------------------------------------------
# Bitping — success with cookies mock
# ---------------------------------------------------------------------------


class TestBitpingDeep:
    def test_collect_token_refresh(self):
        from app.collectors.bitping import BitpingCollector

        login_resp = _mock_response(200, {"token": "tok"})
        expired_resp = MagicMock()
        expired_resp.status_code = 401
        ok_resp = _mock_response(200, {"usdEarnings": 0.25})

        client = _make_async_client()
        client.cookies = MagicMock()
        client.cookies.items.return_value = [("token", "tok123")]
        client.post.return_value = login_resp
        client.get.side_effect = [expired_resp, ok_resp]

        with patch("app.collectors.bitping.httpx.AsyncClient", return_value=client):
            c = BitpingCollector(email="test@test.com", password="pass")
            result = asyncio.run(c.collect())
        assert result.error is None
        assert result.balance == 0.25
