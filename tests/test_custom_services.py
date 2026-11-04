"""A user adds their own service from an image reference, with no YAML editing.

The need came up in discussion #441: a service CashPilot does not list yet
should still be deployable to a worker and visible on the dashboard. The
definition lives in the database, encrypted, and is turned into the same shape
the deploy path reads for a catalog entry, minus everything a catalog entry can
be granted: no ports, capabilities, devices, host network, privileged mode or
entrypoint. The worker refuses those for an unknown slug on its own side too,
which the last class here pins.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app import constants, custom_services, database, main, orchestrator, worker_api

SECRET = "s3cr3t-Value-9f1c2e"


# ---------------------------------------------------------------------------
# Validation (pure)
# ---------------------------------------------------------------------------


def _payload(**over):
    base = {"name": "My Node", "image": "example/node:1.2", "env": [], "command": "", "data_path": "", "mem_limit": ""}
    return {**base, **over}


class TestValidation:
    @pytest.mark.parametrize(
        "ref",
        [
            "honeygain/honeygain:0.8.1",
            "registry.example.com:5000/mirror/honeygain:0.8.1",
            "ghcr.io/proxybaseorg/peer-cli@sha256:" + "a" * 64,
            "traffmonetizer/cli_v2:arm64v8",
            "busybox",
        ],
    )
    def test_a_plain_image_reference_is_accepted(self, ref):
        definition, _ = custom_services.validate(_payload(image=ref))
        assert definition["image"] == ref

    @pytest.mark.parametrize(
        "ref",
        [
            "",
            "https://example.com/x",
            "Honeygain/Honeygain",
            "demo/demo --privileged",
            "demo:tag;rm -rf /",
            "-v/:/host",
            "a" * 300,
        ],
    )
    def test_anything_else_is_refused(self, ref):
        with pytest.raises(ValueError):
            custom_services.validate(_payload(image=ref))

    @pytest.mark.parametrize("ref", ["busybox", "x:latest", "ghcr.io/a/b:latest"])
    def test_an_unpinned_image_is_warned_about(self, ref):
        assert custom_services.validate(_payload(image=ref))[1] == [custom_services.UNPINNED_WARNING]

    @pytest.mark.parametrize("ref", ["x:1.2", "x@sha256:" + "b" * 64, "x:latest@sha256:" + "b" * 64, "reg:5000/x:2"])
    def test_a_pinned_image_is_not(self, ref):
        assert custom_services.validate(_payload(image=ref))[1] == []

    @pytest.mark.parametrize(
        "env",
        [
            [{"key": "1BAD", "value": "x"}],
            [{"key": "BAD-KEY", "value": "x"}],
            [{"key": "", "value": "x"}],
            [{"key": "A", "value": "x"}, {"key": "A", "value": "y"}],
            [{"key": "A", "value": "x\x00y"}],
            [{"key": "A", "value": "x" * 4097}],
            [{"key": f"K{i}", "value": ""} for i in range(51)],
            "A=1",
        ],
    )
    def test_bad_variables_are_refused(self, env):
        with pytest.raises(ValueError):
            custom_services.validate(_payload(env=env))

    @pytest.mark.parametrize("path", ["data", "/", "/a/../b", "/a/", "/a//b", "/a b", "/a:b", "/../etc"])
    def test_a_bad_data_path_is_refused(self, path):
        with pytest.raises(ValueError):
            custom_services.validate(_payload(data_path=path))

    @pytest.mark.parametrize("path", ["/data", "/var/lib/node", "/app/.config"])
    def test_a_plain_data_path_is_accepted(self, path):
        assert custom_services.validate(_payload(data_path=path))[0]["data_path"] == path

    @pytest.mark.parametrize("mem", ["16m", "31m", "17g", "512", "1t", "1.5g", "-1m"])
    def test_a_memory_limit_out_of_bounds_is_refused(self, mem):
        with pytest.raises(ValueError):
            custom_services.validate(_payload(mem_limit=mem))

    @pytest.mark.parametrize(("mem", "stored"), [("32m", "32m"), ("16g", "16g"), ("2G", "2g"), ("", "512m")])
    def test_a_memory_limit_in_bounds_is_kept(self, mem, stored):
        assert custom_services.validate(_payload(mem_limit=mem))[0]["mem_limit"] == stored

    @pytest.mark.parametrize("command", ["a\nb", "a\rb", "x" * 1025])
    def test_a_multi_line_or_long_command_is_refused(self, command):
        with pytest.raises(ValueError):
            custom_services.validate(_payload(command=command))

    def test_a_blank_secret_on_an_edit_keeps_the_stored_value(self):
        previous, _ = custom_services.validate(_payload(env=[{"key": "TOKEN", "value": SECRET, "secret": True}]))
        edited, _ = custom_services.validate(_payload(env=[{"key": "TOKEN", "value": "", "secret": True}]), previous)
        assert edited["env"] == [{"key": "TOKEN", "value": SECRET, "secret": True}]

    def test_clearing_the_secret_tick_on_a_blank_box_keeps_the_stored_value(self):
        """The box was blank because the value is never sent back, not because
        the user emptied it; unticking Secret to look at it must not wipe it."""
        previous, _ = custom_services.validate(_payload(env=[{"key": "TOKEN", "value": SECRET, "secret": True}]))
        edited, _ = custom_services.validate(_payload(env=[{"key": "TOKEN", "value": "", "secret": False}]), previous)
        assert edited["env"] == [{"key": "TOKEN", "value": SECRET, "secret": False}]

    def test_a_blank_plain_value_is_a_blank_value(self):
        previous, _ = custom_services.validate(_payload(env=[{"key": "MODE", "value": "fast"}]))
        edited, _ = custom_services.validate(_payload(env=[{"key": "MODE", "value": ""}]), previous)
        assert edited["env"][0]["value"] == ""


class TestSlugs:
    def test_a_slug_is_prefixed_and_lowercased(self):
        assert custom_services.make_slug("My Cool Node!", set()) == "custom-my-cool-node"

    def test_a_taken_slug_gets_a_version(self):
        taken = {"custom-node", "custom-node-v2"}
        assert custom_services.make_slug("node", taken) == "custom-node-v3"

    def test_a_trailing_number_loses_its_dash(self):
        assert custom_services.make_slug("Node 2", set()) == "custom-node2"

    def test_no_slug_shares_a_container_name_with_another_slugs_copy(self):
        """Copy N runs as cashpilot-<slug>-N. A slug ending in -<digits> would be
        another service's copy, and a deploy of one replaced the other."""
        taken: set[str] = set()
        for name in ("Foo", "Foo", "Foo 2", "Foo-3", "Foo", "foo 10", "Bar 1"):
            taken.add(custom_services.make_slug(name, taken))
        names = {
            orchestrator._container_name(slug, n): (slug, n)
            for slug in taken
            for n in range(1, constants.MAX_INSTANCES + 1)
        }
        assert len(names) == len(taken) * constants.MAX_INSTANCES

    def test_a_name_with_no_letters_still_gets_a_slug(self):
        assert custom_services.make_slug("!!!", set()) == "custom-service"

    def test_a_long_name_is_cut(self):
        slug = custom_services.make_slug("x" * 200, set())
        assert slug == "custom-" + "x" * 40


