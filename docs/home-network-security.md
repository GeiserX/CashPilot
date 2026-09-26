# Protecting your home network

CashPilot runs closed-source containers from companies you have never met, on a
machine inside your home. This page is about keeping that from costing you more
than the earnings are worth.

Three things can go wrong, in order of how likely they are:

1. **Someone else's traffic leaves under your IP address.** That is what most
   bandwidth-sharing services sell, and nothing on your side can filter it.
   [Network isolation](isolation.md) explains the attribution risk, and the
   dashboard warns you before deploying a service that does this.
2. **A container reaches the rest of your network.** Your NAS, your Home
   Assistant, your router's admin page, the machine CashPilot runs on. For a
   hostile image, those are the prize, not your bandwidth.
3. **A container escapes to the host** through a kernel bug. CashPilot's
   defaults already make this hard, as
   [what every deploy gets](#what-every-deploy-already-gets) lists, and gVisor can
   make it harder on some hosts.

You cannot fix the first one, only decide whether to accept it. The rest of this
page is about the second and third.

## The short version

1. [Put the earning machine on its own network segment](#1-give-it-its-own-network-segment),
   a guest network or VLAN.
2. [Firewall the containers off your LAN and off the host](#2-firewall-the-containers-off-your-lan-and-the-host).
3. [Keep CashPilot's own dashboard and worker private](#3-keep-cashpilots-control-plane-private).
4. [Don't run it next to your valuable data](#4-dont-run-it-next-to-what-you-cannot-lose),
   or put it in a VM.
5. [Tidy up the router](#5-router-hygiene).
6. [Protect the accounts and the money](#6-accounts-and-payouts).
7. Optionally, [run the containers under gVisor](#7-gvisor-optional) on a host
   that supports it.

Do the first two and you have removed most of the risk.

## 1. Give it its own network segment

The strongest and simplest protection is a network the earning machine shares
with nothing else you care about.

- **A guest network** on your router is often enough. Most consumer routers keep
  guest devices off the main LAN. To check yours, open your NAS or another
  computer from a device on the guest network. It should fail.
- **A VLAN** does the same thing on a wired network, with a firewall rule on the
  router that lets the VLAN reach the internet but not your other VLANs.

A segment protects against everything on that machine, including services that
use the host's network directly, such as Mysterium. The container firewall
below cannot confine those.

Storj and Anyone Protocol need an inbound port forwarded. Point those forwards
into the new segment and nothing else changes.

## 2. Firewall the containers off your LAN and the host

When the machine has to stay on your main network, the host firewall can still
keep the containers off it. Two separate things need blocking:

- **Other machines on your networks.** Traffic from a container to another
  machine is *forwarded* by the host, and Docker's `DOCKER-USER` chain is where
  you filter it.
- **The host itself.** Traffic from a container to the machine it runs on never
  reaches `DOCKER-USER`; it arrives on the host's `INPUT` chain. On a NAS this is
  the part that matters most, because the host *is* the NAS.

A Docker network on its own does neither. It only keeps containers off *other
Docker networks*.

### Put the containers on their own bridge

Create a bridge whose interface name the rules can match. Linux limits interface
names to 15 characters, so the network is `cashpilot-isolated` and its interface
is `cp-isolated`:

```bash
docker network create --driver bridge \
  -o com.docker.network.bridge.name=cp-isolated \
  cashpilot-isolated
```

Then tell the CashPilot worker to use it, by adding this to the worker's
environment and recreating the worker:

```yaml
CASHPILOT_CONTAINER_NETWORK: cashpilot-isolated
```

From then on, every service the worker deploys onto a bridge joins
`cashpilot-isolated` instead of Docker's default bridge. Services that use host
networking are unaffected. The worker never creates the network or any firewall
rule itself. If the network is missing, it refuses the deploy and tells you the
command above, and it checks before it touches the running container.

Already-deployed services move over on their next redeploy. To move one now
without recreating it, keeping its configuration and identity as they are:

```bash
docker network connect cashpilot-isolated cashpilot-honeygain
docker network disconnect bridge cashpilot-honeygain
```

Published ports move with it and survive a restart. A service that holds a
long-lived connection may keep trying the old one for a while; Bitping did, and a
`docker restart` of that one service fixed it.

If you run the services from an exported compose file instead, add
`networks: [cashpilot-isolated]` to each service and declare the network as
`external: true` at the bottom of the file.

### The rules

```sh
#!/bin/sh
# Containers on the cp-isolated bridge may reach the internet, but not your
# private networks and not this host. Safe to run more than once.
BR=cp-isolated
iptables -N DOCKER-USER 2>/dev/null || true   # Docker keeps it if it exists
add() { iptables -C "$@" 2>/dev/null || iptables -I "$@"; }
for net in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 169.254.0.0/16 100.64.0.0/10; do
  add DOCKER-USER -i "$BR" -d "$net" -j REJECT
done
add DOCKER-USER -i "$BR" -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
add INPUT -i "$BR" -j REJECT
add INPUT -i "$BR" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
```

What each part does:

- The five ranges are the private networks, link-local addresses (including
  the `169.254.169.254` metadata address a cloud VPS exposes), and
  `100.64.0.0/10`, which carrier-grade NAT and Tailscale use.
- The `ESTABLISHED,RELATED` rules let replies through. Without them a port you
  published, such as Storj's dashboard, stops answering: the request gets in and
  the reply is rejected on its way out.
- Each rule is inserted at the top, and the reply rules are inserted last, so
  they end up first. `iptables -C` skips a rule that already exists, so running
  the script again adds nothing.

We ran this script twice on a Docker host and checked the result:

| From a container on `cp-isolated` | Result |
|---|---|
| A web service on the host itself | blocked |
| Another machine on the LAN | blocked |
| The internet, by address and by name | works |
| A port published from the container, reached from the host | works |
| The same port with the reply rule removed | times out |

### Name lookups need a resolver the rules allow

Docker answers a container's lookups and forwards them to the DNS servers it was
given, **from inside the container's network**. On most home networks that
server is the router, which the rules above block, so every lookup fails and the
services stop earning. Pick one fix:

- **Give Docker public resolvers.** In `/etc/docker/daemon.json`, set
  `"dns": ["1.1.1.1", "9.9.9.9"]` and restart Docker (this restarts every
  container). If you keep a local resolver first in that list, lookups still
  work, a little slower, because Docker falls through to the next server.
- **Or let the containers reach the router's DNS port and nothing else on it,**
  by adding this to the script, with your router's address:

  ```sh
  ROUTER=192.168.1.1
  add DOCKER-USER -i "$BR" -d "$ROUTER" -p udp --dport 53 -j RETURN
  add DOCKER-USER -i "$BR" -d "$ROUTER" -p tcp --dport 53 -j RETURN
  ```

We tested both: with the exception, lookups through the router work and the
router's web interface stays blocked.

**When to run it.** The rules survive a Docker restart but not a reboot, so run
the script at every boot. It creates the `DOCKER-USER` chain if Docker has not
started yet, and Docker keeps an existing chain and its rules, so the order does
not matter. A systemd unit works, as does Unraid's User Scripts plugin set to
run at array start.

**IPv6.** Docker bridges have IPv6 off unless you enabled it. If you did, the
IPv6 rules need your LAN's own prefix as well as the private and link-local
ranges, because a home network with IPv6 usually has a globally routed prefix
that `fc00::/7` does not cover. `ip -6 route` lists it; the `2001:db8:1:2::/64`
below is only an example:

```sh
#!/bin/sh
BR=cp-isolated
LAN6=2001:db8:1:2::/64   # replace with your LAN's prefix
ip6tables -N DOCKER-USER 2>/dev/null || true
add() { ip6tables -C "$@" 2>/dev/null || ip6tables -I "$@"; }
for net in fc00::/7 fe80::/10 "$LAN6"; do
  add DOCKER-USER -i "$BR" -d "$net" -j REJECT
done
add DOCKER-USER -i "$BR" -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
add INPUT -i "$BR" -j REJECT
add INPUT -i "$BR" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
```

We checked that these rules load, but tested the blocking only for IPv4.

**What it cannot cover.** A service on host networking uses the host's own
interfaces, so a rule on a bridge does not apply to it. That is Mysterium today.
Use a separate segment for the machine, or run such services somewhere else.

### Check it yourself

After applying the rules, from the host:

```bash
# should FAIL: another machine on your LAN (use a real address of yours)
docker run --rm --network cashpilot-isolated busybox wget -T3 -qO- http://192.168.1.1/
# should work: the internet, by name
docker run --rm --network cashpilot-isolated busybox wget -T5 -qO- http://example.com/ | head -3
```

If the first command succeeds, the rules are not in place. Check that
`iptables -S DOCKER-USER` shows them and that the interface really is
`cp-isolated` (`ip link show cp-isolated`). If the second fails with a name
error but `wget http://1.1.1.1/` works, it is DNS: see
[name lookups](#name-lookups-need-a-resolver-the-rules-allow).

## 3. Keep CashPilot's control plane private

The dashboard can command the worker, and the worker holds the Docker socket,
which is as good as root on that machine. Both bind to `127.0.0.1` out of the box
([security defaults](security-defaults.md)). Keep it that way:

- **Never port-forward** the dashboard (8080) or the worker (8081) from your
  router.
- **Use a VPN** such as Tailscale or WireGuard to reach the dashboard from
  elsewhere, or put an authenticating reverse proxy in front of it.
- **Bind the worker to one address**, on a multi-machine setup, with
  `CASHPILOT_WORKER_BIND_ADDR`: the one the dashboard reaches it on, never
  `0.0.0.0` on a machine with a public address.
- **Don't publish a node's own management UI to your LAN** unless you need it.
  Mysterium's WebUI and API bind to the machine itself by default. Reach them
  over an SSH tunnel, or add only your reverse proxy's address.

## 4. Don't run it next to what you cannot lose

The machine that runs these containers should hold nothing you would hate to see
leak. On a NAS or a server with your photos, documents and password vault, the
best move is a **virtual machine**:

- Proxmox, Unraid and most NAS systems can run a small Linux VM.
- Install Docker and the CashPilot worker inside it, and give the VM its own
  network segment if you can.
- A container that escapes lands in the VM, not on your NAS. A VM is a stronger
  boundary than any container runtime, and it works everywhere, including on
  Unraid, where gVisor cannot run.

A Raspberry Pi or an old laptop dedicated to earning does the same job for very
little money.

## 5. Router hygiene

- **Turn off UPnP.** It lets any device on your network open ports on your
  router without asking you. Forward the few ports a service documents by hand.
- **Change the router's admin password** and turn off remote administration.
- **Keep the router's firmware updated.**
- **Watch the traffic.** CashPilot shows network use per container. A service
  that suddenly moves far more than usual deserves a look.

## 6. Accounts and payouts

- **Use a unique password, and two-factor authentication where offered,** for
  every earning account. These accounts hold money.
- **Pay out to a wallet you control,** never to an exchange deposit address
  unless the provider says that is supported. See each service's guide.
- **Back up CashPilot's encryption key.** It decrypts every stored credential.
  See [backing up the encryption key](security-defaults.md#backing-up-the-encryption-key).
- **Check your ISP's terms.** Many consumer contracts forbid reselling the
  connection, and the account that gets suspended is yours.

## 7. gVisor, optional

[gVisor](https://gvisor.dev/) runs a container against a kernel written in user
space instead of the host's kernel. A container that exploits a kernel bug hits
gVisor's kernel, not yours. It adds a layer against risk 3 above. It does
nothing for risks 1 and 2: traffic still leaves under your IP address, and a
container can still reach your LAN unless you firewall it.

### What it costs

We measured it on an x86_64 Ubuntu 24.04 server with kernel 6.8, running gVisor
`release-20260921.0` on its default platform. Each run downloaded the same 1 GiB
file in a container under each runtime:

| | runc (Docker's default) | runsc (gVisor) |
|---|---|---|
| Throughput, three runs | 64, 61, 57 MB/s | 53, 44, 45 MB/s |
| CPU time for 1 GiB | 3.3 s | 20 to 30 s |
| Connection setup, median of 10 | 10.8 ms | 11.4 ms |

gVisor reached about 78 % of runc's throughput and used six to nine times the CPU
for the same traffic. For a typical bandwidth-sharing service moving a few tens
of gigabytes a month, that is minutes of CPU a month. For a busy storage node,
or on a Raspberry Pi, it adds up.

With network passthrough, the setup that works on a CashPilot network (see
below), throughput matched runc's in two runs each, 38 to 44 MB/s on a link that
was the limit that day, and CPU stayed at about six times runc's: 19 to 20 s for
1 GiB against 3 s.

### What breaks

- **Docker's DNS on your own networks.** Plain `runsc` cannot resolve names on
  any network you create, `cashpilot-isolated` included. Docker answers lookups
  at `127.0.0.11` through firewall rules inside the container's network, and
  gVisor's own network stack does not apply them. This is
  [gVisor issue 7469](https://github.com/google/gvisor/issues/7469), still open.
  The fix that works is to register gVisor with `--network=host`, which, despite
  the name, uses the kernel network stack *inside the container's own network*:
  Docker's DNS works, and the container stays on the firewalled bridge. It
  weakens gVisor's network isolation, and every other system call is still
  handled by gVisor.
- **Raw sockets are off by default.** `ping` fails under gVisor even when the
  container is granted `NET_RAW`. Bitping declares `NET_RAW` to probe the
  network, so it needs gVisor registered with the `--net-raw` flag, which gives
  that capability back.
- **A service on host networking gains little.** gVisor's own documentation says
  network passthrough "decreases the isolation to the host", and a service that
  already shares the host's network, like Mysterium, has nothing left to
  confine it there. A service that needs host networking
  plus a TUN device, like Mysterium, is a poor fit.
- **Stock Unraid cannot run it at all.** Unraid runs from its initial RAM
  filesystem. That root has no parent mount, so gVisor cannot `pivot_root` out
  of it, and working around that with a chroot hits a second kernel rule: no new
  user namespace inside a chroot, which gVisor needs. We tested this on Unraid
  7.3.2. On Unraid, use [a VM](#4-dont-run-it-next-to-what-you-cannot-lose)
  instead.
- **Docker Desktop** on macOS and Windows already runs every container inside a
  Linux VM, so gVisor there adds a second layer rather than the first.

### Installing it on a standard Linux host

gVisor supports x86_64 and ARM64 on Linux 5.6 or newer. The
[official install guide](https://gvisor.dev/docs/user_guide/install/) installs a
checksummed release and registers it with Docker, without restarting Docker or
your running containers:

```bash
(
  set -e
  ARCH=$(uname -m)
  URL=https://storage.googleapis.com/gvisor/releases/release/latest/${ARCH}
  wget ${URL}/gvisor.tar.zstd ${URL}/gvisor.tar.zstd.sha512
  sha512sum -c gvisor.tar.zstd.sha512
  sudo tar --zstd -xf gvisor.tar.zstd -C /usr/local/bin
  rm -f gvisor.tar.zstd gvisor.tar.zstd.sha512
)
sudo /usr/local/bin/runsc install
sudo systemctl reload docker
docker run --rm --runtime=runsc hello-world
```

For CashPilot's networks, add the passthrough runtimes to
`/etc/docker/daemon.json`, next to the `runsc` entry the install wrote, and run
`sudo systemctl reload docker`:

```json
"runtimes": {
  "runsc": { "path": "/usr/local/bin/runsc" },
  "runsc-hostnet": { "path": "/usr/local/bin/runsc", "runtimeArgs": ["--network=host"] },
  "runsc-hostnet-raw": { "path": "/usr/local/bin/runsc", "runtimeArgs": ["--network=host", "--net-raw"] }
}
```

`runsc-hostnet-raw` is for a service that needs raw sockets, such as Bitping.

### What we ran under it

On an Ubuntu 24.04 host, each of these ran under `runsc-hostnet` on
`cashpilot-isolated` without restarting and without name-lookup errors: EarnApp, Earn.fm, Honeygain, IPRoyal Pawns, PacketStream, ProxyBase,
ProxyLite, ProxyRack, Repocket and Traffmonetizer, plus Bitping under
`runsc-hostnet-raw`. We did not try Mysterium, which needs host networking and a
TUN device, or Storj, whose disk traffic would pay gVisor's overhead on every
read and write.

CashPilot's deploy spec accepts a `runtime`, allowed only when your Docker daemon
reports it (see
[container runtimes](security-defaults.md#container-runtimes-gvisor-where-it-works)).
Nothing selects gVisor for you.

## What every deploy already gets

You do not have to configure any of this; it is always on
([security defaults](security-defaults.md)):

- every Linux capability dropped, and only the ones a service's own catalog
  entry declares added back;
- `no-new-privileges`, and a limit on the number of processes;
- no privileged containers, and no host device unless the service's own entry
  declares it and it is on a fixed allow-list, which today holds only
  `/dev/net/tun`, for Mysterium;
- no bind mounts of system paths, including the Docker socket;
- credentials encrypted at rest.
