# Configuration reference

Every `CASHPILOT_*` setting, what reads it, and — where a file can also supply
the value — **which one wins**.

That last column is the reason this page exists. Three settings look identical
from the outside (a secret, supplied by an environment variable or by a file
under `/data`) and resolve in three *different* directions. Each behaviour is
defensible on its own; together they are impossible to guess.

!!! warning "The precedence is not uniform, and the differences are deliberate"

    - **Credential-encryption key** — the **file wins**. Switching keys would make
      every stored credential unreadable, so an existing `/data/.fernet_key` beats
      `CASHPILOT_ENCRYPTION_KEY`, and CashPilot logs loudly when they differ.
    - **Session-signing key** — the **environment wins**. Sessions are cheap to
      invalidate, so `CASHPILOT_SECRET_KEY` takes precedence and the file is only
      a fallback.

    If you set an environment variable and nothing changed, this is why.

## UI

| Variable | Default | What it does | Precedence |
|---|---|---|---|
| `CASHPILOT_SECRET_KEY` | generated | Signs session cookies. | **Env wins**, then `/data/.secret_key`, then a generated key that is persisted. A known-placeholder value is ignored. |
| `CASHPILOT_ENCRYPTION_KEY` | generated | Fernet key for credentials at rest. | **File wins.** An existing `/data/.fernet_key` beats this; the env key is adopted only when no file exists. |
| `CASHPILOT_ALLOW_EPHEMERAL_KEY` | `false` | Allow starting when the encryption key cannot be persisted. | — |
| `CASHPILOT_API_KEY` | from `/fleet` | Shared **enrolment** key. Not an ongoing credential — see [Fleet](fleet.md). | Env, else `/fleet/.fleet_key`, else generated there. |
| `CASHPILOT_ADMIN_API_KEY` | unset | Bearer token for API access without a session. Grants **owner**: it can deploy, stop and remove containers and read stored credentials. | — |
| `CASHPILOT_READONLY_API_KEY` | unset | Bearer token for **reporting only**. Accepted on a small allowlist of GET endpoints (earnings summary and breakdown, fleet summary, health scores, deployed services) and refused everywhere else, including on endpoints added in future. Use this for a dashboard tile, a Grafana panel or Home Assistant sensors rather than handing them a key that controls containers. | — |
| `CASHPILOT_DATA_DIR` | `/data` | Where the database and keys live. | — |
| `CASHPILOT_FLEET_DIR` | `/fleet` | Where the shared enrolment key lives. | — |
| `CASHPILOT_BASE_URL` | unset | Absolute base URL, for links in notifications. | — |
| `CASHPILOT_SECURE_COOKIE` | auto | Force the `Secure` cookie flag. | — |
| `CASHPILOT_SESSION_EPOCH` | unset | Bumping this invalidates every existing session. | — |
| `CASHPILOT_TRUSTED_PROXY` | unset | Trust `X-Forwarded-For` from these addresses. | — |
| `CASHPILOT_COLLECT_INTERVAL` | `60` | Minutes between earnings collections. | — |
| `CASHPILOT_HOSTNAME_PREFIX` | `cashpilot` | Prefix for managed container names. | — |
| `CASHPILOT_VERSION` | `dev` | Set by the image build. Shown in the sidebar. | — |
| `CASHPILOT_METRICS_ENABLED` | `false` | Serve `/metrics`. | — |
| `CASHPILOT_METRICS_TOKEN` | unset | Require `Authorization: Bearer` on `/metrics`. | — |
| `CASHPILOT_UPDATE_CHECK` | `on` | Set to `off` to disable the once-a-day check for a newer release. See below. |
| `CASHPILOT_NTFY_URL` | unset | ntfy endpoint for alerts. | — |
| `CASHPILOT_WEBHOOK_URL` | unset | Generic webhook for alerts. | — |
| `CASHPILOT_TELEGRAM_BOT_TOKEN` | unset | Telegram alerts. | — |
| `CASHPILOT_TELEGRAM_CHAT_ID` | unset | Telegram alerts. | — |
| `CASHPILOT_WORKER_ALLOWED_HOSTS` | unset | Restrict which hosts the UI will proxy to. | — |
| `CASHPILOT_WORKER_ALLOW_METADATA` | `false` | Allow proxying to cloud metadata IPs. Leave off. | — |
| `CASHPILOT_WORKER_URL_POLICY` | strict | How worker URLs are validated. | — |

