# cashpilot-anyone

An unofficial Anyone Protocol relay container for [CashPilot](https://github.com/GeiserX/CashPilot). It is not made, endorsed or supported by the Anyone Protocol project.

## Why it exists

The vendor's multi-arch image, `ghcr.io/anyone-protocol/ator-protocol:latest`, was last built in April 2025. Newer releases go only to separate per-architecture images. The vendor image also starts as root, chowns its data directory and then switches to the `anond` user, so it needs the CHOWN, DAC_OVERRIDE, FOWNER, SETUID and SETGID capabilities. CashPilot drops every capability from the containers it runs, so that image crash-loops there.

## What it is

- Debian bookworm slim, pinned by digest.
- The vendor's own `anon` package at the version in `VERSION`, installed from their signed apt repository https://deb.en.anyone.tech (`anon-live-bookworm`). The signing key is committed as `anon.asc`; its fingerprint is `DC73B31AA1F797B180A87CBC7571AA42A0CBEFE9`, the one published in https://github.com/anyone-protocol/ator-protocol/blob/main/README.md, and the build checks it.
- The `anond` user baked in as uid 100, gid 101: the same ids as in the vendor image. A volume that image wrote, identity keys included, is readable here without a chown.
- A small entrypoint that never changes ownership or permissions. It checks that `/etc/anon/anonrc` is readable and `/var/lib/anon` is writable, says how to fix it when not, then runs `anon -f /etc/anon/anonrc --User ""` as PID 1.

The `--User ""` is there because every anonrc written for the vendor image says `User anond`. Already running as anond, anon cannot switch users, and with that line it crashes at start. The command-line value overrides the file, also after a reload, so an existing anonrc works unedited. You can delete the line from your anonrc, but you do not need to.

anon sizes its cell queues from the host's RAM, three quarters of it, and knows nothing about the container's memory limit. On a 32 GB host a busy relay could grow its queues far past 1536 MB and be killed. So when the container has a memory limit and your anonrc sets no `MaxMemInQueues`, the entrypoint passes `--MaxMemInQueues` at half the limit, 768 MB under the catalog's 1536 MB, never below anon's 256 MB floor. A `MaxMemInQueues` line in your anonrc wins. It is read at start, so a line you add later takes effect on the next restart, not on a `SIGHUP` reload: the command-line value outranks the file until then.

It runs under the hardening CashPilot gives every earner, with no capability added back: all capabilities dropped, `no-new-privileges`, not privileged, 512 pids and the catalog's 1536 MB. A relay uses about 250 MB after start.

## Volumes and anonrc

The same layout as the vendor image, so switching keeps the relay's identity:

| Path | Holds |
|---|---|
| `/var/lib/anon` | The relay identity keys, its state and its cache. Losing it retires the relay's reputation. |
| `/etc/anon` | Your `anonrc`, and `notices.log` if your anonrc logs there. |
| `/run/anon` | Runtime files. Nothing needs it without a `ControlSocket`. |

A fresh named volume mounted at these paths starts owned by 100:101, so nothing needs a chown. A host directory (a bind mount) must be owned by 100:101: `chown -R 100:101 <dir>`. The anonrc needs `AgreeToTerms 1`; anon refuses to start without it. The ORPort must be above 1024 (9001 by default), since the relay holds no capability to bind a lower port. The setup guide is https://github.com/GeiserX/CashPilot/blob/main/docs/guides/anyone-protocol.md

## Use

CashPilot deploys it for you. By hand:

```sh
docker run -d --name anyone-relay \
  --cap-drop ALL --security-opt no-new-privileges:true --pids-limit 512 --memory 1536m \
  -p 9001:9001 \
  -v anon-data:/var/lib/anon -v anon-config:/etc/anon -v anon-run:/run/anon \
  --restart unless-stopped \
  drumsergio/cashpilot-anyone:0.4.10.2-r2
```

`docker kill -s HUP <container>` reloads anonrc. `docker stop` shuts the relay down at once and cleanly.

The health check passes while anon is listening on an ORPort set in anonrc (an advertised-only `NoListen` ORPort is skipped). It cannot prove that port is reachable from the internet, which the relay needs before it publishes itself; `notices.log` says so when it is not.

## Switching from the vendor image

Stop the old container and start this image on the same three volumes or directories. Nothing else changes. The relay keeps its fingerprint: the smoke test starts a relay with the vendor image, then this image on its volumes, and checks that both fingerprints match.

## Tags

- `<anon version>-r<revision>`, for example `0.4.10.2-r1`: never changes once pushed. Pin this one.
- `<anon version>`, for example `0.4.10.2`: the newest revision of that anon version.

There is no `latest` tag. Platforms: `linux/amd64`, `linux/arm64`. The vendor publishes no 32-bit ARM package.

## Upgrades

A weekly job reads the newest anon version from the repository's package index for both architectures, builds and tests it, and opens a pull request. Merging it publishes the new tag. The repository keeps only its newest package, so an old pin stops building once the vendor releases; images already published keep working.

Source: https://github.com/GeiserX/CashPilot/tree/main/images/anyone-protocol
