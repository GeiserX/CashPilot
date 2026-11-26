from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from app import catalog, orchestrator, preflight

XMRIG = Path("xmrig.yml")
WALLET = "4" + "A" * 94


@pytest.fixture
def xmrig():
    service = catalog.get_service("xmrig")
    assert service is not None
    return deepcopy(service)


def test_mining_pool_entries_do_not_require_a_miner_fee():
    for slug in ("ocean", "supportxmr"):
        service = catalog.get_service(slug)
        assert service is not None
        assert catalog.mining_facts(service) is None


@pytest.mark.parametrize("fee", [None, True, "1", -1, 11, float("nan"), float("inf")])
def test_invalid_or_missing_miner_developer_fee(xmrig, fee):
    if fee is None:
        del xmrig["mining"]["dev_fee_percent"]
    else:
        xmrig["mining"]["dev_fee_percent"] = fee
    assert any("mining.dev_fee_percent" in error for error in catalog._validate(xmrig, XMRIG))


def test_zero_is_a_valid_fee_when_stated(xmrig):
    xmrig["mining"]["dev_fee_percent"] = 0
    assert catalog._validate(xmrig, XMRIG) == []


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("hardware", "cpu", "unknown mining fields"),
        ("dev_fee_source", "http://example.com", "mining.dev_fee_source"),
        ("dev_fee_source", "https://[", "mining.dev_fee_source"),
        ("pool_fee_note", 0, "mining.pool_fee_note"),
    ],
)
def test_invalid_miner_facts_fail_validation(xmrig, field, value, error):
    xmrig["mining"][field] = value
    assert any(error in issue for issue in catalog._validate(xmrig, XMRIG))


def test_miner_requires_fee_hosting_note_and_pinned_images(xmrig):
    without_fee = deepcopy(xmrig)
    del without_fee["mining"]
    assert any("mining must be a mapping" in error for error in catalog._validate(without_fee, XMRIG))

    del xmrig["requirements"]["hosting_note"]
    xmrig["docker"]["image_by_arch"] = {"arm64": "example/miner:1.2.3"}
    errors = catalog._validate(xmrig, XMRIG)
    assert any("hosting_note" in error for error in errors)
    assert any("must pin each image" in error for error in errors)


def test_xmrig_uses_the_published_image_pin(xmrig):
    # A bump PR advances the build pin before main can publish its image.
    # The catalog keeps pulling its published digest until that update.
    image = re.fullmatch(
        r"drumsergio/cashpilot-xmrig:(\d+\.\d+\.\d+)-r[1-9]\d*@sha256:[0-9a-f]{64}",
        xmrig["docker"]["image"],
    )
    assert image is not None
    assert xmrig["mining"]["dev_fee_source"].endswith(f"/v{image[1]}/src/donate.h")
    assert xmrig["payout"]["address_env"] == "WALLET"
    assert "accrual" not in xmrig["collector"]


def test_xmrig_command_sets_the_fee_and_does_not_allow_wallet_flags(xmrig):
    docker = xmrig["docker"]
    wallet_pattern = next(field["pattern"] for field in docker["env"] if field["key"] == "WALLET")
    assert re.fullmatch(wallet_pattern, WALLET)
    injected = f"{WALLET} --donate-level=9"
    assert not re.fullmatch(wallet_pattern, injected)
    args = orchestrator._catalog_command_tokens(docker["command"], {"WALLET": injected})
    assert "--donate-level=9" not in args
    assert "--donate-level=1" in args
    assert "--randomx-wrmsr=-1" in args
    assert "--randomx-no-numa" in args
    assert "--http-host=127.0.0.1" in args
    assert "--http-port=18088" in args


@pytest.mark.parametrize("network_type", ["hosting", "residential", None])
def test_hosting_note_is_advice_for_a_reported_hosting_exit(xmrig, network_type):
    result = preflight.assess(xmrig, system_info={"egress_network_type": network_type})
    note = {
        "verdict": preflight.CHECK_YOURSELF,
        "message": xmrig["requirements"]["hosting_note"],
        "kind": "hosting_note",
    }
    assert (note in result["findings"]) is (network_type == "hosting")
    assert result["blocking"] is False


def test_a_second_miner_on_the_same_worker_shares_cpu(xmrig):
    result = preflight.assess(xmrig, already_deployed_slugs={"xmrig"})
    messages = [f["message"] for f in result["findings"]]
    assert any("shares its CPU" in message for message in messages)
    assert not any("shares the same connection" in message for message in messages)


