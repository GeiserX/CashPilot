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
        ["cookie", "seed", "mnemonic", "private_key", "passphrase", "jwt", "bearer", "api_key", "password"],
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

        for value in ("", "false", "0", "no"):
            os.environ["CASHPILOT_METRICS_ENABLED"] = value
            try:
                assert not importlib.reload(metrics).METRICS_ENABLED, f"enabled by {value!r}"
            finally:
                os.environ.pop("CASHPILOT_METRICS_ENABLED", None)
        importlib.reload(metrics)

    def test_alerting_is_inert_until_configured(self):
        """No delivery target configured must mean nothing is sent anywhere."""
        saved = {
            k: os.environ.pop(k, None)
            for k in ("CASHPILOT_NTFY_URL", "CASHPILOT_WEBHOOK_URL", "CASHPILOT_TELEGRAM_TOKEN")
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
        needles = ("telemetry", "phone_home", "posthog", "mixpanel", "amplitude")
        offenders = []
        for path in (PROJECT_ROOT / "app").rglob("*.py"):
            lowered = path.read_text().lower()
            offenders += [f"{path.name}:{n}" for n in needles if n in lowered]
        assert not offenders, f"telemetry-shaped code found: {offenders}"
