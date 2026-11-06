# Keeping these containers off the rest of your network

The real risk of running proxyware is not a container breaking out. It is two
much more ordinary things.

**Someone else's traffic leaves under your IP address.** The FBI/IC3 has issued
a public notice about residential proxy networks, and researchers have shown
that node operators cannot see what traffic exits through them. Whatever a buyer
does looks like you: to your ISP, to sites that block the address, and to law
enforcement. That is not a bug in these services; it is what they sell.

**A hostile image's realistic prize is your LAN.** Not the bandwidth, but your Home
Assistant, your NAS shares, your media server, your password manager. Those sit
on the same network you just handed a closed-source container.

CashPilot cannot fix the first. Selling that egress is the product, and blocking
it would break the thing you installed this to do. What it says instead is the
truth, before you deploy, rather than in an FAQ nobody opens.

The second one you *can* reduce.

## LAN isolation by default

A worker fences its earners off your LAN, the host it runs on, your tailnet and
cloud metadata by itself. A new install needs no setup for it.

How it works:

- The worker creates a Docker network, `cashpilot-isolated`, with bridge
  interface `cp-isolated`. Docker's own masquerade (NAT) is off on it, and so is
  traffic between containers on it. The network carries the label
  `cashpilot.isolation=managed`.
- The worker writes one firewall table, `table ip cashpilot`, into the host's
  network namespace, plus `table ip6 cashpilot` when the host has IPv6. It does that through a short-lived helper container started
  from its own image, with host networking and the `NET_ADMIN` and `NET_RAW`
  capabilities. The helper is removed when it finishes. The worker process
  itself never gets those capabilities.