# The shape handed to the deploy path. These keys are what a catalog entry can
# be granted; a custom service must never carry any of them.
FORBIDDEN_DOCKER_KEYS = ("ports", "cap_add", "devices", "network_mode", "privileged", "entrypoint", "image_by_arch")


class TestTheServiceShape:
    @pytest.mark.parametrize("reveal", [True, False])
    @pytest.mark.parametrize(
        "payload",
        [
            _payload(),
            _payload(data_path="/data", command="run --fast", env=[{"key": "A", "value": "1", "secret": True}]),
        ],
    )
    def test_nothing_a_catalog_entry_can_be_granted(self, payload, reveal):
        definition, _ = custom_services.validate(payload)
        docker = custom_services.as_service("custom-x", definition, reveal=reveal)["docker"]
        assert not set(FORBIDDEN_DOCKER_KEYS) & set(docker)

    def test_the_data_path_is_a_named_volume(self):
        definition, _ = custom_services.validate(_payload(data_path="/data"))
        docker = custom_services.as_service("custom-x", definition, reveal=True)["docker"]
        assert docker["volumes"] == ["cashpilot-custom-x-data:/data"]

    def test_the_masked_form_carries_no_secret(self):
        definition, _ = custom_services.validate(_payload(env=[{"key": "TOKEN", "value": SECRET, "secret": True}]))
        svc = custom_services.as_service("custom-x", definition, reveal=False)
        assert SECRET not in json.dumps(svc)
        assert svc["docker"]["env"] == []
        assert svc["definition"]["env"] == [{"key": "TOKEN", "value": "", "secret": True, "is_set": True}]

    def test_the_revealed_form_carries_it_for_the_deploy(self):
        """The control for the test above: the value is in the definition to be hidden."""
        definition, _ = custom_services.validate(_payload(env=[{"key": "TOKEN", "value": SECRET, "secret": True}]))
        assert SECRET in json.dumps(custom_services.as_service("custom-x", definition, reveal=True))


# ---------------------------------------------------------------------------
# Storage and routes, against a real database
# ---------------------------------------------------------------------------


