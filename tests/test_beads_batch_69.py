"""CashPilot-4gxr: a security boundary that survived on nobody noticing it.

The shipped compose files give the UI and the worker SEPARATE `/data` volumes.
That is not incidental. The worker holds the Docker socket — root on the host —
and the UI's `/data` holds `cashpilot.db` and `.fernet_key`: the credential store
and the only key that can decrypt it. The component that can start any container
on the machine must not also be able to read every provider password.

Nothing said so, and nothing enforced it. Consolidating the two into one volume
is the obvious "simplification" when tidying a compose file, it looks harmless,
and it silently removes the boundary.

These tests are what makes that impossible to do quietly.

The `/fleet` volume IS shared, deliberately: it holds only the shared enrolment
key, which both sides need by definition. A test pins that too, so "share
nothing" is not over-applied later.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = ("docker-compose.yml", "docker-compose.fleet.yml")


def compose(name: str) -> dict:
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))


def mounts(name: str, service_substring: str) -> list[str]:
    """The volume lines of the first service whose key contains the substring."""
    doc = compose(name)
    for key, spec in doc["services"].items():
        if service_substring in key:
            return list(spec.get("volumes") or [])
    raise AssertionError(f"no service matching {service_substring!r} in {name}: {list(doc['services'])}")


def data_volume(name: str, service_substring: str) -> str:
    """The NAMED volume mounted at /data, which is the thing under test."""
    for line in mounts(name, service_substring):
        parts = str(line).split(":")
        if len(parts) >= 2 and parts[1] == "/data":
            return parts[0]
    raise AssertionError(f"{service_substring} in {name} mounts nothing at /data: {mounts(name, service_substring)}")


class TestTheWorkerCannotReadTheCredentialStore:
    """The boundary itself."""

    @pytest.mark.parametrize("name", COMPOSE_FILES)
    def test_the_ui_and_worker_use_different_data_volumes(self, name):
        ui = data_volume(name, "cashpilot-ui")
        worker = data_volume(name, "worker")
        assert ui != worker, (
            f"{name}: the worker shares the UI's /data ({ui}). The worker holds the Docker "
            "socket, which is root on the host; it must not be able to read cashpilot.db "
            "or .fernet_key."
        )

    @pytest.mark.parametrize("name", COMPOSE_FILES)
    def test_both_volumes_are_declared(self, name):
        """A mount naming a volume that is not declared makes Docker create an
        anonymous one — same name in the file, different data, no error."""
        declared = set(compose(name).get("volumes") or {})
        for service in ("cashpilot-ui", "worker"):
            assert data_volume(name, service) in declared, f"{name}: {service}'s /data volume is not declared"

    @pytest.mark.parametrize("name", COMPOSE_FILES)
    def test_the_worker_is_the_one_with_the_docker_socket(self, name):
        """The premise of the whole boundary, checked rather than assumed. If the
        UI ever gained the socket, this test is where that gets noticed."""
        worker_mounts = " ".join(str(m) for m in mounts(name, "worker"))
        ui_mounts = " ".join(str(m) for m in mounts(name, "cashpilot-ui"))
        assert "docker.sock" in worker_mounts, f"{name}: the worker no longer has the Docker socket"
        assert "docker.sock" not in ui_mounts, f"{name}: the UI has gained the Docker socket"


class TestTheSharedVolumeIsStillShared:
    """The mirror. "Separate everything" would break enrolment, and a rule
    applied without its reason gets over-applied."""

    @pytest.mark.parametrize("name", COMPOSE_FILES)
    def test_both_mount_the_same_fleet_volume(self, name):
        def fleet_volume(service: str) -> str | None:
            for line in mounts(name, service):
                parts = str(line).split(":")
                if len(parts) >= 2 and parts[1] == "/fleet":
                    return parts[0]
            return None

        ui, worker = fleet_volume("cashpilot-ui"), fleet_volume("worker")
        assert ui is not None and ui == worker, (
            f"{name}: /fleet must be SHARED — it holds the enrolment key both sides need"
        )


class TestTheReasonIsWrittenDown:
    """A boundary nobody can see is one the next person removes."""

    @pytest.mark.parametrize("name", COMPOSE_FILES)
    def test_the_compose_file_explains_it(self, name):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "SEPARATE FROM THE UI'S /data" in text, f"{name} does not say why"
        assert "docker socket" in text.lower()

    def test_the_docs_explain_it(self):
        """Someone reading the fleet docs, not the compose file, should also
        find out.

        Specific on purpose. The first version asserted that "separate" and
        "/data" both appeared somewhere in the page, and it PASSED before a word
        of this was written -- it was matching "Comma-separated" in an unrelated
        environment-variable table. Caught by noticing the test went green too
        early, which is the same class of near-miss as a negative control that
        passes.
        """
        text = (ROOT / "docs" / "fleet.md").read_text(encoding="utf-8")
        assert "## Why the UI and worker have separate data directories" in text
        assert "cashpilot_worker_data" in text
        assert "root on the host" in text
