"""Checks run by scripts/socket_proxy_live_test.sh inside a worker image.

Not a module of the app. The live test pipes it into ``python -`` in the
running worker container (phases ``allowed``, ``refused``, ``update``,
``access``) and in a throwaway copy of the worker image that holds the host's
raw socket (phase ``control``). Each check prints one PASS or FAIL line; the
exit code is the number of failures.

    allowed  every Docker call the worker makes, through the real worker code
    refused  requests the proxy must refuse, sent as raw HTTP to the proxy
    control  the same requests sent to the raw socket, which must accept them,
             so each refusal is the proxy's and not a malformed request
    update   start the in-app update (the shell script checks what it did)
    access   print how this worker reaches Docker
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tarfile

import docker
from docker.errors import APIError, NotFound

PREFIX = "cashpilot-cplive-"
LABEL = {"cashpilot.live-test": "1"}
ALPINE = os.environ.get("LIVE_ALPINE", "alpine:3.22")
BINDS = os.environ.get("LIVE_BIND_DIR", "")
TUNNEL_IMAGE = os.environ.get("LIVE_TUNNEL_IMAGE", "")
FAILS = 0


def result(ok: bool, name: str, detail: str = "") -> None:
    global FAILS
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  ' + detail) if detail else ''}", flush=True)
    if not ok:
        FAILS += 1


def check(name: str, fn) -> object:
    from app import orchestrator

    try:
        value = fn()
    except Exception as exc:  # noqa: BLE001 - reported, the run goes on
        refusal = orchestrator.proxy_refusal(exc)
        result(False, name, refusal or f"{type(exc).__name__}: {exc}"[:300])
        return None
    result(True, name)
    return value


# ---------------------------------------------------------------------------
# allowed: the worker's own code, through the proxy
# ---------------------------------------------------------------------------


def phase_allowed() -> None:
    import base64

    import yaml

    from app import activity, isolation_check, orchestrator, proxy_tunnel

    # The policy the proxy actually loaded, handed over by the shell script.
    policy = yaml.safe_load(base64.b64decode(os.environ["LIVE_POLICY"]))
    commands = policy["request_body"]["exec"]["allowed_commands"]

    result(orchestrator.proxied(), "the worker reaches Docker through the proxy", os.environ.get("DOCKER_HOST", ""))
    client = check("ping and info", lambda: orchestrator._get_client())
    if client is None:
        return
    check("info", client.info)
    check("version", client.version)
    check("available runtimes", orchestrator.available_runtimes)

    plain = "cplive-plain"
    volumes = {PREFIX + "data": {"bind": "/data", "mode": "rw"}}
    if BINDS:
        volumes[f"{BINDS}/plain"] = {"bind": "/srv", "mode": "rw"}
    check(
        "deploy a hardened container with a bind from the allowed folder and NET_RAW",
        lambda: orchestrator.deploy_raw(
            slug=plain,
            image=ALPINE,
            command="sleep 600",
            volumes=volumes,
            cap_add=["NET_RAW"],
            labels=dict(LABEL),
        ),
    )
    check(
        "deploy on host networking with NET_ADMIN and /dev/net/tun",
        lambda: orchestrator.deploy_raw(
            slug="cplive-host",
            image=ALPINE,
            command="sleep 600",
            network_mode="host",
            cap_add=["NET_ADMIN", "SETUID", "SETGID"],
            devices=["/dev/net/tun"],
            labels=dict(LABEL),
        ),
    )
    name = PREFIX + "plain"
    container = check("inspect a container", lambda: client.containers.get(name))
    if container is None:
        return
    check("list containers", lambda: client.containers.list(all=True, filters={"label": "cashpilot.live-test=1"}))
    check("status of every managed container", orchestrator.get_status)
    check("logs", lambda: orchestrator.get_service_logs(plain))
    check("stats", lambda: container.stats(stream=False))
    for argv in commands:
        check(f"exec {json.dumps(argv)[:60]}", lambda argv=argv: container.exec_run(argv))
    check("pause", container.pause)
    check(
        "read a file from a paused container",
        lambda: orchestrator._read_file_from_container(container, "/etc/hostname"),
    )
    check("unpause", container.unpause)
    check("stop", lambda: orchestrator.stop_service(plain))
    check("start", lambda: orchestrator.start_service(plain))
    check("restart", lambda: orchestrator.restart_service(plain))
    check("inspect a named volume", lambda: client.volumes.get(PREFIX + "data").attrs)
    check("inspect the bridge network", lambda: client.networks.get("bridge").attrs)

    if TUNNEL_IMAGE:
        kwargs = proxy_tunnel.sidecar_kwargs(PREFIX + "tunnel", "cplive", 1, None, hostname="cplive-tunnel")
        kwargs.update(entrypoint=["sleep", "600"])
        kwargs["labels"] = {**kwargs["labels"], **LABEL}
        kwargs.pop("detach")
        sidecar = check(
            "create the tunnel sidecar (sysctls, tmpfs, init, pids limit)", lambda: client.containers.create(**kwargs)
        )
        if sidecar is not None:
            tar = proxy_tunnel._secret_tar({"proxy_ip": "203.0.113.1"})
            check(
                "write the proxy settings into the sidecar", lambda: sidecar.put_archive(proxy_tunnel.SECRET_DIR, tar)
            )
            check("start the sidecar", sidecar.start)
            check("read the sidecar's readiness file", lambda: sidecar.exec_run(["cat", "/run/ready"]))
            check(
                "deploy an earner inside the sidecar's network namespace",
                lambda: orchestrator.deploy_raw(
                    slug="cplive-earner",
                    image=ALPINE,
                    command="sleep 600",
                    network_mode=f"container:{sidecar.id}",
                    labels=dict(LABEL),
                    name=PREFIX + "earner",
                ),
            )

    check("isolation check (probe containers, network and node reads)", isolation_check.run)
    check("activity round", lambda: activity.run_round())
    check("update facts", orchestrator.self_update_info)

    for slug in (["cplive-earner"] if TUNNEL_IMAGE else []) + ["cplive-host", plain]:
        check(
            f"remove {slug} and its volumes",
            lambda slug=slug: orchestrator.remove_service(slug, delete_volumes=True, allow_delete_critical=True),
        )
    for c in client.containers.list(all=True, filters={"label": "cashpilot.live-test=1"}):
        check(f"remove {c.name}", lambda c=c: c.remove(force=True, v=True))
    try:
        client.volumes.get(PREFIX + "data")
        result(False, "the named volume went with its service")
    except NotFound:
        result(True, "the named volume went with its service")


# ---------------------------------------------------------------------------
# refused / control: the same raw requests, two expected outcomes
# ---------------------------------------------------------------------------


def _create(host_config: dict, **extra) -> tuple[str, dict]:
    body = {"Image": ALPINE, "Cmd": ["true"], "Labels": LABEL, "HostConfig": host_config, **extra}
    return "/containers/create", body


NNP = ["no-new-privileges:true"]
REQUESTS: list[tuple[str, str, str, object]] = [
    ("privileged container", "POST", *_create({"Privileged": True, "SecurityOpt": NNP})),
    ("bind of /", "POST", *_create({"Binds": ["/:/host"], "SecurityOpt": NNP})),
    (
        "bind of the Docker socket",
        "POST",
        *_create({"Binds": ["/var/run/docker.sock:/var/run/docker.sock"], "SecurityOpt": NNP}),
    ),
    ("capability SYS_ADMIN", "POST", *_create({"CapAdd": ["SYS_ADMIN"], "SecurityOpt": NNP})),
    (
        "device /dev/zero",
        "POST",
        *_create(
            {
                "Devices": [{"PathOnHost": "/dev/zero", "PathInContainer": "/dev/zero", "CgroupPermissions": "rwm"}],
                "SecurityOpt": NNP,
            }
        ),
    ),
    ("host PID namespace", "POST", *_create({"PidMode": "host", "SecurityOpt": NNP})),
    ("seccomp unconfined", "POST", *_create({"SecurityOpt": [*NNP, "seccomp=unconfined"]})),
    ("a container without no-new-privileges", "POST", *_create({})),
    (
        'lowercase "privileged"',
        "POST",
        "/containers/create",
        {"image": ALPINE, "cmd": ["true"], "labels": LABEL, "hostconfig": {"privileged": True, "securityopt": NNP}},
    ),
    (
        "a local volume bound to /",
        "POST",
        "/volumes/create",
        {
            "Name": PREFIX + "rootvol",
            "Labels": LABEL,
            "Driver": "local",
            "DriverOpts": {"type": "none", "o": "bind", "device": "/"},
        },
    ),
    ("exec sh", "POST", "/containers/{target}/exec", {"Cmd": ["sh"], "AttachStdout": True}),
    (
        "exec with LD_PRELOAD",
        "POST",
        "/containers/{target}/exec",
        {"Cmd": ["cat", "/etc/anon/anonrc"], "Env": ["LD_PRELOAD=/tmp/x.so"]},
    ),
    ("container update", "POST", "/containers/{target}/update", {"Memory": 0, "CpuShares": 512}),
    ("swarm init", "POST", "/swarm/init", {"ListenAddr": "127.0.0.1:2377", "AdvertiseAddr": "127.0.0.1:2377"}),
    ("image build", "POST", "/build?t=" + PREFIX + "build", None),
    ("plugin list", "GET", "/plugins", None),
    ("events stream", "GET", "/events?until=0", None),
]

_TAR = io.BytesIO()
with tarfile.open(fileobj=_TAR, mode="w") as _t:
    _info = tarfile.TarInfo("Dockerfile")
    _data = b"FROM scratch\nLABEL cashpilot.live-test=1\n"
    _info.size = len(_data)
    _t.addfile(_info, io.BytesIO(_data))
BUILD_CONTEXT = _TAR.getvalue()


def _send(api: docker.APIClient, method: str, path: str, body: object) -> tuple[int, str]:
    url = api._url(path.split("?")[0]) + ("?" + path.split("?", 1)[1] if "?" in path else "")
    if path.startswith("/build"):
        resp = api._post(url, data=BUILD_CONTEXT, headers={"Content-Type": "application/x-tar"})
    elif method == "GET":
        resp = api._get(url, timeout=10)
    else:
        resp = api._post_json(url, data=body)
    return resp.status_code, resp.text[:300]


def _target(client: docker.DockerClient) -> str:
    name = PREFIX + "target"
    with_name = client.containers.list(all=True, filters={"name": name})
    if with_name:
        return with_name[0].id
    c = client.containers.run(ALPINE, ["sleep", "600"], name=name, labels=LABEL, security_opt=NNP, detach=True)
    return c.id


def phase_refused_or_control(control: bool) -> None:
    client = docker.from_env()
    api = client.api
    target = _target(client)
    try:
        for name, method, path, body in REQUESTS:
            code, text = _send(api, method, path.format(target=target), body)
            by_proxy = code == 403 and "sockguard" in text
            if control:
                # The raw daemon must take the request: proof it is well formed
                # and that a 403 from the proxy is the proxy's own decision.
                result(200 <= code < 300, f"raw socket accepts: {name}", f"{code} {text[:120]}")
            else:
                reason = ""
                with contextlib.suppress(ValueError, AttributeError):
                    reason = json.loads(text).get("reason", "")
                result(by_proxy, f"proxy refuses: {name}", f"{code} {reason or text[:120]}")
    finally:
        if control:
            _undo_control(client)
        for c in client.containers.list(all=True, filters={"label": "cashpilot.live-test=1"}):
            c.remove(force=True, v=True)


def _undo_control(client: docker.DockerClient) -> None:
    """Put the daemon back the way the control found it."""
    with contextlib.suppress(APIError):
        client.swarm.leave(force=True)
    for v in client.volumes.list(filters={"label": "cashpilot.live-test=1"}):
        v.remove(force=True)
    with contextlib.suppress(NotFound, APIError):
        client.images.remove(PREFIX + "build", force=True)


# ---------------------------------------------------------------------------


def phase_update() -> None:
    from app import orchestrator

    started = check("start the in-app update", orchestrator.spawn_self_update)
    print(json.dumps(started or {}), flush=True)


def phase_access() -> None:
    from app import orchestrator

    print(orchestrator.docker_access(), flush=True)


if __name__ == "__main__":
    sys.path.insert(0, "/app")
    phase = sys.argv[1]
    if phase == "allowed":
        phase_allowed()
    elif phase in ("refused", "control"):
        phase_refused_or_control(phase == "control")
    elif phase == "update":
        phase_update()
    elif phase == "access":
        phase_access()
    else:
        raise SystemExit(f"unknown phase {phase}")
    sys.exit(min(FAILS, 100))