@pytest.fixture
def db(tmp_path):
    with (
        patch.object(database, "DB_DIR", tmp_path),
        patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"),
    ):
        yield tmp_path


def _run(fn):
    """Run ``fn()`` on one loop with a fresh schema, and close that loop's connection."""

    async def go():
        await database.init_db()
        try:
            return await fn()
        finally:
            await database.close_shared()

    return asyncio.run(go())


def _body(**over):
    return main.CustomServiceBody(**_payload(**over))


async def _create(**over):
    return await main.api_create_custom_service(MagicMock(), _body(**over), {})


class TestStorage:
    def test_a_secret_never_reaches_the_database_file_in_plaintext(self, db):
        async def go():
            await _create(env=[{"key": "TOKEN", "value": SECRET, "secret": True}])

        _run(go)
        blobs = b"".join(p.read_bytes() for p in db.iterdir() if p.name.startswith("cashpilot.db"))
        assert b"custom_services" in blobs, "the table is not in the file, so the check below proves nothing"
        assert SECRET.encode() not in blobs

    def test_a_plain_value_is_encrypted_too(self, db):
        async def go():
            await _create(env=[{"key": "MODE", "value": SECRET, "secret": False}])

        _run(go)
        blobs = b"".join(p.read_bytes() for p in db.iterdir() if p.name.startswith("cashpilot.db"))
        assert SECRET.encode() not in blobs

    def test_an_unreadable_row_is_skipped(self, db):
        async def go():
            await _create(name="good")
            conn = await database._get_db()
            await conn.execute(
                "INSERT INTO custom_services (slug, definition_encrypted) VALUES ('custom-bad', 'enc:x')"
            )
            await conn.commit()
            return await database.list_custom_services()

        assert [r["slug"] for r in _run(go)] == ["custom-good"]


def _reader():
    return patch.object(main, "_require_reader", lambda r: None)


def _as(role):
    """Sign the request in as ``role``, through the real guards."""
    return patch("app.auth.get_current_user", lambda r: {"u": role, "r": role})


class TestTheRoutes:
    def test_create_returns_the_slug_and_the_warnings(self, db):
        result = _run(lambda: _create(image="busybox"))
        assert result == {"slug": "custom-my-node", "warnings": [custom_services.UNPINNED_WARNING]}

    def test_two_with_one_name_get_two_slugs(self, db):
        async def go():
            return [(await _create())["slug"], (await _create())["slug"]]

        assert _run(go) == ["custom-my-node", "custom-my-node-v2"]

    def test_a_bad_definition_is_a_400(self, db):
        async def go():
            with pytest.raises(HTTPException) as err:
                await _create(image="not an image")
            return err.value.status_code

        assert _run(go) == 400

    def test_the_list_masks_secrets(self, db):
        async def go():
            await _create(env=[{"key": "TOKEN", "value": SECRET, "secret": True}, {"key": "MODE", "value": "fast"}])
            with _as("owner"):
                return await main.api_list_custom_services(MagicMock())

        listed = _run(go)
        assert SECRET not in json.dumps(listed)
        assert listed[0]["definition"]["env"] == [
            {"key": "TOKEN", "value": "", "secret": True, "is_set": True},
            {"key": "MODE", "value": "fast", "secret": False, "is_set": True},
        ]
        assert listed[0]["custom"] is True

    def test_the_detail_view_masks_secrets_and_limits_copies(self, db):
        async def go():
            slug = (await _create(data_path="/data", env=[{"key": "TOKEN", "value": SECRET, "secret": True}]))["slug"]
            with (
                patch.object(main, "_require_auth_api", lambda r: None),
                patch.object(main.database, "get_deployments", AsyncMock(return_value=[])),
                patch.object(main, "_get_all_worker_containers", AsyncMock(return_value=[])),
            ):
                return await main.api_get_service(MagicMock(), slug)

        svc = _run(go)
        assert SECRET not in json.dumps(svc)
        assert svc["custom"] is True
        assert svc["has_collector"] is False
        assert svc["max_instances"] == 1

    def test_an_unknown_custom_slug_is_a_404(self, db):
        async def go():
            with (
                patch.object(main, "_require_auth_api", lambda r: None),
                pytest.raises(HTTPException) as err,
            ):
                await main.api_get_service(MagicMock(), "custom-nothing")
            return err.value.status_code

        assert _run(go) == 404

    def test_an_edit_with_a_blank_secret_keeps_it(self, db):
        async def go():
            slug = (await _create(env=[{"key": "TOKEN", "value": SECRET, "secret": True}]))["slug"]
            with patch.object(main, "_custom_deployed_on", AsyncMock(return_value=[])):
                out = await main.api_update_custom_service(
                    MagicMock(),
                    slug,
                    _body(image="example/node:1.3", env=[{"key": "TOKEN", "value": "", "secret": True}]),
                    {},
                )
            return out, await database.get_custom_service(slug)

        out, stored = _run(go)
        assert out == {"warnings": [], "deployed": False}
        assert stored["image"] == "example/node:1.3"
        assert stored["env"][0]["value"] == SECRET

    def test_an_edit_of_a_catalog_slug_is_a_404(self, db):
        async def go():
            with pytest.raises(HTTPException) as err:
                await main.api_update_custom_service(MagicMock(), "honeygain", _body(), {})
            return err.value.status_code

        assert _run(go) == 404

    def test_delete_is_refused_while_a_box_runs_it_and_allowed_after(self, db):
        worker = {"id": 7, "name": "box-a", "status": "online", "containers": json.dumps([{"slug": "custom-my-node"}])}

        async def go():
            slug = (await _create())["slug"]
            with (
                patch.object(main.database, "list_workers", AsyncMock(return_value=[worker])),
                pytest.raises(HTTPException) as err,
            ):
                await main.api_delete_custom_service(MagicMock(), slug, {})
            with patch.object(main.database, "list_workers", AsyncMock(return_value=[{**worker, "containers": "[]"}])):
                done = await main.api_delete_custom_service(MagicMock(), slug, {})
            return err.value, done, await database.get_custom_service(slug)

        refused, done, stored = _run(go)
        assert refused.status_code == 409
        assert "box-a" in refused.detail
        assert done == {"status": "deleted"}
        assert stored is None

    def test_delete_is_refused_while_a_box_has_a_record_of_it(self, db):
        async def go():
            slug = (await _create())["slug"]
            await database.save_deployment(slug=slug, container_id="c1", spec={"image": "x"}, worker_id=3)
            with (
                patch.object(main.database, "list_workers", AsyncMock(return_value=[])),
                pytest.raises(HTTPException) as err,
            ):
                await main.api_delete_custom_service(MagicMock(), slug, {})
            return err.value.status_code

        assert _run(go) == 409

    def test_every_route_is_owner_only_for_writes(self):
        """Writes resolve the owner guard as a dependency, before the body is read."""
        import inspect

        for fn in (main.api_create_custom_service, main.api_update_custom_service, main.api_delete_custom_service):
            assert inspect.signature(fn).parameters["_auth"].default.dependency is main._require_owner


