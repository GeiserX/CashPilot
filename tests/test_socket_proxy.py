"""The Docker socket proxy: the shipped compose files, the policy, and what the
worker tells you when the proxy refuses a call.

The live proof (real proxy, real daemon, positive control without the proxy) is
scripts/socket_proxy_live_test.sh. These tests pin what can be checked without
a daemon: the policy the compose files ship, and the worker's side of it.
"""

from __future__ import annotations

import os
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from fastapi.testclient import TestClient

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

from docker.errors import APIError  # noqa: E402

from app import orchestrator, worker_api  # noqa: E402
from tests import test_update_feature as tuf  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import socket_proxy_policy as spp  # noqa: E402

PINNED = "codeswhat/sockguard:2.4.5@sha256:d15f93e856626ff21f48400034d887874a4dafbbf6bb1e31799511beea07d84c"
PROXY_SOCKET = f"unix://{orchestrator.PROXY_SOCKET_DIR}/docker.sock"


def _compose(name: str) -> dict:
    return yaml.safe_load((ROOT / name).read_text())


def _policy_of(compose: dict) -> dict:
    content = compose["configs"]["cashpilot_socket_policy"]["content"]
    # Compose turns `$$` into `$`; nothing else in the block is interpolated.
    assert re.search(r"(?<!\$)\$(?!\$)", content.replace("$$", "")) is None, "an unescaped $ in the policy"
    return yaml.safe_load(content.replace("$$", "$"))


def _catalog() -> list[dict]:
    return [
        yaml.safe_load(p.read_text()) or {}
        for p in sorted((ROOT / "services").rglob("*.yml"))
        if not p.name.startswith("_")
    ]


def _allowed(policy: dict, method: str, path: str) -> bool:
    """First matching rule wins, as in sockguard; `*` stops at `/`, `**` does not."""
    for rule in policy["rules"]:
        m = rule["match"]
        if m["method"] not in ("*", method):
            continue
        pattern = re.escape(m["path"]).replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
        if re.fullmatch(pattern, path):
            return rule["action"] == "allow"
    return False


def policy_problems(policy: dict, catalog: list[dict]) -> list[str]:
    """Everything wrong with a policy, so a mutated copy can prove each check fires."""
    problems: list[str] = []
    create = policy["request_body"]["container_create"]
    exec_ = policy["request_body"]["exec"]
    if create.get("allow_privileged") is not False:
        problems.append("privileged containers allowed")
    if not create.get("require_no_new_privileges"):
        problems.append("no-new-privileges not required")
    for key in ("allow_host_pid", "allow_host_ipc", "allow_host_userns", "allow_host_cgroupns"):
        if create.get(key):
            problems.append(f"{key} on")
    if create.get("allow_all_capabilities") or create.get("allow_all_devices"):
        problems.append("capability or device allowlist switched off")
    caps = {c.upper().removeprefix("CAP_") for c in create.get("allowed_capabilities") or []}
    devices = set(create.get("allowed_devices") or [])
    for svc in catalog:
        docker = svc.get("docker") or {}
        for cap in docker.get("cap_add") or []:
            if str(cap).upper().removeprefix("CAP_") not in caps:
                problems.append(f"{svc.get('slug')} needs capability {cap}")
        for dev in docker.get("devices") or []:
            if str(dev).split(":")[0] not in devices:
                problems.append(f"{svc.get('slug')} needs device {dev}")
    commands = exec_.get("allowed_commands") or []
    for argv in spp.catalog_commands():
        if argv not in commands:
            problems.append(f"exec {argv[:2]} not allowed")
    if exec_.get("allowed_env_vars") != ["CASHPILOT_EXEC_SENDS_NO_ENV"]:
        problems.append("exec Env not limited to the sentinel")
    if ["sh"] in commands or any(argv[:1] == ["sh"] and len(argv) < 3 for argv in commands):
        problems.append("a bare shell is allowed")
    response = policy["response"]
    for key in ("redact_container_env", "redact_mount_paths", "redact_network_topology"):
        if response.get(key) is not False:
            problems.append(f"{key} on: the worker reads those fields")
    if create.get("allowed_bind_mounts"):
        problems.append("bind mounts allowed in YAML, not only through the environment")
    for method, path in (
        ("POST", "/swarm/init"),
        ("POST", "/plugins/pull"),
        ("POST", "/build"),
        ("POST", "/containers/abc/update"),
        ("POST", "/containers/abc/attach"),
        ("POST", "/containers/abc/kill"),
        ("POST", "/commit"),
        ("GET", "/containers/abc/export"),
        ("GET", "/events"),
        ("POST", "/volumes/create"),
        ("POST", "/networks/create"),
        ("POST", "/images/load"),
        ("POST", "/session"),
        ("DELETE", "/images/abc"),
    ):
        if _allowed(policy, method, path):
            problems.append(f"{method} {path} allowed")
    last = policy["rules"][-1]
    if last["match"] != {"method": "*", "path": "/**"} or last["action"] != "deny":
        problems.append("the last rule is not a deny-everything")
    return problems


