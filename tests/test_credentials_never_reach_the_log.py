"""A live credential must never be written to the container log.

Several providers authenticate with a bare header value — Salad's auth cookie,
Grass's access token, ProxyRack's API key, EarnApp's OAuth token, PacketStream's
JWT. When httpx rejects one, the exception TEXT is the credential.

Two independent sites wrote it out in plaintext:

* ``app/main.py`` logged ``result.error`` raw, one line ABOVE the comment
  explaining that collector errors must be redacted because "an httpx exception
  embeds the offending header or URL — which for several providers is a live
  credential". The alert was sanitised; the log line above it was not.
* all sixteen collector modules did
  ``logger.error("X collection failed: %s", exc, exc_info=True)`` — the message
  leaking it once and the chained traceback repeating it.

So the string was carefully redacted for the notification bell while being
printed in full to ``docker logs cashpilot-ui`` and to whatever ships those logs
off the box. Anyone in the ``docker`` group could read it.

These tests use a distinctive fake credential and assert it appears nowhere in
captured log output, which is the only formulation that cannot be satisfied by
redacting in the wrong place.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COLLECTORS = sorted((ROOT / "app" / "collectors").glob("*.py"))

#: Shaped like the real thing: a JWT in an httpx "Illegal header value" error.
CREDENTIAL = "eyJhbGciOiJIUzI1NiJ9.THIS-IS-A-LIVE-USER-TOKEN.signature"
HTTPX_ERROR = f"Illegal header value b'Bearer {CREDENTIAL}'"


class TestTheRedactorItself:
    def test_it_removes_a_bare_header_credential(self):
        from app import notify

        assert CREDENTIAL not in notify.redact(HTTPX_ERROR)

    def test_it_leaves_an_ordinary_message_readable(self):
        """Over-redacting would make every error useless instead of unsafe."""
        from app import notify

        plain = "Connection refused by dashboard.honeygain.com"
        assert notify.redact(plain) == plain


class TestTheCollectionLoopRedactsBeforeLogging:
    """The order is the whole bug: redacting after the log line changes nothing."""

    def test_a_failed_collection_does_not_log_the_credential(self, caplog):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from app import main
        from app.collectors.base import EarningsResult

        failed = EarningsResult(platform="grass", balance=0.0, currency="GRASS", error=HTTPX_ERROR)

        async def run():
            with (
                patch.object(main, "_collect_bounded", AsyncMock(return_value=failed)),
                patch.object(main.database, "get_config", AsyncMock(return_value={})),
                patch.object(main.database, "list_alerts", AsyncMock(return_value=[])),
                patch.object(main.database, "record_alert", AsyncMock()),
                patch.object(main.database, "get_payouts", AsyncMock(return_value=[])),
                patch("app.collectors.make_collectors", return_value=[MagicMock(platform="grass")]),
                caplog.at_level(logging.DEBUG),
            ):
                await main._run_collection()

        asyncio.run(run())
        assert CREDENTIAL not in caplog.text, "the collection loop wrote a live credential to the log"

    def test_the_redaction_is_applied_above_the_log_call(self):
        """Asserted structurally too, since a passing runtime test can drift."""
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert 'logger.warning("Collection error for %s: %s", result.platform, result.error)' not in source


class TestEveryCollectorGoesThroughTheHelper:
    """Fixing main.py alone leaves the second, independent leak fully intact."""

    def test_no_collector_passes_exc_info(self):
        """Checked as CODE. The helper's own docstring quotes the old idiom."""
        offenders = []
        for path in COLLECTORS:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and any(k.arg == "exc_info" for k in node.keywords):
                    offenders.append(f"{path.name}:{node.lineno}")
        assert not offenders, f"traceback logging re-leaks the credential at {offenders}"

    def test_the_helper_exists_and_redacts(self, caplog):
        from app.collectors import base

        logger = logging.getLogger("test.collector")
        with caplog.at_level(logging.ERROR, logger="test.collector"):
            base.log_failure(logger, "Grass", RuntimeError(HTTPX_ERROR))
        assert CREDENTIAL not in caplog.text
        assert "Grass collection failed" in caplog.text, "the log must still say which service failed"

    def test_every_collector_uses_it(self):
        """One helper, so a new collector cannot reintroduce this by copying a neighbour."""
        using = [p.name for p in COLLECTORS if "base.log_failure(" in p.read_text(encoding="utf-8")]
        assert len(using) >= 15, f"only {len(using)} collectors route failures through the helper: {using}"

    @pytest.mark.parametrize("name", ["grass.py", "salad.py", "proxyrack.py", "earnapp.py", "packetstream.py"])
    def test_the_bare_header_providers_are_covered(self, name):
        """These five send the raw secret AS a header value, so they leak worst."""
        source = (ROOT / "app" / "collectors" / name).read_text(encoding="utf-8")
        assert "base.log_failure(" in source