# ---------------------------------------------------------------------------
# The deploy
# ---------------------------------------------------------------------------


def _deploy(body_env=None, body_image=None, recorded=None, **definition):
    """Create a custom service, deploy it, and return (sent spec, recorded spec)."""
    captured: dict = {}

    async def capture(worker_id, slug, spec):
        captured.setdefault("specs", []).append(dict(spec))
        return {"container_id": "abc"}

    body = MagicMock()
    body.env = body_env or {}
    body.hostname = None
    body.image = body_image
    body.instances = None
    saved = AsyncMock()

    async def go():
        slug = (await _create(**definition))["slug"]
        with (
            patch.object(main, "_resolve_worker_id", AsyncMock(return_value=1)),
            patch.object(main, "_proxy_worker_deploy", capture),
            patch.object(main.database, "get_deployment_spec", AsyncMock(return_value=recorded)),
            patch.object(main.database, "save_deployment", saved),
            patch.object(main.database, "record_health_event", AsyncMock()),
            patch.object(main, "_spawn", lambda coro: coro.close()),
            patch.object(main.metrics, "record_container_lifecycle", lambda *a: None),
        ):
            return await main.api_deploy(MagicMock(), slug, body)

    response = _run(go)
    return captured["specs"][0], saved.call_args.kwargs["spec"], response


