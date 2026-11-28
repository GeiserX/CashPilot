"""scripts/cashpilot-vm: the pins it carries and the fence it renders.

The script runs as root on the user's host, so these tests only source it
and call its pure parts with the host's facts stubbed. The real proof (a
guest that cannot reach the LAN, red then green) is in docs/secure-vm.md.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "cashpilot-vm"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _pin(name: str) -> str:
    match = re.search(rf"^readonly {name}=(\S+)$", SCRIPT.read_text(), re.MULTILINE)
    assert match, name
    return match.group(1)


def _run(body: str, *args: str) -> str:
    """Source the script with stubbed host facts, then run ``body`` with ``args`` as $1, $2..."""
    prelude = """
set -euo pipefail
source "$1"; shift
# The real egress_ip, for the tests of its own rules.
eval "orig_$(declare -f egress_ip)"
NET_BASE=10.213.0; derive_net
UI_IP=192.168.1.50; UI_PORT=8080; HOST_PORT=18081
STATE=$(mktemp -d)/cashpilot-vm; mkdir -p "$STATE"
host_addrs() { printf '%s\\n' 192.168.1.10 100.101.102.103; }
host_connected_public() { echo 203.0.113.0/24; }
egress_ip() { echo 198.51.100.7; }
"""
    # mktemp in the script and the prelude writes under a folder that goes with the test.
    with tempfile.TemporaryDirectory() as tmp:
        out = subprocess.run(
            ["bash", "-c", prelude + body, "bash", str(SCRIPT), *args],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "TMPDIR": tmp},
        )
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_compose_pin_matches_the_worker_compose_file():
    # The guest downloads docker-compose.worker.yml from the release tag and
    # refuses it unless it hashes to this pin. Change both together.
    actual = hashlib.sha256((ROOT / "docker-compose.worker.yml").read_bytes()).hexdigest()
    assert _pin("COMPOSE_SHA256") == actual, (
        "docker-compose.worker.yml changed: set COMPOSE_SHA256 in scripts/cashpilot-vm to " + actual
    )


@pytest.mark.skipif(sys.platform != "linux", reason="the release runs GNU sed")
def test_the_release_moves_the_compose_pin_with_the_image_pins(tmp_path):
    # The release bumps the image pins in docker-compose.worker.yml on main
    # after the tag. If the hash did not move with them, the test above would
    # fail on main after every minor release. Run the step's own lines on a copy.
    import yaml

    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text())
    steps = [s for job in wf["jobs"].values() for s in job.get("steps", [])]
    run = next(s["run"] for s in steps if s.get("name") == "Bump the example compose pins to this series")
    lines = run.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip().startswith("HASH=$(sha256sum"))
    end = next(i for i in range(start, len(lines)) if lines[i].strip() == "fi")
    snippet = "\n".join(lines[start : end + 1])
    assert "scripts/cashpilot-vm" in next(ln for ln in lines if ln.strip().startswith("git add"))

    (tmp_path / "scripts").mkdir()
    shutil.copy(SCRIPT, tmp_path / "scripts" / "cashpilot-vm")
    compose = (ROOT / "docker-compose.worker.yml").read_text() + "# moved\n"
    (tmp_path / "docker-compose.worker.yml").write_text(compose)
    out = subprocess.run(["bash", "-euo", "pipefail", "-c", snippet], cwd=tmp_path, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    pinned = re.search(r"^readonly COMPOSE_SHA256=(\w+)$", (tmp_path / "scripts" / "cashpilot-vm").read_text(), re.M)
    assert pinned and pinned.group(1) == hashlib.sha256(compose.encode()).hexdigest()


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
    # The UI hole is one TCP port on one address, from the guest's tap out of
    # the namespace, and it accepts: the whole rule, not a substring of it.
    assert fwd[2] == (
        "-A FORWARD -i cpvm-tap -o cpvm-ns -d 192.168.1.50/32 -p tcp -m tcp --dport 8080 -m comment --comment cpvm:ui -j ACCEPT"
    )
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
    body = """
