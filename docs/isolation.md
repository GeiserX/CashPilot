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
    driver: bridge
    driver_opts:
      com.docker.network.bridge.name: "cashpilot-isolated"
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