class TestTheDeploy:
    def test_the_spec_is_the_definition_with_the_catalog_hardening(self, db):
        sent, recorded, _ = _deploy(
            image="example/node:1.2",
            data_path="/data",
            command="run --token ${TOKEN}",
            mem_limit="1g",
            env=[{"key": "TOKEN", "value": SECRET, "secret": True}, {"key": "MODE", "value": "fast"}],
        )
        assert sent["image"] == "example/node:1.2"
        assert sent["env"] == {"TOKEN": SECRET, "MODE": "fast"}
        assert sent["command"] == f"run --token {SECRET}"
        assert sent["ports"] == {}
        assert sent["cap_add"] is None
        assert sent["devices"] is None
        assert sent["privileged"] is False
        assert sent["network_mode"] is None
        assert sent["volumes"] == {"cashpilot-custom-my-node-data": {"bind": "/data", "mode": "rw"}}
        assert sent["resources"] == {"mem_limit": "1g"}
        assert sent["labels"] == {constants.LABEL_CUSTOM: "true"}
        assert "custom_image" not in recorded

    def test_without_a_data_path_nothing_is_mounted(self, db):
        sent, _, _ = _deploy()
        assert sent["volumes"] == {}
        assert sent["resources"] == {"mem_limit": "512m"}

    def test_a_typed_image_is_refused(self, db):
        with pytest.raises(HTTPException) as err:
            _deploy(body_image="evil/image:1")
        assert err.value.status_code == 400

    def test_a_typed_variable_is_refused(self, db):
        with pytest.raises(HTTPException) as err:
            _deploy(body_env={"TOKEN": "other"})
        assert err.value.status_code == 400

    def test_blank_form_values_are_not_a_change(self, db):
        sent, _, _ = _deploy(body_env={"TOKEN": "  "}, body_image="", env=[{"key": "TOKEN", "value": "t"}])
        assert sent["env"] == {"TOKEN": "t"}

    def test_an_edited_definition_wins_over_the_record(self, db):
        """The record of the last deploy must not bring back an old value or mount."""
        old = {
            "image": "example/node:1.1",
            "env": {"TOKEN": "old"},
            "volumes": {"/somewhere": {"bind": "/data", "mode": "rw"}},
            "command": "old",
        }
        sent, _, response = _deploy(recorded=old, env=[{"key": "TOKEN", "value": "new"}])
        assert sent["env"] == {"TOKEN": "new"}
        assert sent["volumes"] == {}
        assert "command" not in sent
        assert "kept_from_previous_deployment" not in response

    def test_a_catalog_deploy_gets_no_custom_label(self):
        """The control: the label marks custom services only."""
        from tests.test_custom_image import _deploy as catalog_deploy

        sent, _ = catalog_deploy(None, None)
        assert "labels" not in sent


# ---------------------------------------------------------------------------
# The dashboard
# ---------------------------------------------------------------------------


def _deployed(definition_image, running_image):
    container = {
        "slug": "custom-my-node",
        "status": "running",
        "image": running_image,
        "category": "bandwidth",
        "_worker_id": 1,
        "_node": "box-a",
        "deployed_by": "worker",
    }

    async def go():
        await _create(image=definition_image)
        with (
            _reader(),
            patch.object(main, "_get_all_worker_containers", AsyncMock(return_value=[container])),
            patch.object(main.database, "get_earnings_summary", AsyncMock(return_value=[])),
            patch.object(main.database, "get_health_scores", AsyncMock(return_value=[])),
            patch.object(main.database, "get_config", AsyncMock(return_value={})),
            patch.object(main.database, "get_deployments", AsyncMock(return_value=[])),
        ):
            return await main.api_services_deployed(MagicMock())

    return _run(go)[0]


class TestTheDashboardRow:
    def test_a_custom_row_is_named_and_marked(self, db):
        row = _deployed("example/node:1.2", "example/node:1.2")
        assert row["name"] == "My Node"
        assert row["custom"] is True
        assert row["category"] == "custom"
        assert row["balance"] is None
        assert row["balance_known"] is False
        assert row["collector_needs_setup"] is False
        assert row["image_outdated"] is False

    def test_an_edited_tag_is_an_update(self, db):
        assert _deployed("example/node:1.3", "example/node:1.2")["image_outdated"] is True

    def test_docker_hub_spelling_is_not_an_update(self, db):
        assert _deployed("docker.io/library/busybox:1.36", "busybox:1.36")["image_outdated"] is False

    def test_no_tag_reads_as_latest(self, db):
        assert _deployed("busybox", "busybox:latest")["image_outdated"] is False


# ---------------------------------------------------------------------------
# The worker, on its own: a custom slug gets nothing the catalog grants
# ---------------------------------------------------------------------------