OUT=$1
UI_HOST=192.168.1.50; UI_URL=http://192.168.1.50:8080; WORKER_NAME=nas-secure-vm; HOST_WORKER=nas
WORKER_URL=http://192.168.1.10:18081; REF=v1.2.3
ssh-keygen -q -t ed25519 -N "" -f "$STATE/ssh/id_ed25519" 2>/dev/null || { mkdir -p "$STATE/ssh"; ssh-keygen -q -t ed25519 -N "" -f "$STATE/ssh/id_ed25519"; }
ssh-keygen -q -t ed25519 -N "" -f "$STATE/ssh/guest_host_ed25519"
mkfs.vfat() { touch "${@: -2:1}"; }; chown() { :; }
mcopy() { shift 2; for f in "$@"; do [ "$f" = :: ] || cp "$f" "$OUT"/; done; }
write_seed 0123456789abcdef0123
"""
    _run(body, str(out))
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
    assert _run('unraid_home "$1" "$2"', str(cfg), str(tmp_path)).strip() == f"{tmp_path}/{want}"


def test_no_domains_share_on_unraid_means_no_disk(tmp_path):
    assert _run('unraid_home "$1" "$2"', str(tmp_path / "missing.cfg"), str(tmp_path)).strip() == ""


def test_the_config_reads_back_exactly_what_install_wrote(tmp_path):
    # load_conf sources the config as bash, so every value must come back as
    # written, and none may run as a command.
    conf = tmp_path / "config"
    out = _run(
        """
CPVM_HOME="/srv/a b/cashpilot-vm" UI_URL='http://ui.lan:8080/$(touch "$2/pwned")' UI_IP=192.168.1.50 UI_PORT=8080 \\
  UI_LOCAL=0 HOST_WORKER="nas 1" WORKER_NAME="nas 1-secure-vm" HOST_PORT=18081 NET_BASE=10.213.0 \\
  VM_RAM_MB=2048 VM_CPUS=2 VM_DISK_GB=20 REF='v1.2.3;id' write_conf >"$1"
unset CPVM_HOME UI_URL HOST_WORKER REF
CONF=$1 load_conf
printf '%s|%s|%s|%s|%s\\n' "$CPVM_HOME" "$STATE" "$UI_URL" "$HOST_WORKER" "$REF"
""",
        str(conf),
        str(tmp_path),
    )
    assert out.strip() == (
        '/srv/a b/cashpilot-vm|/srv/a b/cashpilot-vm|http://ui.lan:8080/$(touch "$2/pwned")|nas 1|v1.2.3;id'
    )
    assert not (tmp_path / "pwned").exists()


def test_state_on_unraid_without_a_domains_share_is_empty():
    # The root file system is in RAM on Unraid: no share and no CPVM_HOME
    # means no disk, never /var/lib.
    out = _run(
        'is_unraid() { true; }; unset CPVM_HOME; set_state; echo "[$STATE]";'
        'is_unraid() { false; }; set_state; echo "[$STATE]";'
        'CPVM_HOME=/srv/x/cashpilot-vm; set_state; echo "[$STATE]"'
    )
    assert out.split() == ["[]", "[/var/lib/cashpilot-vm]", "[/srv/x/cashpilot-vm]"]


@pytest.mark.skipif(sys.platform != "linux", reason="GNU stat")
@pytest.mark.parametrize(
    ("cache_age", "want"),
    [
        (None, "refused"),  # no lookup ever worked: no drop for the home's IP
        (60, "198.51.100.9"),  # fresh
        (1800, "refused"),  # every lookup fails: the address may have changed
    ],
)
def test_the_fence_is_not_written_without_a_current_public_ip(cache_age, want):
    setup = (
        ""
        if cache_age is None
        else f'echo 198.51.100.9 >"$STATE/egress"; touch -d "@$(($(date +%s) - {cache_age}))" "$STATE/egress";'
    )
    out = _run(
        setup
        + "curl() { return 7; }; egress_ip() { orig_egress_ip; };"
        + 'if r=$(render_ns_rules); then grep -o "egress-[0-9.]*" <<<"$r" | cut -d- -f2; else echo refused; fi'
    )
    assert out.strip() == want


def _selftest(guest: str, controls: str, layers_rc: int = 0) -> tuple[int, str]:
    body = f"""
