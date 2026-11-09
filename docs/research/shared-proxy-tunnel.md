# One tunnel per proxy: what proxied copies cost, and the cheapest safe design

Design note behind the shared tunnel of [proxied copies](../proxies.md#one-tunnel-per-proxy).
Date: 2026-11-09.

## The problem

A proxied copy runs an earner on one box while its traffic leaves from another
public IP. Until this change every copy was two containers: the earner and a
tunnel of its own, the earner living in the tunnel's network namespace. A
Tailscale tunnel runs its own `tailscaled` and joins the tailnet as its own
ephemeral device.

Copies through the same proxy already share its exit IP, so a tunnel each buys
them nothing. But the copies are what a user adds, and memory grew with them.

## What we measured

A box running seven copies through one Tailscale exit node (Docker on btrfs):

| | per tunnel | 7 tunnels |
|---|---|---|
| cgroup `memory.current` | 43.7 to 53.4 MB | **339 MB** (147 anon, 175 file, about 17 kernel) |
| `docker stats` | 35.3 to 41.2 MiB | about 271 MiB |
| `tailscaled` anonymous heap | 20.0 to 22.0 MB, **flat across traffic** (138 MB moved: 20.8 MB; 10 MB moved: 20.4 MB) | |
| startup peak | 79 to 114 MB (`tailscale up`, the 34 MB CLI paged in, the probes) | |
| the 7 earners they carried | | 190 MB (101 anon) |

The tunnels cost more than the earners they carried, and nearly all of a
tunnel's cost is fixed. On btrfs the page cache is not shared between
containers: every `tailscaled` mapping is private, so each container pays for
its own copy of the binary. On overlay2 those pages would be shared.

The exit box served one tailnet peer per copy (7 of its 28 peers were these
tunnels), and each tunnel was a device in the tailnet admin console.

The lab (`scripts/proxy_shared_tunnel_lab.sh`, a local headscale tailnet, Docker
on overlayfs, an idle stand-in earner) drives the worker's own code. Sum of the
proxy's tunnels' cgroup `memory.current`, 25 seconds after the last deploy:

| | N=1 | N=7 |
|---|---|---|
| one tunnel per copy (the base branch) | 1 tunnel, 15.6 MiB | 7 tunnels, 110.1 MiB |
| one tunnel per proxy (this change) | 1 tunnel, 15.0 MiB | 1 tunnel, 15.8 MiB |

The lab tunnel is smaller than a production one: overlayfs shares the
binaries' page cache between containers, the test tailnet has two nodes, and
the stand-in earner moves almost nothing. The shape is the point: the tunnel
side stops growing with the copies.

## The options

All memory figures are the tunnel side only; earners cost the same in every option.

| | Design | Per copy | Per exit, per box | Fail closed | Runs on |
|---|---|---|---|---|---|
| **A** | One tunnel per (box, proxy); every copy joins it with `container:` | 0 | one tunnel (about 45 to 50 MB for Tailscale) | Unchanged: same nftables table, kernel TUN, fwmark rule, ready gate | Everywhere the tunnel runs today, Docker Desktop included. Podman pods are this model natively. |
| **C** | Kernel WireGuard: a `wg` interface created in the host namespace and moved into an otherwise empty holder namespace the earner joins | about 0.5 to 1 MB (estimate, not measured) | no daemon on either side | By construction: the namespace holds only `lo` and `wg0`, and the UDP socket stays in the host namespace | Rootful Linux with the `wireguard` module. Not rootless Docker or rootless Podman. |
| **B** | A gateway container per exit; earners on an `--internal` bridge with their default route pointed at it | 0 | about the same as A | The gateway's forward chain allows only the tunnel; a dead gateway means no next hop | Needs route injection into each earner, an events watcher, its own DNS handling |

Not ranked:

- **Host policy routing with no container at all.** Tailscale cannot choose an
  exit node per source address (an upstream request for it was declined, and a
  node cannot use an exit node while advertising one). It would need our own
  tunnel plus `ip rule` edits on the host, which only works on rootful Linux
  and can break the host's own networking. Option C gets the same memory
  inside a namespace, without touching the host's routes.
- **A shared tun2proxy for SOCKS5 and HTTP proxies.** That is option A for
  those kinds, and comes with it.
- **Routing at the routers.** Needs capable routers at both ends; nothing we
  can ship.
- **tsnet, or tailscaled in userspace mode with a SOCKS listener.** Both cost
  more memory, not less, and userspace mode dials from the box itself when the
  exit node's route is missing ([why the tunnel runs in kernel mode](../proxies.md#tailscale-exit-nodes)).

## The decision

1. **Option A now.** One tunnel per (box, proxy), named `cashpilot-tunnel-p<id>`,
   tailnet host name `cashpilot-p<id>`. It saves almost all of the memory with
   no new requirement on anyone's host, and nothing new to set up.
2. **Option C later, as an advanced mode,** once a lab has measured it,
   offered only where the worker finds a rootful Linux engine with the
   `wireguard` module. Option A stays the fallback everywhere.

## How option A works

- **Who belongs to which tunnel.** An earner's tunnel is the container its
  `NetworkMode` names, never a name lookup. That one rule makes legacy pairs
  (one tunnel per copy, from older workers), a half-finished move and the
  shared tunnel all read the same way in the heartbeat.
- **Adding copy N+1.** If the proxy's tunnel runs, is ready, and was started on
  the same settings (a digest kept in its root-only secret volume, never a
  label) and the same image, only the earner is created. No other copy is
  touched.
- **Replacing the tunnel** (an edited proxy, a new tunnel image): a new tunnel
  starts under a staged name and proves its exit while the old one keeps
  carrying its copies. Then each copy is recreated inside the new one. A
  container's namespace is fixed when it is created, so a restart is not
  enough. The worker rebuilds each copy from `docker inspect` (image,
  environment, command, labels, capabilities, limits), creating the clone
  first so a refusal leaves the copy as it was. Then the old tunnel goes. On a
  failure halfway, the copies already moved are moved back.
- **A stopped tunnel** on the same image is started in place with the
  settings rewritten. Its copies keep their `NetworkMode`, since the container
  id does not change, and are restarted into the new namespace.
- **Stops are written down.** With a tunnel per copy, a stopped earner beside
  a ready tunnel could only mean a reboot or a crash, so the heartbeat started
  it. With a shared tunnel that is also what a stopped copy looks like while
  its siblings run. So a stop writes the earner's name to `/data/.proxied_held`
  before anything is stopped (and refuses if it cannot), a start or a removal
  clears it, and the heartbeat never starts a held copy. The tunnel stops when
  no copy that should run is left in it, and is removed with its secret volume
  when no copy is left at all.
- **Traffic and the cap.** Every copy reports its tunnel's counters and id.
  The cap already keys each baseline by `worker:tunnel id`, so N entries with
  one id count once. Per-copy traffic is gone; per-proxy-per-box traffic is
  what the UI shows. That loss is accepted.
- **Migration.** At worker start, per proxy, the settings are read back from
  a running, ready legacy tunnel's secret files (nothing is asked of the UI),
  the shared tunnel is started and proves its exit, and each legacy copy is
  recreated inside it before its old tunnel is removed. A legacy pair that was
  stopped moves held, so it stays stopped. Any failure leaves the pairs not
  moved yet as they are: each is valid and fails closed. A proxy with no
  running tunnel moves on its next start. Running it again does nothing.

## The fail-closed argument

1. The firewall loads before anything else. Before `tailscaled` or
   `tun2proxy` starts, `cp-tunnel` loads `table inet cashpilot` with an output
   policy of drop. Egress on the real interface is allowed only for
   tailscaled's own fwmark, or for the proxy's address and port.
2. Earners cannot forge that mark: they get no `NET_ADMIN`, `NET_RAW` or
   `SYS_ADMIN`. Sharing changes nothing here. N earners in one namespace are N
   unprivileged processes behind the same table.
3. Exit down, `tailscaled` crashed, re-authentication failed: no route through
   `tailscale0`, so the drop policy applies. Kernel mode means no userspace
   dialer.
4. The tunnel container dies or restarts: the earners stay in the old
   namespace, which keeps only `lo`. The heartbeat restarts them into the new
   one only after `/run/ready` is written, which happens only after the
   firewall is loaded and a probe saw an exit that is not the box's own.
5. Reboot or Docker restart: earners have restart policy `no`, so Docker never
   starts one before the tunnel. Only the heartbeat gate does.
6. The LAN and tailnet fence (private and tailnet ranges dropped on the way
   into the tunnel) applies to the whole namespace, so to every copy in it.
7. New: copies in one namespace see each other's sockets in `/proc/net` and can
   reach each other's `127.0.0.1` listeners. They still cannot sniff traffic or
   change the firewall. One `tailscaled` failure cuts every copy on that proxy
   on that box; it fails closed, and those copies already shared the exit.

## How it is tested

- Unit tests (`tests/test_proxy_shared_tunnel.py`) run the real module against
  an in-memory Docker that tracks labels, status, `NetworkMode`, the secret
  volume and the ready file: reuse, replacement, a tunnel that cannot start,
  stop and start of one copy among several, held copies and the heartbeat, a
  reboot, the cap counting one tunnel once, `remove_all` keeping a tunnel
  another service uses, and migration (idempotent, untouched on failure,
  stopped pairs stay stopped).
- `scripts/proxy_tunnel_mutants.py` applies twelve mutants, one per promise
  above, and requires every one to turn those tests red.
- `scripts/proxy_shared_tunnel_lab.sh` runs against a real Docker daemon and a
  local headscale tailnet. With two earners in one tunnel it checks egress
  through the exit only, no interruption of one copy by another's stop, no
  tailnet access, no DNS name on the tunnel's interface, no interface during a
  tunnel restart, and no escape or packet with the exit node stopped,
  `tailscaled` frozen or killed, or no exit node set. Three negative controls
  must turn those checks red: the firewall deleted, a copy created on the
  bridge instead of inside the tunnel, and a tunnel image whose output policy
  is accept. Then it drives the worker's own code with 1 and 7 copies, on this
  tree and on the base branch, counts the tunnels, measures cgroup memory, and
  migrates copies the base branch deployed.

## Follow-ups

- **Recover in place.** Supervise `tailscaled` and `tun2proxy` inside the
  tunnel and restart the process instead of exiting, removing `/run/ready`
  during the gap. The namespace and the firewall survive, so the copies need
  no restart: a gap of seconds instead of a heartbeat.
- **Shrink the tunnel.** Measure `GOMEMLIMIT` and `GOGC` for `tailscaled`
  (start at 64 to 96 MiB), build one multicall binary so the 34 MB CLI is not
  paged in at start, and set a memory limit above the startup peak.
- **A copy that wants its own tunnel,** for owners who do not want two
  providers' software in one namespace.
- **CashPilot Desktop** still runs one tunnel per copy and gets the same change
  separately.
- **Kernel WireGuard (option C).** A one-shot privileged helper creates the
  interface and moves it into a `--network none` holder; on the exit side, a
  one-shot helper sets up the interface, forwarding and NAT, and exits. The
  same leak suite and negative controls as option A.
- **Your tailnet policy.** Grant the tunnels' tag only `autogroup:internet`
  through the exit node, and nothing into the tag ([before you add one](../proxies.md#tailscale-exit-nodes)).
