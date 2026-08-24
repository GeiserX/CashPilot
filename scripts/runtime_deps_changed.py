#!/usr/bin/env python3
"""Did the dependencies that SHIP change between two refs?

``uv.lock`` holds the dev group as well as the runtime one, and release.yml
treated any change to it as a reason to build. So a bump of pytest or ruff --
the most frequent kind of dependency PR there is -- cut a full release whose
images were identical to the previous one. v1.36.4 was exactly that: 78 entries
in site-packages, zero difference from v1.36.3, three containers restarted on
the fleet for a version label.

Both images build with ``uv sync --frozen --no-dev``, so the question that
decides a release is not "did uv.lock change" but "did the no-dev resolution
change". This answers that by exporting it at both refs with the real resolver
and comparing.

    python scripts/runtime_deps_changed.py v1.36.3 HEAD    # -> false
    python scripts/runtime_deps_changed.py v1.36.2 v1.36.3 # -> true

FAIL-SAFE, and this is the whole design. Every way of not knowing -- uv is
missing, a ref does not exist, an export fails, the lock disagrees with
pyproject -- prints ``true`` and explains itself on stderr. A release that
should not have happened costs a pointless image. A release that silently did
not happen ships nothing while the run reports success, which is the failure
this repo has been bitten by before.
"""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
import tempfile

#: What both Dockerfiles copy before `uv sync`. Nothing else feeds the resolution.
MANIFESTS = ("pyproject.toml", "uv.lock")


def _warn(message: str) -> None:
    print(f"runtime_deps_changed: {message}", file=sys.stderr)


def _run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    """Never raise. A missing binary is an answer, not a crash.

    ``subprocess.run`` raises FileNotFoundError when the executable is absent,
    which is precisely the case this script has to survive: no uv on PATH must
    mean "assume it changed", not a traceback that fails the release job.
    """
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=180, check=False, **kwargs)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(args, returncode=127, stdout="", stderr=str(exc))


def _materialise(repo: pathlib.Path, ref: str, into: pathlib.Path) -> bool:
    """Write the manifests as they were at ``ref``. False if any is unreadable."""
    for name in MANIFESTS:
        result = _run(["git", "-C", str(repo), "show", f"{ref}:{name}"])
        if result.returncode != 0:
            _warn(f"cannot read {name} at {ref}: {result.stderr.strip()}")
            return False
        (into / name).write_text(result.stdout, encoding="utf-8")
    return True


def _runtime_requirements(directory: pathlib.Path) -> set[str] | None:
    """Everything the no-dev resolution pins, or None when uv cannot say.

    ``--frozen`` so uv reports a lock that disagrees with its pyproject instead
    of quietly re-resolving it, which would need the network and would answer a
    different question from the one the Dockerfile asks.

    HASHES ARE INCLUDED. Exporting with ``--no-hashes`` and keeping only the
    ``name==version`` lines compares less than the build consumes: a lock can
    gain or change an artifact for a version that already exists -- a new wheel
    for a platform, a re-resolved sdist -- and every pin still reads the same
    while ``uv sync --frozen`` installs something different. That returns
    "unchanged" for a change that ships, which is the one direction this script
    must never get wrong. (CodeRabbit, PR #354.)

    Comment lines go, and only those. uv writes the command it was run with into
    the header, and that names the temp directory, so it differs on every call
    by construction. The ``# via ...`` provenance notes are dropped with it;
    they restate the graph the pins already describe.
    """
    result = _run(
        [
            "uv",
            "export",
            "--directory",
            str(directory),
            "--frozen",
            "--no-dev",
            "--format",
            "requirements-txt",
        ]
    )
    if result.returncode != 0:
        _warn(f"uv export failed in {directory}: {result.stderr.strip()[:400]}")
        return None
    return {line.strip() for line in result.stdout.splitlines() if line.strip() and not line.strip().startswith("#")}


def runtime_deps_changed(repo: pathlib.Path, base: str, head: str) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        exported = []
        for ref in (base, head):
            into = root / ref.replace("/", "_")
            into.mkdir(parents=True, exist_ok=True)
            if not _materialise(repo, ref, into):
                _warn("assuming the runtime dependencies changed")
                return True
            requirements = _runtime_requirements(into)
            if requirements is None:
                _warn("assuming the runtime dependencies changed")
                return True
            exported.append(requirements)

    before, after = exported
    if before == after:
        _warn(f"{len(before)} runtime requirements, identical between {base} and {head}")
        return False

    for pin in sorted(after - before):
        _warn(f"  + {pin}")
    for pin in sorted(before - after):
        _warn(f"  - {pin}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", help="the ref to compare from, usually the last release tag")
    parser.add_argument("head", nargs="?", default="HEAD")
    parser.add_argument("--repo", default=".", help="repository root (default: cwd)")
    args = parser.parse_args(argv)

    if _run(["uv", "--version"]).returncode != 0:
        _warn("uv is not on PATH; assuming the runtime dependencies changed")
        print("true")
        return 0

    print("true" if runtime_deps_changed(pathlib.Path(args.repo), args.base, args.head) else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