probe_targets() {{ printf '%s\\n' "lan-gateway 192.168.1.1 53" "lan-device 192.168.1.20 22"; }}
run_controls() {{ cat >/dev/null; printf '%b' '{controls}'; }}
run_probes_from_guest() {{
  if [ "$(cat)" = "192.168.1.50 8080" ]; then echo "192.168.1.50 8080 reached"; else printf '%b' '{guest}'; fi
}}
guest_ssh() {{ true; }}
guest_layers() {{ echo "ok    gVisor"; return {layers_rc}; }}
rc=0; selftest_once quiet || rc=1
printf '%s\\n%s' "$rc" "$SELFTEST_LINES"
"""
    rc, lines = _run(body).split("\n", 1)
    return int(rc), lines


def test_selftest_passes_only_on_explicit_blocks():
    live = "192.168.1.1 53 live\\n192.168.1.20 22 live\\n"
    rc, lines = _selftest("192.168.1.1 53 blocked\\n192.168.1.20 22 blocked\\n", live)
    assert rc == 0, lines
    # A target the guest got no result for fails, never passes by default.
    rc, lines = _selftest("192.168.1.1 53 blocked\\n", live)
    assert rc == 1 and "FAIL  lan-device 192.168.1.20:22 no result" in lines
    # The fence drops silently, so a refusal came from past it.
    rc, lines = _selftest("192.168.1.1 53 refused\\n192.168.1.20 22 blocked\\n", live)
    assert rc == 1 and "FAIL  lan-gateway 192.168.1.1:53 answered the guest (refused)" in lines


def test_a_block_without_a_live_control_proves_nothing():
    rc, lines = _selftest(
        "192.168.1.1 53 blocked\\n192.168.1.20 22 blocked\\n", "192.168.1.1 53 live\\n192.168.1.20 22 blocked\\n"
    )
    assert rc == 0
    assert "skip  lan-device 192.168.1.20:22 blocked, but proves nothing" in lines
    assert "ok    lan-device" not in lines


def test_the_saved_selftest_includes_the_layers():
    live = "192.168.1.1 53 live\\n192.168.1.20 22 live\\n"
    rc, lines = _selftest("192.168.1.1 53 blocked\\n192.168.1.20 22 blocked\\n", live, layers_rc=1)
    assert rc == 1 and "ok    gVisor" in lines


@pytest.mark.skipif(sys.platform != "linux", reason="reads /proc")
def test_an_abandoned_red_test_hold_is_not_live():
    out = _run(
        "RUN_DIR=$(mktemp -d); now=$(date +%s);"
        'echo "$$ $now" >"$RUN_DIR/hold"; hold_is_live && echo live || echo gone;'
        'echo "$$ $((now - 3600))" >"$RUN_DIR/hold"; hold_is_live && echo live || echo gone;'
        'sleep 0 & dead=$!; wait; echo "$dead $now" >"$RUN_DIR/hold"; hold_is_live && echo live || echo gone;'
        'echo junk >"$RUN_DIR/hold"; hold_is_live && echo live || echo gone'
    )
    assert out.split() == ["live", "gone", "gone", "gone"]


def test_an_explicit_port_in_use_is_refused():
    out = _run(
        'ss() { echo "LISTEN 0 4096 0.0.0.0:18081 0.0.0.0:*"; };'
        "HOST_PORT=18081; if (pick_host_port) 2>/dev/null; then echo took; else echo refused; fi;"
        'ss() { :; }; HOST_PORT=18555; pick_host_port; echo "$HOST_PORT"'
    )
    assert out.split() == ["refused", "18555"]


@pytest.mark.parametrize(
    ("links", "up", "ok"),
    [
        ("cpvm-ns cpvm-tap lo", "lo cpvm-ns", True),
        # Unraid loads ipip, so every new namespace gets tunl0. Down, it carries nothing.
        ("cpvm-ns cpvm-tap lo tunl0", "lo cpvm-ns", True),
        ("cpvm-ns cpvm-tap lo tunl0", "lo cpvm-ns tunl0", False),
        ("cpvm-ns cpvm-tap eth9 lo", "lo cpvm-ns", False),
        ("cpvm-ns lo", "lo cpvm-ns", False),
    ],
)
def test_the_first_fence_write_checks_the_namespace_links(links, up, ok):
    out = _run(
        """