- The table holds the NAT that gives the earners their internet, plus drops for
  `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `100.64.0.0/10` (carrier-grade
  NAT and Tailscale), `169.254.0.0/16` (cloud metadata), any subnet directly
  connected to a real interface of the host (a LAN numbered in public space, a
  VPS's neighbours), the host itself, and your home's own public IP. That last
  one matters because most home routers loop a connection to their own public
  address straight back into the LAN (NAT loopback), where it arrives with a
  LAN source address. The worker learns the address from its public IP
  detection, so with detection off (`CASHPILOT_EGRESS_DETECT=off`) this drop
  is missing, even with `CASHPILOT_EGRESS_IP` set. A starting worker looks the
  address up before it writes the first table, a new address is fenced as soon
  as the worker sees it, and while a lookup fails the table keeps the address it
  already drops. A host whose first lookup after a reboot fails has no such
  drop until a lookup succeeds. Setting `CASHPILOT_EGRESS_IP` to your current
  public IP, with detection left on, closes that gap: the worker then needs no
  lookup. Replies to published ports still go out, so Storj,
  Sia and Anyone Protocol keep accepting inbound connections. Only replies pass:
  a connection an earner opened while the table was missing meets the drops
  again once the table is back.
- The IPv6 table drops every IPv6 packet that enters from the bridge. The
  network has IPv6 off, but Docker engines before 26 (Unraid 6.12, Synology
  and QNAP ship them) still give each container an `fe80::` address, and over
  it an earner could reach any host service listening on `[::]`.
- Every service the worker deploys onto a bridge joins that network, with DNS
  servers `1.1.1.1` and `9.9.9.9` (`CASHPILOT_CONTAINER_DNS` changes them).
  Services on host networking, such as Mysterium, are not covered: see
  [Mysterium, which uses host networking](isolation-check.md#mysterium-which-uses-host-networking).

**It fails closed, with three conditions.** The NAT and the drops live in the
same table. When something removes the table (a reboot, `nft flush ruleset`, a
firewalld reload), the earners lose their internet and do not gain your LAN
for TCP. The worker writes the table again when it starts, before every
deploy, and every 5 minutes. After a restart of the Docker VM on a test host,
the table was back 1.4 s after the worker container started. While the table
is missing:

- An earner can reach the host itself on every port, since traffic to the
  host needs no NAT. That lasts as long as the worker is not running: earners
  come back with the Docker daemon on their own, and a worker that is stopped
  or crash-looping writes nothing. Keep the worker running with a restart
  policy, as the shipped compose files do.
- A host that already has its own masquerade rule covering other subnets (a
  common WireGuard `PostUp` line, a UFW `before.rules` recipe, or a firewalld
  zone with masquerade on) NATs the earners' traffic with that rule. They then
  reach your LAN and the internet with nothing filtering them until the
  worker writes the table again.
- One-way traffic, such as a UDP packet to a LAN device, still leaves without
  NAT; only the reply cannot come back.

If the worker cannot read the host's routes, it leaves the table as it is
rather than write one without the drops for directly connected subnets, and
refuses deploys until it can. An earner that Unraid's reboot left on a removed
copy of the network is started again only after the table is in place.

**When the table cannot be written, deploys are refused.** The message says why
and how to opt out. The running container is never touched first. The fleet page
shows the error on the worker's row.

The worker uses `nft` when the kernel has nf_tables, and `iptables-legacy`
otherwise (older NAS kernels). Both write the same rules.

### Modes

| Mode | When | What happens |
|---|---|---|
| on | a new install, `CASHPILOT_ISOLATION=on`, the `cashpilot-isolated` network CashPilot created exists, or an earner is still bound to it after Unraid removed it | earners join the fenced network |
| legacy | an upgraded install whose earners already sit on Docker's default bridge | nothing changes on upgrade; the fleet page offers **Turn on isolation** |
| off | `CASHPILOT_ISOLATION=off` | Docker's default bridge, as before; earners left on the fenced network keep their internet until you redeploy them |
| your own network | `CASHPILOT_CONTAINER_NETWORK` is set | that network, with your own rules, as before; CashPilot writes no table, except the NAT alone while earners are still on `cashpilot-isolated`, so they keep their internet until you redeploy them |

The mode lives in Docker and in the worker's `/data` (`.isolation_on`, written
the first time the worker is on, deleted by `CASHPILOT_ISOLATION=off`), so losing
either one alone does not switch it off: a reinstall with a fresh volume keeps
the network, and a reboot or `docker network prune` that took the network after
every fenced earner was removed keeps the file. The file needs a writable
`/data`: if the worker cannot write it, it logs a warning saying so and decides
from Docker alone, as before.

### Turning it on for an upgraded install

On the **Fleet** page, a worker in legacy mode shows "Earners on this worker can
reach your LAN and this host" and a **Turn on isolation** button (owner only).
It creates the network and the table, then redeploys each earner on Docker's
default bridge once onto the new network, one at a time, from its recorded
settings. Volumes, identities and settings stay the same. Storj gets its full
clean stop first, so that one can take a few minutes. A redeploy starts the
container, so stopped earners are left alone: the page names them, and each
moves the next time you deploy it. Starting one as it is keeps it on the old
network. If one redeploy fails, the page carries on with the rest and names
the ones it could not move; redeploy or remove those from their service pages.
The same switch is `POST /api/workers/{id}/isolation`.

### Turning it off

Set `CASHPILOT_ISOLATION=off` on the worker and recreate the worker, then
redeploy the earners to move them back to Docker's default bridge. There is no
off button on purpose: one click should not take the fence down.

### Limits

- Host-networked services (Mysterium) are not covered.
- IPv6: the fenced network has IPv6 off. On Docker 26 and later the earners
  get no IPv6 address at all; on older engines they get a link-local one,
  which the IPv6 table drops. A host booted with IPv6 disabled gets no IPv6
  table, since it has no IPv6 to filter.
- Unraid removes every user-defined Docker network when its Docker service
  starts, unless **Settings > Docker > Preserve user defined networks** is
  Yes. The worker creates the network again and moves each earner that
  failed to start because of it back onto the new one, then starts it, so
  they come back within a few minutes of the worker. This holds even when
  stopped earners are still on Docker's default bridge from before the switch:
  an earner bound to the removed network is enough to keep isolation on.
  Setting it to Yes avoids the gap.
- A LAN on a public range behind another router (not directly connected to the
  host) is not dropped. Use a VLAN or your own rules.
- Tested on Linux Docker 29 with nf_tables (colima on macOS, the same VM model
  as Docker Desktop), including the `iptables-legacy` fallback. Docker Desktop
  itself, rootless Docker, Podman and Unraid are not tested yet. On Docker
  Desktop, the Enhanced Container Isolation setting may block the helper; the
  deploy is then refused with the opt-out in the message.

## What CashPilot tells you per service

It **tells you** which services can be confined and exactly what each needs
allowed through: `GET /api/fleet/isolation-guide`.

## The three answers

| Verdict | Meaning |
|---|---|
| **isolatable** | Outbound only. Confine it as-is. |
| **needs exceptions** | It can be confined, but specific things must stay reachable. |
| **not isolatable** | It runs on the host network, so a container bridge does not apply. Use a VLAN or a separate machine. |

Today `mysterium` is the third case (it declares `network_mode: "host"`), and
`storj` is the second: it needs its inbound port **and** its local dashboard
reachable, because that dashboard is where CashPilot reads its earnings.

## Running your own rules

Only if you set `CASHPILOT_CONTAINER_NETWORK` to manage the bridge and its
firewall yourself. Put the managed containers on their own bridge:

```yaml
networks:
  cashpilot-isolated:
    # Without it Compose prefixes the project name to the network.
    name: cashpilot-isolated
    driver: bridge
    driver_opts:
      # Linux caps interface names at 15 characters; the rules match this one.
      com.docker.network.bridge.name: "cp-isolated"