class TestTheWorkerBackstop:
    @pytest.mark.parametrize(
        "spec",
        [
            {"cap_add": ["NET_ADMIN"]},
            {"devices": ["/dev/net/tun"]},
            {"network_mode": "host"},
            {"network_mode": "container:abc"},
            {"privileged": True},
            {"volumes": {"/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"}}},
            {"volumes": {"/etc": {"bind": "/host-etc", "mode": "ro"}}},
        ],
    )
    def test_anything_a_catalog_entry_can_be_granted_is_refused(self, spec):
        # Workers run on Linux; on macOS /etc and /var are symlinks into
        # /private, which realpath would follow past the blocked roots.
        with (
            patch("app.worker_api.os.path.realpath", side_effect=lambda p: p),
            pytest.raises(HTTPException) as err,
        ):
            worker_api._validate_deploy_spec(worker_api.DeploySpec(image="x/y:1", **spec), "custom-x")
        assert err.value.status_code == 403

    def test_the_named_data_volume_is_accepted(self):
        """The control: what the UI actually sends passes."""
        spec = worker_api.DeploySpec(
            image="x/y:1",
            volumes={"cashpilot-custom-x-data": {"bind": "/data", "mode": "rw"}},
            labels={constants.LABEL_CUSTOM: "true"},
            resources={"mem_limit": "512m"},
        )
        worker_api._validate_deploy_spec(spec, "custom-x")

    def test_the_container_is_created_with_the_full_hardening(self):
        client = MagicMock()
        client.containers.get.side_effect = orchestrator.NotFound("nope")
        client.networks.get.return_value.attrs = {"Driver": "bridge"}
        client.images.get.return_value.attrs = {"Config": {"Entrypoint": ["/node"], "Cmd": None}}
        with (
            patch.object(orchestrator, "_CONTAINER_NETWORK", "cashpilot-iso"),
            patch.object(orchestrator, "_get_client", return_value=client),
        ):
            orchestrator.deploy_raw(
                slug="custom-x",
                image="x/y:1",
                labels={constants.LABEL_CUSTOM: "true"},
                resources={"mem_limit": "512m"},
                keep_targets=worker_api._catalog_volume_targets("custom-x"),
            )
        kwargs = client.containers.run.call_args.kwargs
        assert kwargs["cap_drop"] == ["ALL"]
        assert kwargs["cap_add"] is None
        assert kwargs["devices"] is None
        assert kwargs["security_opt"] == ["no-new-privileges:true"]
        assert kwargs["privileged"] is False
        assert kwargs["pids_limit"] == orchestrator._PIDS_LIMIT
        assert kwargs["network"] == "cashpilot-iso"
        assert kwargs["network_mode"] is None
        assert kwargs["entrypoint"] is None
        assert kwargs["mem_limit"] == "512m"
        assert kwargs["labels"][constants.LABEL_CUSTOM] == "true"
        assert kwargs["labels"][constants.LABEL_SERVICE] == "custom-x"

    def test_the_worker_keeps_no_mount_for_a_custom_slug(self):
        assert worker_api._catalog_volume_targets("custom-x") == set()


# ---------------------------------------------------------------------------
# Review fixes: names that collide, who reads a definition, outdated images
# ---------------------------------------------------------------------------


class TestNamesNeverCollide:
    def test_foo_twice_and_foo_2_get_three_distinct_container_families(self, db):
        async def go():
            return [(await _create(name=n))["slug"] for n in ("Foo", "Foo", "Foo 2")]

        slugs = _run(go)
        assert slugs == ["custom-foo", "custom-foo-v2", "custom-foo2"]
        copy_two = orchestrator._container_name("custom-foo", 2)
        assert copy_two not in {orchestrator._container_name(s) for s in slugs}

    def test_a_deleted_slug_is_never_given_out_again(self, db):
        """Its data volume may still sit on a box; a new image must not mount it."""

        async def go():
            first = (await _create(name="Node", data_path="/data"))["slug"]
            with patch.object(main, "_custom_deployed_on", AsyncMock(return_value=[])):
                await main.api_delete_custom_service(MagicMock(), first, {})
            second = (await _create(name="Node", image="other/image:2", data_path="/data"))["slug"]
            return first, second

        first, second = _run(go)
        assert first == "custom-node"
        assert second != first
        assert custom_services.volume_name(second) != custom_services.volume_name(first)

    def _replace(self, old_labels, slug, instance):
        client = MagicMock()
        old = MagicMock()
        old.labels = old_labels
        client.containers.get.return_value = old
        client.networks.get.return_value.attrs = {"Driver": "bridge"}
        client.images.get.return_value.attrs = {"Config": {"Entrypoint": ["/node"], "Cmd": None}}
        with patch.object(orchestrator, "_get_client", return_value=client):
            orchestrator.deploy_raw(slug=slug, image="x/y:1", instance=instance)
        return old, client

    def test_the_worker_refuses_to_replace_another_services_container(self):
        with pytest.raises(orchestrator.ContainerRuntimeError) as err:
            self._replace({constants.LABEL_SERVICE: "custom-foo-2"}, "custom-foo", 2)
        assert "custom-foo-2" in str(err.value)

    def test_the_worker_refuses_to_replace_another_copy_of_the_same_service(self):
        labels = {constants.LABEL_SERVICE: "foo", constants.LABEL_INSTANCE: "3"}
        with pytest.raises(orchestrator.ContainerRuntimeError):
            self._replace(labels, "foo", 2)

    @pytest.mark.parametrize(
        ("labels", "instance"),
        [
            ({constants.LABEL_SERVICE: "custom-foo"}, 1),
            ({constants.LABEL_SERVICE: "custom-foo", constants.LABEL_INSTANCE: "2"}, 2),
            ({}, 1),
        ],
    )
    def test_the_same_copy_is_still_replaced(self, labels, instance):
        """The control: a redeploy of the container itself goes through."""
        old, client = self._replace(labels, "custom-foo", instance)
        old.remove.assert_called_once()
        client.containers.run.assert_called_once()