nsx() {
  case "$*" in
    "ip -o link show up") for l in $UP; do echo "1: $l: <UP>"; done ;;
    "ip -4 rule show") printf '0:\\tfrom all lookup local\\n32766:\\tfrom all lookup main\\n32767:\\tfrom all lookup default\\n' ;;
  esac
}
links=$1; UP=$2
live=$(printf '## links\\n'; printf '%s\\n' $links; printf '## sysctl\\nnet.ipv4.ip_forward=1\\n## iptables\\n')
ns_base_ok "$live" && echo yes || echo no
""",
        links,
        up,
    )
    assert out.strip() == ("yes" if ok else "no")


def test_the_uis_own_address_and_port_is_not_a_forbidden_target():
    # A UI on this host listens on one of its addresses: the guest may reach
    # exactly that address and port, which the self-test checks apart.
    out = _run(
        'UI_IP=192.168.1.10; UI_PORT=8080; ss() { echo "LISTEN 0 4096 0.0.0.0:8080 0.0.0.0:*"; };'
        "ip() { :; }; probe_targets | grep '^host '"
    )
    assert out.split("\n")[:1] == ["host 100.101.102.103 8080"]
    assert "192.168.1.10 8080" not in out


@pytest.mark.parametrize("installed", [True, False])
def test_remove_changes_nothing_while_the_guard_lock_is_held(installed):
    # A guard pass that still holds the lock can write the host rules back
    # while remove takes them away. So remove must stop before it asks the UI
    # to forget the worker, stops the units or the guest, or deletes anything.
    out = _run(
        """
INSTALLED=$1; CALLS=$(mktemp)
need_root() { :; }
load_conf() { [ "$INSTALLED" = yes ] && WORKER_NAME=w; }
flock() { return 1; }
guest_pid() { echo guest_pid >>"$CALLS"; }
tap_up() { :; }
guest_ssh() { echo guest_ssh >>"$CALLS"; }
svc_remove() { echo svc_remove >>"$CALLS"; }
guest_stop() { echo guest_stop >>"$CALLS"; }
host_rules_remove() { echo host_rules_remove >>"$CALLS"; }
RUN_DIR=$(mktemp -d)/run; CONF=$(mktemp)
if (cmd_remove --yes) 2>/dev/null; then echo RAN; else echo STOPPED; fi
[ -f "$CONF" ] && echo CONF-KEPT
cat "$CALLS"
""",
        "yes" if installed else "no",
    )
    assert out.split() == ["STOPPED", "CONF-KEPT"]


@pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="needs ssh-keygen")
@pytest.mark.parametrize("fail", ["mkfs.vfat", "mcopy", "none"])
def test_the_seed_folder_with_the_fleet_key_never_stays_behind(fail):
    # write_seed stages the fleet key in plain text before it copies it onto
    # the seed disk. The folder must go when a step fails, too.
    out = _run(
        """
FAIL=$1
UI_HOST=192.168.1.50; UI_URL=http://192.168.1.50:8080; WORKER_NAME=nas-secure-vm; HOST_WORKER=nas
WORKER_URL=http://192.168.1.10:18081; REF=v1.2.3
mkdir -p "$STATE/ssh"
ssh-keygen -q -t ed25519 -N "" -f "$STATE/ssh/id_ed25519"
ssh-keygen -q -t ed25519 -N "" -f "$STATE/ssh/guest_host_ed25519"
mkfs.vfat() { [ "$FAIL" != mkfs.vfat ] && touch "${@: -2:1}"; }
mcopy() { [ "$FAIL" != mcopy ]; }
chown() { :; }
SEED_DIR=$(command mktemp -d)/seed
mktemp() { mkdir "$SEED_DIR" && echo "$SEED_DIR"; }
# A background job keeps set -e on inside, as at the real call; an if would turn it off.
write_seed 0123456789abcdef0123 2>/dev/null &
if wait $!; then echo WROTE; else echo FAILED; fi
[ -e "$SEED_DIR" ] || echo NOTHING-LEFT
""",
        fail,
    )
    assert out.split() == ["WROTE" if fail == "none" else "FAILED", "NOTHING-LEFT"]


@pytest.mark.parametrize("broken", ["host_addrs", "host_connected_public"])
def test_the_fence_is_not_rendered_when_a_host_list_cannot_be_read(broken):
    # A drop missing from the fence would open that address to the guest.
    out = _run(
        """