@pytest.fixture
def unmineable():
    service = catalog.get_service("unmineable")
    assert service is not None
    return deepcopy(service)


def _user_token(service, env):
    args = orchestrator._catalog_command_tokens(service["docker"]["command"], env)
    [user] = [arg for arg in args if arg.startswith("--user=")]
    return args, user


def test_every_unmineable_worker_carries_the_referral_code(unmineable):
    code = unmineable["referral"]["code"]
    assert code == "awk6-j1z0"
    assert unmineable["referral"]["program"] is True
    assert code in unmineable["referral"]["signup_url"]
    args, user = _user_token(unmineable, {"PAYOUT_COIN": "SHIB", "WALLET": "0x" + "ab" * 20, "WORKER_NAME": "rig-1"})
    assert user == f"--user=SHIB:0x{'ab' * 20}.rig-1#{code}"
    assert "--url=stratum+ssl://rx.unmineable.com:443" in args
    assert "--algo=rx/0" in args
    assert "--donate-level=1" in args
    assert unmineable["docker"]["image"] == catalog.get_service("xmrig")["docker"]["image"]
    assert "#awk6-j1z0" in unmineable["mining"]["pool_fee_note"]
    guide = (Path(__file__).parents[1] / "docs/guides/unmineable.md").read_text()
    assert f"#{code}" in guide and "0.25%" in guide and "0.75%" in guide


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("WALLET", f"{WALLET}.other#someone-else"),
        ("WALLET", f"{WALLET}#someone-else"),
        ("WALLET", f"XMR:{WALLET}"),
        ("WALLET", f"{WALLET} --url=stratum+tcp://evil.example:3333"),
        ("WORKER_NAME", "rig#someone-else"),
        ("WORKER_NAME", "rig.two"),
        ("PAYOUT_COIN", "XMR:other"),
        ("PAYOUT_COIN", "X"),
    ],
)
def test_no_field_can_replace_or_drop_the_referral_code(unmineable, key, value):
    pattern = next(field["pattern"] for field in unmineable["docker"]["env"] if field["key"] == key)
    assert not re.fullmatch(pattern, value)


def test_unmineable_has_no_fixed_minimum_or_chain(unmineable):
    # One entry pays in many coins: the collector reports each coin's threshold.
    assert "min_amount" not in unmineable["cashout"]
    assert "chain" not in unmineable["payout"]
    assert "currency" not in unmineable["payment"]
    assert unmineable["payout"]["address_env"] == "WALLET"
    assert unmineable["collector"]["accrual"] == "pool"


XMRIG_BINARY = "/usr/local/bin/xmrig"
SYSFS_CPU = "/sys/devices/system/cpu"
# What sysfs shows for cpu0 of an i5-14500: (level, size) per cache index.
CACHES_SHOWN = {
    "cpu0/cache/index0": ("1", "48K"),
    "cpu0/cache/index1": ("1", "32K"),
    "cpu0/cache/index2": ("2", "1280K"),
    "cpu0/cache/index3": ("3", "24576K"),
}


@pytest.fixture(params=["xmrig", "unmineable"])
def cpu_miner(request):
    """Every entry that runs the CashPilot XMRig image with a CPU_PERCENT field."""
    service = catalog.get_service(request.param)
    assert service is not None
    return deepcopy(service)