```

!!! warning "A Docker bridge alone does not stop LAN access"

    Containers on a user-defined bridge can still reach your other subnets. The
    rule that matters is on the **host firewall**, applied to that bridge,
    denying:

    - `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`: your LAN
    - `169.254.0.0/16`: cloud metadata. On a VPS, a container that reaches this
      can often mint credentials for the whole account.

    ...while still allowing every exception the guide lists for the services you
    run. Miss one and that service silently stops earning.

    [Protecting your home network](home-network-security.md#2-firewall-the-containers-off-your-lan-and-the-host)
    has the exact rules, tested, including the one most recipes miss: traffic
    to the Docker host itself never passes the `DOCKER-USER` chain. It also
    shows how to make the CashPilot worker deploy onto this bridge with
    `CASHPILOT_CONTAINER_NETWORK`.

Whatever you apply, [test it from inside an earner](isolation-check.md): a rule
that looks right can still be skipped, and the test shows it in one command.

## Check it from the dashboard

On the **Fleet** page, the owner sees **Check isolation** on each worker. The
same check is `POST /api/workers/{id}/isolation-check`. The worker has to run
1.46.0 or later, and reach its Docker socket: a worker without one does
not offer the button.

The worker starts two short-lived containers from its own image, so it pulls
nothing. With CashPilot's own fence on, it also reads the fence's packet
counters before and after. They have no capabilities, run as `nobody`, and the worker removes
them and their volumes when the check ends, whether it passed, failed or timed
out. If Docker refuses to remove one, the result names it and gives the
`docker rm -fv` line to clear it; the check's answer still stands. It touches
no firewall rule.

1. **The control** runs on the host's network. It collects addresses to try:
   the default gateway, the host's own addresses with ports it listens on, your
   private DNS resolvers, `100.100.100.100` when Tailscale runs, one tailnet
   peer when the host has a connection open to one, and `169.254.169.254`. It
   keeps only the ones that answer from the host, so a closed port can never
   pass for a blocked one. Each of the host's addresses is tried on two
   paths, since a rule can close one and miss the other: a port the host
   serves itself, such as SSH or its web interface, which arrives on the
   `INPUT` chain, and a port Docker publishes for a container, which Docker
   forwards to that container through `FORWARD`. The result labels the second
   kind "forwarded to a container". Listeners on `[::]` count too, since a
   dual-stack socket also accepts IPv4. When an address has several open
   ports, the result names SSH, then 80, then 443 before any other, so the
   line is one you recognise. The host's LAN and tailnet addresses and the
   earner's own bridge gateway are always tried. On a host with many Docker
   networks, the other bridge gateways are tried up to a limit, and the result
   counts the ones it left out.
2. **The earner side** joins a running earner's network, or the isolated
   network when no earner runs, and tries the same addresses. It also tries
   `1.1.1.1:443`, to show the earner still reaches the internet. The CashPilot
   dashboard's own address is one of the targets: an earner that reaches it is
   the clearest risk there is.
3. **The fence's own proof**, with CashPilot's fence on. The earner side sends
   one connection to an unused address in each blocked range (for example
   `10.255.255.254:9`) and one to the host. Each drop rule's packet counter is
   read before and after. A counter that went up proves the fence dropped that
   connection, even on a host where nothing on the LAN answers, which is the
   case under Docker Desktop and colima. A counter that did not go up is
   reported: something on the host routes that traffic around the fence. Two
   more targets join when the table holds their drops: your home's public IP,
   and the host's IPv6 link-local address on the bridge. For those, a refused
   connection also counts as reaching, since the drop answers nothing. An
   earner with no IPv6 sends nothing to the second, which is not a finding.

### Reading the result

- **Isolated.** The earner reached none of the addresses, and it reached the
  internet. The one exception is an expected DNS line (see below): when one
  got through, the result says so and names it.
- **Not isolated.** The result lists each problem with a link to its fix,
  grouped as your LAN, this host, overlay network and cloud metadata. It also
  flags three things the probes cannot see:
    - earners on a bridge other than `CASHPILOT_CONTAINER_NETWORK`, which your
      rules do not cover, including stopped ones, which are exposed again as
      soon as they start;
    - earners on `CASHPILOT_CONTAINER_NETWORK` that are also attached to
      another network, which is a way round the rules on its bridge;
    - a Mysterium node whose `MYST` chain leaves out a private range, such as
      `100.64.0.0/10` or `169.254.0.0/16`. Redeploy it from the dashboard, since
      the catalog now passes the full list. The check reads the chain from
      inside the node, so it also sees rules written through `nf_tables`, which
      the host's `iptables` misses on Unraid. An empty chain means the node has
      carried no session since it started. Check again later. The chain
      name and the blackhole address come from the service's catalog entry
      (`docker.node_firewall`), not from CashPilot's code.
- **Could not test.** Nothing answered from the host, the earner could not
  reach the internet either, or a probe could not run at all: a Docker error,
  no running earner on a bridge and no `CASHPILOT_CONTAINER_NETWORK` to test
  from, a network name that does not exist, or a Docker daemon that did not
  answer within 10 s. A "blocked" line would prove
  nothing then, so the check does not claim isolation, and the result shows
  the exact reason.

Two lines need a closer look.

- `100.100.100.100:53` can read reachable on a fenced host with Tailscale. The
  [DNS rewrite](isolation-check.md#with-tailscale-or-another-overlay-network-on-the-host)
  sends that traffic to a public resolver before the fence sees it. A rule
  that lets port 53 to that address through on purpose looks the same. When
  port 80 on the same address reads blocked, the fence works and only DNS gets
  through, and the result says so.
- Port 53 on your router or a LAN resolver can read reachable when you added the
  [router DNS exception](home-network-security.md#name-lookups-need-a-resolver-the-rules-allow).
  The check also tries another port on that address, such as its web
  interface. When that one reads blocked, only DNS gets through, and the result
  says so. When nothing else on the address answers from the host, the result
  says it cannot tell the exception from a missing fence.
- A warning that earners ask a resolver the fence blocks is about speed, not a
  leak. Those earners were deployed before `CASHPILOT_CONTAINER_DNS` and wait
  about 4 s on every name lookup. Redeploy them.

Apart from the fence's IPv6 target above, the check covers IPv4 only. When the
earners' network has IPv6 enabled, or an earner has a global IPv6 address, the
result says so, since reaching the LAN over IPv6 needs its own
[ip6tables rules](home-network-security.md#the-rules). It shows what an
earner can reach right now, so run it again after any change to the host.

## A VLAN is stronger

A separate VLAN with its own firewall policy contains host-networked services
too, and does not depend on getting Docker's bridge rules exactly right. If you
already run VLANs, that is the better answer.

## Before you deploy

`GET /api/services/{slug}/deploy-risk` returns the attribution notice for a
service, driven by its own catalog disclosure. Three outcomes, and the third
matters most:

- documented as reselling your IP: you get the full warning;
- documented as **not** reselling (a storage node): no warning, because a false
  one teaches you to click past the real ones;
- **not documented at all**: it says exactly that. Most of the catalog is
  undocumented, and "nobody checked" must never read as "no risk".