eval "$1() { return 1; }"
if render_ns_rules >/dev/null; then echo RENDERED; else echo REFUSED; fi
host_addrs() { :; }; host_connected_public() { :; }
render_ns_rules >/dev/null && echo EMPTY-LISTS-OK
""",
        broken,
    )
    assert out.split() == ["REFUSED", "EMPTY-LISTS-OK"]


@pytest.mark.parametrize(("age", "ran"), [(60, False), (400, True)])
def test_a_selftest_request_waits_out_the_gap_instead_of_vanishing(age, ran):
    # The UI accepted the request, so it must run on the first pass after
    # the 5-minute gap, not be deleted unrun.
    out = _run(
        """
AGE=$1; CALLS=$(mktemp)
load_conf() { :; }; tap_up() { :; }
RUN_DIR=$(mktemp -d); echo provisioned >"$STATE/provisioned"
echo $(( $(date +%s) - AGE )) >"$RUN_DIR/selftest.last"
guest_ssh() { echo "ssh $*" >>"$CALLS"; }
selftest_once() { echo selftest >>"$CALLS"; SELFTEST_LINES="ok x"; }
save_selftest() { :; }; log() { :; }
selftest_if_asked
grep -c 'rm -f /run/cashpilot-vm-ask/selftest' "$CALLS" || true
grep -c '^selftest$' "$CALLS" || true
""",
        str(age),
    )
    assert out.split() == (["1", "1"] if ran else ["0", "0"])


def test_the_red_tests_host_exception_is_only_for_the_vms_link():
    # Without -i, the ACCEPT would let every interface skip the host's INPUT rules.
    text = SCRIPT.read_text()
    rule = next(line for line in text.splitlines() if "CPVM-IN 1" in line and "cpvm:red-test" in line)
    assert '-i "$VETH_HOST"' in rule


@pytest.mark.parametrize(("answered", "ok"), [(True, True), (False, False)])
def test_verify_json_prove_red_prints_only_json_and_counts_the_red_run(answered, ok):
    out = _run(
        """
ANSWERED=$1; N=0
need_root() { :; }; load_conf() { :; }; guest_pid() { echo 1; }; tap_up() { :; }
nsx() { :; }; iptables() { :; }; flock() { :; }; guard_pass() { GUARD_LOCKED=1; }; save_selftest() { :; }
ns_fingerprint() { echo golden; }; echo golden >"$STATE/fence.golden"
RUN_DIR=$(mktemp -d)
selftest_once() {
  N=$((N + 1))
  if [ "$N" = 1 ] && [ "$ANSWERED" = yes ]; then
    SELFTEST_LINES="FAIL lan 192.168.1.1:80 answered the guest (reached)"
  elif [ "$N" = 1 ]; then
    SELFTEST_LINES="FAIL lan 192.168.1.1:80 missing result"
  else
    SELFTEST_LINES="ok lan 192.168.1.1:80 blocked"
  fi
  [ "$1" = loud ] && echo "probe line $N"
  return 0
}
cmd_verify --json --prove-red 2>/dev/null && echo RC=0 || echo RC=1
""",
        "yes" if answered else "no",
    )
    lines = out.strip().splitlines()
    assert len(lines) == 2, out
    assert json.loads(lines[0])["ok"] is ok
    assert lines[1] == ("RC=0" if ok else "RC=1")


@pytest.mark.parametrize(
    ("left", "ok"),
    [("none", True), ("drift", False), ("host-rule", False), ("cut", False), ("no-lock", False), ("guard-failed", False)],
)
def test_the_red_run_reports_the_fence_back_only_when_it_reads_back(left, ok):
    # A guard pass that cannot take the lock (a second red run holds it)
    # returns without checking anything. The tap stays up while the fence is
    # open, so only the fence itself can say it is back.
    out = _run(
        """
