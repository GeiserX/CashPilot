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
| SOCKS5 | host, port, optional user and password | TCP only: the tunnel lets out only TCP to the proxy's port, so SOCKS5 UDP relays are dropped. Name lookups still work (see [DNS](#dns)). |
| HTTP CONNECT | host, port, optional user and password | TCP only. Name lookups still work (see [DNS](#dns)). |
| Tailscale exit node | an auth key and the exit node's name or 100.x address | Traffic leaves from the exit node's connection, UDP included. See [Tailscale exit nodes](#tailscale-exit-nodes). |

Any provider works. Nothing in CashPilot is specific to one.

Credentials are encrypted at rest like every other secret. The API and the
page never send them back: an edit form leaves those boxes empty, and leaving
one empty keeps what is stored. To drop a stored user or password (for example
when you move to IP allowlisting), tick **Remove the stored user** or **Remove
the stored password** and save.

The **Test** button starts a throwaway tunnel on the box picked in **Run a copy
through a proxy**, reports the exit IP and country it gets, and removes it. It
passes only when the exit IP is public and, when the worker knows its own
public IP, is not the box's own. A failed test
stays on the proxy's row, with the box and the reason, until the next test.

### Filling in a provider's details

Use the host and port your provider gives for SOCKS5 or HTTP proxies, and the
proxy user and password, not your dashboard login. Two common shapes:

| You have | Type | Host and port | User and password |
|---|---|---|---|
| A SOCKS5 endpoint with a login | SOCKS5 | `gate.example.net`, `7000` | the proxy user and password |
| An HTTP proxy that allowlists your IP | HTTP CONNECT | `203.0.113.10`, `8080` | empty |

Many residential providers rotate the exit IP on every connection unless you
ask for a sticky session, and the session or country options usually go inside
the user name (for example `user-session-abc123`). Check your provider's
documentation for the exact format. If you leave rotation on, tick **Rotating
exit IP**, because the exit IP CashPilot shows is sampled once when the tunnel
starts.

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
   marked as its own). Packets into the tunnel addressed to a private or
   tailnet range are dropped too, so the earner cannot ask the proxy to
   connect to the proxy's own LAN by address. The rule checks addresses
   only. A name the proxy resolves to a private address, or a request sent
   straight to the proxy's port, is up to the proxy's own rules, so use a
   proxy that refuses private destinations.
2. Name lookups sent to Docker's resolver are redirected into the tunnel, and
   anything else sent to that resolver is dropped.
3. The routes and the tunnel process: [tun2proxy](https://github.com/tun2proxy/tun2proxy)
   v0.8.7 for SOCKS5 and HTTP, tailscaled v1.104.4 for Tailscale.
4. A probe through the tunnel. The earner is started only after the probe sees
   an exit IP within 45 seconds, and, when the worker knows its own public IP,
   one that is not the box's own. Otherwise the copy is refused and the tunnel
   removed.

The tunnel joins the same network as every other earner. With
[LAN isolation](isolation.md#lan-isolation-by-default) on, that network is fenced
off private and tailnet ranges, so the proxy must be reachable at a public
address: a proxy on your LAN or at a tailnet address is dropped by the fence and
the probe fails. A Tailscale exit node still works, over its public endpoints or
DERP relays rather than a direct LAN path.

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
- the tunnel's log names no session or destination the earner reached;
- `docker inspect` of the tunnel shows no proxy password.

After a reboot or a Docker restart, Docker starts the tunnel but never the
earner: a container that shares another's namespace could join it before the
tunnel's firewall is loaded. The worker starts the earner on its next
heartbeat, once the tunnel has written its ready file, which happens only
after the firewall is in and an exit through the tunnel was seen. The same
happens when the earner itself crashes.

Every leak check is first run against a namespace opened on purpose (the
firewall table deleted and a default route put back) and must see the leak
there, so a check that cannot fail is caught.

### Hardening

The tunnel container gets `NET_ADMIN` and `/dev/net/tun` and nothing else:
every other capability dropped, never privileged, `no-new-privileges`, a
read-only root filesystem, a process limit, no Docker socket and no published
ports. It joins `CASHPILOT_CONTAINER_NETWORK` like every other earner, so your
host firewall rules for that bridge still apply.

The tunnel runs as root inside its own container, because cp-tunnel loads the
firewall, sets the routes and creates the tun device, and the settings files
are readable by root only. That root holds `NET_ADMIN` over the tunnel's own
namespace and nothing else; the earner runs in a separate process namespace and
cannot reach it.

The earner keeps the hardening every deploy gets. The worker API refuses
`network_mode: container:` from any caller; only the worker itself sets it for
a proxied copy. A proxied earner may never hold `NET_ADMIN`, `NET_RAW` or
`SYS_ADMIN`, or any host device: inside the tunnel's namespace those would let
it rewrite the firewall or send packets past it. The worker refuses them
whatever the catalog says.

tun2proxy runs at the `warn` log level, so the tunnel's log holds errors and
never the sites the earner's sessions reach. The log is capped at two files of
1 MB.

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
- the capabilities `NET_ADMIN`, `NET_RAW` or `SYS_ADMIN` (Bitping asks for
  `NET_RAW`);
- terms that forbid proxies or VPNs: `requirements.proxy_prohibited` in the
  catalog, with a link to the provider's own terms.

Services that need UDP do not work through SOCKS5 or HTTP CONNECT: the
tunnel lets out only TCP to the proxy's address and port. A Tailscale exit
node carries UDP.

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
proxy provider offers them (see [Filling in a provider's details](#filling-in-a-providers-details)).

The proxy's host name is looked up on the worker when a copy is deployed, and
again each time it is started from the page or by a cap reset, so a provider
that moves its gateway to a new address needs only a Stop and Start. A host
that no longer resolves stops the start, rather than sending the proxy login
to the old address.

## Editing a proxy

A copy keeps the settings it was last started with. An edit (a new password,
host, port, type, auth key or exit node) reaches a copy the next time it is
started from the page or by a cap reset: the worker writes the proxy's current
settings into the tunnel before it starts. To apply an edit to a copy that is
running, press **Stop**, then **Start**. A restart that Docker does on its own,
after a reboot or a Docker restart, uses the settings of the last start.

This needs a worker at least as new as the UI; an older worker only looks the
host name up again, and a copy on it keeps the rest until you remove it and run
it again.

## Traffic cap

Optional, off by default. Set a cap in GB (10^9 bytes, the unit providers
sell), the percentage to stop at (90 by default), and a reset day (1 to 28) or
none for resetting by hand.

Traffic is counted from the tunnel container's own interface, which every byte
of the earner crosses. That count includes TCP, TLS and WireGuard overhead, so
it can differ from your provider's. The tunnel's counters run for the
container's whole life, so a gap in reports (the UI down for hours, a worker
that could not reach it) is counted in full when reports come back.

At the threshold every copy through that proxy is stopped, the page shows
"Stopped: <proxy> reached 90% of its 10 GB cap on <date>", and an alert goes
to the bell and to your notification channel. New copies and starts are
refused until the reset. While the cap holds, every report that still shows a
copy through that proxy running stops it again, so a box that was offline at
the moment of the stop is stopped when it comes back. If a stop fails, the
alert says which copy is still running.

A reset, on the day or by hand, starts only the copies the cap stopped; a copy
you stopped yourself stays stopped. The reset day is checked every hour and
each time the app starts. If a copy cannot be started at the reset, for example
because its box is offline, every report from that box tries again until it
starts or the cap holds again. Turning a cap on starts a fresh period, so
traffic from before it existed does not count. Turning it off, or raising it
above what this period has used, lifts the stop and starts those copies again.

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

The tunnel keeps the earner off the tailnet itself: packets to `100.64.0.0/10`,
`fd7a:115c:a1e0::/48` and private ranges are dropped before they reach
tailscaled, and nothing on the tailnet can open a connection into the earner.
The script checks this against a test tailnet that allows everything.

Before you add one, in this order:

1. In your tailnet policy, declare the tag in `tagOwners` (for example
   `"tag:cashpilot-proxy": ["autogroup:admin"]`) and allow it to use the exit
   node, for example a grant from `tag:cashpilot-proxy` to
   `autogroup:internet`. Check that no other rule matches the tag (a default
   allow-all policy does); the tunnel blocks the tailnet anyway, but the
   policy should not offer it.
2. Create an auth key that is **reusable**, **ephemeral** and tagged with
   `tag:cashpilot-proxy`. It must be reusable: the tunnel keeps no state, so
   every Test, every copy and every restart of a copy (a reboot, a worker
   update, a cap reset) joins as a new ephemeral node with the same key. A
   one-off key works once and then every start fails with "the auth key was
   refused".
3. On the exit node's machine, turn on **Run as exit node**, and approve it in
   the admin console.
4. Add the proxy here with the key and the exit node's name or 100.x address.

Each tunnel joins your tailnet as its own ephemeral node and is removed from
it soon after it stops. Keys expire (90 days at most); when one does, every
start fails the same way. Create a new key, paste it into the proxy's
settings, then press **Start** on each copy (see [Editing a proxy](#editing-a-proxy)).
A leaked reusable key lets anyone join your tailnet as that tag,
which is why it must be ephemeral, tagged and used for nothing else.
