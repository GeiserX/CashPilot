# Security defaults

CashPilot runs unattended, holds credentials for services that pay you real money, and talks to a worker that has the Docker socket — which is equivalent to root on that host. So it needs a stated position on what you may switch off, what you may not, and above all **what happens when you just follow the quickstart**.

The governing principle:

> You may choose to weaken your own installation, but never by accident and never by default.

If you genuinely want an open bind address, that is your call. It has to be an explicit, documented decision — not the consequence of not knowing there was a decision to make.

A fresh install with no configuration at all is secure. You should not have to read this page to be safe; you should only need it to deliberately change something.

---

## Tier 1 — always on, not configurable

These have no off switch. If you need one of them disabled, CashPilot is the wrong tool for that job, and we would rather say so than ship a flag that quietly makes everyone less safe.

| Behaviour | Why there is no toggle |
|---|---|
| **Credentials encrypted at rest** | The database holds the keys to accounts with money in them. There is no plaintext mode. See [the encryption key](#backing-up-the-encryption-key) below. |
| **Deployed containers drop all capabilities**, get `no-new-privileges`, and a PID limit | These images are third-party and closed-source. They get the minimum kernel surface. Capabilities are granted per-service from the catalog, never globally. |
| **Privileged containers are refused** | A privileged container is not isolated in any meaningful sense. No service in the catalog needs one. |
| **System volume roots are blocked** | A container that can mount `/etc` or `/var/run` owns the host. Specific paths can be opted in (tier 2), but the blanket block cannot be removed. |
| **Host devices are allowlisted, and per-service** | Passing a host device into a container widens what that container can touch, so it is not something to enable casually. A deploy may request a device only if **its own** catalog entry declares it *and* the device is on a fixed ceiling — today that ceiling is `/dev/net/tun` alone, for [Mysterium](guides/mysterium.md). One service declaring a device does not let any other request it, and anything outside the ceiling is refused rather than quietly dropped. |
| **No telemetry, no phone-home** | Absent rather than opt-out. A toggle would imply the capability exists; it does not. There is no code that reports anything about you anywhere. |
| **Volumes holding irreplaceable state are protected from deletion** | Node identities and generated wallets have no server-side copy. See [what counts as irreplaceable](#irreplaceable-state). |

## Tier 2 — configurable, secure by default

You can change all of these. None of them require changing for a normal install.

| Setting | Default | What changing it costs you |
|---|---|---|
| `CASHPILOT_BIND_ADDR` | `127.0.0.1` | The dashboard can command a Docker-socket worker. Exposing it publicly exposes the host. Prefer a VPN or an authenticating reverse proxy. |
| `CASHPILOT_WORKER_BIND_ADDR` | `127.0.0.1` | The worker API is equivalent to root on that machine. Never publish port 8081. |
| `CASHPILOT_METRICS_ENABLED` | off | `/metrics` exposes balances and hostnames. If you enable it, set `CASHPILOT_METRICS_TOKEN` too. |
| `CASHPILOT_ALLOWED_VOLUME_ROOTS` | empty | Opts specific host paths past the volume block. Each entry is a deliberate widening; system paths are still refused. |
| `CASHPILOT_ALLOW_EPHEMERAL_KEY` | off | Lets CashPilot start when the encryption key cannot be persisted. Every credential then dies on the next restart. |
| `allow_delete_critical` (per request) | refuses | Permits deleting a volume that holds irreplaceable state. There is no undo. |
| Alert delivery (ntfy / webhook / Telegram) | inert | Nothing is sent anywhere until you configure a target. |
| Image tags | mostly unpinned | Only some service images in this catalog carry a version tag; the rest follow the image's default tag, so an upstream push changes what runs on your next deploy. The desktop app pins every service image by digest. CashPilot's own images are pinned to a release series in both compose files. |

## Tier 3 — preference, no security dimension

Display currency, collection interval, retention window, theme. Set them to whatever you like.

---

## Irreplaceable state

Some services keep state that cannot be recovered if it is destroyed — there is no server-side copy and no reset link:

- **Storj** — the node identity is proof-of-work bound, takes hours to regenerate, and carries the held payout balance.
- **Mysterium** — the keystore *is* the node identity.
- **Anyone Protocol** — the relay identity key carries the relay's earning history.
- **ProxyBase Markets** — the wallet is generated inside the volume. That volume is the money.

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

That last mechanism matters more than it looks. The at-rest encryption boundary is a **naming convention** — a config key is encrypted when it matches a known secret suffix. An audit of this page found that a collector argument named `cookie`, `seed`, `mnemonic` or `private_key` would have been stored in plaintext, purely because nothing enforced the convention. The suffix list was widened and the test now fails if a new collector adds a credential field that would not be encrypted.

## What is deliberately not encrypted

Account emails, API URLs, and public relay fingerprints are stored as-is. Emails are identifiers shown back to you in the UI, and fingerprints are published by the networks themselves. Each exception is listed explicitly in the test with its reason, so adding another is a conscious decision rather than an oversight.

## Reporting a problem

See [SECURITY.md](https://github.com/GeiserX/CashPilot/blob/main/SECURITY.md). Please do not open a public issue for a vulnerability.

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
typical bandwidth-sharing service, and more for a busy storage node. It turns
off raw sockets unless registered with `--net-raw`, gains little for services on
host networking, and cannot run at all on stock Unraid, where a VM is the better
boundary. The figures, the install steps and the details are in
[the gVisor section](home-network-security.md#7-gvisor-optional).

If you have installed a runtime and want a specific service in it, set `runtime`
on that service and own the outcome. The allowlist is read from your daemon, so
you cannot select something the host does not have; that would only fail later
with an error you could not act on.