## Worker

| Variable | Default | What it does | Precedence |
|---|---|---|---|
| `CASHPILOT_UI_URL` | — | **Required.** Where to send heartbeats. | — |
| `CASHPILOT_API_KEY` | — | **Required for enrolment only.** After enrolling, the worker uses its own key from `/data/.worker_key`. | — |
| `CASHPILOT_WORKER_NAME` | hostname | Display name. **Set it.** Inside a container the default is the container ID, which Docker regenerates on every recreate. | — |
| `CASHPILOT_WORKER_URL` | detected | The URL this worker **advertises**. | — |
| `CASHPILOT_PORT` | `8081` | The port this worker **advertises** — see the note below. | — |
| `CASHPILOT_WORKER_NETWORK` | detected | `residential` or `hosting`. | — |
| `CASHPILOT_EGRESS_DETECT` | on | Hourly public-IP lookup. `off` disables it. | — |
| `CASHPILOT_EGRESS_IP` | unset | State the public IP directly. A LAN or tailnet address is rejected. | — |
| `CASHPILOT_EGRESS_IP_URL` | unset | Custom IP-echo endpoint. | — |
| `CASHPILOT_ALLOWED_VOLUME_ROOTS` | unset | Host paths a deploy may bind-mount. | — |
| `CASHPILOT_PIDS_LIMIT` | unset | `pids` limit applied to managed containers. | — |
| `CASHPILOT_DATA_DIR` | `/data` | Where `.worker_id` and `.worker_key` live. | — |

!!! danger "`CASHPILOT_PORT` does not change the port the worker listens on"

    The listen port is fixed at `8081` by the image's `CMD`. `CASHPILOT_PORT`
    only changes the port the worker **advertises** to the UI. Setting it alone
    makes the worker advertise a port nothing is listening on, and the UI's
    container commands then fail with nothing in the logs connecting the two.

    To actually move the port, override the container's `command:` **and** set
    `CASHPILOT_PORT` to match.

## GPU passthrough

CashPilot reports a worker's GPU as one of three answers — **yes**, **no**, or
**unknown** — and inside a container the honest answer is almost always
*unknown*: the absence of a GPU there says nothing about the host.

That matters because four services only earn with a real GPU (Salad, Nosana,
io.net, Vast.ai), and a GPU service deployed **without** the device starts,
reports healthy, and earns nothing. It is the same shape as the Mysterium
`/dev/net/tun` failure.

To let the worker see an Intel or AMD GPU, uncomment the block in the compose
file:

```yaml
devices:
  - /dev/dri:/dev/dri
```

!!! warning "Only on a host that actually has one"

    Docker **refuses to start a container** when a listed device does not exist,
    so this is shipped commented out. Uncommenting it on a GPU-less host breaks
    the worker outright.

### NVIDIA is a different mechanism

`/dev/dri` does nothing for an NVIDIA card, and installing the
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
is only the **prerequisite** — the toolkit on its own does *not* hand the GPU to
a Compose service. You have to ask for it as well, with **either** of these:

=== "Shorthand"

    ```yaml
    gpus: all
    ```

=== "Explicit reservation"

    ```yaml
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    ```

Both are Compose-spec attributes and both were validated against Compose
v2.40.3. Pick one; do not set both. Use the explicit reservation when you need
to pin particular cards, which it can do via `device_ids` and `capabilities`.

!!! warning "These fail on a GPU-less host too"

    Verified: on a machine with no NVIDIA card, *both* forms exit 1, the
    reservation form reporting `could not select device driver`. So like
    `/dev/dri`, they ship commented out rather than enabled by default.

