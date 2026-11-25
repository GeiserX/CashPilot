"""The GPU grant (app/gpu.py): a catalog entry's docker.gpu reaches that one
container, and nothing else reaches a GPU.

The sysfs trees below are shaped like real hosts. watchtower's was read from
inside its cashpilot-worker container, which has no device passed in: three
Intel render nodes (an iGPU and two SR-IOV functions) and the ASPEED BMC chip.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

from docker.errors import APIError  # noqa: E402

from app import catalog, drift, gpu, main, orchestrator, preflight, proxies, worker_api  # noqa: E402

LINUX = {"system": "Linux", "release": "6.12.54-Unraid"}


def _pci(root: Path, addr: str, vendor: str, cls: str) -> None:
    d = root / "bus" / "pci" / "devices" / addr
    d.mkdir(parents=True)
    (d / "vendor").write_text(vendor + "\n")
    (d / "class").write_text(cls + "\n")


def _render(root: Path, n: int, vendor: str) -> None:
    d = root / "class" / "drm" / f"renderD{n}" / "device"
    d.mkdir(parents=True)
    (d / "vendor").write_text(vendor + "\n")


def _card(root: Path, n: int, vendor: str) -> None:
    d = root / "class" / "drm" / f"card{n}" / "device"
    d.mkdir(parents=True)
    (d / "vendor").write_text(vendor + "\n")


def watchtower(root: Path) -> Path:
    for fn in ("0", "1", "2"):
        _pci(root, f"0000:00:02.{fn}", "0x8086", "0x030000")
    _pci(root, "0000:09:00.0", "0x1a03", "0x030000")  # ASPEED BMC display
    _pci(root, "0000:00:1f.3", "0x8086", "0x040380")  # Intel audio, not a display
    for n in (128, 129, 130):
        _render(root, n, "0x8086")
    _card(root, 0, "0x8086")
    return root


def read(root: Path, system: str = "Linux", release: str = "6.12.54-Unraid") -> dict:
    with (
        patch.object(gpu.platform, "system", return_value=system),
        patch.object(gpu.platform, "release", return_value=release),
    ):
        return gpu.host_gpus(root)


NVIDIA = {"vendor": "nvidia", "count": 1, "rocm": False}
NVIDIA_HOST = {"conclusive": True, "vendors": {"nvidia": {"pci": 1, "render_nodes": []}}, "kfd": False}
UNKNOWN_HOST = {"conclusive": False, "vendors": {}, "kfd": False, "reason": "this is WSL"}


# ---------------------------------------------------------------------------
# What sysfs says
# ---------------------------------------------------------------------------


def test_watchtower_reads_as_intel_only(tmp_path):
    host = read(watchtower(tmp_path))
    assert host["conclusive"] is True
    assert set(host["vendors"]) == {"intel"}, "the ASPEED BMC chip is not a GPU"
    assert host["vendors"]["intel"]["pci"] == 3
    assert host["vendors"]["intel"]["render_nodes"] == [
        "/dev/dri/renderD128",
        "/dev/dri/renderD129",
        "/dev/dri/renderD130",
    ]


def test_an_nvidia_card_is_found_on_the_pci_bus(tmp_path):
    _pci(tmp_path, "0000:01:00.0", "0x10de", "0x030000")
    (tmp_path / "module" / "nvidia").mkdir(parents=True)
    host = read(tmp_path)
    assert host["vendors"]["nvidia"]["pci"] == 1
    assert host["nvidia_module"] is True


def test_wsl_says_nothing(tmp_path):
    """WSL2 passes the GPU through /dev/dxg: an empty PCI list there is not "no GPU"."""
    _pci(tmp_path, "0000:01:00.0", "0x1414", "0x030000")
    host = read(tmp_path, release="6.6.114.1-microsoft-standard-WSL2")
    assert host["conclusive"] is False
    assert host["vendors"] == {}


def test_a_mac_and_an_unreadable_sysfs_say_nothing(tmp_path):
    assert read(tmp_path, system="Darwin")["conclusive"] is False
    assert read(tmp_path / "missing")["conclusive"] is False


def test_a_conclusive_read_with_no_gpu_is_a_real_no(tmp_path):
    _pci(tmp_path, "0000:09:00.0", "0x1a03", "0x030000")
    host = read(tmp_path)
    assert host["conclusive"] is True and host["vendors"] == {}


def test_an_unreadable_display_vendor_is_unknown(tmp_path):
    address = "0000:03:00.0"
    _pci(tmp_path, address, "0x10de", "0x030200")
    (tmp_path / "bus" / "pci" / "devices" / address / "vendor").unlink()
    assert read(tmp_path)["conclusive"] is False


# ---------------------------------------------------------------------------
# What a grant becomes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("count", "docker_count"), [(1, 1), ("all", -1)])
def test_an_nvidia_grant_is_one_device_request(count, docker_count):
    kwargs = gpu.docker_kwargs({**NVIDIA, "count": count}, NVIDIA_HOST)
    (request,) = kwargs["device_requests"]
    assert request["Driver"] == "nvidia"
    assert request["Count"] == docker_count
    assert request["Capabilities"] == [["gpu"]]
    assert kwargs["devices"] == []


def test_an_nvidia_grant_goes_ahead_when_the_read_says_nothing():
    """WSL with Docker Desktop: Docker gives the clear error at start if it cannot."""
    assert gpu.docker_kwargs(NVIDIA, UNKNOWN_HOST)["device_requests"]


def test_amd_gets_only_its_own_render_nodes_and_never_a_card(tmp_path):
    watchtower(tmp_path)
    _pci(tmp_path, "0000:03:00.0", "0x1002", "0x030000")
    _render(tmp_path, 131, "0x1002")
    _render(tmp_path, 132, "0x1002")
    _card(tmp_path, 1, "0x1002")
    host = read(tmp_path)
    one = gpu.docker_kwargs({"vendor": "amd", "count": 1, "rocm": False}, host)
    assert one == {"device_requests": [], "devices": ["/dev/dri/renderD131:/dev/dri/renderD131:rwm"]}
    every = gpu.docker_kwargs({"vendor": "amd", "count": "all", "rocm": False}, host)["devices"]
    assert every == ["/dev/dri/renderD131:/dev/dri/renderD131:rwm", "/dev/dri/renderD132:/dev/dri/renderD132:rwm"]
    assert not any("card" in d for d in every)


def test_rocm_adds_kfd_and_is_refused_without_it(tmp_path):
    _pci(tmp_path, "0000:03:00.0", "0x1002", "0x030000")
    _render(tmp_path, 128, "0x1002")
    rocm = {"vendor": "amd", "count": 1, "rocm": True}
    with pytest.raises(gpu.GpuRefused, match="/dev/kfd"):
        gpu.docker_kwargs(rocm, read(tmp_path))
    (tmp_path / "class" / "kfd" / "kfd").mkdir(parents=True)
    assert "/dev/kfd:/dev/kfd:rwm" in gpu.docker_kwargs(rocm, read(tmp_path))["devices"]


def test_a_render_node_past_the_ceiling_is_never_passed(tmp_path):
    _pci(tmp_path, "0000:03:00.0", "0x8086", "0x030000")
    _render(tmp_path, 136, "0x8086")
    with pytest.raises(gpu.GpuRefused, match="renderD128 to renderD135"):
        gpu.docker_kwargs({"vendor": "intel", "count": 1, "rocm": False}, read(tmp_path))


def test_all_stops_at_the_ceiling(tmp_path):
    _pci(tmp_path, "0000:03:00.0", "0x8086", "0x030000")
    _render(tmp_path, 135, "0x8086")
    _render(tmp_path, 136, "0x8086")
    devices = gpu.docker_kwargs({"vendor": "intel", "count": "all", "rocm": False}, read(tmp_path))["devices"]
    assert devices == ["/dev/dri/renderD135:/dev/dri/renderD135:rwm"]


def test_a_conclusive_read_without_the_vendor_refuses(tmp_path):
    with pytest.raises(gpu.GpuRefused, match=r"no AMD GPU .*\(it sees: Intel\)"):
        gpu.docker_kwargs({"vendor": "amd", "count": 1, "rocm": False}, read(watchtower(tmp_path)))


def test_a_dri_vendor_needs_a_conclusive_read():
    with pytest.raises(gpu.GpuRefused, match="cannot pick"):
        gpu.docker_kwargs({"vendor": "intel", "count": 1, "rocm": False}, UNKNOWN_HOST)


def test_no_grant_gives_nothing_and_the_void_stamp():
    assert gpu.docker_kwargs(None) == {"device_requests": [], "devices": []}
    assert gpu.env_for(None) == {"NVIDIA_VISIBLE_DEVICES": "void"}
    assert gpu.env_for(NVIDIA) == {}
    # An Intel grant holds no NVIDIA GPU: the stamp stays.
    assert gpu.env_for({"vendor": "intel", "count": 1, "rocm": False}) == {"NVIDIA_VISIBLE_DEVICES": "void"}


def _catalog(services: dict[str, dict]):
    return patch.object(catalog, "get_service", side_effect=lambda slug: services.get(slug))


MINER = {"slug": "gpuminer", "name": "GPU Miner", "requirements": {"gpu": True}}
MINER_IMAGE = "example/miner:1@sha256:" + "a" * 64
MINER["docker"] = {"image": MINER_IMAGE, "runtime": "runc", "gpu": {"vendor": "nvidia"}}


def test_only_a_catalog_slug_gets_a_grant():
    with _catalog({"gpuminer": MINER, "custom-gpuminer": MINER}):
        assert gpu.grant("gpuminer") == NVIDIA
        assert gpu.grant("custom-gpuminer") is None, "a custom service never gets a GPU"
        assert gpu.grant("unknown") is None
        assert gpu.grant(None) is None


# ---------------------------------------------------------------------------
# The deploy: negative controls that fail on a worker without the grant
# ---------------------------------------------------------------------------


def _deploy(slug: str, services: dict[str, dict], host: dict = NVIDIA_HOST, image: str = MINER_IMAGE, **kwargs) -> dict:
    captured: dict = {}

    def fake_run(**kw):
        captured.update(kw)
        return MagicMock(short_id="abc123", id="abc123")

    client = MagicMock()
    client.containers.run.side_effect = fake_run
    client.containers.get.side_effect = orchestrator.NotFound("nope")
    with (
        patch.object(orchestrator, "_get_client", return_value=client),
        _catalog(services),
        patch.object(orchestrator, "get_service", side_effect=services.get),
        patch.object(gpu, "host_gpus", return_value=host),
    ):
        orchestrator.deploy_raw(slug=slug, image=image, **kwargs)
    return captured


def test_a_gpu_slug_is_created_with_its_gpu():
    run = _deploy("gpuminer", {"gpuminer": MINER})
    (request,) = run["device_requests"]
    assert request["Driver"] == "nvidia"
    assert "NVIDIA_VISIBLE_DEVICES" not in run["environment"]


def test_a_slug_without_gpu_gets_none_even_when_another_declares_one():
    run = _deploy("plain", {"gpuminer": MINER, "plain": {"slug": "plain", "docker": {"image": "x"}}})
    assert run["device_requests"] is None
    assert run["environment"]["NVIDIA_VISIBLE_DEVICES"] == "void"


def test_a_custom_service_gets_the_void_stamp_and_no_gpu():
    run = _deploy("custom-gpuminer", {"custom-gpuminer": MINER}, env={"A": "1"})
    assert run["device_requests"] is None
    assert run["environment"] == {"A": "1", "NVIDIA_VISIBLE_DEVICES": "void"}


def test_an_intel_grant_merges_its_render_node_with_the_catalog_devices(tmp_path):
    intel = {**MINER, "docker": {**MINER["docker"], "gpu": {"vendor": "intel"}}}
    run = _deploy("gpuminer", {"gpuminer": intel}, host=read(watchtower(tmp_path)), devices=["/dev/net/tun"])
    assert run["devices"] == ["/dev/net/tun", "/dev/dri/renderD128:/dev/dri/renderD128:rwm"]
    assert run["device_requests"] is None


def test_a_proxied_copy_of_a_gpu_slug_is_refused_before_anything_runs():
    with (
        patch.object(orchestrator.route_gate, "check"),
        pytest.raises(orchestrator.ContainerRuntimeError, match="proxied copy does not get"),
    ):
        _deploy("gpuminer", {"gpuminer": MINER}, network_mode="container:abc", name="cashpilot-gpuminer-p1")


def test_a_machine_without_the_vendor_is_refused_before_the_pull(tmp_path):
    client = MagicMock()
    with (
        patch.object(orchestrator, "_get_client", return_value=client),
        _catalog({"gpuminer": MINER}),
        patch.object(orchestrator, "get_service", return_value=MINER),
        patch.object(gpu, "host_gpus", return_value=read(watchtower(tmp_path))),
        pytest.raises(orchestrator.ContainerRuntimeError, match=r"no NVIDIA GPU .*not touched"),
    ):
        orchestrator.deploy_raw(slug="gpuminer", image=MINER_IMAGE)
    client.images.pull.assert_not_called()
    client.containers.run.assert_not_called()


# ---------------------------------------------------------------------------
# The worker API
# ---------------------------------------------------------------------------


def test_a_request_cannot_set_an_nvidia_variable():
    spec = worker_api.DeploySpec(image="example/miner:1", env={"nvidia_visible_devices": "all"})
    with pytest.raises(HTTPException) as exc:
        worker_api._validate_deploy_spec(spec, "plain")
    assert exc.value.status_code == 403
    assert "NVIDIA_" in exc.value.detail


@pytest.mark.parametrize(
    ("image", "instance", "status", "detail"),
    [(MINER_IMAGE, 2, 400, "one copy"), ("example/other:1", 1, 403, "catalog pins")],
)
@pytest.mark.asyncio
async def test_worker_deploy_checks_gpu_image_and_instance_before_start(image, instance, status, detail):
    spec = worker_api.DeploySpec(image=image, instance=instance)
    with (
        _catalog({"gpuminer": MINER}),
        patch.object(orchestrator, "get_service", return_value=MINER),
        patch.object(worker_api, "_verify_api_key"),
        patch.object(orchestrator, "proxy_policy_current", return_value=None),
        patch.object(gpu, "host_gpus", return_value=NVIDIA_HOST),
        patch.object(worker_api, "_deploy_direct", side_effect=AssertionError("should refuse before deployment")),
        pytest.raises(HTTPException, match=detail) as exc,
    ):
        await worker_api.api_deploy_container(MagicMock(), "gpuminer", spec)
    assert exc.value.status_code == status


@pytest.mark.asyncio
async def test_ui_refuses_gpu_deploy_when_worker_catalog_lacks_the_grant():
    worker = {"system_info": json.dumps({"features": ["gpu_grant"], "gpu_grants": {}})}
    with (
        _catalog({"gpuminer": MINER}),
        patch.object(main, "_resolve_worker_id", AsyncMock(return_value=1)),
        patch.object(main, "_device_names", AsyncMock(return_value=("box", []))),
        patch.object(main.database, "get_deployment_spec", AsyncMock(return_value=None)),
        patch.object(main.database, "get_worker", AsyncMock(return_value=worker)),
        pytest.raises(HTTPException, match="catalog") as exc,
    ):
        await main._deploy("gpuminer", main.DeployRequest(), 1)
    assert exc.value.status_code == 409


def test_the_worker_refuses_a_gpu_its_machine_does_not_have(tmp_path):
    spec = worker_api.DeploySpec(image=MINER_IMAGE)
    with (
        _catalog({"gpuminer": MINER}),
        patch.object(orchestrator, "get_service", return_value=MINER),
        patch.object(gpu, "host_gpus", return_value=read(watchtower(tmp_path))),
        patch.object(orchestrator, "proxy_policy_current", return_value=None),
        pytest.raises(HTTPException) as exc,
    ):
        worker_api._validate_gpu("gpuminer", spec)
    assert exc.value.status_code == 409
    assert "no NVIDIA GPU" in exc.value.detail and "Intel" in exc.value.detail


def test_the_worker_refuses_a_gpu_while_the_proxy_policy_is_old():
    fix = {"release": "v9", "command": "c", "url": "u", "recreate": "r"}
    spec = worker_api.DeploySpec(image=MINER_IMAGE)
    with (
        _catalog({"gpuminer": MINER}),
        patch.object(orchestrator, "get_service", return_value=MINER),
        patch.object(orchestrator, "proxy_policy_current", return_value=False),
        patch.object(orchestrator, "proxy_policy_fix", return_value=fix),
        pytest.raises(HTTPException) as exc,
    ):
        worker_api._validate_gpu("gpuminer", spec)
    assert exc.value.status_code == 409
    assert "socket proxy" in exc.value.detail
    # The control: a slug without a grant never asks the proxy.
    with _catalog({}), patch.object(orchestrator, "proxy_policy_current", return_value=False):
        worker_api._validate_gpu("plain", spec)


def test_a_proxied_copy_request_for_a_gpu_slug_is_refused():
    spec = worker_api.ProxiedDeploySpec(
        earner=worker_api.DeploySpec(image="example/miner:1"),
        proxy=worker_api.ProxySpec(kind="socks5", host="proxy.example", port=1080),
    )
    with _catalog({"gpuminer": MINER}), pytest.raises(HTTPException) as exc:
        worker_api._validate_proxied("gpuminer", spec)
    assert exc.value.status_code == 400
    assert exc.value.detail == "A proxied copy gets no GPU"


# ---------------------------------------------------------------------------
# What Docker says at start, and what the user reads
# ---------------------------------------------------------------------------

RECORDED = {
    "nvidia": 'could not select device driver "nvidia" with capabilities: [[gpu]]',
    "cdi": "failed to discover GPU vendor from CDI: no known GPU vendor found",
    "render": 'error gathering device information while adding custom device "/dev/dri/renderD128": '
    "no such file or directory",
    "kfd": 'error gathering device information while adding custom device "/dev/kfd": no such file or directory',
}


def test_each_recorded_docker_gpu_error_gets_its_hint():
    assert "NVIDIA Container Toolkit" in gpu.failure_hint(RECORDED["nvidia"])
    assert "nvidia-ctk runtime configure" in gpu.failure_hint(RECORDED["cdi"])
    assert "render node is gone" in gpu.failure_hint(RECORDED["render"])
    assert "ROCm driver" in gpu.failure_hint(RECORDED["kfd"])
    assert gpu.failure_hint("port is already allocated") == ""


def test_the_deploy_error_carries_the_hint():
    response = MagicMock(status_code=500)
    exc = APIError("500 Server Error", response=response, explanation=RECORDED["nvidia"])
    err = orchestrator._deploy_failure(exc, "The previous container is running again.", "gpuminer")
    assert "NVIDIA Container Toolkit" in str(err)


def test_a_proxy_device_refusal_names_the_policy_fix_when_it_is_old():
    response = MagicMock(status_code=403)
    response.json.return_value = {
        "message": "request denied by sockguard policy",
        "reason": "container create denied: device requests are not allowed",
    }
    exc = APIError("403", response=response, explanation="denied")
    fix = {"release": "v9", "command": "c", "url": "u", "recreate": "r"}
    with (
        patch.object(orchestrator, "proxy_policy_current", return_value=False),
        patch.object(orchestrator, "proxy_policy_fix", return_value=fix),
    ):
        err = orchestrator._deploy_failure(exc, "restored.", "gpuminer")
    assert "behind this worker" in str(err)
    with patch.object(orchestrator, "proxy_policy_current", return_value=True):
        assert "behind this worker" not in str(orchestrator._deploy_failure(exc, "restored.", "gpuminer"))


def test_the_shape_reports_the_gpu_request_driver():
    container = MagicMock()
    container.attrs = {"Config": {}, "HostConfig": {"DeviceRequests": [{"Driver": "nvidia", "Count": 1}]}}
    assert orchestrator._shape(container)["gpu"] == ["nvidia"]
    container.attrs = {"Config": {}, "HostConfig": {"DeviceRequests": None}}
    assert orchestrator._shape(container)["gpu"] == []


def test_runtime_facts_see_the_toolkit_but_never_say_it_is_missing():
    def facts(info):
        client = MagicMock()
        client.info.return_value = info
        orchestrator._gpu_facts = None
        with patch.object(orchestrator.docker, "from_env", return_value=client):
            return orchestrator.gpu_runtime_facts()

    try:
        assert facts({"Runtimes": {"runc": {}, "nvidia": {}}, "DefaultRuntime": "runc"}) == {
            "nvidia_toolkit": True,
            "default_runtime": "runc",
        }
        assert facts({"Runtimes": {"runc": {}}, "DiscoveredDevices": [{"Source": "cdi", "ID": "nvidia.com/gpu=0"}]})[
            "nvidia_toolkit"
        ]
        assert facts({"Runtimes": {"runc": {}}, "DefaultRuntime": "runc"})["nvidia_toolkit"] is None
    finally:
        orchestrator._gpu_facts = None


def test_the_heartbeat_lists_vendors_from_sysfs(tmp_path):
    host = read(watchtower(tmp_path))
    with (
        patch.object(gpu, "host_gpus", return_value=host),
        patch.object(orchestrator, "gpu_runtime_facts", return_value={"default_runtime": "runc"}),
    ):
        info = worker_api._gpu_info()
    assert info["available"] is True
    assert info["detected_by"] == "sysfs"
    assert info["devices"] == ["Intel GPU (3 render nodes)"]
    assert set(info["vendors"]) == {"intel"}
    assert info["nvidia_toolkit"] is None and info["default_runtime"] == "runc"


# ---------------------------------------------------------------------------
# The UI side
# ---------------------------------------------------------------------------


def test_one_copy_per_worker_and_no_proxied_copy():
    assert main.scaling_limit(MINER) == (1, "GPU Miner uses this machine's GPU, which two copies would share.")
    assert proxies.refusal(MINER) == "GPU Miner needs this machine's GPU, which a proxied copy does not get."


def test_compose_export_reserves_the_gpu():
    from app import compose_generator

    nvidia = compose_generator._service_to_compose(MINER, {}, None, None)
    assert nvidia["deploy"]["resources"]["reservations"]["devices"] == [
        {"driver": "nvidia", "count": 1, "capabilities": ["gpu"]}
    ]
    amd = {**MINER, "docker": {**MINER["docker"], "gpu": {"vendor": "amd", "rocm": True}}}
    out = compose_generator._service_to_compose(amd, {}, None, None)
    assert out["devices"] == ["/dev/dri/renderD128:/dev/dri/renderD128", "/dev/kfd:/dev/kfd"]
    assert "deploy" not in out


def _gpu_report(**kw):
    return {"gpu": kw}


@pytest.mark.parametrize(
    ("report", "deployed", "verdicts"),
    [
        # A conclusive read without NVIDIA: the worker refuses too.
        (_gpu_report(available=True, vendors={"intel": {}}), set(), [preflight.EARNS_NOTHING]),
        # The worker could not tell.
        (_gpu_report(available=None, reason="WSL"), set(), [preflight.CHECK_YOURSELF]),
        # NVIDIA present, toolkit unseen: install line.
        (_gpu_report(available=True, vendors={"nvidia": {}}, nvidia_toolkit=None), set(), [preflight.CHECK_YOURSELF]),
        # NVIDIA present, toolkit seen: nothing to say.
        (_gpu_report(available=True, vendors={"nvidia": {}}, nvidia_toolkit=True), set(), []),
        # Another GPU miner already runs there.
        (
            _gpu_report(available=True, vendors={"nvidia": {}}, nvidia_toolkit=True),
            {"othergpu"},
            [preflight.REDUCED],
        ),
    ],
)
def test_preflight_reads_the_workers_gpu_report(report, deployed, verdicts):
    other = {**MINER, "slug": "othergpu", "name": "Other Miner"}
    with patch.object(catalog, "get_service", side_effect=lambda s: {"othergpu": other}.get(s)):
        found = preflight._gpu_findings(MINER, report, deployed)
    assert [f["verdict"] for f in found] == verdicts
    if verdicts == [preflight.REDUCED]:
        assert "Other Miner" in found[0]["message"]
    if (
        report["gpu"].get("nvidia_toolkit") is None
        and verdicts == [preflight.CHECK_YOURSELF]
        and "vendors" in report["gpu"]
    ):
        assert "nvidia-ctk" in found[0]["message"]


def test_a_tracked_only_gpu_entry_keeps_the_old_message():
    tracked = {"slug": "salad", "requirements": {"gpu": True}, "docker": {"image": ""}}
    (finding,) = preflight._gpu_findings(tracked, _gpu_report(available=True, vendors={}), set())
    assert finding == {"verdict": preflight.CHECK_YOURSELF, "message": preflight._GPU_CHECK_YOURSELF}


@pytest.mark.parametrize(("nodes", "reason"), [([], "render node"), (["/dev/dri/renderD128"], "/dev/kfd")])
def test_preflight_warns_when_amd_has_no_usable_device(nodes, reason):
    miner = {**MINER, "docker": {**MINER["docker"], "gpu": {"vendor": "amd", "rocm": True}}}
    report = _gpu_report(available=True, vendors={"amd": {"render_nodes": nodes, "kfd": False}})
    result = preflight.assess(miner, system_info=report)
    (finding,) = result["findings"]
    assert finding["verdict"] == preflight.EARNS_NOTHING
    assert reason in finding["message"]
    assert "refuse this deploy" in result["summary"]


def test_preflight_without_a_worker_does_not_claim_gpu_sharing():
    with _catalog({"othergpu": {**MINER, "slug": "othergpu"}}):
        result = preflight.assess(MINER, already_deployed_slugs={"othergpu"})
    assert not any("shares the GPU" in finding["message"] for finding in result["findings"])


def test_drift_leaves_gpu_devices_alone_and_flags_a_missing_gpu():
    intel = {**MINER, "docker": {**MINER["docker"], "gpu": {"vendor": "intel"}}}
    base = {"devices": ["/dev/dri/renderD128"], "gpu": [], "cap_add": [], "network_mode": "bridge"}
    assert not [f for f in drift.container_drift(intel, base, None) if "device" in f or "GPU" in f]
    # The same node on a service with no grant is extra.
    plain = {"slug": "plain", "docker": {"image": "x"}}
    assert any("still has device" in f for f in drift.container_drift(plain, base, None))
    # The grant exists, the container has neither the request nor the node.
    bare = {**base, "devices": []}
    assert "missing GPU, which the catalog now passes in" in drift.container_drift(MINER, bare, None)
    assert "missing GPU, which the catalog now passes in" not in drift.container_drift(
        MINER, {**bare, "gpu": ["nvidia"]}, None
    )
    # An older worker sends no "gpu" list: nothing is claimed.
    old = {k: v for k, v in bare.items() if k != "gpu"}
    assert "missing GPU, which the catalog now passes in" not in drift.container_drift(MINER, old, None)


def test_the_drift_fingerprint_of_an_entry_without_gpu_is_unchanged():
    plain = {"slug": "plain", "docker": {"image": "x"}}
    with_gpu = {"slug": "plain", "docker": {"image": "x", "gpu": {"vendor": "nvidia"}}}
    assert drift.catalog_fingerprint(plain) != drift.catalog_fingerprint(with_gpu)
    # The value fixed before the GPU grant existed: an "Ignore" made then still holds.
    assert drift.catalog_fingerprint(plain) == "80a78e6a8ec77667"