class TestOnlyTheOwnerReadsValues:
    TOKEN_CMD = "run --token cmd-token-7a1"

    async def _seed(self):
        return (
            await _create(
                command=self.TOKEN_CMD,
                env=[{"key": "TOKEN", "value": SECRET, "secret": True}, {"key": "EMAIL", "value": "me@example.org"}],
            )
        )["slug"]

    @pytest.mark.parametrize("role", ["viewer", "writer"])
    def test_a_non_owner_sees_names_only_in_the_list(self, db, role):
        async def go():
            await self._seed()
            with _as(role):
                return await main.api_list_custom_services(MagicMock())

        dumped = json.dumps(_run(go))
        assert "me@example.org" not in dumped
        assert "cmd-token-7a1" not in dumped
        assert '"TOKEN"' in dumped and '"EMAIL"' in dumped

    def test_the_read_only_token_gets_nothing(self, db):
        async def go():
            await self._seed()
            with _as("reader"), pytest.raises(HTTPException) as err:
                await main.api_list_custom_services(MagicMock())
            return err.value.status_code

        assert _run(go) == 403

    @pytest.mark.parametrize("role", ["viewer", "writer"])
    def test_a_non_owner_sees_names_only_in_the_detail_view(self, db, role):
        async def go():
            slug = await self._seed()
            with (
                _as(role),
                patch.object(main.database, "get_deployments", AsyncMock(return_value=[])),
                patch.object(main, "_get_all_worker_containers", AsyncMock(return_value=[])),
            ):
                return await main.api_get_service(MagicMock(), slug)

        svc = _run(go)
        dumped = json.dumps(svc)
        assert "me@example.org" not in dumped
        assert "cmd-token-7a1" not in dumped
        assert svc["definition"]["command_set"] is True

    def test_the_owner_still_sees_them(self, db):
        """The control: the values are there to be hidden."""

        async def go():
            await self._seed()
            with _as("owner"):
                return await main.api_list_custom_services(MagicMock())

        dumped = json.dumps(_run(go))
        assert "me@example.org" in dumped
        assert "cmd-token-7a1" in dumped
        assert SECRET not in dumped


class TestOutdatedIsExact:
    @pytest.mark.parametrize(
        ("deployed", "wanted"),
        [
            ("busybox:1.36", "library/busybox:1.36"),
            ("busybox:1.36", "docker.io/library/busybox:1.36"),
            ("x/y@sha256:" + "a" * 64, "x/y@sha256:" + "a" * 64),
            ("busybox:latest", "busybox"),
        ],
    )
    def test_the_same_image_is_not_outdated(self, deployed, wanted):
        assert main._custom_image_outdated(deployed, wanted) is False

    @pytest.mark.parametrize(
        ("deployed", "wanted"),
        [
            ("x/y@sha256:" + "a" * 64, "x/y:2"),
            ("x/y:1", "x/y@sha256:" + "b" * 64),
            ("x/y@sha256:" + "a" * 64, "x/y@sha256:" + "b" * 64),
            ("x/y:1", "x/y:2"),
            ("x/y:1", "x/z:1"),
        ],
    )
    def test_any_edit_is_outdated(self, deployed, wanted):
        assert main._custom_image_outdated(deployed, wanted) is True

    def test_the_tag_the_container_was_created_from_wins(self):
        image = MagicMock()
        image.tags = ["busybox:latest", "busybox:1.36"]
        assert orchestrator._image_ref(image, "busybox:1.36") == "busybox:1.36"
        assert orchestrator._image_ref(image, "") == "busybox:latest"


class TestADataPathWithSeveralCopies:
    def _update_with(self, instances):
        async def go():
            slug = (await _create())["slug"]
            await database.save_deployment(
                slug=slug, container_id="c1", spec={"image": "x", "instances": instances}, worker_id=3
            )
            with patch.object(main, "_custom_deployed_on", AsyncMock(return_value=["box"])):
                return await main.api_update_custom_service(MagicMock(), slug, _body(data_path="/data"), {})

        return _run(go)

    def test_adding_a_data_path_while_a_box_runs_copies_is_refused(self, db):
        with pytest.raises(HTTPException) as err:
            self._update_with(3)
        assert err.value.status_code == 409
        assert "one copy" in err.value.detail

    def test_with_one_copy_it_is_saved(self, db):
        """The control."""
        assert self._update_with(1)["deployed"] is True


