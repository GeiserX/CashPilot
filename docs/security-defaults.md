# Security defaults

CashPilot runs unattended, holds credentials for services that pay you real money, and talks to a worker that drives Docker on that host. The shipped compose files put a [Docker socket proxy](#docker-socket-proxy) between the worker and the socket; without it the worker holds the socket itself, which is equivalent to root on that host. So it needs a stated position on what you may switch off, what you may not, and above all **what happens when you just follow the quickstart**.

The governing principle:

> You may choose to weaken your own installation, but never by accident and never by default.

If you genuinely want an open bind address, that is your call. It has to be an explicit, documented decision, not the consequence of not knowing there was a decision to make.

A fresh install with no configuration at all is secure. You should not have to read this page to be safe; you should only need it to deliberately change something.

---

## Tier 1: always on, not configurable

These have no off switch. If you need one of them disabled, CashPilot is the wrong tool for that job, and we would rather say so than ship a flag that quietly makes everyone less safe.

| Behaviour | Why there is no toggle |
|---|---|
| **Credentials encrypted at rest** | The database holds the keys to accounts with money in them. There is no plaintext mode. See [the encryption key](#backing-up-the-encryption-key) below. |
| **Deployed containers drop all capabilities**, get `no-new-privileges`, and a PID limit | These images are third-party and closed-source. They get the minimum kernel surface. Capabilities are granted per-service from the catalog, never globally. |
| **Privileged containers are refused** | A privileged container is not isolated in any meaningful sense. No service in the catalog needs one. |
| **System volume roots are blocked** | A container that can mount `/etc` or `/var/run` owns the host. Specific paths can be opted in (tier 2), but the blanket block cannot be removed. |
| **Host devices are allowlisted, and per-service** | Passing a host device into a container widens what that container can touch, so it is not something to enable casually. A deploy may request a device only if **its own** catalog entry declares it *and* the device is on a fixed ceiling. Today that ceiling is `/dev/net/tun` alone, for [Mysterium](guides/mysterium.md). One service declaring a device does not let any other request it, and anything outside the ceiling is refused rather than quietly dropped. |
| **No telemetry** | Absent rather than opt-out. A toggle would imply the capability exists; it does not. There is no code that reports anything about you anywhere. The outbound calls that do exist (the daily release check, a worker's public-IP lookup, exchange rates) carry no identifier, and the first two can be switched off (tier 2). |
| **Custom services get the catalog hardening and nothing a catalog entry can grant** | An image you add yourself has not been reviewed. It runs with every rule above, no published ports, no host directories and a memory limit, and the worker refuses it any capability, device or host networking. See [custom services](custom-services.md#what-it-is-allowed-to-do). |
| **Volumes holding irreplaceable state are protected from deletion** | Node identities and generated wallets have no server-side copy. See [what counts as irreplaceable](#irreplaceable-state). |

## Tier 2: configurable, secure by default

You can change all of these. None of them require changing for a normal install.

| Setting | Default | What changing it costs you |
|---|---|---|
| `CASHPILOT_BIND_ADDR` | `127.0.0.1` | The dashboard can command a Docker-socket worker. Exposing it publicly exposes the host. Prefer a VPN or an authenticating reverse proxy. |
| `CASHPILOT_WORKER_BIND_ADDR` | `127.0.0.1` | The worker API is equivalent to root on that machine. Never publish port 8081. |
| `CASHPILOT_METRICS_ENABLED` | off | `/metrics` exposes balances and hostnames. If you enable it, set `CASHPILOT_METRICS_TOKEN` too. |
| `CASHPILOT_PROXY_BIND_MOUNTS` | empty | Host folders the [Docker socket proxy](#docker-socket-proxy) lets containers bind, comma-separated. Each entry also counts as a `CASHPILOT_ALLOWED_VOLUME_ROOTS` entry and must pass the same checks (a service folder such as `/mnt/user/storj`, never a whole root). Any container the worker creates may then mount it. |
| `CASHPILOT_COMPOSE_DIR` | empty | Your compose folder, which the proxy then lets the in-app update bind. Unset, the **Update** button tells you the line to add. |
| `CASHPILOT_ALLOWED_VOLUME_ROOTS` | empty | Opts specific host paths past the volume block. Each entry is a deliberate widening; system paths are still refused. |
| `CASHPILOT_ALLOW_EPHEMERAL_KEY` | off | Lets CashPilot start when the encryption key cannot be persisted. Every credential then dies on the next restart. |
| `allow_delete_critical` (per request) | refuses | Permits deleting a volume that holds irreplaceable state. There is no undo. |
| Alert delivery (ntfy / webhook / Telegram) | inert | Nothing is sent anywhere until you configure a target. |
| `CASHPILOT_UPDATE_CHECK` | on | One unauthenticated request a day to GitHub's public releases endpoint, to tell you a newer CashPilot exists. `off` stops it and the banner never appears. |
| `CASHPILOT_EGRESS_DETECT` (worker) | on | One request an hour to a public IP-echo service, so the fleet can warn when two workers share an IP. `off` stops it; `CASHPILOT_EGRESS_IP` states the address instead. See [Egress IP](fleet.md#egress-ip-and-per-ip-limits). |
| Image tags | mostly unpinned | Only some service images in this catalog carry a version tag; the rest follow the image's default tag, so an upstream push changes what runs on your next deploy. The desktop app pins every service image by digest. In the web app you can pin one yourself under the service's **Advanced** box ([Configuration](configuration.md#a-services-image)). CashPilot's own images are pinned to a release series in both compose files. |

## Tier 3: preference, no security dimension

Display currency, collection interval, retention window, theme. Set them to whatever you like.

---

## Irreplaceable state

Some services keep state that cannot be recovered if it is destroyed: there is no server-side copy and no reset link:

- **Storj**: the node identity is proof-of-work bound, takes hours to regenerate, and carries the held payout balance.
- **Mysterium**: the keystore *is* the node identity.
- **Anyone Protocol**: the relay identity key carries the relay's earning history.
- **ProxyBase Markets**: the wallet is generated inside the volume. That volume is the money.
- **Sia (hostd)**: the wallet database and contract state, plus the stored renter data whose loss forfeits the locked collateral.

These are declared as `critical_volumes` in the service catalog. CashPilot refuses to delete them, and tells you what would have been lost rather than just saying no.

## Backing up the encryption key

Your credentials are only as recoverable as `/data/.fernet_key`. Lose it and you re-enter everything, because there is no way to decrypt the stored values without it.

```bash
docker exec cashpilot-ui cat /data/.fernet_key
```

Restoring onto a fresh volume: pass the saved value as `CASHPILOT_ENCRYPTION_KEY`. An existing key file always wins over the environment variable, so setting it on a running instance is safe and changes nothing.

Note this is a **different key** from `CASHPILOT_SECRET_KEY`, which only signs login sessions.

---

## How this is kept honest

A stated posture that nobody checks is just prose. `tests/test_secure_defaults.py` asserts the machine-checkable parts of this page: that every collector credential is either encrypted or explicitly listed as public with a reason, that metrics are off until enabled, that alerting is inert until configured, that the volume allowlist starts empty, that the dashboard binds to loopback in every compose file, and that no telemetry-shaped code exists.

That last mechanism matters more than it looks. The at-rest encryption boundary is a **naming convention**: a config key is encrypted when it matches a known secret suffix. An audit of this page found that a collector argument named `cookie`, `seed`, `mnemonic` or `private_key` would have been stored in plaintext, purely because nothing enforced the convention. The suffix list was widened and the test now fails if a new collector adds a credential field that would not be encrypted.

## What is deliberately not encrypted

Account emails, API URLs, and public relay fingerprints are stored as-is. Emails are identifiers shown back to you in the UI, and fingerprints are published by the networks themselves. Each exception is listed explicitly in the test with its reason, so adding another is a conscious decision rather than an oversight.

## Reporting a problem

See [SECURITY.md](https://github.com/GeiserX/CashPilot/blob/main/SECURITY.md). Please do not open a public issue for a vulnerability.

## Docker socket proxy

The worker creates and runs containers, so something on the host has to hold
the Docker socket. Whoever holds it is root on the host: one
`POST /containers/create` with `"Privileged": true` and a bind of `/` takes the
machine. In the shipped compose files that holder is a proxy, not the worker.

The shipped compose files (`docker-compose.yml`, `docker-compose.fleet.yml`,
`docker-compose.worker.yml`, `docker-compose.build.yml`) run
[sockguard](https://github.com/CodesWhat/sockguard) 2.4.5 as
`cashpilot-socket-proxy`, pinned by digest
(`codeswhat/sockguard:2.4.5@sha256:d15f93e856626ff21f48400034d887874a4dafbbf6bb1e31799511beea07d84c`).
It holds the socket read-only, runs as root with every capability dropped and no
network, and serves a filtered socket in the `cashpilot-docker-api` volume. The
worker mounts that volume and sets `DOCKER_HOST` to it. It has no Docker socket
of its own.

The proxy reads each request, including its JSON body, so it refuses
dangerous containers, not only dangerous URLs:

- **Only the calls the worker makes.** Every other Docker API call is refused:
  swarm, services, secrets, plugins, builds, commit, export, events, attach,
  container update, prune, image push or load. The allow list is the set of
  calls the live test recorded from the worker, its update helper and Compose.
- **Containers.** No privileged mode, no host PID, IPC, user or cgroup
  namespace, `no-new-privileges` required, no unconfined seccomp, AppArmor or
  system paths. Added capabilities only from `NET_ADMIN`, `NET_RAW`, `SETUID`,
  `SETGID` (what the catalog declares), devices only `/dev/net/tun`, runtimes
  only `runc` and the gVisor ones (the worker refuses any other runtime itself,
  before the running container is touched). Host folders only from
  `CASHPILOT_PROXY_BIND_MOUNTS` and `CASHPILOT_COMPOSE_DIR`, so a bind of `/`
  or of the socket is refused. The body is parsed the way Docker parses it, so
  `"privileged": true` in lowercase is refused too.
- **Exec.** Only the exact commands the catalog's readers run (Mysterium's node
  and wallet reads, Anyone Protocol's `anonrc`, the isolation check's firewall
  read, the tunnel sidecar's readiness file). No environment variables at all,
  so `PATH` or `LD_PRELOAD` cannot change what such a command runs.
- **Files into a container** only under `/run/cashpilot-secret` (the tunnel
  sidecar's proxy settings), with no setuid files, device nodes or escaping
  links.

The policy is the `configs` block at the end of each compose file, so it moves
with the file that pins the CashPilot release. An image update does not rewrite
that file, so the worker gets the policy's fingerprint (`CASHPILOT_PROXY_POLICY`)
and compares it with the policy its own catalog needs; when they differ its
status page says to replace the compose file. `scripts/socket_proxy_policy.py`
writes it from the catalog, and `tests/test_socket_proxy.py` fails when a
catalog change adds a reader the policy lacks, or when anyone loosens it.
`scripts/socket_proxy_live_test.sh` runs the real proxy against a real daemon:
every call the worker makes passes, every refusal above is refused, and the
same refused requests sent to the raw socket succeed, which proves each refusal
is the proxy's.

When the proxy refuses a deploy, the dashboard shows its reason, for example
*The Docker socket proxy refused this: container create denied: bind mount
source "/mnt/user/storj" is not allowlisted.* `docker logs cashpilot-socket-proxy`
has one line per call, refusals included.

**Not yet a root boundary.** The proxy closes the one-call ways to root: a
privileged container, a bind of `/` or of the socket, an added capability. It
does not yet stop a compromised worker that takes two steps, because sockguard
2.4.5 has no setting for either of these:

- **Joining another container's process namespace.** sockguard refuses
  `PidMode: host` but lets `container:<name>` through for the PID and IPC
  namespaces. The only switch that refuses it also refuses
  `NetworkMode: container:<id>`, which the tunnel sidecar, the activity
  reader and the isolation check depend on. A container that joins a root
  container's PID namespace can read that container's files through
  `/proc/1/root`. The proxy itself is protected: it holds one capability
  (`WAKE_ALARM`) that no created container may ask for, so the kernel refuses
  the joiner its files. Any other container on the host that holds the Docker
  socket (a dashboard, an auto-updater) is not, and the UI's files are
  readable this way when the UI runs on the same host.
- **A symlink in an allowed folder.** sockguard checks a bind's source as a
  string; Docker follows symlinks when it mounts. A container that binds an
  allowed folder can plant `evil -> /` in it, and a second container that
  binds `<folder>/evil` gets the host's `/` and its socket. This applies to
  every folder in `CASHPILOT_COMPOSE_DIR` and `CASHPILOT_PROXY_BIND_MOUNTS`.
  With both unset, no host folder is bindable at all.

Both need a change in sockguard (a per-namespace switch, and binds that are
exact or symlink-free). Until then, an install that keeps both variables unset
and runs no other socket-holding container on the host is the one where the
proxy stands between the worker and root.

**What a compromised worker can still do** even once those are closed:

- Stop, remove, inspect and read the logs and files of **any** container on the
  host, not only CashPilot's, and read their environment variables.
- Run the allowed reader commands in any container.
- Mount any named volume into a new container, including the UI's
  `cashpilot_data` when the UI runs on the same host.
- Start a container on host networking with `NET_ADMIN`, `NET_RAW` and
  `/dev/net/tun`, which can reconfigure the host's network but not reach its
  files.
- Write into your compose folder, through a container that binds it. A change
  there takes effect the next time you run `docker compose up` yourself, which
  uses the raw socket. Leave `CASHPILOT_COMPOSE_DIR` unset if you update by
  hand, and the folder is not bindable at all.
- Pull images from any registry (custom services need it) and set namespaced
  sysctls on its own containers (the tunnel sidecar needs it).

sockguard can also scope every call to containers, volumes and networks that
carry its owner label, which would close the first three. CashPilot does not
turn that on yet: labels cannot be added to an existing volume, so every
Mysterium identity, EarnApp device id and compose volume created before it
would become unusable through the proxy, and Compose offers to delete and
recreate a volume whose labels change.

Two upstream gaps are not exploitable on current Docker: sockguard does not
decode `HostConfig.Capabilities` (Docker 29 drops that field), and a lowercase
HTTP method skips body inspection (Docker's router answers 404 to it).

**Without the proxy.** An install whose compose file predates it, the Unraid
templates, and a worker started with `docker run` still mount
`/var/run/docker.sock` into the worker, so the worker is root on the host.
[UPGRADING.md](https://github.com/GeiserX/CashPilot/blob/main/UPGRADING.md)
says how to move an existing install. The worker's status page says which one
it uses: *Docker access: socket proxy* or *direct socket (root on this host)*.

## Container runtimes: gVisor where it works

CashPilot supports an optional `runtime` on a deploy spec, allowed only when your
Docker daemon reports it. Nothing selects one for you.

gVisor's `runsc` runtime puts a user-space kernel between a container and
yours. That is a real extra layer against a container escaping through a kernel
bug. It does
not address the two risks that actually occur in this category: attribution of
other people's traffic to your IP address, and containers reaching your LAN.
[Protecting your home network](home-network-security.md) covers those first.

Measured on a standard Linux host, it cost about a fifth of peak throughput and
six to nine times the CPU per byte moved. That is minutes of CPU a month for a
typical bandwidth-sharing service, and more for a busy storage node. Plain
`runsc` cannot resolve names on a Docker network you created, so on CashPilot's
networks it needs its network passthrough mode. It turns off raw sockets unless
registered with `--net-raw`, gains little for services on host networking, and
cannot run at all on stock Unraid, where a VM is the better boundary. The figures, the install steps and the details are in
[the gVisor section](home-network-security.md#7-gvisor-optional).

If you have installed a runtime, `CASHPILOT_CONTAINER_RUNTIME` on the worker puts
its bridge-networked services in it, and `CASHPILOT_CONTAINER_RUNTIME_OVERRIDES`
sets exceptions per service ([configuration](configuration.md)). A deploy spec can
also name a `runtime` for one service. Either way you own the outcome. The allowlist is read from your daemon, so
you cannot select something the host does not have; that would only fail later
with an error you could not act on.
