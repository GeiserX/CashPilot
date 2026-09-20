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


def platform_family(platform: Any) -> str | None:
    """``linux/arm64/v8`` -> ``arm64``; ``linux/arm/v7`` -> ``arm``; ``linux/386`` -> None."""
    parts = str(platform or "").strip().lower().split("/")
    if len(parts) < 2 or parts[0] != "linux":
        return None
    return parts[1] if parts[1] in FAMILIES else None


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
