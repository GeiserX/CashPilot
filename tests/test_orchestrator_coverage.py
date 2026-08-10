"""Tests targeting uncovered lines in app/orchestrator.py.

Covers get_status / get_status_light (running / exited / missing-container /
docker-unavailable branches and the image-matched external-container path),
_collect_stats CPU/memory parsing (including zero-delta and error edge
cases), and _find_container's label-based fallback lookup.

Mocks the Docker SDK entirely — no real Docker socket is used.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402

docker = pytest.importorskip("docker")  # noqa: E402

from docker.errors import APIError, NotFound  # noqa: E402

from app import orchestrator  # noqa: E402
from app.constants import LABEL_MANAGED, LABEL_SERVICE  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_container(*, name, status, slug, deployed_by="worker", category="bandwidth", container_id="short123"):
    c = MagicMock()
    c.id = f"id-{name}"
    c.name = name
    c.status = status
    c.short_id = container_id
    c.labels = {
        LABEL_SERVICE: slug,
        LABEL_MANAGED: "true",
        "cashpilot.deployed-by": deployed_by,
        "cashpilot.category": category,
    }
    c.image.tags = [f"{slug}:latest"]
    c.image.short_id = "sha256:abcdef"
    c.attrs = {"Created": "2026-01-01T00:00:00Z"}
    return c


def _zero_stats():
    return {
        "cpu_stats": {"cpu_usage": {"total_usage": 1, "percpu_usage": [1]}, "system_cpu_usage": 10},
        "precpu_stats": {"cpu_usage": {"total_usage": 0}, "system_cpu_usage": 5},
        "memory_stats": {"usage": 0},
    }


# ---------------------------------------------------------------------------
# _collect_stats
# ---------------------------------------------------------------------------


class TestCollectStats:
    def test_parses_cpu_and_memory(self):
        c = MagicMock()
        c.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 2_000_000_000, "percpu_usage": [1, 1]},
                "system_cpu_usage": 100_000_000_000,
                "online_cpus": 2,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 1_000_000_000},
                "system_cpu_usage": 90_000_000_000,
            },
            "memory_stats": {"usage": 209_715_200},  # 200 MB
        }
        cpu_pct, mem_mb, _, _ = orchestrator._collect_stats(c)
        assert cpu_pct == 20.0
        assert mem_mb == 200.0

    def test_zero_system_delta_returns_zero_cpu(self):
        c = MagicMock()
        c.stats.return_value = {
            "cpu_stats": {"cpu_usage": {"total_usage": 500, "percpu_usage": [1]}, "system_cpu_usage": 500},
            "precpu_stats": {"cpu_usage": {"total_usage": 500}, "system_cpu_usage": 500},
            "memory_stats": {"usage": 0},
        }
        cpu_pct, mem_mb, _, _ = orchestrator._collect_stats(c)
        assert cpu_pct == 0.0
        assert mem_mb == 0.0

    def test_missing_memory_usage_defaults_to_zero(self):
        c = MagicMock()
        c.stats.return_value = {
            "cpu_stats": {"cpu_usage": {"total_usage": 100, "percpu_usage": [1]}, "system_cpu_usage": 500},
            "precpu_stats": {"cpu_usage": {"total_usage": 50}, "system_cpu_usage": 400},
            "memory_stats": {},  # no "usage" key
        }
        _, mem_mb, _, _ = orchestrator._collect_stats(c)
        assert mem_mb == 0.0

    def test_missing_key_reports_unknown(self):
        """A malformed stats payload measured nothing (CashPilot-zdi).

        This asserted (0.0, 0.0, None, None). The network counters were already
        None because a failed read is not evidence of no traffic — and exactly
        the same argument applies to CPU and memory, which were reporting a
        confident 0.00% for a container nobody could measure.
        """
        c = MagicMock()
        c.stats.return_value = {"cpu_stats": {}}  # precpu_stats missing -> KeyError
        assert orchestrator._collect_stats(c) == (None, None, None, None)

    def test_stats_api_error_reports_unknown(self):
        c = MagicMock()
        c.stats.side_effect = APIError("stats unavailable")
        assert orchestrator._collect_stats(c) == (None, None, None, None)


# ---------------------------------------------------------------------------
# _find_container
# ---------------------------------------------------------------------------


class TestFindContainer:
    def test_finds_by_name(self):
        container = MagicMock()
        container.labels = {LABEL_MANAGED: "true", LABEL_SERVICE: "honeygain"}
        client = MagicMock()
        client.containers.get.return_value = container
        with patch.object(orchestrator, "_get_client", return_value=client):
            result = orchestrator._find_container("honeygain")
        assert result is container
        client.containers.get.assert_called_once_with("cashpilot-honeygain")
        client.containers.list.assert_not_called()

    def test_a_name_hit_without_the_managed_label_is_not_ours(self):
        """CashPilot-o4uw: the platform's own containers are cashpilot-worker
        and cashpilot-ui, so slug 'worker' name-matched the worker's OWN
        container and command channel 'remove' force-removed it -- the worker
        deleting itself, unrecoverable remotely. An unlabelled name hit must
        be invisible, exactly like NotFound."""
        own_container = MagicMock()
        own_container.labels = {}  # compose-created, carries no cashpilot labels
        client = MagicMock()
        client.containers.get.return_value = own_container
        client.containers.list.return_value = []
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            pytest.raises(ValueError, match="worker"),
        ):
            orchestrator._find_container("worker")
        own_container.remove.assert_not_called()
        own_container.stop.assert_not_called()

    def test_an_unlabelled_name_hit_still_allows_the_label_fallback(self):
        """Control: the guard must reroute to the label lookup, not dead-end.
        A managed container that lost its name to an impostor is still found."""
        impostor = MagicMock()
        impostor.labels = {}
        real = MagicMock()
        client = MagicMock()
        client.containers.get.return_value = impostor
        client.containers.list.return_value = [real]
        with patch.object(orchestrator, "_get_client", return_value=client):
            assert orchestrator._find_container("honeygain") is real

    def test_none_labels_do_not_crash_the_guard(self):
        """Docker can hand back labels=None; absent is not 'managed'."""
        container = MagicMock()
        container.labels = None
        client = MagicMock()
        client.containers.get.return_value = container
        client.containers.list.return_value = []
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            pytest.raises(ValueError, match="ui"),
        ):
            orchestrator._find_container("ui")

    def test_falls_back_to_label_lookup_when_renamed(self):
        container = MagicMock()
        client = MagicMock()
        client.containers.get.side_effect = NotFound("nope")
        client.containers.list.return_value = [container]
        with patch.object(orchestrator, "_get_client", return_value=client):
            result = orchestrator._find_container("honeygain")
        assert result is container
        _, kwargs = client.containers.list.call_args
        assert kwargs["filters"]["label"] == [
            f"{LABEL_SERVICE}=honeygain",
            f"{LABEL_MANAGED}=true",
        ]

    def test_raises_value_error_when_not_found_anywhere(self):
        client = MagicMock()
        client.containers.get.side_effect = NotFound("nope")
        client.containers.list.return_value = []
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            pytest.raises(ValueError, match="honeygain"),
        ):
            orchestrator._find_container("honeygain")


# ---------------------------------------------------------------------------
# get_status (slow path, includes CPU/mem stats)
# ---------------------------------------------------------------------------


class TestGetStatus:
    def test_docker_unavailable_returns_empty(self):
        with patch.object(orchestrator, "_get_client", side_effect=RuntimeError("no socket")):
            assert orchestrator.get_status() == []

    def test_running_container_reports_stats(self):
        container = _mock_container(name="cashpilot-honeygain", status="running", slug="honeygain")
        container.stats.return_value = {
            "cpu_stats": {"cpu_usage": {"total_usage": 100, "percpu_usage": [1]}, "system_cpu_usage": 500},
            "precpu_stats": {"cpu_usage": {"total_usage": 50}, "system_cpu_usage": 400},
            "memory_stats": {"usage": 1_048_576},
        }
        client = MagicMock()
        client.containers.list.return_value = [container]
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "_build_image_slug_map", return_value={}),
        ):
            results = orchestrator.get_status()
        assert len(results) == 1
        row = results[0]
        assert row["slug"] == "honeygain"
        assert row["status"] == "running"
        assert row["memory_mb"] == 1.0

    def test_exited_container_missing_stats_handled_gracefully(self):
        container = _mock_container(name="cashpilot-earnapp", status="exited", slug="earnapp")
        container.stats.side_effect = APIError("exited, no stats")
        client = MagicMock()
        client.containers.list.return_value = [container]
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "_build_image_slug_map", return_value={}),
        ):
            results = orchestrator.get_status()
        assert results[0]["status"] == "exited"
        # Unknown, not zero: the stats call failed, so nothing was measured.
        # The status above is what says the container is not running.
        assert results[0]["cpu_percent"] is None
        assert results[0]["memory_mb"] is None

    def test_corrupted_container_is_skipped_not_crashed(self):
        good = _mock_container(name="cashpilot-honeygain", status="running", slug="honeygain")
        good.stats.return_value = _zero_stats()
        bad = MagicMock()
        bad.id = "bad-id"
        bad.short_id = "bad12"
        bad.labels.get.side_effect = RuntimeError("corrupted container labels")
        client = MagicMock()
        client.containers.list.return_value = [bad, good]
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "_build_image_slug_map", return_value={}),
        ):
            results = orchestrator.get_status()
        assert len(results) == 1
        assert results[0]["slug"] == "honeygain"

    def test_image_matched_external_container_included(self):
        external = MagicMock()
        external.id = "ext-1"
        external.name = "manually-run-storj"
        external.status = "running"
        external.image.tags = ["storjlabs/storagenode:latest"]
        external.short_id = "ext1"
        external.attrs = {"Created": "2026-01-01T00:00:00Z"}
        external.stats.return_value = _zero_stats()
        client = MagicMock()
        client.containers.list.side_effect = [[], [external]]
        image_map = {"storjlabs/storagenode:latest": "storj"}
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "_build_image_slug_map", return_value=image_map),
        ):
            results = orchestrator.get_status()
        assert len(results) == 1
        assert results[0]["slug"] == "storj"
        assert results[0]["deployed_by"] == "external"

    def test_all_containers_listing_failure_still_returns_labeled(self):
        labeled = _mock_container(name="cashpilot-honeygain", status="running", slug="honeygain")
        labeled.stats.return_value = _zero_stats()
        client = MagicMock()
        client.containers.list.side_effect = [[labeled], Exception("docker daemon hiccup")]
        image_map = {"some/image:latest": "svc"}
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "_build_image_slug_map", return_value=image_map),
        ):
            results = orchestrator.get_status()
        assert len(results) == 1
        assert results[0]["slug"] == "honeygain"


# ---------------------------------------------------------------------------
# get_status_light (fast path, no CPU/mem stats)
# ---------------------------------------------------------------------------


class TestGetStatusLight:
    def test_docker_unavailable_returns_empty(self):
        with patch.object(orchestrator, "_get_client", side_effect=RuntimeError("no socket")):
            assert orchestrator.get_status_light() == []

    def test_no_stats_call_even_when_running(self):
        container = _mock_container(name="cashpilot-honeygain", status="running", slug="honeygain")
        client = MagicMock()
        client.containers.list.return_value = [container]
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "_build_image_slug_map", return_value={}),
        ):
            results = orchestrator.get_status_light()
        assert results[0]["cpu_percent"] == 0.0
        assert results[0]["memory_mb"] == 0.0
        container.stats.assert_not_called()

    def test_a_second_container_of_the_same_service_is_still_reported(self):
        """It is a DIFFERENT container, and get_status reports it (CashPilot-dw1).

        This used to assert the opposite. get_status_light deduped image-matched
        externals by slug while get_status did not, and get_status_cached serves
        whichever of the two is current -- so a host running a managed honeygain
        alongside a hand-started one reported two containers or one depending
        purely on how warm the cache was.

        Reporting both is the correct side of that disagreement. The IDs differ,
        so these are genuinely separate containers; `seen_ids` already prevents
        counting one twice. Collapsing them hid a running container from the
        person responsible for it -- and a second instance of the same service on
        one host is exactly the situation a user needs to see, since most
        providers pay per IP.
        """
        labeled = _mock_container(name="cashpilot-honeygain", status="running", slug="honeygain")
        dup = MagicMock()
        dup.id = "dup-id"
        dup.image.tags = ["honeygain/desktop:latest"]
        client = MagicMock()
        client.containers.list.side_effect = [[labeled], [dup]]
        image_map = {"honeygain/desktop:latest": "honeygain"}
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "_build_image_slug_map", return_value=image_map),
        ):
            results = orchestrator.get_status_light()
        assert len(results) == 2
        assert {r["slug"] for r in results} == {"honeygain"}
        # "worker" is what the labeled scan emits — read from the code, not assumed.
        assert {r["deployed_by"] for r in results} == {"worker", "external"}

    def test_the_same_container_is_never_reported_twice(self):
        """ID-based dedupe stays: the two scans can surface one container."""
        labeled = _mock_container(name="cashpilot-honeygain", status="running", slug="honeygain")
        labeled.image.tags = ["honeygain/desktop:latest"]
        client = MagicMock()
        client.containers.list.side_effect = [[labeled], [labeled]]
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "_build_image_slug_map", return_value={"honeygain/desktop:latest": "honeygain"}),
        ):
            results = orchestrator.get_status_light()
        assert len(results) == 1

    def test_all_containers_listing_failure_handled(self):
        labeled = _mock_container(name="cashpilot-honeygain", status="running", slug="honeygain")
        client = MagicMock()
        client.containers.list.side_effect = [[labeled], Exception("boom")]
        image_map = {"x": "y"}
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "_build_image_slug_map", return_value=image_map),
        ):
            results = orchestrator.get_status_light()
        assert len(results) == 1


class TestAdvertisedAddressExtraction:
    """The worker reads ONE declared env var into the heartbeat — never more.

    Container env holds credentials (wallets, API keys), so the security
    property under test is as important as the feature: only the variable the
    catalog declares may ever leave the container inspect.
    """

    def _container(self, env):
        c = MagicMock()
        c.id = "cid123"
        c.client.api.inspect_container.return_value = {"Config": {"Env": env}}
        return c

    def test_the_declared_var_is_extracted(self):
        with patch.object(orchestrator, "get_service", return_value={"docker": {"advertised_address_env": "ADDRESS"}}):
            value = orchestrator._advertised_address(
                self._container(["WALLET=0xdeadbeef", "ADDRESS=storj.example.org:28967"]), "storj"
            )
        assert value == "storj.example.org:28967"

    def test_an_undeclared_service_never_even_inspects(self):
        c = self._container(["ADDRESS=whatever:1"])
        with patch.object(orchestrator, "get_service", return_value={"docker": {}}):
            assert orchestrator._advertised_address(c, "honeygain") is None
        c.client.api.inspect_container.assert_not_called()

    def test_an_unset_declared_var_is_none_not_empty(self):
        with patch.object(orchestrator, "get_service", return_value={"docker": {"advertised_address_env": "ADDRESS"}}):
            assert orchestrator._advertised_address(self._container(["WALLET=0xdeadbeef"]), "storj") is None

    def test_an_inspect_failure_is_none_not_a_crash(self):
        c = self._container([])
        c.client.api.inspect_container.side_effect = RuntimeError("daemon hiccup")
        with patch.object(orchestrator, "get_service", return_value={"docker": {"advertised_address_env": "ADDRESS"}}):
            assert orchestrator._advertised_address(c, "storj") is None

    def test_an_unknown_service_is_none(self):
        with patch.object(orchestrator, "get_service", return_value=None):
            assert orchestrator._advertised_address(self._container(["ADDRESS=x:1"]), "ghost") is None


class TestStatusCarriesAdvertisedAddress:
    """get_status_light forwards the field — and omits it when undeclared."""

    def _labeled(self, slug, env):
        c = MagicMock()
        c.id = f"id-{slug}"
        c.short_id = f"id-{slug}"[:10]
        c.name = f"cashpilot-{slug}"
        c.status = "running"
        c.labels = {"cashpilot.managed": "true", "cashpilot.service": slug}
        c.image.tags = ["img:1"]
        c.attrs = {"Created": "2026-08-10"}
        c.client.api.inspect_container.return_value = {"Config": {"Env": env}}
        return c

    def _entries(self, container, service):
        client = MagicMock()
        client.containers.list.return_value = [container]
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "_build_image_slug_map", return_value={}),
            patch.object(orchestrator, "get_service", return_value=service),
        ):
            return orchestrator.get_status_light()

    def test_a_declaring_service_reports_its_address(self):
        entries = self._entries(
            self._labeled("storj", ["ADDRESS=node.example.org:28967", "WALLET=0xdeadbeef"]),
            {"docker": {"advertised_address_env": "ADDRESS"}},
        )
        assert entries[0]["advertised_address"] == "node.example.org:28967"
        # The security property: nothing else from the env may ride along.
        assert "0xdeadbeef" not in str(entries[0])

    def test_an_undeclared_service_has_no_key_at_all(self):
        # Absent, not None: the key's absence is "nothing to say".
        entries = self._entries(self._labeled("honeygain", ["EMAIL=a@b.c"]), {"docker": {}})
        assert "advertised_address" not in entries[0]


class TestAdvertisedAddressSecretBackstop:
    def test_a_secret_flagged_var_is_refused_even_when_declared(self):
        # Runtime backstop: a catalog edit pointing advertised_address_env at
        # a credential must not export it into every heartbeat.
        c = MagicMock()
        c.id = "cid"
        c.client.api.inspect_container.return_value = {"Config": {"Env": ["TOKEN=supersecret"]}}
        service = {
            "docker": {
                "advertised_address_env": "TOKEN",
                "env": [{"key": "TOKEN", "secret": True}],
            }
        }
        with patch.object(orchestrator, "get_service", return_value=service):
            assert orchestrator._advertised_address(c, "shady") is None
        c.client.api.inspect_container.assert_not_called()


class TestExternalContainersCarryAdvertisedAddress:
    def test_an_image_matched_external_node_is_not_a_blind_spot(self):
        # Running a storagenode BEFORE installing CashPilot is the common storj
        # adoption path; the address check must cover those containers too.
        c = MagicMock()
        c.id = "ext1"
        c.short_id = "ext1"
        c.name = "storagenode"
        c.status = "running"
        c.labels = {}
        c.image.tags = ["storjlabs/storagenode:latest"]
        c.attrs = {"Created": "2026-08-10"}
        c.client.api.inspect_container.return_value = {"Config": {"Env": ["ADDRESS=node.example.org:28967"]}}
        client = MagicMock()
        client.containers.list.side_effect = [[], [c]]  # no labeled, one external
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "_build_image_slug_map", return_value={"storjlabs/storagenode": "storj"}),
            patch.object(orchestrator, "get_service", return_value={"docker": {"advertised_address_env": "ADDRESS"}}),
        ):
            entries = orchestrator.get_status_light()
        assert entries and entries[0]["deployed_by"] == "external"
        assert entries[0]["advertised_address"] == "node.example.org:28967"
