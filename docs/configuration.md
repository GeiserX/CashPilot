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
| `CASHPILOT_ADMIN_API_KEY` | unset | Bearer token for API access without a session. | — |
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

For **NVIDIA**, `/dev/dri` is not the mechanism — install the NVIDIA Container
Toolkit and the worker will find `nvidia-smi`, which reports the real model name
rather than just a device count.

Passing a device into the worker only lets the **worker** see it. A deployed GPU
**service** needs the device too — declare it in that service's catalog entry.

## Compose-level

These are read by the compose files, not by CashPilot itself.

| Variable | Default | What it does |
|---|---|---|
| `CASHPILOT_BIND_ADDR` | `127.0.0.1` | Which host interface publishes the **UI** port. |
| `CASHPILOT_WORKER_BIND_ADDR` | `127.0.0.1` | Which host interface publishes the **worker** port, in the fleet compose. The worker holds the Docker socket — root-equivalent on the host — so publish it only on an interface the UI needs, never `0.0.0.0`. |