LEFT=$1
need_root() { :; }; load_conf() { :; }; guest_pid() { echo 1; }; nsx() { :; }; flock() { :; }
save_selftest() { :; }
guard_pass() {
  case "$LEFT" in
    no-lock) return 0 ;;  # waited out another red run: took no lock, checked nothing
    guard-failed) GUARD_LOCKED=1; return 1 ;;
    *) GUARD_LOCKED=1 ;;
  esac
}
RUN_DIR=$(mktemp -d); echo golden >"$STATE/fence.golden"
N=0; tap_up() { N=$((N + 1)); [ "$LEFT" != cut ] || [ "$N" = 1 ]; }
ns_fingerprint() { if [ "$LEFT" = drift ]; then echo open; else echo golden; fi; }
iptables() { if [ "$LEFT" = host-rule ] && [ "$*" = "-w -S CPVM-IN" ]; then echo "-A CPVM-IN -i cpvm-host -m comment --comment cpvm:red-test -j ACCEPT"; fi; }
selftest_once() { SELFTEST_LINES="FAIL lan 192.168.1.1:80 answered the guest (reached)"; }
(cmd_verify --prove-red) >/dev/null 2>&1 && echo RC=0 || echo RC=1
""",
        left,
    )
    assert out.strip() == ("RC=0" if ok else "RC=1")


@pytest.mark.parametrize(("fails", "rc"), [(False, 0), (True, 1)])
def test_a_host_rule_that_cannot_be_put_back_is_not_reported_ok(fails, rc):
    # The guard runs with errexit off, so host_rules_ensure must say itself
    # that an insert failed, and the pass must not end in state ok.
    out = _run(
        """
FAILS=$1; CALLS=$(mktemp)
sysctl() { echo 1; }; has() { return 1; }
iptables() {
  case " $* " in
    *" -I "*) [ "$FAILS" = no ] || return 1 ;;
    *" -D "*) return 1 ;;
  esac
  return 0
}
host_rules_ensure && echo ENSURE=0 || echo ENSURE=1
# The tail of a guard pass: the fence matches, then the host side.
CONF=$(mktemp); RUN_DIR=$(mktemp -d); load_conf() { :; }; ns_exists() { :; }; nsx() { :; }
desired=$(render_ns_rules); printf '%s\n' "$desired" >"$STATE/fence.rules"; echo g >"$STATE/fence.golden"
ns_fingerprint() { echo g; }; tap_up() { :; }; log() { :; }; ns_ready() { :; }
echo yes >"$STATE/provisioned"; push_state_to_guest() { echo pushed >>"$CALLS"; }
eval "real_$(declare -f write_guard_state)"; write_guard_state() { echo "state:$1" >>"$CALLS"; real_write_guard_state "$@"; }
rc=0; guard_pass || rc=$?
echo "PASS=$rc"; python3 -c 'import json,sys; print("STATE=" + json.load(open(sys.argv[1]))["state"])' "$RUN_DIR/fence.json"
cat "$CALLS"
""",
        "yes" if fails else "no",
    )
    # One state write, after the host rules: never an ok that a failure follows.
    state = "failed" if fails else "ok"
    assert out.split() == [f"ENSURE={rc}", f"PASS={rc}", f"STATE={state}", f"state:{state}", "pushed"]


@pytest.mark.parametrize(("first_pass", "rc"), [(0, 0), (1, 0)])
def test_net_up_lets_the_guest_start_cut_off_when_the_first_pass_fails(first_pass, rc):
    # The guest unit Requires= the net unit, so a failed public-IP lookup at
    # boot must not fail net-up, or the guest never starts. guest_run keeps an
    # unchecked tap down, and the guard connects it later.
    out = _run(
        """
FIRST=$1
need_root() { :; }; load_conf() { :; }; RUN_DIR=$(mktemp -d); net_up() { echo net_up; }
guard_pass() { return "$FIRST"; }
# Not in an && list: that would turn errexit off, as it is not when systemd runs it.
set +e; (set -e; main net-up) 2>/dev/null; echo "RC=$?"
""",
        str(first_pass),
    )
    assert out.split() == ["net_up", f"RC={rc}"]


def test_net_up_still_fails_when_the_namespace_cannot_be_made():
    out = _run(
        """
