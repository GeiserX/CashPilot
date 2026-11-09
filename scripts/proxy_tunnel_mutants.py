"""Mutants of app/proxy_tunnel.py that the shared-tunnel tests must catch.

Each mutant breaks one promise of the shared tunnel (docs/proxies.md, "One
tunnel per proxy"). For each, this copies the tree to a scratch directory,
applies the edit, runs the proxy tests there and expects them to fail. A
mutant the tests survive is a promise nothing checks.

    python scripts/proxy_tunnel_mutants.py            # exit 1 if any mutant survives

Run it on a box where a test suite may run, not on a laptop with little memory.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = "app/proxy_tunnel.py"
TESTS = ["tests/test_proxy_shared_tunnel.py", "tests/test_proxy_tunnel.py"]

MUTANTS: list[tuple[str, str, str]] = [
    (
        "the heartbeat starts a held copy",
        "if earner is not None and str(earner.name) not in stopped:",
        "if earner is not None:",
    ),
    (
        "a stop is not written down",
        "    _set_held(name, True, strict=True)\n    if tunnel is not None and not _is_shared(tunnel):",
        "    if tunnel is not None and not _is_shared(tunnel):",
    ),
    (
        "a ready tunnel on the same settings is restarted for every new copy",
        '    if running and _read_secret_file(current, "settings") == files["settings"]:',
        "    if False:",
    ),
    (
        "a running tunnel on new settings is kept",
        '    if running and _read_secret_file(current, "settings") == files["settings"]:',
        "    if running:",
    ),
    (
        "new settings reach the running tunnel before they proved an exit",
        "        _prove(client, proxy, own_ip, files)\n",
        "        pass\n",
    ),
    (
        "a new tunnel image recreates every copy on the proxy",
        "upgrade=not others)",
        "upgrade=True)",
    ),
    (
        "stopping one copy stops the tunnel under the others",
        "        if not any(str(m.name) not in stopped for m in _members(client, tunnel)):",
        "        if True:",
    ),
    (
        "a tunnel others use is removed",
        "    if tunnel is None or not _is_shared(tunnel) or _members(client, tunnel):",
        "    if tunnel is None or not _is_shared(tunnel):",
    ),
    (
        "a moved copy stays in the old tunnel",
        '        network_mode=f"container:{tunnel.id}",\n        cap_drop=',
        '        network_mode=hc.get("NetworkMode"),\n        cap_drop=',
    ),
    (
        "a moved copy loses its hardening",
        '        cap_drop=hc.get("CapDrop") or ["ALL"],',
        "        cap_drop=None,",
    ),
    (
        "a migrated stopped pair is started",
        "                if not was_up:\n",
        "                if False:\n",
    ),
    (
        "every copy reports its own tunnel id, so the cap counts it N times",
        '                "tunnel_container_id": sidecar.short_id if sidecar is not None else "",',
        '                "tunnel_container_id": (earner.short_id if earner is not None else ""),',
    ),
    (
        "a tunnel is replaced instead of restarted in place",
        "    if current is not None and (_image_of(current) == image or not upgrade):",
        "    if False:",
    ),
    (
        "a tunnel Docker cannot start blocks every later start",
        "        except _Broken as exc:\n",
        "        except ZeroDivisionError as exc:\n",
    ),
    (
        "the settings volume is a bind with no source, lost on a daemon restart",
        '"mounts": [secret_mount()],',
        '"volumes": [SECRET_DIR],',
    ),
    (
        "a moved copy is removed before its clone holds its name",
        "        member.rename(aside)\n",
        "        member.remove(force=True, v=True)\n",
    ),
    (
        "the heartbeat removes a staged tunnel that copies still live in",
        "            if any(_tunnel_id_of(e) == container.id for e in every_earner):",
        "            if False:",
    ),
    (
        "a staged tunnel is finished while a copy is still half moved",
        '    if half := _moving(client, _labels(staged).get(LABEL_PROXY, "")):\n',
        "    if half := []:\n",
    ),
    (
        "a staged tunnel copies live in is swept",
        "            and not _members(client, container)\n",
        "\n",
    ),
]


def run(tree: Path) -> int:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *TESTS],
        cwd=tree,
        capture_output=True,
        text=True,
        timeout=600,
    ).returncode


def main() -> int:
    source = (ROOT / TARGET).read_text()
    if run(ROOT) != 0:
        print("the tests fail on the unmutated tree; fix that first")
        return 1
    survivors = 0
    with tempfile.TemporaryDirectory(prefix="cp-mutants-") as tmp:
        tree = Path(tmp) / "tree"
        shutil.copytree(ROOT, tree, ignore=shutil.ignore_patterns(".git", ".venv", "site", "__pycache__"))
        for label, old, new in MUTANTS:
            if source.count(old) != 1:
                print(f"STALE   {label}: the text to mutate is not in {TARGET} exactly once")
                survivors += 1
                continue
            (tree / TARGET).write_text(source.replace(old, new))
            code = run(tree)
            print(f"{'KILLED ' if code != 0 else 'SURVIVED'} {label}")
            survivors += code == 0
        (tree / TARGET).write_text(source)
    print(f"{len(MUTANTS) - survivors} of {len(MUTANTS)} mutants killed")
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
