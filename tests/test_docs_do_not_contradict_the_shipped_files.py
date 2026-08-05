"""CashPilot-4le: the first page a new user reads contradicted the security page.

``docs/getting-started.md`` hand-copied a compose file that

* published the worker's Docker-socket API as ``"8081:8081"`` — on every
  interface — while ``docs/security-defaults.md`` says, in as many words,
  *"The worker API is equivalent to root on that machine. Never publish port
  8081."*
* pinned ``:latest`` for both images, which ``docker-compose.yml``'s own header
  identifies as the cause of issue #188.

Meanwhile the **shipped** ``docker-compose.yml`` binds ``127.0.0.1`` by default,
uses ``expose:`` for the worker so it is never published, and pins a release
series.

A copy drifts. The fix is not to correct the copy — it is to stop having one:
the page now includes the real file through ``pymdownx.snippets``, so the
quickstart and the shipped compose cannot disagree again.

Two smaller drifts fixed alongside:

* ``security-defaults.md`` advertised a "Known gap" about ``:latest`` that had
  been closed. A doc that overstates the project's insecurity costs trust the
  same way an understatement does.
* ``CASHPILOT_PORT`` was described in **three** places as the port the worker
  *listens on*. It is not — the listen port is fixed by the image's ``CMD`` and
  the variable only changes what the worker *advertises*.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GETTING_STARTED = ROOT / "docs" / "getting-started.md"
SECURITY = ROOT / "docs" / "security-defaults.md"


class TestTheQuickstartShowsTheRealComposeFile:
    def test_it_includes_rather_than_copies(self):
        assert '--8<-- "docker-compose.yml"' in GETTING_STARTED.read_text(encoding="utf-8"), (
            "the quickstart has gone back to hand-copying compose, which is how it drifted"
        )

    def test_the_include_is_enabled_in_mkdocs(self):
        """Without the extension the marker renders literally as text."""
        text = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
        assert "pymdownx.snippets" in text
        assert "check_paths: true" in text, "a missing include would fail silently rather than failing the build"

    def test_the_page_no_longer_publishes_the_worker_port(self):
        assert '"8081:8081"' not in GETTING_STARTED.read_text(encoding="utf-8")

    def test_the_page_no_longer_pins_latest(self):
        text = GETTING_STARTED.read_text(encoding="utf-8")
        assert not re.search(r"image:\s*drumsergio/\S+:latest", text)


class TestTheShippedComposeIsActuallySafe:
    """The include is only an improvement if what it includes is right."""

    def _compose(self):
        return (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    def test_the_ui_binds_loopback_by_default(self):
        assert "${CASHPILOT_BIND_ADDR:-127.0.0.1}:8080:8080" in self._compose()

    def test_the_worker_port_is_never_published(self):
        """`expose:` makes it reachable inside the Docker network only."""
        compose = self._compose()
        assert "expose:" in compose
        assert '"8081:8081"' not in compose

    def test_the_images_are_pinned(self):
        assert not re.search(r"image:\s*drumsergio/\S+:latest", self._compose())


class TestTheSecurityPageDescribesReality:
    def test_it_still_forbids_publishing_the_worker_port(self):
        """The rule the quickstart was breaking. If this goes, so does the point."""
        assert "Never publish port 8081" in SECURITY.read_text(encoding="utf-8")

    def test_it_no_longer_advertises_a_gap_that_is_closed(self):
        text = SECURITY.read_text(encoding="utf-8")
        assert "Known gap" not in text, "a doc that overstates the project's insecurity costs trust too"

    def test_and_the_gap_really_is_closed(self):
        """Do not just delete the sentence — prove the claim it made is false."""
        for name in ("docker-compose.yml", "docker-compose.fleet.yml"):
            assert not re.search(r"image:\s*drumsergio/\S+:latest", (ROOT / name).read_text(encoding="utf-8"))


class TestTheAdvertiseOnlyPortIsDescribedCorrectlyEverywhere:
    DOCS = ["README.md", "docs/getting-started.md", "docs/fleet.md"]

    @pytest.mark.parametrize("name", DOCS)
    def test_it_is_not_called_the_listen_port(self, name):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "Mini-UI/API port the worker listens on" not in text, (
            f"{name} still says CASHPILOT_PORT is the listen port; it only changes what is advertised"
        )

    @pytest.mark.parametrize("name", DOCS)
    def test_it_says_what_the_variable_really_does(self, name):
        text = (ROOT / name).read_text(encoding="utf-8")
        if "CASHPILOT_PORT" not in text:
            pytest.skip(f"{name} does not mention CASHPILOT_PORT")
        assert "advertises" in text

    def test_the_listen_port_really_is_fixed_by_the_image(self):
        """The correction is only right while this stays true."""
        assert '"--port", "8081"' in (ROOT / "Dockerfile.worker").read_text(encoding="utf-8")
