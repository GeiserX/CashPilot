# Running CashPilot on ARM

CashPilot runs on 64-bit ARM and 32-bit ARM as well as x86-64. A Raspberry Pi 4 or 5, an Apple Silicon Mac, or an ARM cloud box (AWS Graviton, Oracle Ampere) can host the UI, a worker, or both.

## What runs where

| Component | x86-64 | 64-bit ARM (arm64) | 32-bit ARM (arm) |
|---|:--:|:--:|:--:|
| CashPilot UI (`drumsergio/cashpilot`) | yes | yes | no |
| CashPilot worker (`drumsergio/cashpilot-worker`) | yes | yes | no |
| The services a worker deploys | all | most | some |

The UI and worker images are published for `linux/amd64` and `linux/arm64`. A 32-bit Pi cannot run them. A Pi 3, 4 or 5 on the 64-bit Pi OS can.

Which services have an ARM build is a fact about the provider, not about CashPilot. Each [service guide](guides/README.md) lists it under Docker Configuration, and the catalog entry's `docker.platforms` field (see [the schema](https://github.com/GeiserX/CashPilot/blob/main/services/_schema.yml)) is where that line comes from. As of September 2026, [ProxyLite](guides/proxylite.md) and [ProxyRack](guides/proxyrack.md) publish x86-64 only. Every other Docker-deployable service in the catalog has an arm64 build.

## How a deploy picks the right build

Most images are multi-architecture. Docker reads the manifest and pulls the build for the host by itself, and CashPilot does nothing special.

Two cases need help, and both are handled for you.

**Images whose ARM builds Docker cannot select.** [Traffmonetizer](guides/traffmonetizer.md) publishes its ARM builds as separate tags (`arm64v8`, `arm32v7`) and labels all of them `linux/amd64`. The catalog names the tag per architecture (`docker.image_by_arch`) and the deploy picks it from the architecture the worker reports in its heartbeat. The worker itself needs no change.

**Providers with no build for your CPU.** Before a deploy, the preflight compares the worker's CPU with the entry's `platforms`, including the 32-bit ARM variant: a v7 board runs v5 and v6 builds, but a Pi Zero (v6) cannot run a v7 build, and the preflight knows the difference. If the provider publishes nothing for that CPU, the deploy dialog says so and explains that the container would die with `exec format error`. You can still deploy. That is the right call if your Docker runs foreign images under emulation (Docker Desktop with Rosetta, or binfmt with qemu). CashPilot cannot see the host's emulation setup from inside the worker container, so it does not claim to.

## Exporting a compose file for an ARM box

The compose export has no worker to ask, so tell it the target:

```
GET  /api/compose/<slug>?arch=arm64
GET  /api/compose?arch=arm64
POST /api/compose            {"slugs": ["traffmonetizer"], "arch": "arm64"}
```

`arch` accepts `amd64`, `arm64` or `arm`, and also a raw machine name such as `aarch64` or `armv7l`. Without it the export writes the catalog's default image, which for Traffmonetizer is the x86-64 build.

## Checking a box by hand

```bash
uname -m            # aarch64 = arm64, armv7l = 32-bit arm, x86_64 = amd64
docker version --format '{{.Server.Arch}}'
```

If a container you started by hand exits at once and `docker logs` shows `exec format error`, the image has no build for that CPU. For Traffmonetizer, use the `arm64v8` or `arm32v7` tag explicitly.

## Keeping the catalog honest

A `platforms` entry with no build behind it is a promise a Pi user acts on. The [weekly catalog liveness check](https://github.com/GeiserX/CashPilot/blob/main/.github/workflows/catalog-liveness.yml) runs [`scripts/check_catalog_liveness.py`](https://github.com/GeiserX/CashPilot/blob/main/scripts/check_catalog_liveness.py), which reads every image's manifest and reports a declared platform the registry does not publish as a catalog problem. A provider dropping its ARM build is caught within a week.