class TestAReplacedCustomContainerTakesItsAnonymousVolumes:
    """An image's VOLUME with no data path gets a fresh anonymous volume with each container."""

    def _client(self, old):
        client = MagicMock()
        client.containers.get.return_value = old
        client.networks.get.return_value.attrs = {"Driver": "bridge"}
        client.images.get.return_value.attrs = {"Config": {"Entrypoint": ["/node"], "Cmd": None}}
        return client

    def _redeploy(self, slug):
        old = MagicMock()
        old.labels = {constants.LABEL_SERVICE: slug}
        with patch.object(orchestrator, "_get_client", return_value=self._client(old)):
            orchestrator.deploy_raw(slug=slug, image="x/y:1")
        return old

    def test_a_custom_redeploy_removes_the_old_anonymous_volumes(self):
        self._redeploy("custom-foo").remove.assert_called_once_with(force=True, v=True)

    def test_a_catalog_redeploy_is_unchanged(self):
        """The control: a catalog service's volumes are never touched on a replace."""
        self._redeploy("honeygain").remove.assert_called_once_with(force=True)

    @pytest.mark.parametrize(("slug", "expected"), [("custom-foo", {"v": True}), ("demo", {})])
    def test_scaling_down_does_the_same(self, slug, expected):
        copy = MagicMock()
        copy.name = f"cashpilot-{slug}-2"
        copy.labels = {constants.LABEL_SERVICE: slug, constants.LABEL_INSTANCE: "2"}
        client = MagicMock()
        client.containers.get.return_value = copy
        client.containers.list.return_value = [copy]
        with patch.object(orchestrator, "_get_client", return_value=client):
            orchestrator.remove_instance(slug, 2)
            orchestrator.remove_extra_instances(slug)
        assert copy.remove.call_args_list == [((), {"force": True, **expected})] * 2


class TestADeleteNeverRacesADeploy:
    """A definition deleted while its deploy is in flight leaves a container nothing describes."""

    def _deploy_body(self):
        body = MagicMock()
        body.env = {}
        body.hostname = None
        body.image = None
        body.instances = None
        return body

    def _patches(self, proxy):
        return (
            patch.object(main, "_resolve_worker_id", AsyncMock(return_value=1)),
            patch.object(main, "_proxy_worker_deploy", proxy),
            patch.object(main.database, "get_deployment_spec", AsyncMock(return_value=None)),
            patch.object(main.database, "save_deployment", AsyncMock()),
            patch.object(main.database, "record_health_event", AsyncMock()),
            patch.object(main, "_spawn", lambda coro: coro.close()),
            patch.object(main.metrics, "record_container_lifecycle", lambda *a: None),
            patch.object(main, "_custom_deployed_on", AsyncMock(return_value=[])),
        )

    def test_a_delete_during_a_deploy_is_refused_and_allowed_after(self, db):
        pulling, release = asyncio.Event(), asyncio.Event()

        async def proxy(worker_id, slug, spec):
            pulling.set()
            await release.wait()
            return {"container_id": "abc"}

        async def go():
            slug = (await _create())["slug"]
            p = self._patches(proxy)
            with p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7]:
                deploy = asyncio.create_task(main.api_deploy(MagicMock(), slug, self._deploy_body()))
                await pulling.wait()
                with pytest.raises(HTTPException) as err:
                    await main.api_delete_custom_service(MagicMock(), slug, {})
                release.set()
                await deploy
                done = await main.api_delete_custom_service(MagicMock(), slug, {})
            return err.value, done

        refused, done = _run(go)
        assert refused.status_code == 409
        assert "being deployed" in refused.detail
        assert done == {"status": "deleted"}
        assert not main._custom_deploying and not main._custom_deleting

    def test_a_deploy_during_a_delete_is_refused(self, db):
        checking, release = asyncio.Event(), asyncio.Event()

        async def deployed_on(slug):
            checking.set()
            await release.wait()
            return []

        async def go():
            slug = (await _create())["slug"]
            p = self._patches(AsyncMock(return_value={"container_id": "abc"}))
            with p[0], p[1], p[2], p[3], p[4], p[5], p[6], patch.object(main, "_custom_deployed_on", deployed_on):
                delete = asyncio.create_task(main.api_delete_custom_service(MagicMock(), slug, {}))
                await checking.wait()
                with pytest.raises(HTTPException) as err:
                    await main.api_deploy(MagicMock(), slug, self._deploy_body())
                release.set()
                return err.value, await delete

        refused, done = _run(go)
        assert refused.status_code == 409
        assert done == {"status": "deleted"}
        assert not main._custom_deploying and not main._custom_deleting
