"""scripts/cashpilot-vm: the pins it carries and the fence it renders.

The script runs as root on the user's host, so these tests only source it
and call its pure parts with the host's facts stubbed. The real proof (a
guest that cannot reach the LAN, red then green) is in docs/secure-vm.md.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "cashpilot-vm"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _pin(name: str) -> str:
    match = re.search(rf"^readonly {name}=(\S+)$", SCRIPT.read_text(), re.MULTILINE)
    assert match, name
    return match.group(1)


def _run(body: str) -> str:
    """Source the script with stubbed host facts, then run ``body``."""
    prelude = f"""
set -euo pipefail
source {SCRIPT}
NET_BASE=10.213.0; derive_net
UI_IP=192.168.1.50; UI_PORT=8080; HOST_PORT=18081
STATE=$(mktemp -d)/cashpilot-vm; mkdir -p "$STATE"
host_addrs() {{ printf '%s\\n' 192.168.1.10 100.101.102.103; }}
host_connected_public() {{ echo 203.0.113.0/24; }}
egress_ip() {{ echo 198.51.100.7; }}
"""
    out = subprocess.run(["bash", "-c", prelude + body], capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_compose_pin_matches_the_worker_compose_file():
    # The guest downloads docker-compose.worker.yml from the release tag and
    # refuses it unless it hashes to this pin. Change both together.
    actual = hashlib.sha256((ROOT / "docker-compose.worker.yml").read_bytes()).hexdigest()
    assert _pin("COMPOSE_SHA256") == actual, (
        "docker-compose.worker.yml changed: set COMPOSE_SHA256 in scripts/cashpilot-vm to " + actual
    )


def test_image_and_gvisor_are_pinned_by_full_checksums():
    assert re.fullmatch(r"[0-9a-f]{128}", _pin("IMAGE_SHA512_AMD64"))
    assert re.fullmatch(r"[0-9a-f]{128}", _pin("GVISOR_SHA512_X86_64"))
    assert re.fullmatch(r"\d{8}-\d+", _pin("IMAGE_SERIAL"))
    assert "latest" not in _pin("GVISOR_RELEASE")


def _forward_rules(rules: str) -> list[str]:
    return [line for line in rules.splitlines() if line.startswith("-A FORWARD")]


def test_fence_drops_everything_private_and_the_hosts_own_addresses():
    rules = _run("render_ns_rules")
    fwd = _forward_rules(rules)
    drops = {re.search(r"-d (\S+)", r).group(1) for r in fwd if r.endswith("-j DROP")}
    for cidr in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "100.64.0.0/10",
        "169.254.0.0/16",
        "127.0.0.0/8",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "0.0.0.0/8",
    ):
        assert cidr in drops, cidr
    # The host's own addresses, its public connected subnet and the home's IP.
    for cidr in ("192.168.1.10/32", "100.101.102.103/32", "203.0.113.0/24", "198.51.100.7/32"):
        assert cidr in drops, cidr
    # Default policies drop; only OUTPUT from the namespace itself is open.
    assert ":FORWARD DROP [0:0]" in rules
    assert ":INPUT DROP [0:0]" in rules


def test_fence_order_puts_the_two_holes_before_the_drops_and_the_internet_last():
    fwd = _forward_rules(_run("render_ns_rules"))
    names = [re.search(r"cpvm:(\S+)", r).group(1) for r in fwd]
    assert names[0] == "reply"
    assert names[1:3] == ["worker-in", "ui"]
    assert names[-1] == "internet"
    ui = fwd[2]
    # The UI hole is one TCP port on one address, nothing wider.
    assert "-d 192.168.1.50/32 -p tcp -m tcp --dport 8080" in ui
    # Replies pass only in the reply direction, so a connection the guest
    # opened meets the drops on every packet.
    assert "--ctdir REPLY" in fwd[0]
    # The worker port is reachable only after the namespace's own DNAT.
    assert "--ctstate DNAT" in fwd[1]
    # Every rule has a name the guard can check.
    assert len(names) == len(set(names))


def test_every_rule_carries_a_cpvm_comment_the_guard_checks():
    rules = _run("render_ns_rules")
    for line in rules.splitlines():
        if line.startswith("-A "):
            assert "--comment cpvm:" in line, line


@pytest.mark.parametrize(
    ("ip", "public"),
    [
        ("8.8.8.8", True),
        ("198.51.100.7", True),
        ("192.168.1.1", False),
        ("10.1.2.3", False),
        ("100.100.100.100", False),
        ("169.254.169.254", False),
        ("172.31.0.1", False),
        ("224.0.0.1", False),
        ("256.1.1.1", False),
        ("not-an-ip", False),
    ],
)
def test_is_public_ipv4(ip, public):
    out = _run(f"is_public_ipv4 {ip} && echo yes || echo no").strip()
    assert out == ("yes" if public else "no")


@pytest.mark.parametrize(
    ("a", "b", "overlap"),
    [
        ("10.213.0.0/29", "10.0.0.0/8", True),
        ("10.213.0.0/29", "10.213.0.4/30", True),
        ("10.213.0.0/29", "10.213.1.0/24", False),
        ("10.213.0.0/29", "192.168.1.0/24", False),
    ],
)
def test_cidr_overlap(a, b, overlap):
    out = _run(f"cidr_overlap {a} {b} && echo yes || echo no").strip()
    assert out == ("yes" if overlap else "no")


def test_state_folder_must_end_in_cashpilot_vm():
    # remove deletes it with rm -rf, so a stray CPVM_HOME must never reach it.
    out = subprocess.run(
        ["bash", str(SCRIPT), "version"],
        env={"PATH": "/usr/bin:/bin", "CPVM_HOME": "/"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode != 0
    assert "must be an absolute path ending in /cashpilot-vm" in out.stderr


def test_ui_url_parsing():
    out = _run(
        'parse_url http://ui.lan:8088; echo "$UI_SCHEME $UI_HOST $UI_PORT";'
        'parse_url https://cashpilot.example.com; echo "$UI_SCHEME $UI_HOST $UI_PORT"'
    )
    assert out.split("\n")[:2] == ["http ui.lan 8088", "https cashpilot.example.com 443"]


@pytest.mark.skipif(sys.platform != "linux", reason="checks against a Linux userland")
def test_no_function_shadows_a_command():
    # A function named like a command replaces it for the whole script. One
    # called cut() once took the guest's link down wherever the script meant
    # coreutils cut, and left the pinned guest host key empty.
    names = re.findall(r"^([a-z_][a-z0-9_]*)\(\) \{", SCRIPT.read_text(), re.MULTILINE)
    assert names
    shadowed = [
        n for n in names if shutil.which(n, path="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
    ]
    assert shadowed == []


@pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="needs ssh-keygen")
def test_the_guests_first_boot_script_is_valid_bash(tmp_path):
    # The provisioning script sits in an unquoted heredoc, so one missing
    # backslash runs a command on the host or breaks the guest's first boot.
    out = tmp_path / "seed"
    out.mkdir()
    body = f"""
