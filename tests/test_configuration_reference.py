"""CashPilot-5fy: no table of config options, and the precedence is not uniform.

Three settings look identical from the outside — a secret supplied either by an
environment variable or by a file under ``/data`` — and resolve in **different
directions**:

* the credential-encryption key: the **file** wins, because switching keys would
  make every stored credential unreadable;
* the session-signing key: the **environment** wins, because sessions are cheap
  to invalidate.

Both are defensible individually. Together they are impossible to guess, and
nothing documented either — so "I set the env var and nothing changed" had no
answer anywhere in the project.

``docs/configuration.md`` is that answer. This test is what stops it rotting the
way the changelog did: **every ``CASHPILOT_*`` the code actually reads must
appear in the reference**, and the two documented precedence directions must
still match the code.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "docs" / "configuration.md"

#: How every env-var read in this codebase looks.
_READ = re.compile(r'(?:getenv|environ\.get|environ\[)\(?\s*["\'](CASHPILOT_[A-Z0-9_]+)["\']')


def _read_in_code() -> set[str]:
    names: set[str] = set()
    for path in (ROOT / "app").rglob("*.py"):
        names |= set(_READ.findall(path.read_text(encoding="utf-8")))
    return names


def _documented() -> set[str]:
    return set(re.findall(r"CASHPILOT_[A-Z0-9_]+", REFERENCE.read_text(encoding="utf-8")))


class TestTheReferenceCoversWhatTheCodeReads:
    def test_the_reference_exists(self):
        assert REFERENCE.is_file()

    def test_the_scan_finds_something(self):
        """An empty scan would make the sweep below vacuously green."""
        assert len(_read_in_code()) >= 20, "the env-var scan is not seeing the codebase"

    def test_every_variable_the_code_reads_is_documented(self):
        missing = sorted(_read_in_code() - _documented())
        assert not missing, (
            f"these are read by the code and absent from docs/configuration.md, so nobody can discover them: {missing}"
        )

    def test_it_does_not_document_variables_nothing_reads(self):
        """A reference that lists dead knobs sends people after nothing.

        The compose-level ones are exempt: they are read by the compose files,
        not by Python, and the reference says so in its own section.
        """
        compose_only = {"CASHPILOT_BIND_ADDR", "CASHPILOT_WORKER_BIND_ADDR"}
        ghosts = sorted(_documented() - _read_in_code() - compose_only)
        assert not ghosts, f"documented but read by nothing: {ghosts}"

    @pytest.mark.parametrize(
        "name", sorted(compose for compose in ("CASHPILOT_BIND_ADDR", "CASHPILOT_WORKER_BIND_ADDR"))
    )
    def test_the_compose_only_variables_really_are_used_by_compose(self, name):
        """Their exemption above is only honest if compose actually uses them."""
        text = "".join(
            (ROOT / f).read_text(encoding="utf-8") for f in ("docker-compose.yml", "docker-compose.fleet.yml")
        )
        assert name in text


class TestThePrecedenceMatchesTheCode:
    """The whole point of the page. If the code flips, this must fail."""

    def test_the_encryption_key_file_still_wins(self):
        source = (ROOT / "app" / "database.py").read_text(encoding="utf-8")
        assert "An existing key file always wins" in source, (
            "the credential-encryption precedence changed; docs/configuration.md says the FILE wins"
        )

    def test_the_session_key_env_still_wins(self):
        """auth.py resolves the env var before the persisted file."""
        source = (ROOT / "app" / "auth.py").read_text(encoding="utf-8")
        body = source[source.index("def _resolve_secret_key") :][:900]
        env_at = body.index("CASHPILOT_SECRET_KEY")
        file_at = body.index(".secret_key")
        assert env_at < file_at, (
            "the session key no longer prefers the environment; docs/configuration.md says ENV wins"
        )

    def test_the_reference_states_both_directions(self):
        text = REFERENCE.read_text(encoding="utf-8")
        assert "File wins" in text and "Env wins" in text
        assert "not uniform" in text, "the page does not warn that the directions differ"


class TestTheAdvertiseOnlyPortIsCalledOut:
    """The documented behaviour and the real behaviour disagreed for a long time."""

    def test_the_reference_says_it_does_not_change_the_listen_port(self):
        text = REFERENCE.read_text(encoding="utf-8")
        assert "does not change the port the worker listens on" in text

    def test_the_listen_port_really_is_fixed_in_the_image(self):
        dockerfile = (ROOT / "Dockerfile.worker").read_text(encoding="utf-8")
        assert '"--port", "8081"' in dockerfile, "the worker's port is no longer hardcoded; the warning may be stale"

    def test_the_variable_really_is_only_advertised(self):
        source = (ROOT / "app" / "worker_api.py").read_text(encoding="utf-8")
        uses = [ln for ln in source.splitlines() if "WORKER_PORT" in ln and "getenv" not in ln]
        assert uses, "WORKER_PORT is no longer used at all"
        assert all("url" in ln.lower() or 'f"http' in ln for ln in uses), (
            f"WORKER_PORT is now used for something other than the advertised URL: {uses}"
        )