need_root() { :; }; load_conf() { :; }; RUN_DIR=$(mktemp -d); net_up() { return 1; }; guard_pass() { :; }
set +e; (set -e; main net-up) 2>/dev/null; echo "RC=$?"
"""
    )
    assert out.strip() == "RC=1"


def test_an_install_that_stops_before_the_first_boot_is_over_deletes_the_seed():
    # The seed disk holds the fleet key in plain text.
    out = _run(
        """
CALLS=$(mktemp); is_unraid() { return 1; }; systemctl() { echo "systemctl $*" >>"$CALLS"; }
guest_stop() { echo guest_stop >>"$CALLS"; }
echo key >"$STATE/seed.img"
install_failed >/dev/null
[ -e "$STATE/seed.img" ] && echo SEED=left || echo SEED=gone
cat "$CALLS"
"""
    )
    assert out.splitlines() == ["SEED=gone", "systemctl stop cashpilot-vm.service"]
    # The trap covers the whole stretch the seed exists, and goes once it is deleted.
    text = SCRIPT.read_text()
    body = text[text.index("\ncmd_install() {") :]
    assert body.index("trap install_failed EXIT") < body.index('write_seed "$api_key"')
    assert body.index('rm -f "$STATE/seed.img"\n  trap - EXIT') > body.index('write_seed "$api_key"')


def test_the_ui_is_not_a_forbidden_target_on_the_lan_either():
    # A UI on the LAN gateway or on a neighbour answers the guest on its port by
    # design. That tuple must not count as a leak, but its other ports do.
    out = _run(
        """
UI_IP=192.168.1.50; UI_PORT=443; ss() { :; }
ip() {
  case "$*" in
    "-4 route show default") echo "default via 192.168.1.50 dev eth0" ;;
    "-4 neigh show"*) echo "192.168.1.60 dev eth0 lladdr 00:11:22:33:44:55 REACHABLE" ;;
    *) return 1 ;;
  esac
}
probe_targets
"""
    )
    assert "192.168.1.50 443" not in out
    assert "lan-gateway 192.168.1.50 80" in out
    assert "lan-device 192.168.1.60 443" in out


@pytest.mark.parametrize("step", ["tap-gateway", "veth", "none"])
def test_net_up_fails_when_any_step_fails_and_the_guard_then_stops(step):
    # The guard calls net_up with errexit off, so the last command's status is
    # not enough: a missing tap gateway must not become the golden copy.
    out = _run(
        """
STEP=$1; CALLS=$(mktemp)
ns_exists() { :; }; sysctl() { :; }; warn() { :; }; host_rules_ensure() { :; }
ip() { [ "$STEP" = veth ] && [ "$*" = "addr replace 10.213.0.5/30 dev cpvm-host" ] && return 1; return 0; }
nsx() { [ "$STEP" = tap-gateway ] && [ "$*" = "ip addr replace 10.213.0.1/30 dev cpvm-tap" ] && return 1; return 0; }
net_up && echo NET=0 || echo NET=1
# The guard: a namespace that is not ready runs net_up, and stops on its failure.
CONF=$(mktemp); RUN_DIR=$(mktemp -d); load_conf() { :; }; ns_ready() { return 1; }; log() { :; }
link_cut() { echo link_cut >>"$CALLS"; }; link_connect() { echo link_connect >>"$CALLS"; }
render_ns_rules() { echo rules; }; apply_ns_rules() { echo apply >>"$CALLS"; }
rc=0; guard_pass >/dev/null 2>&1 || rc=$?
echo "PASS=$rc"; cat "$CALLS"
""",
        step,
    )
    if step == "none":
        assert out.split()[:2] == ["NET=0", "PASS=1"]  # the stubbed fence does not read back
        assert "apply" in out.split()
    else:
        assert out.split() == ["NET=1", "PASS=1", "link_cut"]


def test_a_tap_without_its_gateway_address_is_not_ready():
    out = _run(
        """
ns_exists() { :; }
nsx() { [ "$1 $2 $3" = "ip -4 -o" ] && printf '%s\n' "$ADDR"; }
ADDR="4: cpvm-tap    inet 10.213.0.1/30 scope global cpvm-tap\\       valid_lft forever"; ns_ready && echo yes || echo no
ADDR=""; ns_ready && echo yes || echo no
ADDR="4: cpvm-tap    inet 10.213.0.13/30 scope global cpvm-tap"; ns_ready && echo yes || echo no
"""
    )
    assert out.split() == ["yes", "no", "no"]


def test_net_up_does_not_fail_on_the_host_rules():
    # They carry the guest's traffic, not its fence; the guard puts them back.
    out = _run(
        """