Once the GPU is actually allocated, the worker finds `nvidia-smi` and reports
the real model name rather than just a device count.

Passing a device into the worker only lets the **worker** see it. A deployed GPU
**service** needs the device too — declare it in that service's catalog entry.

## Compose-level

These are read by the compose files, not by CashPilot itself.

| Variable | Default | What it does |
|---|---|---|
| `CASHPILOT_BIND_ADDR` | `127.0.0.1` | Which host interface publishes the **UI** port. |
| `CASHPILOT_WORKER_BIND_ADDR` | `127.0.0.1` | Which host interface publishes the **worker** port, in the fleet compose. The worker holds the Docker socket — root-equivalent on the host — so publish it only on an interface the UI needs, never `0.0.0.0`. |

## Memory

**The shipped compose files set no memory limit, deliberately.** If you set one,
size it from the numbers below rather than from what the container looks like
when idle — because those two figures are very far apart.

### Measured, not estimated

Read from the kernel's own high-water mark (`memory.peak`) on a live install
after 8 hours of normal operation, which covers roughly 8 hourly collection
cycles:

| Container | Steady state | **Peak** | Database |
|---|---|---|---|
| `cashpilot-ui` | ~72 MiB | **207 MiB** | 54.7 MB |
| `cashpilot-worker` | ~65 MiB | **130 MiB** | — |

*Provenance: `drumsergio/cashpilot:1.14.1`, 15 managed containers, 54.7 MB
SQLite database, collectors running hourly in-process under APScheduler.
Figures are `memory.peak` and `docker stats` from the container's own cgroup.*

### Why the peak is what matters

The UI idles around **72 MiB and peaks near 207 MiB** — close to three times
its resting size. Collection runs every service's collector in-process, and the
transient cost of that dwarfs the steady state.

So a limit chosen by looking at a running container is almost certainly too
low. **128 MiB looks generous against 72 MiB and will be exceeded on the first
collection cycle.**

!!! danger "An OOM here does not look like an OOM"

    The container is killed and restarted mid-collection. The dashboard keeps
    serving the last figures it stored, so nothing on screen says anything is
    wrong — the symptom is "earnings stopped updating", days later, which is
    the hardest kind of failure to notice and the hardest to report.

    That is the reason this page gives you a number instead of a limit.

### If you do set one

Leave real headroom above the measured peak. **256 MiB leaves only 49 MiB above
the 207 MiB observed here**, on one install with one database size — a larger
database, more services, or a slower provider that holds connections longer
will all push it up.

```yaml
services:
  cashpilot-ui:
    mem_limit: 384m     # 177 MiB above the measured peak
  cashpilot-worker:
    mem_limit: 256m     # 126 MiB above the measured peak
```

Re-measure on your own install rather than trusting these:

```bash
docker exec cashpilot-ui cat /sys/fs/cgroup/memory.peak
```

## Update check

CashPilot asks GitHub once a day whether a newer release exists, and shows a
dismissible banner if there is one. A fleet running 33 releases behind with no
indication anywhere is the problem this solves.

Three things it deliberately does not do:

- **It never updates anything.** It tells you; you decide. This application
  deploys containers and holds credentials, and nothing about that should happen
  because a version number changed.
- **It never says "up to date".** Offline, firewalled, disabled, or simply not
  run yet all produce *unknown*, and unknown renders nothing at all — no error,
  no spinner, and no reassurance it has not earned.
- **It sends nothing about you.** One unauthenticated `GET` to the public
  releases endpoint. No request body, no identifier, and your version is not
  reported upstream. GitHub learns that an IP asked what the latest release is.

Turn it off entirely and no connection is made:

```yaml
environment:
  - CASHPILOT_UPDATE_CHECK=off
```

The banner is dismissible per version — dismiss `v1.20.1` and it stays gone until
there is a `v1.20.2`, so it cannot become wallpaper.
