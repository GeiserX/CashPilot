# Keeping these containers off the rest of your network

The real risk of running proxyware is not a container breaking out. It is two
much more ordinary things.

**Someone else's traffic leaves under your IP address.** The FBI/IC3 has issued
a public notice about residential proxy networks, and researchers have shown
that node operators cannot see what traffic exits through them. Whatever a buyer
does looks like you — to your ISP, to sites that block the address, and to law
enforcement. That is not a bug in these services; it is what they sell.

**A hostile image's realistic prize is your LAN.** Not the bandwidth — your Home
Assistant, your NAS shares, your media server, your password manager. Those sit
on the same network you just handed a closed-source container.

CashPilot cannot fix the first. Selling that egress is the product, and blocking
it would break the thing you installed this to do. What it says instead is the
truth, before you deploy, rather than in an FAQ nobody opens.

The second one you *can* reduce.

## What CashPilot does and does not do

It **tells you** which services can be confined and exactly what each needs
allowed through: `GET /api/fleet/isolation-guide`.

It **does not** create bridges or firewall rules on your host. That is a change
with real blast radius, and getting the exceptions wrong costs money rather than
convenience — a storage node that cannot accept inbound connections stops
earning and puts its held balance at risk. So the recipe is yours to apply.

## The three answers

| Verdict | Meaning |
|---|---|
| **isolatable** | Outbound only. Confine it as-is. |
| **needs exceptions** | It can be confined, but specific things must stay reachable. |
| **not isolatable** | It runs on the host network — a container bridge does not apply. Use a VLAN or a separate machine. |

Today `mysterium` is the third case (it declares `network_mode: "host"`), and
`storj` is the second: it needs its inbound port **and** its local dashboard
reachable, because that dashboard is where CashPilot reads its earnings.

## Doing it

Put the managed containers on their own bridge:

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

    - `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` — your LAN
    - `169.254.0.0/16` — cloud metadata. On a VPS, a container that reaches this
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
this release or later, and reach its Docker socket: a worker without one does
not offer the button.

The worker starts two short-lived containers from its own image, so it pulls
nothing. They have no capabilities, run as `nobody`, and the worker removes
them and their volumes when the check ends, whether it passed, failed or timed
out. It touches no firewall rule.

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
   kind "forwarded to a container". The host's LAN and tailnet addresses and the
   earner's own bridge gateway are always tried. On a host with many Docker
   networks, the other bridge gateways are tried up to a limit, and the result
   counts the ones it left out.
2. **The earner side** joins a running earner's network, or
   [`CASHPILOT_CONTAINER_NETWORK`](home-network-security.md#put-the-containers-on-their-own-bridge)
   when no earner runs, and tries the same addresses. It also tries
   `1.1.1.1:443`, to show the earner still reaches the internet.

### Reading the result

- **Isolated.** The earner reached none of the addresses, and it reached the
  internet.
- **Not isolated.** The result lists each problem with a link to its fix,
  grouped as your LAN, this host, overlay network and cloud metadata. It also
  flags two things the probes cannot see:
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

The check covers IPv4 only. When the earners' network has IPv6 enabled, or an
earner has an IPv6 address, the result says so, since reaching the LAN over
IPv6 needs its own [ip6tables rules](home-network-security.md#the-rules). It
shows what an earner can reach right now, so run it again after any change to
the host.

## A VLAN is stronger

A separate VLAN with its own firewall policy contains host-networked services
too, and does not depend on getting Docker's bridge rules exactly right. If you
already run VLANs, that is the better answer.

## Before you deploy

`GET /api/services/{slug}/deploy-risk` returns the attribution notice for a
service, driven by its own catalog disclosure. Three outcomes, and the third
matters most:

- documented as reselling your IP — you get the full warning;
- documented as **not** reselling (a storage node) — no warning, because a false
  one teaches you to click past the real ones;
- **not documented at all** — it says exactly that. Most of the catalog is
  undocumented, and "nobody checked" must never read as "no risk".