ns_exists() { :; }; sysctl() { :; }; ip() { :; }; nsx() { :; }; host_rules_ensure() { return 1; }
net_up 2>/dev/null && echo NET=0 || echo NET=1
"""
    )
    assert out.strip() == "NET=0"


@pytest.mark.parametrize("json_out", [False, True])
def test_a_plain_verify_holds_the_guard_lock_through_its_probes(json_out):
    # Without it, a plain verify that runs during a red run reports the open
    # fence as a leak, and saves that for the UI.
    out = _run(
        """
JSON=$1; CALLS=$(mktemp)
need_root() { :; }; load_conf() { :; }; guest_pid() { echo 1; }; tap_up() { :; }; save_selftest() { :; }
RUN_DIR=$(mktemp -d)
flock() { echo "flock $*" >>"$CALLS"; }
selftest_once() { echo "probes locked=$GUARD_LOCKED" >>"$CALLS"; SELFTEST_LINES=ok; }
if [ "$JSON" = yes ]; then cmd_verify --json >/dev/null; else cmd_verify >/dev/null; fi
cat "$CALLS"
""",
        "yes" if json_out else "no",
    )
    assert out.splitlines() == ["flock -w 50 9", "probes locked=1"]


def test_a_selftest_with_no_live_control_is_not_green():
    rc, lines = _selftest("192.168.1.1 53 blocked\n192.168.1.20 22 blocked\n", "")
    assert rc == 1 and "FAIL  no forbidden target answered from outside the fence" in lines


@pytest.mark.parametrize("disk_deletes", [False, True])
def test_remove_keeps_the_disk_path_until_the_disk_is_gone(disk_deletes):
    # A remove that cannot delete the disk must leave a record of where it is,
    # or the next run looks in the default place and calls the host clean.
    out = _run(
        """
DELETES=$1
need_root() { :; }; flock() { :; }; guest_pid() { return 1; }; svc_remove() { :; }; guest_stop() { :; }
host_rules_remove() { :; }; ns_exists() { return 1; }; ip() { :; }; pkill() { :; }; has() { return 1; }
is_unraid() { return 1; }; id() { return 1; }; leftovers() { [ -e "$STATE" ] && echo "folder $STATE"; true; }
BIN=$(mktemp); RUN_DIR=$(mktemp -d)/run
CONF_DIR=$(mktemp -d)/cashpilot-vm; mkdir -p "$CONF_DIR"; CONF=$CONF_DIR/config
DISK=$(mktemp -d)/custom/cashpilot-vm; mkdir -p "$DISK"
printf 'CPVM_HOME=%q\nWORKER_NAME=w\n' "$DISK" >"$CONF"
set_state() { STATE=$CPVM_HOME; }
eval "real_$(declare -f cmd_remove)"
rm() { if [ "$DELETES" = no ] && [ "$*" = "-rf $DISK" ]; then return 1; fi; command rm "$@"; }
(real_cmd_remove --yes) >/dev/null 2>&1 && echo RC=0 || echo RC=1
[ -f "$CONF.removing" ] && grep -q "$DISK" "$CONF.removing" && echo MARKER || echo NO-MARKER
[ -e "$CONF_DIR" ] && echo CONF_DIR-KEPT || echo CONF_DIR-GONE
# The retry finds the disk through the marker.
unset -f rm; DELETES=yes
(real_cmd_remove --yes) >/dev/null 2>&1 && echo RETRY=0 || echo RETRY=1
[ -e "$DISK" ] && echo DISK-LEFT || echo DISK-GONE
""",
        "yes" if disk_deletes else "no",
    )
    if disk_deletes:
        assert out.split()[:3] == ["RC=0", "NO-MARKER", "CONF_DIR-GONE"]
    else:
        assert out.split() == ["RC=1", "MARKER", "CONF_DIR-KEPT", "RETRY=0", "DISK-GONE"]