def _xmrig_args(
    entrypoint,
    tmp_path,
    cpu_percent,
    cpus,
    machine="aarch64",
    command=("--url=pool:1", "--no-color"),
    caches=CACHES_SHOWN,
):
    """The arguments XMRig gets when the catalog's entrypoint runs the command.

    The real wrapper runs with a stand-in ``nproc`` that reports ``cpus`` (None:
    nproc fails), a stand-in ``uname -m`` that reports ``machine`` (None: it
    fails), a stand-in for the image's XMRig that prints its arguments, and a
    stand-in for ``/sys/devices/system/cpu`` that holds ``caches``: per cache
    index, its ``level`` and ``size`` file contents (None: no such file).
    """
    sysfs = tmp_path / "sysfs-cpu"
    sysfs.mkdir()
    for index, files in caches.items():
        (sysfs / index).mkdir(parents=True)
        for name, value in zip(("level", "size"), files, strict=True):
            if value is not None:
                (sysfs / index / name).write_text(f"{value}\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stand_ins = {
        "nproc": "exit 1" if cpus is None else f"echo {cpus}",
        "uname": "exit 1" if machine is None else f"echo {machine}",
    }
    for name, body in stand_ins.items():
        (bin_dir / name).write_text(f"#!/bin/sh\n{body}\n")
    fake = tmp_path / "xmrig"
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    for path in (*bin_dir.iterdir(), fake):
        path.chmod(0o755)
    script = entrypoint[2]
    assert script.count(XMRIG_BINARY) == 1
    env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    if cpu_percent is not None:
        env["CPU_PERCENT"] = cpu_percent
    out = subprocess.run(
        [
            *entrypoint[:2],
            script.replace(XMRIG_BINARY, str(fake)).replace(SYSFS_CPU, str(sysfs)),
            *entrypoint[3:],
            *command,
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return out.stdout.splitlines()


def _xmrig_x86_threads(cpus, hint):
    """The thread count XMRig v6.27.0 on x86 derives from a hint, before its CPU cache limit.

    HwlocCpuInfo::threads: round(threads * hint / 100) with C's round (half away
    from zero), at least 1. A hint of 100 or more sets no limit.
    """
    if hint >= 100:
        return cpus
    return max(math.floor(cpus * (hint / 100.0) + 0.5), 1)


ARGS = ["--url=pool:1", "--no-color"]


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
@pytest.mark.parametrize("machine", ["aarch64", "armv8l", None])
@pytest.mark.parametrize(
    ("cpu_percent", "cpus", "threads"),
    [
        # XMRig's arm64 build ignores --cpu-max-threads-hint, so 17% of a
        # 6-core machine started all 6 threads before the wrapper set --threads.
        ("17", 6, 1),
        ("1", 6, 1),
        ("50", 6, 3),
        ("99", 6, 5),
        ("17", 12, 2),
        ("50", 1, 1),
        ("33", 64, 21),
    ],
)
def test_off_x86_cpu_percent_sets_the_threads_xmrig_starts(cpu_miner, tmp_path, machine, cpu_percent, cpus, threads):
    """A share of the CPU threads, rounded down, and never below one."""
    args = _xmrig_args(cpu_miner["docker"]["entrypoint"], tmp_path, cpu_percent, cpus, machine)
    assert args == [*ARGS, f"--threads={threads}"]


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
@pytest.mark.parametrize("cpus", [1, 2, 6, 12, 16, 24, 32, 64, 99, 100])
@pytest.mark.parametrize("cpu_percent", [1, 17, 25, 33, 50, 75, 99])
def test_on_x86_the_last_hint_rounds_to_the_capped_count(cpu_miner, tmp_path, cpu_percent, cpus):
    """On x86 the hint stays, so XMRig keeps its CPU cache limit, but it lands on the rounded-down share.

    --threads there would start more threads than fit the cache: on a 6-core,
    12-thread CPU with 12 MB L3, 75% would start 9 where 100% starts 6.
    """
    args = _xmrig_args(cpu_miner["docker"]["entrypoint"], tmp_path, str(cpu_percent), cpus, "x86_64")
    assert args[:-1] == ARGS
    assert not any(arg.startswith("--threads") for arg in args)
    flag, _, hint = args[-1].partition("=")
    assert flag == "--cpu-max-threads-hint"
    # XMRig keeps the last value of a repeated option (BaseTransform::set).
    assert _xmrig_x86_threads(cpus, int(hint)) == max(cpus * cpu_percent // 100, 1)


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
def test_on_x86_above_100_threads_the_hint_is_too_coarse_so_threads_is_set(cpu_miner, tmp_path):
    assert _xmrig_x86_threads(101, 50) == 51  # 1% steps cannot say 50 of 101
    args = _xmrig_args(cpu_miner["docker"]["entrypoint"], tmp_path, "50", 101, "x86_64")
    assert args == [*ARGS, "--threads=50"]


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
@pytest.mark.parametrize(
    "caches",
    [
        pytest.param({}, id="no-cache-folder"),
        pytest.param({"cpu0/cache/index0": ("1", "48K"), "cpu0/cache/index1": ("1", "32K")}, id="l1-only"),
        pytest.param({"cpu0/cache/index2": ("2", "0K")}, id="l2-size-zero"),
        pytest.param({"cpu0/cache/index2": ("2", None)}, id="l2-no-size"),
        pytest.param({"cpu0/cache/index3": (None, "24576K")}, id="no-level"),
        # The top cache must hold one hash of every algorithm (cn-heavy: 4 MiB,
        # counted from half), or the cache pass starts no thread and XMRig
        # falls back the same way.
        pytest.param({"cpu0/cache/index2": ("2", "4096K")}, id="l2-only"),
        pytest.param({"cpu0/cache/index3": ("3", "0K")}, id="l3-size-zero"),
        pytest.param({"cpu0/cache/index2": ("2", "4096K"), "cpu0/cache/index3": ("3", "1024K")}, id="small-l3"),
        pytest.param({"cpu0/cache/index3": ("3", "2047K")}, id="l3-just-under-2048K"),
        pytest.param({"cpu0/cache/index3": ("3", "2M")}, id="l3-size-not-in-K"),
    ],
)
@pytest.mark.parametrize(("cpu_percent", "cpus", "threads"), [("17", 8, 1), ("50", 8, 4), ("75", 20, 15)])
def test_on_x86_without_an_l3_of_2048k_in_sysfs_threads_is_set(cpu_miner, tmp_path, caches, cpu_percent, cpus, threads):
    """Where XMRig v6.27.0 on x86 finds no cache room for a hash, it ignores the hint.

    HwlocCpuInfo::threads falls back to BasicCpuInfo::threads when hwloc finds no
    L2 or L3 size, or when processTopLevelCache adds no thread: a top cache
    below half a scratchpad (rx/0: 2 MiB, cn-heavy: 4 MiB) holds no hash. The
    fallback starts half the threads for RandomX: 4 of 8 at 17%. hwloc's Linux
    backend reads the sizes from cpuN/cache/indexM/{level,size}, so without an
    L3 of at least 2048K there the cap must come from --threads.
    """
    args = _xmrig_args(cpu_miner["docker"]["entrypoint"], tmp_path, cpu_percent, cpus, "x86_64", caches=caches)
    assert args == [*ARGS, f"--threads={threads}"]


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
@pytest.mark.parametrize(
    "caches",
    [
        pytest.param({"cpu0/cache/index3": ("3", "2048K")}, id="l3-of-2048K"),
        pytest.param({"cpu0/cache/index0": ("1", "48K"), "cpu11/cache/index3": ("3", "24576K")}, id="l3-on-cpu11"),
    ],
)
def test_on_x86_an_l3_of_2048k_on_any_cpu_keeps_the_hint(cpu_miner, tmp_path, caches):
    args = _xmrig_args(cpu_miner["docker"]["entrypoint"], tmp_path, "17", 8, "x86_64", caches=caches)
    assert args[:-1] == ARGS
    assert args[-1].startswith("--cpu-max-threads-hint=")
    assert _xmrig_x86_threads(8, int(args[-1].partition("=")[2])) == 1


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
@pytest.mark.parametrize("machine", ["aarch64", "x86_64"])
@pytest.mark.parametrize(
    ("cpu_percent", "cpus"),
    [
        ("100", 6),  # no cap: XMRig picks the count itself
        (None, 6),
        ("", 6),
        ("0", 6),
        ("abc", 6),
        ("50", None),  # nproc failed: run exactly what the image runs
        ("50", "x"),
    ],
)
def test_the_wrapper_otherwise_runs_xmrig_unchanged(cpu_miner, tmp_path, machine, cpu_percent, cpus):
    assert _xmrig_args(cpu_miner["docker"]["entrypoint"], tmp_path, cpu_percent, cpus, machine) == ARGS


def test_the_wrapper_execs_the_images_own_entrypoint(cpu_miner):
    entrypoint = cpu_miner["docker"]["entrypoint"]
    assert entrypoint[:2] == ["/bin/sh", "-c"]
    assert entrypoint[2].rstrip().endswith(f'exec {XMRIG_BINARY} "$@"')
    dockerfile = (Path(__file__).parent.parent / "images" / "xmrig" / "Dockerfile").read_text()
    assert f'ENTRYPOINT ["{XMRIG_BINARY}"]' in dockerfile
    # The cache check reads the files hwloc 2.x reads (topology-linux.c, look_sysfscpu).
    assert entrypoint[2].count(f"{SYSFS_CPU}/cpu[0-9]*/cache/index[0-9]*/size") == 1
    # The hint stays on the command, so XMRig still gets a limit if the wrapper changes nothing.
    assert "--cpu-max-threads-hint=${CPU_PERCENT}" in cpu_miner["docker"]["command"]


def test_every_entry_with_the_xmrig_image_and_cpu_percent_has_the_wrapper():
    """A new entry on the same image must not bring back the ignored hint."""
    wrapper = catalog.get_service("xmrig")["docker"]["entrypoint"]
    for service in catalog.get_services():
        docker = service.get("docker") or {}
        keys = {field.get("key") for field in docker.get("env") or []}
        if "cashpilot-xmrig" in str(docker.get("image")) and "CPU_PERCENT" in keys:
            assert docker.get("entrypoint") == wrapper, service["slug"]