COMPOSE_FILES = spp.COMPOSE_FILES


# ---------------------------------------------------------------------------
# The shipped compose files
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", COMPOSE_FILES)
def test_the_worker_has_no_socket_and_reaches_docker_through_the_proxy(name):
    services = _compose(name)["services"]
    worker = services["cashpilot-worker"]
    assert not any("docker.sock" in str(v) for v in worker.get("volumes") or [])
    assert f"DOCKER_HOST={PROXY_SOCKET}" in worker["environment"]
    assert f"cashpilot_docker_api:{orchestrator.PROXY_SOCKET_DIR}" in worker["volumes"]
    assert "cashpilot-socket-proxy" in worker["depends_on"]
    for var in (orchestrator.COMPOSE_DIR_ENV, orchestrator.BIND_MOUNTS_ENV):
        assert any(str(e).startswith(f"{var}=") for e in worker["environment"])


@pytest.mark.parametrize("name", COMPOSE_FILES)
def test_the_proxy_is_pinned_and_holds_the_socket_read_only(name):
    compose = _compose(name)
    proxy = compose["services"]["cashpilot-socket-proxy"]
    assert proxy["image"] == PINNED
    assert proxy["container_name"] == orchestrator.PROXY_SERVICE
    assert "/var/run/docker.sock:/var/run/docker.sock:ro" in proxy["volumes"]
    assert proxy["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in proxy["security_opt"]
    assert proxy["network_mode"] == "none"
    assert compose["volumes"]["cashpilot_docker_api"]["name"] == orchestrator.PROXY_VOLUME
    # Only the UI and the worker carry labels the update could act on; the
    # proxy is never in the update's service list.
    assert proxy["configs"] == [{"source": "cashpilot_socket_policy", "target": "/etc/sockguard/sockguard.yaml"}]
    binds = next(e for e in proxy["environment"] if "ALLOWED_BIND_MOUNTS" in e)
    # An unset variable must never become an empty allow-everything entry.
    assert "${CASHPILOT_COMPOSE_DIR:-/nonexistent/" in binds
    assert "${CASHPILOT_PROXY_BIND_MOUNTS:-/nonexistent/" in binds


@pytest.mark.parametrize("name", COMPOSE_FILES)
def test_only_the_proxy_binds_the_socket(name):
    for svc_name, svc in _compose(name)["services"].items():
        if svc_name != "cashpilot-socket-proxy":
            assert not any("docker.sock" in str(v) for v in svc.get("volumes") or []), svc_name


def test_every_compose_file_carries_the_generated_policy():
    assert spp.main(["--check"]) == 0
    policies = {name: _policy_of(_compose(name)) for name in COMPOSE_FILES}
    first = policies[COMPOSE_FILES[0]]
    assert all(p == first for p in policies.values())
    assert first == yaml.safe_load(spp.policy())


@pytest.mark.parametrize("name", COMPOSE_FILES)
def test_the_shipped_policy_has_no_problems(name):
    assert policy_problems(_policy_of(_compose(name)), _catalog()) == []


def test_the_policy_allows_every_call_the_worker_makes():
    policy = _policy_of(_compose("docker-compose.yml"))
    for method, path in spp.ALLOWED_CALLS:
        concrete = path.replace("**", "drumsergio/cashpilot-worker").replace("*", "abc123")
        assert _allowed(policy, method, concrete), (method, path)


# Positive controls: each mutation must make policy_problems report something,
# or the check above could not fail.
MUTATIONS = {
    "privileged": lambda p: p["request_body"]["container_create"].update(allow_privileged=True),
    "no nnp": lambda p: p["request_body"]["container_create"].update(require_no_new_privileges=False),
    "host pid": lambda p: p["request_body"]["container_create"].update(allow_host_pid=True),
    "drop NET_ADMIN": lambda p: p["request_body"]["container_create"]["allowed_capabilities"].remove("NET_ADMIN"),
    "drop tun": lambda p: p["request_body"]["container_create"].update(allowed_devices=[]),
    "drop a reader": lambda p: p["request_body"]["exec"]["allowed_commands"].pop(),
    "exec env": lambda p: p["request_body"]["exec"].update(allowed_env_vars=["PATH"]),
    "bare shell": lambda p: p["request_body"]["exec"]["allowed_commands"].append(["sh"]),
    "redact env": lambda p: p["response"].update(redact_container_env=True),
    "yaml binds": lambda p: p["request_body"]["container_create"].update(allowed_bind_mounts=["/"]),
    "swarm": lambda p: p["rules"].insert(0, {"match": {"method": "POST", "path": "/swarm/**"}, "action": "allow"}),
    "update": lambda p: p["rules"].insert(
        0, {"match": {"method": "POST", "path": "/containers/*/update"}, "action": "allow"}
    ),
    "no final deny": lambda p: p["rules"].pop(),
}


@pytest.mark.parametrize("mutation", sorted(MUTATIONS))
def test_each_policy_check_can_fail(mutation):
    policy = yaml.safe_load(spp.policy())
    MUTATIONS[mutation](policy)
    assert policy_problems(policy, _catalog()), mutation


def test_a_catalog_reader_the_policy_lacks_fails_the_check(tmp_path):
    svc = tmp_path / "bandwidth" / "newnode.yml"
    svc.parent.mkdir()
    svc.write_text(yaml.safe_dump({"slug": "newnode", "collector": {"node_read": {"command": ["cat", "/x"]}}}))
    assert ["cat", "/x"] in spp.catalog_commands(tmp_path)
    assert ["cat", "/x"] not in _policy_of(_compose("docker-compose.yml"))["request_body"]["exec"]["allowed_commands"]


def test_the_policy_check_catches_a_hand_edited_compose_file(tmp_path, monkeypatch):
    for name in COMPOSE_FILES:
        (tmp_path / name).write_text((ROOT / name).read_text())
    edited = tmp_path / COMPOSE_FILES[0]
    edited.write_text(edited.read_text().replace("allow_privileged: false", "allow_privileged: true", 1))
    monkeypatch.setattr(spp, "ROOT", tmp_path)
    assert spp.main(["--check"]) == 1


def test_the_policy_quotes_shell_dollars_for_compose():
    block = spp.compose_block()
    assert "$(" not in block.replace("$$(", "")
    assert "$$id" in block


def test_the_sockguard_digest_matches_the_documented_one():
    for doc in ("SECURITY.md", "docs/security-defaults.md"):
        assert PINNED.split("@")[0] in (ROOT / doc).read_text(), doc


# ---------------------------------------------------------------------------
# The worker's side: proxied(), the refusal, the deploy guard
# ---------------------------------------------------------------------------


def _api_error(status: int, body: object | None, text: str = "") -> APIError:
    response = MagicMock()
    response.status_code = status
    if body is None:
        response.json.side_effect = ValueError("not JSON")
    else:
        response.json.return_value = body
    return APIError(f"{status} Client Error", response=response, explanation=text or "x")


SOCKGUARD_403 = {
    "message": "request denied by sockguard policy",
    "method": "POST",
    "path": "/v1.47/containers/create",
    "reason": 'container create denied: capability "SYS_ADMIN" is not in the allowed list',
}


def test_proxied_reads_docker_host(monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", PROXY_SOCKET)
    assert orchestrator.proxied() is True
    assert orchestrator.docker_access() == "proxy"
    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    assert orchestrator.proxied() is False
    monkeypatch.delenv("DOCKER_HOST")
    assert orchestrator.docker_access() == "socket"


def test_a_proxy_refusal_reads_its_reason():
    text = orchestrator.proxy_refusal(_api_error(403, SOCKGUARD_403))
    assert text == (
        'The Docker socket proxy refused this: container create denied: capability "SYS_ADMIN" '
        "is not in the allowed list."
    )


def test_a_refused_bind_says_which_setting_allows_it():
    body = {**SOCKGUARD_403, "reason": 'container create denied: bind mount source "/srv/storj" is not allowlisted'}
    text = orchestrator.proxy_refusal(_api_error(403, body))
    assert '"/srv/storj" is not allowlisted' in text
    assert "CASHPILOT_PROXY_BIND_MOUNTS" in text


def test_a_path_rule_refusal_reads_its_reason():
    body = {**SOCKGUARD_403, "reason": "the CashPilot worker does not use this Docker API call"}
    assert orchestrator.proxy_refusal(_api_error(403, body)).endswith("does not use this Docker API call.")


def test_an_owner_policy_refusal_is_the_proxy_too():
    body = {"message": 'owner policy denied access to volume "x" referenced by container HostConfig.Binds'}
    assert "owner policy denied" in orchestrator.proxy_refusal(_api_error(403, body))


@pytest.mark.parametrize(
    "exc",
    [
        _api_error(409, SOCKGUARD_403),  # not a 403
        _api_error(403, {"message": "forbidden by an authz plugin"}),  # Docker's own 403
        _api_error(403, None, "not JSON"),
        _api_error(403, ["a list"]),
        ValueError("no status at all"),
    ],
)
def test_anything_else_is_not_a_proxy_refusal(exc):
    assert orchestrator.proxy_refusal(exc) is None


def test_a_long_or_multiline_reason_is_one_capped_line():
    body = {**SOCKGUARD_403, "reason": "denied:\n" + "x" * 1000}
    text = orchestrator.proxy_refusal(_api_error(403, body))
    assert "\n" not in text
    assert len(text) < 400


@asynccontextmanager
async def _noop_lifespan(a):
    yield


def _worker_deploy(spec: dict, **patches):
    worker_api.app.router.lifespan_context = _noop_lifespan
    with patch("app.worker_api._verify_api_key"), patch("app.worker_api.orchestrator.deploy_raw", **patches) as m:
        resp = TestClient(worker_api.app, raise_server_exceptions=False).post(
            "/api/containers/honeygain/deploy", json=spec
        )
    return resp, m


def test_the_deploy_route_returns_the_proxy_reason_as_a_403():
    resp, _ = _worker_deploy({"image": "img"}, side_effect=_api_error(403, SOCKGUARD_403))
    assert resp.status_code == 403
    assert resp.json()["detail"].startswith("The Docker socket proxy refused this: container create denied")


def test_the_deploy_route_keeps_docker_errors_as_409():
    resp, _ = _worker_deploy({"image": "img"}, side_effect=_api_error(409, {"message": "Conflict"}, "name in use"))
    assert resp.status_code == 409
    assert resp.json()["detail"].startswith("Docker refused the container: ")


def test_the_proxy_volume_can_never_go_to_a_container():
    resp, deploy = _worker_deploy(
        {"image": "img", "volumes": {orchestrator.PROXY_VOLUME: {"bind": "/x", "mode": "rw"}}}
    )
    assert resp.status_code == 403
    assert "Docker socket" in resp.json()["detail"]
    deploy.assert_not_called()


def test_proxied_a_bind_outside_the_allowed_folders_is_refused_before_anything_is_touched(monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", PROXY_SOCKET)
    monkeypatch.setenv("CASHPILOT_COMPOSE_DIR", "/srv/cashpilot")
    monkeypatch.setenv("CASHPILOT_PROXY_BIND_MOUNTS", "/storage/storj, /storage/data/")
    ok, deploy = _worker_deploy({"image": "img", "volumes": {"/storage/data/node": {"bind": "/d", "mode": "rw"}}})
    assert ok.status_code == 200, ok.text
    resp, deploy = _worker_deploy({"image": "img", "volumes": {"/storage/storjx": {"bind": "/d", "mode": "rw"}}})
    assert resp.status_code == 403
    assert "CASHPILOT_PROXY_BIND_MOUNTS" in resp.json()["detail"]
    deploy.assert_not_called()


def test_with_the_raw_socket_binds_keep_their_old_rules(monkeypatch):
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("CASHPILOT_PROXY_BIND_MOUNTS", raising=False)
    resp, _ = _worker_deploy({"image": "img", "volumes": {"/storage/storj": {"bind": "/d", "mode": "rw"}}})
    assert resp.status_code == 200, resp.text


def test_get_client_names_the_proxy_when_it_is_down(monkeypatch):
    from docker.errors import DockerException

    monkeypatch.setenv("DOCKER_HOST", PROXY_SOCKET)
    with (
        patch("app.orchestrator.docker.from_env", side_effect=DockerException("no socket")),
        pytest.raises(RuntimeError, match="cashpilot-socket-proxy"),
    ):
        orchestrator._get_client()


# ---------------------------------------------------------------------------
# The in-app update through the proxy
# ---------------------------------------------------------------------------


def _proxied_env(monkeypatch, compose_dir="/srv/cashpilot", bind_mounts=""):
    monkeypatch.setenv("DOCKER_HOST", PROXY_SOCKET)
    monkeypatch.setenv("CASHPILOT_COMPOSE_DIR", compose_dir)
    monkeypatch.setenv("CASHPILOT_PROXY_BIND_MOUNTS", bind_mounts)


def _run_update(labels=None):
    me = tuf._fake_container(labels=labels or tuf._COMPOSE_LABELS)
    client = tuf._fake_docker(me=me)
    tuf._wire_runs(client)
    with patch.object(orchestrator, "_get_client", return_value=client):
        result = orchestrator.spawn_self_update()
    return client, result


def test_proxied_the_helper_gets_the_filtered_socket_not_the_host_one(monkeypatch):
    _proxied_env(monkeypatch)
    client, _ = _run_update()
    kwargs = tuf._updater_call(client).kwargs
    assert "/var/run/docker.sock" not in kwargs["volumes"]
    assert kwargs["volumes"][orchestrator.PROXY_VOLUME] == {"bind": orchestrator.PROXY_SOCKET_DIR, "mode": "rw"}
    assert kwargs["environment"]["DOCKER_HOST"] == PROXY_SOCKET
    assert kwargs["security_opt"] == ["no-new-privileges:true"]
    preflight = client.containers.run.call_args_list[0].kwargs
    # The check resolves the file and needs no Docker at all.
    assert "DOCKER_HOST" not in preflight["environment"]
    assert orchestrator.PROXY_VOLUME not in preflight["volumes"]
    assert preflight["security_opt"] == ["no-new-privileges:true"]


def test_with_the_raw_socket_the_helper_is_unchanged(monkeypatch):
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    client, _ = _run_update()
    kwargs = tuf._updater_call(client).kwargs
    assert set(kwargs["volumes"]) == {"/var/run/docker.sock", "/srv/cashpilot"}
    assert "DOCKER_HOST" not in kwargs["environment"]


@pytest.mark.parametrize("compose_dir", ["", "/srv/elsewhere"])
def test_proxied_a_compose_folder_the_proxy_does_not_know_is_refused_with_the_line_to_paste(monkeypatch, compose_dir):
    _proxied_env(monkeypatch, compose_dir=compose_dir)
    me = tuf._fake_container(labels=tuf._COMPOSE_LABELS)
    client = tuf._fake_docker(me=me)
    tuf._wire_runs(client)
    with (
        patch.object(orchestrator, "_get_client", return_value=client),
        pytest.raises(orchestrator.SelfUpdateUnavailable, match="CASHPILOT_COMPOSE_DIR=/srv/cashpilot$"),
    ):
        orchestrator.spawn_self_update()
    client.containers.run.assert_not_called()


def test_proxied_a_trailing_slash_is_the_same_folder(monkeypatch):
    _proxied_env(monkeypatch, compose_dir="/srv/cashpilot/")
    client, result = _run_update()
    assert result["working_dir"] == "/srv/cashpilot"


ENV_FILE_LABELS = {**tuf._COMPOSE_LABELS, "com.docker.compose.project.environment_file": "/etc/cashpilot/prod.env"}


def test_proxied_an_env_file_outside_the_allowed_folders_is_refused(monkeypatch):
    _proxied_env(monkeypatch)
    me = tuf._fake_container(labels=ENV_FILE_LABELS)
    client = tuf._fake_docker(me=me)
    tuf._wire_runs(client)
    with (
        patch.object(orchestrator, "_get_client", return_value=client),
        pytest.raises(orchestrator.SelfUpdateUnavailable, match="CASHPILOT_PROXY_BIND_MOUNTS"),
    ):
        orchestrator.spawn_self_update()
    client.containers.run.assert_not_called()


def test_proxied_an_env_file_in_an_allowed_folder_is_mounted(monkeypatch):
    _proxied_env(monkeypatch, bind_mounts="/etc/cashpilot")
    client, _ = _run_update(ENV_FILE_LABELS)
    assert "/etc/cashpilot/prod.env" in tuf._updater_call(client).kwargs["volumes"]


def test_a_proxy_refusal_of_the_helper_says_why(monkeypatch):
    _proxied_env(monkeypatch)
    me = tuf._fake_container(labels=tuf._COMPOSE_LABELS)
    client = tuf._fake_docker(me=me)
    preflight = tuf._preflight()

    def run(image, *args, **kwargs):
        if kwargs.get("name") == orchestrator.UPDATER_NAME:
            raise _api_error(403, {**SOCKGUARD_403, "reason": "container create denied: bind mount source x"})
        return preflight

    client.containers.run.side_effect = run
    with (
        patch.object(orchestrator, "_get_client", return_value=client),
        pytest.raises(orchestrator.SelfUpdateUnavailable, match="The Docker socket proxy refused this"),
    ):
        orchestrator.spawn_self_update()


def test_update_facts_say_how_the_worker_reaches_docker(monkeypatch):
    _proxied_env(monkeypatch)
    me = tuf._fake_container(labels=tuf._COMPOSE_LABELS)
    with patch.object(orchestrator, "_get_client", return_value=tuf._fake_docker(me=me)):
        assert orchestrator.self_update_info()["docker_access"] == "proxy"


def test_proxy_bind_mounts_also_open_the_worker_allowlist():
    """One setting opens a host folder for both the worker and the proxy; an entry
    the worker would never allowlist (a whole root) stays refused. Run in a fresh
    interpreter because the allowlist is read once at import."""
    import subprocess

    env = {**os.environ, "CASHPILOT_ALLOWED_VOLUME_ROOTS": "", "CASHPILOT_PROXY_BIND_MOUNTS": "/mnt/user/storj, /mnt"}
    code = "import app.worker_api as w; print(sorted(w._ALLOWED_VOLUME_ROOTS))"
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, check=True
    ).stdout
    assert "'/mnt/user/storj'" in out, out
    assert "'/mnt'" not in out, out


# ---------------------------------------------------------------------------
# Refused before the running container is touched: kept mounts and runtimes
# ---------------------------------------------------------------------------

MYST_TARGET = "/var/lib/mysterium-node"


def _redeploy(monkeypatch, old_mounts, **kwargs):
    """deploy_raw over a running mysterium container; returns (client, old, error)."""
    old = MagicMock()
    old.labels = {"cashpilot.service": "mysterium"}
    old.attrs = {"Mounts": old_mounts}
    client = MagicMock()
    client.containers.get.return_value = old
    client.containers.run.return_value = MagicMock(id="cid")
    error = None
    with patch.object(orchestrator, "_get_client", return_value=client):
        try:
            orchestrator.deploy_raw(slug="mysterium", image="img", **kwargs)
        except orchestrator.ContainerRuntimeError as exc:
            error = exc
    return client, old, error


def test_proxied_a_kept_host_folder_the_proxy_refuses_leaves_the_node_running(monkeypatch):
    _proxied_env(monkeypatch, bind_mounts="/srv/allowed")
    legacy = {"Type": "bind", "Source": "/home/me/legacy", "Destination": MYST_TARGET}
    client, old, error = _redeploy(
        monkeypatch,
        [legacy],
        volumes={"mysterium-data": {"bind": MYST_TARGET, "mode": "rw"}},
        keep_targets={MYST_TARGET},
    )
    assert error is not None and "/home/me/legacy" in str(error)
    assert "CASHPILOT_PROXY_BIND_MOUNTS" in str(error)
    old.stop.assert_not_called()
    old.remove.assert_not_called()
    client.containers.run.assert_not_called()


def test_proxied_a_kept_host_folder_inside_an_allowed_one_redeploys(monkeypatch):
    _proxied_env(monkeypatch, bind_mounts="/srv/allowed")
    kept = {"Type": "bind", "Source": "/srv/allowed/myst", "Destination": MYST_TARGET}
    client, old, error = _redeploy(
        monkeypatch,
        [kept],
        volumes={"mysterium-data": {"bind": MYST_TARGET, "mode": "rw"}},
        keep_targets={MYST_TARGET},
    )
    assert error is None
    old.remove.assert_called_once()
    assert client.containers.run.call_args.kwargs["volumes"] == [f"/srv/allowed/myst:{MYST_TARGET}:rw"]


def test_with_the_raw_socket_a_kept_host_folder_is_not_the_proxys_business(monkeypatch):
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    legacy = {"Type": "bind", "Source": "/home/me/legacy", "Destination": MYST_TARGET}
    _, old, error = _redeploy(
        monkeypatch,
        [legacy],
        volumes={"mysterium-data": {"bind": MYST_TARGET, "mode": "rw"}},
        keep_targets={MYST_TARGET},
    )
    assert error is None
    old.remove.assert_called_once()


@pytest.mark.parametrize("runtime", ["io.containerd.runc.v2", "nvidia", "crun", "sysbox-runc"])
def test_proxied_a_runtime_the_proxy_refuses_leaves_the_service_running(monkeypatch, runtime):
    _proxied_env(monkeypatch)
    client, old, error = _redeploy(monkeypatch, [], runtime=runtime)
    assert error is not None and runtime in str(error)
    old.stop.assert_not_called()
    old.remove.assert_not_called()
    client.images.pull.assert_not_called()


def test_proxied_a_default_runtime_the_proxy_refuses_is_caught_too(monkeypatch):
    _proxied_env(monkeypatch)
    monkeypatch.setattr(orchestrator, "_CONTAINER_RUNTIME", "crun")
    monkeypatch.setattr(orchestrator, "available_runtimes", lambda: {"runc", "crun"})
    with pytest.raises(orchestrator.ContainerRuntimeError, match="crun"):
        orchestrator.container_runtime("honeygain", None, None)


@pytest.mark.parametrize("runtime", ["runc", "runsc", "runsc-hostnet-raw"])
def test_proxied_the_policy_runtimes_pass(monkeypatch, runtime):
    _proxied_env(monkeypatch)
    assert orchestrator.container_runtime("honeygain", None, runtime) == runtime


def test_with_the_raw_socket_any_runtime_the_daemon_has_passes(monkeypatch):
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    assert orchestrator.container_runtime("honeygain", None, "nvidia") == "nvidia"


def test_the_worker_and_the_policy_share_one_runtime_list():
    policy = yaml.safe_load(spp.policy())["request_body"]["container_create"]
    from app import socket_policy

    assert policy["allowed_runtimes"] == list(socket_policy.ALLOWED_RUNTIMES)
    assert policy["allowed_capabilities"] == list(socket_policy.ALLOWED_CAPABILITIES)
    assert policy["allowed_devices"] == list(socket_policy.ALLOWED_DEVICES)


# ---------------------------------------------------------------------------
# The update: what Compose would ask the proxy for
# ---------------------------------------------------------------------------


def _update_with_config(monkeypatch, worker_cfg, bind_mounts=""):
    _proxied_env(monkeypatch, bind_mounts=bind_mounts)
    me = tuf._fake_container(labels=tuf._COMPOSE_LABELS)
    client = tuf._fake_docker(me=me)
    tuf._wire_runs(
        client, preflight=tuf._preflight(cfg={"name": "cashpilot", "services": {"cashpilot-worker": worker_cfg}})
    )
    with patch.object(orchestrator, "_get_client", return_value=client):
        try:
            orchestrator.spawn_self_update()
        except orchestrator.SelfUpdateUnavailable as exc:
            return client, str(exc)
    return client, None


@pytest.mark.parametrize(
    "worker_cfg, needle",
    [
        ({"devices": [{"source": "/dev/dri", "target": "/dev/dri", "permissions": "rwm"}]}, "/dev/dri"),
        ({"devices": ["/dev/dri:/dev/dri"]}, "/dev/dri"),
        ({"gpus": "all"}, "GPU"),
        (
            {"deploy": {"resources": {"reservations": {"devices": [{"driver": "nvidia", "capabilities": ["gpu"]}]}}}},
            "GPU",
        ),
        ({"volumes": [{"type": "bind", "source": "/mnt/user/appdata/cashpilot", "target": "/data"}]}, "/mnt/user"),
        ({"privileged": True}, "privileged"),
        ({"cap_add": ["SYS_ADMIN"]}, "SYS_ADMIN"),
        ({"runtime": "nvidia"}, "nvidia"),
    ],
)
def test_proxied_an_update_compose_would_fail_halfway_is_refused_first(monkeypatch, worker_cfg, needle):
    client, error = _update_with_config(monkeypatch, worker_cfg)
    assert error is not None and needle in error and "cashpilot-worker" in error, error
    assert not tuf._updater_started(client)


def test_proxied_an_update_the_proxy_allows_starts(monkeypatch):
    cfg = {
        "volumes": [
            {"type": "volume", "source": "cashpilot_worker_data", "target": "/data"},
            {"type": "bind", "source": "/srv/data/cashpilot", "target": "/cfg"},
        ],
        "devices": ["/dev/net/tun:/dev/net/tun"],
        "cap_add": ["NET_ADMIN"],
    }
    client, error = _update_with_config(monkeypatch, cfg, bind_mounts="/srv/data")
    assert error is None
    assert tuf._updater_started(client)


# ---------------------------------------------------------------------------
# A policy older than the worker image
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", COMPOSE_FILES)
def test_each_compose_file_gives_the_worker_the_policy_fingerprint(name):
    from app import socket_policy

    env = _compose(name)["services"]["cashpilot-worker"]["environment"]
    assert f"CASHPILOT_PROXY_POLICY={socket_policy.digest()}" in env


def test_a_fingerprint_that_differs_says_the_policy_is_stale(monkeypatch):
    from app import socket_policy

    monkeypatch.setattr(orchestrator, "_policy_digest", None)
    _proxied_env(monkeypatch)
    monkeypatch.setenv("CASHPILOT_PROXY_POLICY", socket_policy.digest())
    assert orchestrator.proxy_policy_current() is True
    assert worker_api._docker_access_text() == "socket proxy"
    monkeypatch.setenv("CASHPILOT_PROXY_POLICY", "0123456789abcdef")
    assert orchestrator.proxy_policy_current() is False
    assert "Replace your compose file" in worker_api._docker_access_text()
    monkeypatch.delenv("DOCKER_HOST")
    assert orchestrator.proxy_policy_current() is None


def test_a_new_catalog_reader_changes_the_fingerprint(tmp_path):
    from app import socket_policy

    svc = tmp_path / "bandwidth" / "newnode.yml"
    svc.parent.mkdir()
    svc.write_text(yaml.safe_dump({"slug": "newnode", "collector": {"node_read": {"command": ["cat", "/x"]}}}))
    assert socket_policy.digest(tmp_path) != socket_policy.digest()


@pytest.mark.parametrize("name", COMPOSE_FILES)
def test_the_proxy_holds_a_capability_no_created_container_may_have(name):
    """A container joining the proxy's PID namespace must hold less than the
    proxy, or the kernel lets it read /proc/1/root and the host socket in it."""
    from app import socket_policy

    proxy = _compose(name)["services"]["cashpilot-socket-proxy"]
    assert proxy["cap_add"] == ["WAKE_ALARM"]
    assert "WAKE_ALARM" not in socket_policy.ALLOWED_CAPABILITIES
