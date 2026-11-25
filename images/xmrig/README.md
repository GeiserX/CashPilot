# cashpilot-xmrig

An unofficial XMRig container for [CashPilot](https://github.com/GeiserX/CashPilot). It is not made, endorsed or supported by the XMRig project, and it is not affiliated with them.

The XMRig project publishes no Docker image. The XMRig images on Docker Hub with the most pulls are years old, amd64 only, or default to someone else's wallet. This image is built from XMRig's own source, for amd64 and arm64.

## What it is

- **Upstream XMRig, unmodified.** The build fetches XMRig's release tag from https://github.com/xmrig/xmrig and compiles the commit pinned in `COMMIT`. GitHub reports a valid signature on that commit. The build refuses to compile when the tag no longer points at the pinned commit.
- **The 1% dev fee stays.** XMRig donates 1% of its hashing time to its developers (`src/donate.h`), and 1% is the lowest value its source allows. `--donate-level=0` still gives 1%. We do not patch it.
- **CPU only.** Built without the CUDA and OpenCL loaders.
- **No root.** It runs as uid 10001 and needs no capabilities, devices or privileged mode. It runs under the hardening CashPilot gives every container: all capabilities dropped, `no-new-privileges`, not privileged, 512 pids.

Two XMRig speed-ups need the host's help:

- **Huge pages.** Without them, RandomX loses up to 50% (https://xmrig.com/docs/miner/hugepages). The container uses them with no extra rights once the host reserves them: `sysctl -w vm.nr_hugepages=1280`, and add `vm.nr_hugepages=1280` to `/etc/sysctl.conf` to keep it after a reboot.
- **The MSR mod is never used.** It needs root, `/dev/cpu/*/msr` and a privileged container. Pass `--randomx-wrmsr=-1` so XMRig does not try it. By XMRig's own figures this costs about 6% on a Ryzen 3700X and up to about 30% on some Intel CPUs.

Antivirus tools flag XMRig as a coin miner (PUA). That is expected for any XMRig build.

## Use

CashPilot's XMRig entry deploys this image. To run it by hand:

```sh
docker run -d --name xmrig \
  --cap-drop ALL --security-opt no-new-privileges:true --pids-limit 512 --init \
  --dns 1.1.1.1 \
  --restart unless-stopped \
  drumsergio/cashpilot-xmrig:6.27.0-r1 \
  -o pool.supportxmr.com:3333 -u <your Monero address> -p <worker name> \
  --donate-level=1 --randomx-wrmsr=-1 --http-port=18088 --threads=2
```

The arguments are XMRig's own (`--help` lists them). The image adds nothing to them.

Some DNS filters block mining pools: an AdGuard Home with common blocklists answers `0.0.0.0` for pool domains, and Quad9 answers NXDOMAIN for some of them. The miner then never connects. `--dns 1.1.1.1` avoids that.

The health check passes while XMRig's local HTTP API answers and its pool connection is up. It needs `--http-port=18088` (by default the API listens on 127.0.0.1 only and answers read-only requests). Without that flag the container shows unhealthy. The check does not prove shares are accepted; the pool's dashboard shows that.

## Tags

- `<xmrig version>-r<revision>`, for example `6.27.0-r1`: never changes once pushed. Pin this one.
- `<xmrig version>`, for example `6.27.0`: the newest revision of that XMRig version.

There is no `latest` tag. Platforms: `linux/amd64`, `linux/arm64`. Each one is compiled on a runner of its own architecture, with no emulation.

## Upgrades

A weekly job reads XMRig's newest release and resolves its tag to a commit. It goes on only when GitHub reports a valid signature on that commit. It then builds and tests the new pin on both platforms and opens a pull request. Merging it publishes the new tag.

The tests never mine: GitHub's terms forbid mining on Actions. They run `--version`, `--dry-run`, and a miner with no network that never gets a job.

Source: https://github.com/GeiserX/CashPilot/tree/main/images/xmrig
