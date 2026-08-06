"""Audit that the code matches the stated security posture (CashPilot-964).

docs/security-defaults.md states three tiers: things that are always on and not
configurable, things that are configurable but secure by default, and plain user
preference. A stated posture nobody checks is just prose, so these tests assert
the parts of it that are machine-checkable.

The governing principle: a user may choose to weaken their own installation, but
never by accident and never by default.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app import notify
from app.collectors import _COLLECTOR_ARGS
from app.database import _is_secret_key

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Collector arguments that are deliberately NOT encrypted, with the reason.
# Anything not listed here must match a secret suffix. Adding an entry is a
# conscious decision to store that field in plaintext.
PUBLIC_COLLECTOR_FIELDS = {
    "email": "an account identifier, shown back to the user in the UI",
    "api_url": "a URL the user pastes; it is not a credential",
    "fingerprints": "public relay identifiers, published by the network itself",
}


def _code_only(source: str) -> str:
    """Source with comments and docstrings removed, string literals kept.

    Keeping literals is the point: a telemetry endpoint lives in a string, and
    dropping strings would make this scan decorative.
    """
    import ast
    import io
    import tokenize

    # Docstrings first, by position, so only the prose ones go.
    try:
        tree = ast.parse(source)
    except SyntaxError:
        tree = None
    doc_spans: set[tuple[int, int]] = set()
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                body = getattr(node, "body", None)
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    doc_spans.add((body[0].lineno, body[0].col_offset))

    out: list[str] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                continue
            if tok.type == tokenize.STRING and tok.start in doc_spans:
                continue
            out.append(tok.string)
    except tokenize.TokenError:
        return source
    return "\n".join(out)


class TestCredentialEncryptionBoundary:
    """Tier 1: credential encryption at rest, with no plaintext mode."""

    def test_every_collector_credential_is_encrypted_or_explicitly_public(self):
        """The at-rest boundary is a naming convention - so enforce it.

        Without this, a new collector silently opts out of encryption just by
        naming its argument something that is not on the suffix list. That is
        how a field called "cookie" or "seed" ends up in plaintext.
        """
        unprotected = []
        for slug, args in _COLLECTOR_ARGS.items():
            for arg in args:
                name = arg.lstrip("?")
                if name in PUBLIC_COLLECTOR_FIELDS:
                    assert PUBLIC_COLLECTOR_FIELDS[name].strip(), (
                        f"{name} is exempted from encryption but gives no reason; "
                        "an empty reason must not permit plaintext storage"
                    )
                    continue
                if not _is_secret_key(f"{slug}_{name}"):
                    unprotected.append(f"{slug}_{name}")

        assert not unprotected, (
            "These collector fields would be stored in PLAINTEXT: "
            f"{sorted(unprotected)}. Either add a matching suffix to "
            "SECRET_CONFIG_KEYS in app/database.py, or add the field to "
            "PUBLIC_COLLECTOR_FIELDS here with the reason it is not a secret."
        )

    @pytest.mark.parametrize(
        "field",
        [
            "cookie",
            "seed",
            "mnemonic",
            "private_key",
            "passphrase",
            "jwt",
            "bearer",
            "credential",
            "api_key",
            "password",
            "keyfile",
            "refresh_token",
        ],
    )
    def test_obvious_secret_names_are_covered(self, field):
        """Guards the wallet work: a seed phrase must never land in plaintext."""
        assert _is_secret_key(f"someservice_{field}")


class TestSecureByDefault:
    """Tier 2: configurable, but the default must be the safe value."""

    def test_metrics_are_off_until_explicitly_enabled(self):
        """/metrics exposes balances and hostnames."""
        import importlib

        from app import metrics

        saved = os.environ.pop("CASHPILOT_METRICS_ENABLED", None)
        try:
            # The real fresh-install case: the variable is not set at all.
            assert not importlib.reload(metrics).METRICS_ENABLED, "must be off when unset"
            # And explicitly falsy values do not enable it either.
            for value in ("", "false", "0", "no"):
                os.environ["CASHPILOT_METRICS_ENABLED"] = value
                assert not importlib.reload(metrics).METRICS_ENABLED, f"enabled by {value!r}"
                os.environ.pop("CASHPILOT_METRICS_ENABLED", None)
            # Sanity: it CAN be turned on, so the test is not vacuous.
            os.environ["CASHPILOT_METRICS_ENABLED"] = "true"
            assert importlib.reload(metrics).METRICS_ENABLED
        finally:
            os.environ.pop("CASHPILOT_METRICS_ENABLED", None)
            if saved is not None:
                os.environ["CASHPILOT_METRICS_ENABLED"] = saved
            importlib.reload(metrics)

    def test_alerting_is_inert_until_configured(self):
        """No delivery target configured must mean nothing is sent anywhere."""
        # notify.py reads CASHPILOT_TELEGRAM_BOT_TOKEN + _CHAT_ID, not _TOKEN;
        # clearing the wrong name left the test unable to isolate the check.
        saved = {
            k: os.environ.pop(k, None)
            for k in (
                "CASHPILOT_NTFY_URL",
                "CASHPILOT_WEBHOOK_URL",
                "CASHPILOT_TELEGRAM_BOT_TOKEN",
                "CASHPILOT_TELEGRAM_CHAT_ID",
            )
        }
        try:
            assert notify.configured_targets() == []
            assert not notify.is_enabled()
        finally:
            for key, value in saved.items():
                if value is not None:
                    os.environ[key] = value

    def test_the_volume_allowlist_is_empty_by_default(self):
        """Opting a path past the block must be a deliberate act."""
        from app.worker_api import _parse_allowed_volume_roots

        assert _parse_allowed_volume_roots("") == frozenset()

    @pytest.mark.parametrize("compose", ["docker-compose.yml", "docker-compose.build.yml", "docker-compose.fleet.yml"])
    def test_the_dashboard_binds_to_loopback_by_default(self, compose):
        """It can command a Docker-socket worker, so it must not be public by default."""
        text = (PROJECT_ROOT / compose).read_text()
        assert "${CASHPILOT_BIND_ADDR:-127.0.0.1}" in text, (
            f"{compose} must default the dashboard to loopback, not 0.0.0.0"
        )


class TestNoTelemetry:
    """Tier 1: absent, not a toggle - a toggle implies it could exist."""

    def test_no_telemetry_or_phone_home_code_exists(self):
        """Scans CODE, not prose.

        The needle list is a substring match, so it used to fire on any COMMENT
        mentioning the word -- including a docstring stating that a module sends
        none, which is the opposite of the thing being forbidden. A check that
        cannot tell a denial from an admission is one that gets worked around by
        rewording, and then it is protecting nothing.

        Comments and docstrings are stripped; STRING LITERALS ARE NOT, so a
        telemetry endpoint URL or a `posthog` import is still caught. Proved by
        the control below rather than asserted.
        """
        needles = ("telemetry", "phone_home", "posthog", "mixpanel", "amplitude")
        offenders = []
        for path in (PROJECT_ROOT / "app").rglob("*.py"):
            lowered = _code_only(path.read_text()).lower()
            offenders += [f"{path.name}:{n}" for n in needles if n in lowered]
        assert not offenders, f"telemetry-shaped code found: {offenders}"

    def test_the_scan_still_catches_real_telemetry(self):
        """The control. Stripping prose must not have stripped the teeth.

        Each of these is a shape the scan exists to catch, and each must survive
        comment-and-docstring removal.
        """
        for source in (
            "import posthog\n",
            "TELEMETRY_URL = 'https://example.invalid/collect'\n",
            "def phone_home():\n    pass\n",
            "client.post('https://mixpanel.example/track')\n",
        ):
            lowered = _code_only(source).lower()
            assert any(n in lowered for n in ("telemetry", "phone_home", "posthog", "mixpanel", "amplitude")), (
                f"the scan no longer catches: {source!r}"
            )

    def test_the_scan_ignores_prose(self):
        """The false positive that prompted this: a module saying it sends no
        telemetry is not telemetry."""
        assert "telemetry" not in _code_only('"""This module sends no telemetry."""\n').lower()
        assert "telemetry" not in _code_only("# no telemetry here\nx = 1\n").lower()


class TestConfigCiphertext:
    """A collector secret written through the config layer must land encrypted."""

    def test_a_collector_password_is_stored_with_the_enc_prefix(self, tmp_path):
        import asyncio
        from unittest.mock import patch

        from app import database

        async def run():
            with (
                patch.object(database, "DB_DIR", tmp_path),
                patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"),
            ):
                await database.init_db()
                await database.set_config("honeygain_password", "PLACEHOLDER-not-a-real-secret")
                conn = await database._get_db()
                try:
                    cur = await conn.execute("SELECT value FROM config WHERE key = 'honeygain_password'")
                    return (await cur.fetchone())["value"]
                finally:
                    await conn.close()

        stored = asyncio.run(run())
        assert stored.startswith("enc:"), "a collector secret must not be stored in plaintext"
        assert "PLACEHOLDER-not-a-real-secret" not in stored
