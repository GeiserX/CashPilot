# Proxied copies

A proxied copy is an extra copy of a service that leaves through a proxy
instead of your box's own internet connection. Providers count devices per
public IP, so one box can earn on several IPs: its own, plus one per proxy.

You add a proxy once, then pick a box, a service already deployed on it, and
the proxy. The copy runs with the same settings as the service on that box,
under its own device name (`cashpilot-box-p3` for proxy 3).

## What a proxy can be

| Type | What you give it | Notes |
|---|---|---|
| SOCKS5 | host, port, optional user and password | Carries UDP only if the provider supports SOCKS5 UDP ASSOCIATE. |
| HTTP CONNECT | host, port, optional user and password | TCP only. Name lookups still work (see [DNS](#dns)). |
| Tailscale exit node | an auth key and the exit node's name or 100.x address | Traffic leaves from the exit node's connection. See [Tailscale exit nodes](#tailscale-exit-nodes). |

Any provider works. Nothing in CashPilot is specific to one.

Credentials are encrypted at rest like every other secret. The API and the
page never send them back: an edit form leaves those boxes empty, and leaving
one empty keeps what is stored.

The **Test** button starts a throwaway tunnel on a box, reports the exit IP and
country it gets, and removes it. It passes only when the exit IP is public and
is not the box's own.

## How it works

Each copy is two containers on the worker:

1. A **tunnel** container from `drumsergio/cashpilot-tunnel`, at the same
   exact version as the worker. It owns a network namespace and makes the
   proxy the only way out of it.
2. The **earner**, started with `network_mode: container:<tunnel>`. It has no
   network interface of its own.

The tunnel sets things up in this order:

1. Firewall rules first (nftables, inside its own namespace only). Every
   outgoing packet is dropped unless it goes into the tunnel, or it is the
   tunnel's own connection to the proxy (for Tailscale: a packet tailscaled
   marked as its own).
2. Name lookups sent to Docker's resolver are redirected into the tunnel, and
   anything else sent to that resolver is dropped.
3. The routes and the tunnel process: [tun2proxy](https://github.com/tun2proxy/tun2proxy)
   v0.8.7 for SOCKS5 and HTTP, tailscaled v1.104.4 for Tailscale.
4. A probe through the tunnel. The earner is started only after the probe sees
   an exit IP within 45 seconds, and, when the worker knows its own public IP,
   one that is not the box's own. Otherwise the copy is refused and the tunnel
   removed.

### It fails closed

If the proxy goes down, the tunnel process dies or the tunnel container stops,
the earner has no way to send a packet anywhere: not to the internet from your
own IP, not to your LAN, not to the Docker bridge. It stops earning; it never
leaks.

`scripts/proxy_leak_test.sh` proves this against a real Docker daemon, for
SOCKS5 and HTTP, each with and without a password:

- with the proxy stopped, and with tun2proxy frozen, the earner reaches
  nothing (not 1.1.1.1, not the bridge gateway, not a LAN address), and a
  packet capture on the namespace's only real interface sees zero packets to
  anything but the proxy;
- with tun2proxy killed, the tunnel container exits and the earner is left
  with no route out;
- a DNS lookup of a random name, through Docker's resolver and straight at
  8.8.8.8, never appears in a capture of the box's own network stack;
- `docker inspect` of the tunnel shows no proxy password.

Every leak check is first run against a namespace opened on purpose (the
firewall table deleted and a default route put back) and must see the leak
there, so a check that cannot fail is caught.

### Hardening

The tunnel container gets `NET_ADMIN` and `/dev/net/tun` and nothing else:
every other capability dropped, never privileged, `no-new-privileges`, a
read-only root filesystem, a process limit, no Docker socket and no published
ports. It joins `CASHPILOT_CONTAINER_NETWORK` like every other earner, so your
host firewall rules for that bridge still apply.

The earner keeps the hardening every deploy gets. The worker API refuses
`network_mode: container:` from any caller; only the worker itself sets it for
a proxied copy.

The proxy URL or auth key reaches the tunnel as root-only files written into
an anonymous volume before the container starts. It is not in a label, the
environment or the recorded command. tun2proxy takes the URL on its command
line, which is visible inside the tunnel container's own process list; the
earner has a separate process namespace and cannot see it. Anyone with the
host's Docker socket can, as they can see every earner's credentials today.

## DNS

Name lookups from the earner never leave the box directly. tun2proxy answers
them inside the tunnel with placeholder addresses and passes the name to the
proxy when a connection opens, so the proxy resolves it where it is. This
works with plain HTTP CONNECT proxies, which cannot carry DNS themselves.

## What cannot run through a proxy

A service is refused when its catalog entry needs the host:

- host networking;
- published ports;
- volumes or host directories;
- devices (Mysterium needs `/dev/net/tun` and UDP);
- terms that forbid proxies or VPNs: `requirements.proxy_prohibited` in the
  catalog, with a link to the provider's own terms.

Services that need UDP do not work through HTTP CONNECT, and through SOCKS5
only when the provider supports UDP ASSOCIATE.

## Exit IPs and grouping

The exit IP a copy shows is the one the tunnel saw when it came up. Copies are
grouped by that IP, not by the box's. The rules are the ones the fleet page
uses for boxes:

- an exit not seen yet, or a private address, is never grouped with anything;
- a proxy you mark as **rotating** changes its exit per connection, so its
  copies are listed as rotating and not grouped;
- when a new copy would leave from an IP where the same service already runs,
  on a box or through another proxy, the page warns. If the provider allows
  one device per IP, the warning says the copy earns nothing there.

Some providers treat a changing IP as abuse. Use sticky sessions where your
proxy provider offers them.

## Traffic cap

Optional, off by default. Set a cap in GB (10^9 bytes, the unit providers
sell), the percentage to stop at (90 by default), and a reset day (1 to 28) or
none for resetting by hand.

Traffic is counted from the tunnel container's own interface, which every byte
of the earner crosses. That count includes TCP, TLS and WireGuard overhead, so
it can differ from your provider's.

At the threshold every copy through that proxy is stopped, the page shows
"Stopped: <proxy> reached 90% of its 10 GB cap on <date>", and an alert is
raised. New copies and starts are refused until the reset. A reset, on the
day or by hand, starts only the copies the cap stopped; a copy you stopped
yourself stays stopped.

Workers report every 60 seconds, so the copies can run up to a minute past the
threshold. That is why the default is 90%, not 100%.

## Tailscale exit nodes

The tunnel runs tailscaled in kernel mode, not userspace mode. In userspace
mode tailscaled's own proxy dials destinations straight from the box when the
exit node's route is missing (an exit node that went offline, lost its
approval, or a netmap that has not loaded yet), so the copy would leak from
your own IP. In kernel mode the firewall rules above let only tailscaled's own
marked packets out, so a missing exit node means no traffic, not a leak.

`scripts/proxy_leak_test_tailscale.sh` proves it against a local
[headscale](https://github.com/juanfont/headscale) control server and a
throwaway exit node, never a real tailnet. With the exit node stopped, deleted
from the control server, or not set at all, the earner reaches nothing and a
capture on the namespace's real interface sees no packet to the targets it
tried. The same checks against a namespace opened on purpose see the leak.

Before you add one:

1. In the Tailscale admin console, create an auth key: ephemeral, tagged (for
   example `tag:cashpilot-proxy`), used only for this.
2. Allow that tag to use the exit node in your access rules, for example a
   grant from `tag:cashpilot-proxy` to `autogroup:internet` through that node.
3. On the exit node's machine, turn on **Run as exit node**, and approve it in
   the admin console.
4. Add the proxy here with the key and the exit node's name or 100.x address.

Each tunnel joins your tailnet as its own ephemeral node and leaves when it is
removed. A leaked reusable key lets anyone join your tailnet, which is why the
key should be ephemeral, tagged and single-purpose.
