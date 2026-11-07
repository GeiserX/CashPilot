# What's new in 2.0

CashPilot 2.0 adds no big feature of its own. It closes a run of releases,
1.62 to 1.73, that changed what the worker can do on your host, how far an
earner can reach into your network, and how many IPs one box can earn on.
Several of those releases need a step from you when you upgrade, so they get a
major version together. This page says why the upgrade is worth it, what
changed, with a link to the page that covers each part, and then
[how to upgrade](#upgrading-from-1x).

## Why upgrade

What an older install leaves open, by version:

- **1.70 and older:** the worker holds the raw Docker socket. Whoever takes
  over the worker is root on your host.
- **1.72 and older,** with the dashboard and a worker on one host: a
  compromised worker can read `.fernet_key` and decrypt every provider login
  you stored.
- **Anything deployed before 1.70:** earners carrying strangers' traffic can
  reach your LAN, your router and your other machines, until you turn the
  fence on.

2.0 closes all three. It also carries the fixes since 1.73: the in-app update
works behind the socket proxy, identity backups you confirmed stay confirmed
through the migration, earners from the old pre-worker deploy path stay
visible after it, Podman workers can deploy, and traffic caps on proxies
recover after a box was offline. Releases are cut from one branch, so every
fix from now on ships in 2.x and the `1.73` tag gets no more patches.

## Security

### The worker no longer holds the Docker socket

Whoever holds the Docker socket is root on the host. In the shipped compose
files the socket now sits with a socket proxy,
[sockguard](https://github.com/CodesWhat/sockguard) 2.4.6, pinned by digest.
The worker talks to Docker only through it. The proxy reads every request,
including its JSON body, and refuses:

- every Docker API call the worker does not make (swarm, secrets, plugins,
  builds, exec of arbitrary commands, image push, and more);
- privileged containers, host PID, IPC and user namespaces, unconfined seccomp
  or AppArmor;
- binds of `/`, of the socket, or of any host folder you did not list;
- any added capability other than `NET_ADMIN`, `NET_RAW`, `SETUID` and
  `SETGID`, any device other than `/dev/net/tun`, and any runtime other than
  `runc` and gVisor.

A CI job opens a pull request when sockguard ships a new release, so the pin
does not go stale. [Docker socket proxy](security-defaults.md#docker-socket-proxy)
has the full list.

### Owner isolation keeps a compromised worker out of the dashboard

The proxy labels every container, volume and network the worker creates with
`cashpilot.deployed-by=worker`, and refuses the worker everything without that
label. On a host that runs the dashboard and a worker together, a compromised
worker can no longer read the dashboard's `/data`. That folder holds
`.fernet_key`, the key that decrypts every login CashPilot stores. Nor can it
read the keys in the dashboard container's environment. It cannot touch containers you started by
hand either.

It is not yet a full root boundary. If you set `CASHPILOT_COMPOSE_DIR` or
`CASHPILOT_PROXY_BIND_MOUNTS`, a symlink planted in one of those folders can
still reach the host's root, until sockguard can check binds for symlinks.
Leave both unset and that path is closed.
[Owner isolation](security-defaults.md#docker-socket-proxy) lists what a
compromised worker can still do.

### Earners are fenced off your LAN

On a new install the worker puts bridge-networked earners on their own Docker
network and writes one firewall table that drops traffic from them to:

- private ranges (`10/8`, `172.16/12`, `192.168/16`);
- `100.64/10`, which covers carrier-grade NAT and your tailnet;
- `169.254/16`, cloud metadata;
- the host itself, any subnet directly attached to it, and your home's own
  public IP, which most routers would loop back into the LAN.

An upgraded install turns it on with **Turn on isolation** on the Fleet page,
and **Check isolation** starts two short-lived containers to test that it holds.

Limits: Mysterium runs on host networking and is not covered by the fence. A
second WAN or extra public IPs are not dropped. Docker Desktop, rootless Docker,
and Unraid are not tested yet. On Podman the fence is not available yet: a
worker there deploys on Podman's default network and the Fleet page says so.
[Network isolation](isolation.md#lan-isolation-by-default) has the details, and
[Test your isolation](isolation-check.md) has the checks by platform.

### gVisor where it works

If your Docker daemon has gVisor's `runsc` runtime, `CASHPILOT_CONTAINER_RUNTIME`
puts the bridge-networked earners in it, with exceptions per service. We
measured about a fifth less peak throughput and six to nine times the CPU per
byte moved. It does not run on stock Unraid.
[gVisor, optional](home-network-security.md#7-gvisor-optional) has the numbers
and the install steps.

### Node identities are backed up before you can lose them

Some earners keep state that has no copy anywhere else: a Mysterium keystore,
a Storj identity. CashPilot refuses to delete those volumes unless you ask for
it explicitly. The Payouts page lists them under **Back these up**, one line
per box, with an encrypted **Download backup** button. A box that has been
backed up asks again when its volume changes or after six months.
[Backing up node identities](backup.md) explains how.

## Proxied copies: earn on more than one IP

Providers count devices per public IP, so a second copy of an earner on the
same box usually earns nothing. A proxied copy is an extra copy of a deployed
service that leaves through a proxy instead, so one box earns on its own IP plus
one IP per proxy.

- Three kinds of proxy: SOCKS5, HTTP CONNECT, or a Tailscale exit node on
  another connection you own.
- **Test** starts a throwaway tunnel, shows the exit IP and country, and passes
  only when that IP is public and, when the worker knows its own public IP, is
  not the box's own.
- It fails closed. The earner has no network of its own. It shares the
  namespace of a tunnel container whose firewall drops every packet that does
  not go through the proxy. The earner starts only after the tunnel has seen an
  exit IP within 45 seconds. If the proxy dies, the copy stops earning
  and nothing leaks out of your own IP. `scripts/proxy_leak_test.sh` checks
  this against a real Docker daemon.
- An optional traffic cap per proxy, in GB, stops its copies at a threshold
  (90% of the cap by default) and starts them again on the reset day.

Limits: services that need host networking, published ports, volumes, devices
or extra network capabilities cannot run through a proxy. That rules out
Mysterium, Bitping and Storj. Neither can a service whose terms forbid proxies.
UDP goes out only through a Tailscale exit node, never through SOCKS5 or HTTP
CONNECT.
[Proxied copies](proxies.md) covers setup and DNS.

## Also new since 1.62

- **Provider ratings.** Every provider gets a letter grade from the same ten
  questions, each answer backed by a source you can open. Today none of the
  graded providers earns an A or a B. [Provider ratings](ratings.md)
- **Activity.** Off by default. Once you turn it on, it shows what each earner
  does on the network: connections, ports, networks, countries, and alerts for
  mail ports and attempts on your LAN. It reads socket tables only, never
  traffic. [Activity](activity.md)
- **Custom services.** Run any image the catalog lacks, by name and tag, with
  the catalog's restrictions. [Custom services](custom-services.md)
- **Import from another tool.** Bring your logins over from money4band,
  CashFactory or InternetIncome, and review them before saving.
  [Moving from money4band](migrate/money4band.md)
- **Payouts.** The Payouts page lists each service, the boxes it runs on and
  the address it pays to. A balance drop is offered as a payout for you to
  confirm. The [service guides](guides/index.md) give each minimum payout, and
  several say what a first cash-out asks for, such as a one-time registration
  link or a phone check by SMS.
- **App stores.** Install from Unraid Community Applications or TrueNAS SCALE.
  CasaOS and Runtipi packages are in this repository and run the socket proxy.
  [App stores](app-stores.md)
- **Catalog.** <!-- n:active -->40<!-- /n --> active services and
  <!-- n:beta -->1<!-- /n --> in beta: <!-- n:docker -->17<!-- /n --> run in
  Docker, <!-- n:tracked -->24<!-- /n --> are tracked, and
  <!-- n:collectors -->15<!-- /n --> have a balance collector.
  [How CashPilot compares](comparison.md) sets this against five other stacks,
  every cell sourced.

## Companion apps

- **[CashPilot Desktop 1.0](https://github.com/GeiserX/CashPilot-Desktop)**
  runs the same catalog as an app for macOS (Apple Silicon), Windows and
  Linux. It works as a full dashboard or as a worker that joins this one, and
  pins every service image by digest.
- **[CashPilot for Android 1.0](https://github.com/GeiserX/CashPilot-android)**
  reports a phone's earning apps to the [Fleet page](fleet.md#fleet-dashboard)
  next to your servers. It ships from GitHub releases and is waiting for
  review on [F-Droid](https://gitlab.com/fdroid/fdroiddata/-/merge_requests/56196).

## Upgrading from 1.x

The compose files pin a release series (`drumsergio/cashpilot:1.73`), so
`docker compose pull` and the in-app **Update** button stay inside 1.x. Moving
to 2.0 means taking the new compose file or changing the tags.

### 1. Back up first

- **The dashboard's `/data`.** `cashpilot.db` holds your earnings history and
  `.fernet_key` decrypts every stored login. Without that key the logins
  cannot be recovered. [Backing up and restoring](backup-restore.md#backup)
  has a script that copies both without stopping the container, and the
  commands to check the copy.
- **Node identities.** On the Payouts page, use **Download backup** for every
  box listed under **Back these up**. A Mysterium keystore or a Storj identity
  has no other copy. [Backing up node identities](backup.md)

The migration below keeps its own copy of every volume it touches, but a
backup you hold is the one that survives a lost disk.

### 2. Take the 2.0 compose file

On each host, replace your compose file with the 2.0 one:
`docker-compose.yml` where the dashboard runs, `docker-compose.fleet.yml` for a
dashboard with remote workers, or `docker-compose.worker.yml` on a worker-only
host. Carry over your own changes and keep your `.env`. If you keep your old
file, it must already have the `cashpilot-socket-proxy` and
`cashpilot-migrate` services; then change every `drumsergio/cashpilot:1.x` and
`drumsergio/cashpilot-worker:1.x` tag to `2.0`.

If your worker still mounts `/var/run/docker.sock`, the new file is what moves
the socket to the proxy. Set `CASHPILOT_COMPOSE_DIR=/folder/with/the/compose/file`
in `.env` if you want the in-app update, which opens the symlink path
described above. On a GPU host, read
[UPGRADING.md](https://github.com/GeiserX/CashPilot/blob/main/UPGRADING.md#docker-socket-proxy-take-the-new-compose-file-once)
first: the proxy refuses to recreate a CashPilot service with a GPU.

### 3. Start it

```sh
docker compose up -d --force-recreate
```

Add `-f` and your file name if it is not `docker-compose.yml`. Do the
dashboard host first, then every worker host. The dashboard and every worker
should run the same version.

### What the one-shot migrator does

On an install from before 1.73, `cashpilot-migrate` runs once, before the
socket proxy starts. Docker cannot add a label to an existing volume or
network, so it moves your data onto labelled ones:

- each volume of an earner the worker started is copied to a backup named
  `<volume>-pre-isolation`, checked by digest, recreated with the label,
  filled back from the backup and checked again. The earner is then recreated
  as it was. A Mysterium identity keeps its address;
- the worker's own volumes are copied into new ones named
  `cashpilot_worker_data_owned` and, where the dashboard runs too,
  `cashpilot_fleet_owned`;
- the `cashpilot-isolated` network is rebuilt with the label, with its earners
  put back on it.

It deletes nothing. It can take a few minutes on a node with a large volume. If it stops halfway, after a reboot
or a kill, run the same command again and it finishes from where it stopped.
If it already ran on 1.73, it finds nothing to do and exits.

### What you see when it is done

- `docker logs cashpilot-migrate` ends with *Migration complete: everything the
  worker uses carries cashpilot.deployed-by=worker.* A run that had to leave
  something alone ends with *Migration done, with N thing(s) left as they
  were*, and the lines above it say what and why.
- The worker's status page says *Docker access: socket proxy*.
- The dashboard shows every earner running, the Fleet page shows each worker on
  2.0, and a Mysterium node shows the same address as before.

Two things work differently afterwards:

- On the host where the dashboard and a worker run together, the in-app update
  updates the worker only. Update the dashboard with
  `docker compose pull && docker compose up -d`.
- Earners you started by hand, or from a compose file CashPilot exported, no
  longer show in the dashboard. They keep running and earning.

If you came from 1.69 or older, your earners are still on Docker's default
bridge. Press **Turn on isolation** on each worker's row on the Fleet page,
then **Check isolation**.

Once everything has run well for a while, remove what the migration left
behind. [UPGRADING.md](https://github.com/GeiserX/CashPilot/blob/main/UPGRADING.md#owner-isolation-take-the-compose-file-again-two-features-change-on-the-uis-host)
lists each leftover and the commands.

### Rolling back

2.0 uses the same database schema as every release since 1.67. To go back to
1.73, set the tags back to `1.73` and run `docker compose up -d`.

To go back further, put your old compose file back and run
`docker compose up -d`. The migration copies and never deletes, so your old
worker volumes and each `<volume>-pre-isolation` backup are still there,
unless you removed them. That is why you keep them for a while. A compose file
from before the socket proxy leaves the proxy running: remove it with
`docker rm -f cashpilot-socket-proxy`. Going back past 1.67, restore the
`/data` backup you took as well.
