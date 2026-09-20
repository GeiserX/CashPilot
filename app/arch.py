"""CPU architecture, folded to the three families a catalog entry can promise.

A worker reports ``platform.machine()`` in its heartbeat, an image manifest
names ``linux/arm64/v8``, a catalog entry declares ``linux/arm/v7`` and a
Traffmonetizer override is keyed ``arm``. They all mean one of three things,
and everything that reasons about "will this image run on that box" reasons in
those three terms:

* ``amd64``: x86-64. Every catalog image has this build.
* ``arm64``: 64-bit ARM. Raspberry Pi 4/5 on a 64-bit OS, Apple Silicon, AWS
  Graviton, Oracle Ampere.
* ``arm``: 32-bit ARM. Raspberry Pi 2/3 and any Pi on the 32-bit OS. Builds
  within the family run each other's binaries (an arm/v5 build runs on a v7
  board), so the variant is not tracked.

Anything else (i386, riscv64, s390x) is unknown here: no catalog image
publishes it, and the honest answer is "cannot say" rather than a guess.
"""

from __future__ import annotations

import re
from typing import Any

FAMILIES = frozenset({"amd64", "arm64", "arm"})

#: What ``platform.machine()`` (Linux, macOS, Android) reports, folded to a family.
MACHINE_FAMILY = {
    "x86_64": "amd64",
    "amd64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
    "arm64-v8a": "arm64",  # Android
    "armv8l": "arm64",  # 64-bit CPU running a 32-bit userland reports this on some kernels
    "armv7l": "arm",
    "armv6l": "arm",
    "armhf": "arm",
    "armeabi-v7a": "arm",  # Android
    "arm": "arm",
}

_LABEL = {"amd64": "x86-64", "arm64": "64-bit ARM", "arm": "32-bit ARM"}


def family(machine: Any) -> str | None:
    """``aarch64`` -> ``arm64``; a family name maps to itself; unknown -> None."""
    if not machine:
        return None
    return MACHINE_FAMILY.get(str(machine).strip().lower())


#: Docker's default variant for a bare ``linux/arm``, and what ``armhf`` means.
_ARM_DEFAULT_VARIANT = 7


def normalise_platform(platform: Any) -> str | tuple[str, int] | None:
    """``linux/amd64`` -> ``amd64``; ``linux/arm64/v8`` -> ``arm64``; ``linux/arm/v6`` -> ``("arm", 6)``.

    32-bit ARM keeps its variant because compatibility runs one way: a v7 board
    runs v5 and v6 builds, but a Pi Zero (v6) cannot run a v7 build. arm64 has
    one variant in practice, so it folds.
    """
    parts = str(platform or "").strip().lower().split("/")
    if len(parts) < 2 or parts[0] != "linux":
        return None
    kind, variant = parts[1], (parts[2] if len(parts) > 2 else "")
    if kind in ("amd64", "arm64"):
        return kind
    if kind == "arm":
        digits = variant.lstrip("v")
        return ("arm", int(digits) if digits.isdigit() else _ARM_DEFAULT_VARIANT)
    return None


def platform_family(platform: Any) -> str | None:
    """``linux/arm64/v8`` -> ``arm64``; ``linux/arm/v7`` -> ``arm``; ``linux/386`` -> None."""
    n = normalise_platform(platform)
    return n if isinstance(n, str) else (n[0] if n else None)


def machine_target(machine: Any) -> str | tuple[str, int] | None:
    """What a machine can run, in the same shape ``normalise_platform`` gives builds.

    ``armv6l`` -> ``("arm", 6)``; ``armv7l`` -> ``("arm", 7)``; ``armhf``,
    ``arm`` and Android's ``armeabi-v7a`` -> ``("arm", 7)``; ``aarch64`` -> ``arm64``.
    """
    fam = family(machine)
    if fam != "arm":
        return fam
    m = re.search(r"armv(\d)", str(machine).lower())
    return ("arm", int(m.group(1)) if m else _ARM_DEFAULT_VARIANT)


def runs_on(build: str | tuple[str, int], target: str | tuple[str, int]) -> bool:
    """Does a build of this platform run on that machine?"""
    if isinstance(build, str) or isinstance(target, str):
        return build == target
    return build[0] == target[0] and build[1] <= target[1]


def label(fam: str | None) -> str:
    """How a family reads to a person."""
    return _LABEL.get(fam or "", str(fam or "unknown"))


def supported_families(docker_conf: dict[str, Any]) -> set[str]:
    """The families a catalog entry has a build for: its platforms plus its overrides.

    Empty when the entry declares nothing, which callers must read as "not
    known", never as "runs nowhere".
    """
    out = {f for f in (platform_family(p) for p in docker_conf.get("platforms") or []) if f}
    by_arch = docker_conf.get("image_by_arch")
    if isinstance(by_arch, dict):
        out.update(k for k in by_arch if k in FAMILIES)
    return out


def supports(docker_conf: dict[str, Any], machine: Any) -> bool | None:
    """Does this catalog entry have a build that runs on this machine?

    None when it cannot be known: no reported architecture, an architecture
    nothing folds, or an entry that declares no platforms. Callers must read
    None as "not checked", never as a pass. An ``image_by_arch`` override counts
    for its whole family: the tag is a separate single-arch image whose label
    lies (that is why it exists), so its variant cannot be read.
    """
    target = machine_target(machine)
    declared = {n for n in (normalise_platform(p) for p in docker_conf.get("platforms") or []) if n}
    by_arch = docker_conf.get("image_by_arch")
    overrides = {k for k in by_arch if k in FAMILIES} if isinstance(by_arch, dict) else set()
    if target is None or not (declared or overrides):
        return None
    fam = target if isinstance(target, str) else target[0]
    if fam in overrides:
        return True
    return any(runs_on(build, target) for build in declared)


def image_for(docker_conf: dict[str, Any], machine: Any) -> str | None:
    """The image a machine of this architecture should run.

    Docker picks the right build from a multi-arch manifest by itself, so most
    entries need only ``image``. ``image_by_arch`` exists for the images whose
    ARM builds Docker cannot select: traffmonetizer/cli_v2 publishes separate
    arm64v8 and arm32v7 tags and labels every one of them linux/amd64, so a
    worker on a Raspberry Pi pulling the default tag gets an x86_64 binary that
    cannot start. An unknown or missing architecture, or a family the entry
    does not name, falls back to ``image``. ``machine`` may be a raw
    ``platform.machine()`` string or a family name.
    """
    image = docker_conf.get("image")
    by_arch = docker_conf.get("image_by_arch")
    fam = family(machine)
    if not isinstance(by_arch, dict) or not fam:
        return image
    override = by_arch.get(fam)
    return override.strip() if isinstance(override, str) and override.strip() else image
