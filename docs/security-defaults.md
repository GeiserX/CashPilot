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
| `CASHPILOT_COMPOSE_DIR` | empty | Your compose folder, which the proxy then lets the in-app update bind. Opt-in: it also lets containers bind that folder, which weakens the proxy (see below). Unset, update with `docker compose pull && docker compose up -d`; the **Update** button tells you the line to add if you want it. |
| `CASHPILOT_ALLOWED_VOLUME_ROOTS` | empty | Opts specific host paths past the volume block. Each entry is a deliberate widening; system paths are still refused. |
| `CASHPILOT_ALLOW_EPHEMERAL_KEY` | off | Lets CashPilot start when the encryption key cannot be persisted. Every credential then dies on the next restart. |
| `CASHPILOT_CAPTCHA_PROVIDER` | off | Adds a CAPTCHA to the sign-in page. Sign-in then needs JavaScript, and both the browser and the server must reach the provider. See [Protect the sign-in page with a CAPTCHA](#protect-the-sign-in-page-with-a-captcha). |
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

## Protect the sign-in page with a CAPTCHA

The sign-in page can show a CAPTCHA. It stops bots that guess passwords. It is off by default.

Turn it on when people on the internet can reach your CashPilot UI, for example through a reverse proxy or a tunnel. A UI that only your LAN or your VPN can reach does not need it. The rate limit on sign-in is always on, with or without a CAPTCHA.

CashPilot supports three providers:

| Provider | `CASHPILOT_CAPTCHA_PROVIDER` |
|---|---|
| Cloudflare Turnstile | `turnstile` |
| hCaptcha | `hcaptcha` |
| Google reCAPTCHA v2, the "I'm not a robot" checkbox | `recaptcha` |

reCAPTCHA v3 is not supported. It gives a score instead of a pass or a fail.

### Get the keys

Each provider gives you two keys: a site key, which is public, and a secret key.

- **Cloudflare Turnstile:** in the Cloudflare dashboard, open **Turnstile** and select **Add widget**. Add the host name you open CashPilot at, for example `cashpilot.example.com`. Choose the **Managed** mode. Copy the site key and the secret key. You do not need to host your domain on Cloudflare.
- **hCaptcha:** sign in at https://dashboard.hcaptcha.com, add a site, and add the same host name. The secret key is in your account settings.
- **Google reCAPTCHA:** open https://www.google.com/recaptcha/admin/create, choose **reCAPTCHA v2** and then **"I'm not a robot" Checkbox**, and add the same host name.

### Turn it on

Set the three variables on the UI container, for example in the `.env` file next to `docker-compose.yml`:

```bash
CASHPILOT_CAPTCHA_PROVIDER=turnstile
CASHPILOT_CAPTCHA_SITE_KEY=<your site key>
CASHPILOT_CAPTCHA_SECRET_KEY=<your secret key>
```

Then recreate the UI container: `docker compose up -d cashpilot-ui`. The log shows one line that names the provider.

On Unraid, the three fields are under **Show more settings** in the CashPilot template. Apply the template to recreate the container.

If the provider name is unknown, or a key is missing, the UI refuses to start. The error names the variable to fix. CashPilot never runs without the CAPTCHA after you asked for one.

### What changes

- The sign-in page shows the provider's widget above the **Sign In** button.
- CashPilot asks the provider to check the answer before it checks the password. A failed check counts as a failed sign-in attempt, the same as a wrong password.
- If CashPilot cannot reach the provider, sign-in fails with a message that says so. It does not let you in without the check.
- Only the sign-in page lets the browser load the provider's script and frame. Every other page keeps the normal security policy.
- Workers, the Android app and API keys do not use the sign-in page. The CAPTCHA does not affect them.

The sign-in page now needs JavaScript. Your browser must also reach the provider. A LAN-only install still works, as long as the browser can reach the internet. The CashPilot server must reach the provider too, to check each answer.

### If you are locked out

Remove the three variables and recreate the UI container (`docker compose up -d cashpilot-ui`). A plain `docker restart` keeps the old variables. The sign-in page is then the same as before, with no CAPTCHA.

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
[sockguard](https://github.com/CodesWhat/sockguard) 2.4.6 as
`cashpilot-socket-proxy`, pinned by digest
(`codeswhat/sockguard:2.4.6@sha256:9a7142d9f8254e7fde7543e046eff920463f5df27b36d959915b44fb4878d06f`).
It holds the socket read-only, runs as root with every capability dropped and no
network, and serves a filtered socket in the `cashpilot-docker-api-owned` volume. The
worker mounts that volume and sets `DOCKER_HOST` to it. It has no Docker socket
of its own.

The proxy reads each request, including its JSON body, so it refuses
dangerous containers, not only dangerous URLs:

- **Only the calls the worker makes.** Every other Docker API call is refused:
  swarm, services, secrets, plugins, builds, commit, export, events, attach,
  container update, prune, image push or load. The allow list is the set of
  calls the live test recorded from the worker, its update helper and Compose.
- **Containers.** No privileged mode, no host PID, IPC or user namespace
  (host networking is allowed, see *What a compromised worker can still do*
  below; the host cgroup namespace is not), `no-new-privileges` required, no unconfined seccomp, AppArmor or
  system paths. Added capabilities only from `NET_ADMIN`, `NET_RAW`, `SETUID`,
  `SETGID` (what the catalog declares), devices only `/dev/net/tun`, runtimes
  only `runc` and the gVisor ones (the worker refuses any other runtime itself,
  before the running container is touched). Host folders only from
  `CASHPILOT_PROXY_BIND_MOUNTS` and `CASHPILOT_COMPOSE_DIR`, so a bind of `/`
  or of the socket is refused as long as neither variable lists `/`, the
  socket or a folder above it: the proxy takes both as given. The body is parsed the way Docker parses it, so
  `"privileged": true` in lowercase is refused too.
- **Exec.** Only the exact commands the catalog's readers run (Mysterium's node
  and wallet reads, Anyone Protocol's `anonrc`, the isolation check's firewall
  read, the tunnel sidecar's readiness file). No environment variables at all,
  so `PATH` or `LD_PRELOAD` cannot change what such a command runs.
- **Files into a container** only under `/run/cashpilot-secret` (the tunnel
  sidecar's proxy settings), with no setuid files, device nodes or escaping
  links.

The policy is the `configs` block at the end of each compose file, never part
of an image: the worker image is what the policy restricts, so an image update
must not be able to widen it. An image update does not rewrite that file either,
so the worker gets the policy's fingerprint (`CASHPILOT_PROXY_POLICY`) and
compares it with the policy its own catalog needs. When they differ, its log,
its status page and the dashboard's update card name the release and give the
command that brings your own compose file to that release's policy, changing
nothing else:

    docker run --rm -i --network none drumsergio/cashpilot-worker:<version> \
        python -m app.socket_policy < docker-compose.yml > docker-compose.new.yml

The image gets no access to the file and no network; read the diff before you
use the new file. The proxy carries the same fingerprint in its environment,
because Compose does not recreate a container when only a config's content
changes: without it, `docker compose up -d` would leave the proxy on the old
policy. `scripts/socket_proxy_policy.py`
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

**Owner isolation.** The proxy stamps the label `cashpilot.deployed-by=worker`
on every container, volume and network the worker creates, and refuses the
worker everything that does not carry it. The worker cannot inspect, read
files from, stop or remove a container it did not start, cannot mount or delete
a volume it did not create, and cannot join the namespace of a container it
does not own. The UI, the proxy itself, a dashboard or auto-updater that holds
the Docker socket, and every container you started by hand are out of its
reach. The worker also lists only its own containers, so it no longer sees
those. Images carry no owner label, so they are not scoped: a custom service can
still pull any image, and the worker can read one by name. The proxy refuses
the worker an image delete and gives it no list of the host's images, so
CashPilot cannot remove old images for you
([cleaning up old images](getting-started.md#cleaning-up-old-images)).

**Not yet a root boundary.** The proxy closes the one-call ways to root: a
privileged container, a bind of `/` or of the socket, an added capability.
Owner isolation closes joining another container's process namespace, which
read a root container's files through `/proc/1/root`. One two-step way is
left, because sockguard 2.4.6 has no setting for it:

- **A symlink in an allowed folder.** sockguard checks a bind's source as a
  string; Docker follows symlinks when it mounts. A container that binds an
  allowed folder can plant `evil -> /` in it, and a second container that
  binds `<folder>/evil` gets the host's `/` and its socket. This applies to
  every folder in `CASHPILOT_COMPOSE_DIR` and `CASHPILOT_PROXY_BIND_MOUNTS`.
  With both unset, no host folder is bindable at all: the stand-ins the
  compose file uses for them are paths under the null device, where Docker
  cannot create a folder, so nothing can be planted there.

What the worker itself enforces on top, for deploys sent through its API:

- It refuses any bind of the compose folder, anything under it, or a folder
  above it (which would reach the compose file and its `.env` too). Only the
  in-app update needs that folder, and the update does not go through a
  deploy. The proxy still allows the folder, so this stops a deploy sent with
  a worker key, not a compromised worker.
- It lets a deploy bind any path under a `CASHPILOT_PROXY_BIND_MOUNTS` folder,
  with any image and command. So with that variable set, anyone holding a
  worker key (the UI, or whoever reads the plain-HTTP traffic between the UI
  and the worker) can take the symlink route above with two deploys, not
  only a compromised worker. The blocked system folders (`/mnt`, `/home` and
  the rest) do not apply inside a folder you listed.

It needs a change in sockguard (binds that are exact or symlink-free). Until
then, an install that keeps both variables unset is the one where the proxy
stands between the worker and root. That is the default: the in-app update is
opt-in for this reason.

**What a compromised worker can still do** even once those are closed:

- Stop, remove, inspect and read the logs, files and environment variables of
  the containers it started: every earner on its host.
- Run the allowed reader commands in those containers.
- Delete or mount the volumes it created. The worker refuses to delete the ones
  the catalog marks critical (Mysterium's keystore, Storj's identity), but the
  proxy does not know about them, so a compromised worker can delete them
  directly.
- Start a container on host networking with `NET_ADMIN`, `NET_RAW` and
  `/dev/net/tun`, which can reconfigure the host's network but not reach its
  files.
- Write into your compose folder, through a container that binds it. A change
  there takes effect the next time you run `docker compose up` yourself, which
  uses the raw socket, and the folder's `.env` holds whatever keys you put
  there. Leave `CASHPILOT_COMPOSE_DIR` unset if you update by hand, and the
  folder is not bindable at all.
- Create Docker networks, and attach, detach and delete the ones it created.
  The LAN fence needs this to build `cashpilot-isolated` and move earners onto
  it, and sockguard 2.4.6 cannot limit it to that one network. The proxy lets bridge driver options and
  a forced disconnect through, because the fence uses both; custom drivers,
  swarm scope, custom address plans and endpoint settings stay refused, except
  network aliases, which sockguard always lets through. It adds little reach, since the worker
  can already start a container on host networking, but a compromised worker
  can take an earner off the fence.
- Start a container on host networking. The LAN fence's helper and the
  isolation check's control probe need it. The worker itself refuses host
  networking to every earner, and the catalog refuses it to any service with
  `NET_ADMIN`, so only those two use it. The proxy no longer allows the host's
  cgroup namespace: only the Activity reader of a host-network earner needed
  it, and no earner shares the host's network since Mysterium moved onto the
  fenced bridge.
- Pull images from any registry (custom services need it) and set namespaced
  sysctls on its own containers (the tunnel sidecar needs it).

**What that means for the default install.** `docker-compose.yml` runs the UI
and a worker on the same host. Owner isolation keeps a compromised worker out
of the UI: it cannot read the UI's `/data` (`.fernet_key`, the key that
decrypts every service login CashPilot stores), mount `cashpilot_data` into a
container, or read `CASHPILOT_SECRET_KEY`, `CASHPILOT_API_KEY` and
`CASHPILOT_ADMIN_API_KEY` from the UI container's environment. Two ways in are
left. With `CASHPILOT_COMPOSE_DIR` set, it can read the `.env` in your compose
folder and change the compose file, which takes effect at your next
`docker compose up`. And the symlink gap above, with either bind variable set,
reaches the host's root. For a boundary that holds without those conditions,
run the UI on a host with no worker and put the earners behind
`docker-compose.worker.yml` on other hosts, as [Fleet](fleet.md) describes.
A worker still receives the logins of the services you deploy to it, so a
compromised worker leaks those, but not the rest. That holds only while
`CASHPILOT_ADMIN_API_KEY` differs from `CASHPILOT_API_KEY`: every worker host
holds the shared key, and the same value would give it the owner role. A worker
that has not enrolled yet, or lost its own key, still accepts the shared key,
so until then a compromised worker that can reach it can stop or remove its
services. Commands and heartbeats both travel over plain HTTP, carrying the
worker's key and those logins, so keep both directions on a LAN you trust or
inside a VPN such as Tailscale, never on the open internet.

**What owner isolation costs.** On the UI's host, the in-app update updates
the worker only: the UI is not the worker's to recreate, so the dashboard is
updated with `docker compose pull && docker compose up -d`, and the update card
says so. And an earner you started by hand, or from a compose file CashPilot
exported, is invisible to the worker, so the dashboard no longer shows it as an
external service.

**Moving an existing install.** Docker cannot add a label to an existing
volume or network, so the compose files run a one-shot `cashpilot-migrate`
service before the proxy starts. It holds the raw socket only while it runs.
For each earner the worker started it copies every unlabelled volume to a
backup (`<volume>-pre-isolation`) and checks the copy, recreates the volume
with the label, copies the data back and checks it against the backup, then
recreates the earner as it was. It rebuilds `cashpilot-isolated` with the label
and puts its members back. Its record of each finished step is a root-only
folder, `cashpilot-migrate-state`, next to the compose file, so a run killed
at any step is finished by the next one. It never deletes a backup. A volume
another container also uses, or one with a driver or driver options, is left
as it was with a warning. The worker still controls the earner, but refuses
to redeploy it on that volume until you move the data yourself.

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