UI_HOST=192.168.1.50; UI_URL=http://192.168.1.50:8080; WORKER_NAME=nas-secure-vm; HOST_WORKER=nas
WORKER_URL=http://192.168.1.10:18081; REF=v1.2.3
ssh-keygen -q -t ed25519 -N "" -f "$STATE/ssh/id_ed25519" 2>/dev/null || {{ mkdir -p "$STATE/ssh"; ssh-keygen -q -t ed25519 -N "" -f "$STATE/ssh/id_ed25519"; }}
ssh-keygen -q -t ed25519 -N "" -f "$STATE/ssh/guest_host_ed25519"
mkfs.vfat() {{ touch "${{@: -2:1}}"; }}; chown() {{ :; }}
mcopy() {{ shift 2; for f in "$@"; do [ "$f" = :: ] || cp "$f" {out}/; done; }}
write_seed 0123456789abcdef0123
"""
    _run(body)
    import yaml

    data = yaml.safe_load((out / "user-data").read_text().split("\n", 1)[1])
    files = {f["path"]: f["content"] for f in data["write_files"]}
    provision = files["/usr/local/sbin/cashpilot-vm-provision"]
    check = subprocess.run(["bash", "-n"], input=provision, capture_output=True, text=True, check=False)
    assert check.returncode == 0, check.stderr
    # Runtime values stay for the guest to expand, never the host.
    assert "$(date -Is)" in provision
    assert '"$@"' in provision
    # Nothing is pulled unpinned: the gVisor check reuses the worker's image.
    assert "hello-world" not in provision
    assert ":latest" not in provision


@pytest.mark.parametrize(
    ("use", "pool_dir", "want"),
    [
        # The share stays on its pool: write to the pool, past the FUSE layer.
        ("only", True, "cache/domains/cashpilot-vm"),
        ("prefer", True, "cache/domains/cashpilot-vm"),
        # The mover moves files of a "yes" share to the array: go through /mnt/user.
        ("yes", True, "user/domains/cashpilot-vm"),
        ("no", False, "user/domains/cashpilot-vm"),
        # The pool holds no domains folder yet: never make one beside the share.
        ("only", False, "user/domains/cashpilot-vm"),
    ],
)
def test_the_guest_disk_on_unraid_follows_the_domains_share(tmp_path, use, pool_dir, want):
    (tmp_path / "user/domains").mkdir(parents=True)
    if pool_dir:
        (tmp_path / "cache/domains").mkdir(parents=True)
    cfg = tmp_path / "domains.cfg"
    # Unraid writes its .cfg files with CRLF line ends.
    cfg.write_bytes(f'shareUseCache="{use}"\r\nshareCachePool="cache"\r\nshareCachePool2=""\r\n'.encode())
    assert _run(f"unraid_home {cfg} {tmp_path}").strip() == f"{tmp_path}/{want}"


def test_no_domains_share_on_unraid_means_no_disk(tmp_path):
    assert _run(f"unraid_home {tmp_path}/missing.cfg {tmp_path}").strip() == ""
