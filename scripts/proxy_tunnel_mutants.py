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
        "            if str(earner.name) in held():\n",
        "            if False:\n",
    ),
    (
        "an unreadable stop marker reads as no copy stopped",
        "    except FileNotFoundError:\n        return set()",
        "    except OSError:\n        return set()",
    ),
    (
        "the heartbeat starts a copy while a stop of its proxy runs",
        "    lock = _deploy_lock(int(proxy_id)) if str(proxy_id).isdigit() else None\n",
        "    lock = None\n",
    ),
    (
        "a start that cannot clear its stop starts the copy anyway",
        "        _set_held(name, False, strict=True)\n    except ProxyTunnelError:\n        # The tunnel was started",
        "        _set_held(name, False)\n    except ProxyTunnelError:\n        # The tunnel was started",
    ),
    (
        "a deploy starts its copy before it clears the copy's stop",
        "    try:\n        _set_held(name, False, strict=True)\n    except ProxyTunnelError:\n        _drop_if_empty(client, tunnel)\n        raise\n",
        "",
    ),
    (
        "a copy is moved while it still runs, so two of it run at once",
        '        if getattr(member, "status", "") in _LIVE:\n            # Never two',
        "        if False:\n            # Never two",
    ),
    (
        "an edit goes on when the old settings could not be read",
        'previous = {key: _read_secret_file_or_raise(current, key) or "" for key in SECRET_KEYS}',
        'previous = {key: _read_secret_file(current, key) or "" for key in SECRET_KEYS}',
    ),
    (
        "a rolled back edit leaves the copies outside the tunnel",
        "                _restart_members(client, current)\n            elif not running:",
        "                pass\n            elif not running:",
    ),
    (
        "an old password shows in a failed edit's tunnel log",
        "        secrets = [*secrets, *_auth_secrets(old)]",
        "        pass",
    ),
    (
        "a redeploy ignores the copies of a staged tunnel and takes a new image",
        "            _get(client, shared_tunnel_name(proxy_id) + STAGED_SUFFIX),\n",
        "",
    ),
    (
        "recovery removes the aside copy of a move whose clone is still starting",
        "        if name in by_name and _age_seconds(by_name[name]) < min_age:\n",
        "        if False:\n",
    ),
    (
        "a start leaves a copy in a tunnel that is gone",
        "        if earner is not None and _tunnel_id_of(earner) != shared.id:",
        "        if earner is not None and tunnel is not None and not _is_shared(tunnel):",
    ),
    (
        "a migrated pair whose tunnel Docker could not start is left behind",
        "        if not was_up and not failed:\n",
        "        if not was_up:\n",
    ),
    (
        "removing a service deletes copies without the proxy's lock",
        "        with _deploy_lock(int(pid)) if pid.isdigit() else contextlib.nullcontext():",
        "        with contextlib.nullcontext():",
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
        "a stopped legacy pair is moved by the migration",
        "        if not was_up and not failed:\n",
        "        if False:\n",
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
    (
        "a migrated password is logged in its decoded form",
        '*_auth_secrets(files.get("proxy_auth", ""))]\n    image = tunnel_image()\n    try:',
        'files.get("proxy_auth", "")]\n    image = tunnel_image()\n    try:',
    ),
    (
        "a migration's edit logs the decoded password",
        '*_auth_secrets(files.get("proxy_auth", ""))]\n    image = tunnel_image()\n    final',
        'files.get("proxy_auth", "")]\n    image = tunnel_image()\n    final',
    ),
    (
        "one Docker refusal replaces the tunnel",
        "    for attempt in (1, 2):\n",
        "    for attempt in (2,):\n",
    ),
    (
        "a copy whose start failed is left created",
        "        if (left := _get(client, name)) is not None and _is_ours(left, slug, proxy_id):\n",
        "        if False:\n",
    ),
    (
        "a settings read error is read as an empty file",
        '    return {key: _read_secret_file_or_raise(container, key) or "" for key in SECRET_KEYS if key != "settings"}',
        '    return {key: _read_secret_file(container, key) or "" for key in SECRET_KEYS if key != "settings"}',
    ),
    (
        "the migration decides on the listing, not on the tunnel as it is",
        "            tunnel.reload()  # read under the proxy's lock, not from the listing\n",
        "            pass\n",
    ),
    (
        "an empty shared tunnel is kept",
        "        if tunnel.id not in used and _is_shared(tunnel) and _age_seconds(tunnel) >= STAGED_STALE_SECONDS:\n",
        "        if False:\n",
    ),
    (
        "a young empty shared tunnel is removed under a filling deploy",
        "        if tunnel.id not in used and _is_shared(tunnel) and _age_seconds(tunnel) >= STAGED_STALE_SECONDS:\n",
        "        if tunnel.id not in used and _is_shared(tunnel):\n",
    ),
    (
        "a start that cannot clear the stop leaves the tunnel running",
        "            if not any(str(m.name) not in stopped for m in _members(client, current)):\n                current.stop(timeout=SIDECAR_STOP_SECONDS)\n",
        "            if not any(str(m.name) not in stopped for m in _members(client, current)):\n                pass\n",
    ),
    (
        "a start that cannot clear the stop stops a tunnel another copy runs in",
        "            if not any(str(m.name) not in stopped for m in _members(client, current)):\n",
        "            if True:\n",
    ),
]


# Not an int: a child killed by a signal returns -signum, so -1 is SIGHUP.
TIMED_OUT = "timed out"


def run(tree: Path) -> int | str:
    try:
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *TESTS],
            cwd=tree,
            capture_output=True,
            text=True,
            timeout=600,
        ).returncode
    except subprocess.TimeoutExpired:
        return TIMED_OUT  # a mutant that hangs the tests is caught by them


def main() -> int:
    source = (ROOT / TARGET).read_text()
    survivors = 0
    with tempfile.TemporaryDirectory(prefix="cp-mutants-") as tmp:
        tree = Path(tmp) / "tree"
        shutil.copytree(ROOT, tree, ignore=shutil.ignore_patterns(".git", ".venv", "site", "__pycache__"))
        # The baseline runs in the same scratch tree as the mutants, so a tree
        # the tests cannot run in is never read as every mutant killed.
        if run(tree) != 0:
            print("the tests fail on the unmutated scratch tree; fix that first")
            return 1
        for label, old, new in MUTANTS:
            if source.count(old) != 1:
                print(f"STALE   {label}: the text to mutate is not in {TARGET} exactly once")
                survivors += 1
                continue
            (tree / TARGET).write_text(source.replace(old, new))
            code = run(tree)
            # pytest exits 1 when tests fail, and a hang is caught too; any
            # other code (a collection or import error, an interrupt) is not a kill.
            killed = code in (1, TIMED_OUT)
            verdict = "KILLED " if killed else "SURVIVED" if code == 0 else f"ERROR {code}"
            print(f"{verdict} {label}")
            survivors += not killed
        (tree / TARGET).write_text(source)
    print(f"{len(MUTANTS) - survivors} of {len(MUTANTS)} mutants killed")
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
