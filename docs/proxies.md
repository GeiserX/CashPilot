# Proxied copies

A proxied copy is an extra copy of a service that leaves through a proxy
instead of your box's own internet connection. Providers count devices per
public IP, so one box can earn on several IPs: its own, plus one per proxy.

You add a proxy once, then pick a box, a service already deployed on it, and
the proxy. The copy runs with the same settings as the service on that box,
under its own device name (`cashpilot-box-p3` for proxy 3).

A service can also run only through a proxy, from its first start: see
[Route a service at deploy](#route-a-service-at-deploy).

## Route a service at deploy

A proxied copy runs beside the service, so the service itself still starts once
from the box's own IP. When you do not want the provider to see that IP at
all, pick a **Route** on the deploy form: the box's own IP (the default), or
one of your proxies. With a proxy, the service never runs outside the tunnel:
its first and every later start is inside it.

- **Only services that can run through a proxy get the choice.** The catalog
  decides, by the rules in
  [What cannot run through a proxy](#what-cannot-run-through-a-proxy). A
  service that publishes a port, keeps a volume, needs a device or extra
  capabilities, or whose terms forbid proxies has no Route box, and the form
  says why.
- **It runs with the settings you deploy it with,** under the device name you
  give it. There is no second device: the routed service is the only copy of
  it on that box.
- **One route per box, one copy.** A routed service runs one instance. To
  route a service that already runs from the box's own IP, remove it first,
  then deploy it with the route; the box's IP was already seen once. To move it
  to another proxy, remove it and deploy it again through the new one: the
  worker refuses a route through a second proxy while a routed copy through
  the first still exists.
- **Its own tunnel.** A routed service gets a tunnel of its own
  (`cashpilot-tunnel-p<id>-<service>`), so it never shares a namespace with
  another provider's software. Proxied copies keep sharing one tunnel per
  proxy, as in [One tunnel per proxy](#one-tunnel-per-proxy).
- **Stop, Start, Restart, Logs and Remove act on it** from the dashboard and
  the service page, as they do on any service. A routed row shows the exit IP
  and country it leaves from.
- **Leaving the route asks for your password.** The worker remembers every
  service routed on it, in its data folder (`.routed`), and refuses to start
  it from its own IP without your confirmation, even after you remove it, and
  whichever way the deploy arrives (the form, a redeploy, the API, an agent).
  The confirmation is the same password prompt as for a wallet change, and it
  names the IP the provider would then see. On the deploy form of a routed
  service, the Route box keeps the route by default, and a box that already
  runs it is ticked and locked like any deployed box. Pick **Direct** to leave
  the route: the boxes where it runs routed unlock, and you tick the ones to
  switch. Back on the default they lock again, so a plain redeploy never asks
  for the password. The worker also refuses to leave the route while a routed
  copy of the service still runs through any proxy on it.

The usual route is a Tailscale exit node at another site you own (a
relative's house, a second line): set it up with the steps in
[Tailscale exit nodes](#tailscale-exit-nodes). In short, an auth key that is
reusable, ephemeral, pre-approved and tagged `tag:cashpilot-proxy`, and a
tailnet policy that lets that tag reach `autogroup:internet` through the exit
node and nothing else. A SOCKS5 or HTTP proxy works the same way, but it is not
encrypted (see [What a proxy can be](#what-a-proxy-can-be)).

Routing hides the box's IP from the service's own traffic: its connections,
its name lookups and its registration with the provider's servers. It does not
hide it from what you do outside the container. Your login to the provider's
website, an earnings collector CashPilot runs from the UI's own connection, and
a referral or payout page you open in your browser all come from wherever they
run. If the provider must never link the account to your home IP, open its
website through the same exit too.

### A worker that runs only routed services

Set `CASHPILOT_PROXIED_ONLY=true` in a worker's environment and it refuses to
start any earner outside one of its tunnels. A deploy without a route, a
redeploy of an old direct service, an extra copy, and Start or Restart of a
direct service all fail with a message naming the setting. A direct service
that was already running when you set it is stopped when the worker starts and
checked again every 30 seconds; Docker would otherwise start it after each
reboot. After a reboot it can run for the few seconds before the worker is up,
so remove direct services from the box (or redeploy them with a route) rather
than leave them stopped. Proxied copies and routed services still run. Picking
**Direct** for a routed service on such a box is refused before anything
changes: its routed copy and its route stay. The UI cannot change it: only whoever edits the worker's
compose file can. The deploy form marks such a box **proxy only**.

## What a proxy can be

| Type | What you give it | Notes |
|---|---|---|
| SOCKS5 | host, port, optional user and password | TCP only: the tunnel lets out only TCP to the proxy's port, so SOCKS5 UDP relays are dropped. Name lookups still work (see [DNS](#dns)). Not encrypted: the user, the password and any plain-HTTP traffic cross the network in the clear. |
| HTTP CONNECT | host, port, optional user and password | TCP only. Name lookups still work (see [DNS](#dns)). Not encrypted, as SOCKS5. |
| Tailscale exit node | an auth key and the exit node's 100.x address | Traffic leaves from the exit node's connection, UDP included. See [Tailscale exit nodes](#tailscale-exit-nodes). |

Any provider works. Nothing in CashPilot is specific to one.

Credentials are encrypted at rest like every other secret. The API and the
page never send them back: an edit form leaves those boxes empty, and leaving
one empty keeps what is stored. To drop a stored user or password (for example
when you move to IP allowlisting), tick **Remove the stored user** or **Remove
the stored password** and save.

A stored secret is kept only while the proxy points at the same server. When
you change a SOCKS5 or HTTP proxy's host or port, or a Tailscale proxy's login
server, type the user, password or auth key again (or tick **Remove** to save
without it); the save is refused otherwise. So an edit can never send a stored
credential to a server it was not entered for. A new name, cap or exit node
keeps the stored secret.

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

Every copy through one proxy on one box shares a single tunnel:

1. A **tunnel** container from `drumsergio/cashpilot-tunnel`, created at the
   same exact version as the worker (it keeps that image until it is replaced,
   see below), named `cashpilot-tunnel-p<id>` for proxy
   `<id>`. It owns a network namespace and makes the proxy the only way out
   of it.
2. One **earner** per copy, started with `network_mode: container:<tunnel>`.
   It has no network interface of its own.

So seven copies through one proxy on a box are eight containers, not
fourteen. See [One tunnel per proxy](#one-tunnel-per-proxy) for why and what it
changes.

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
   removed. A copy added through a proxy whose tunnel already runs on the
   same settings skips all four steps: its earner is created inside the
   running tunnel, and no other copy is touched.

The tunnel joins the same network as every other earner. With
[LAN isolation](isolation.md#lan-isolation-by-default) on, that network is fenced
off private and tailnet ranges, so the proxy must be reachable at a public
address: a proxy on your LAN or at a tailnet address is dropped by the fence and
the probe fails. A Tailscale exit node still works, over its public endpoints or
DERP relays rather than a direct LAN path.

### It fails closed

If the proxy goes down, the tunnel process dies or the tunnel container stops,
no earner in that tunnel has a way to send a packet anywhere: not to the
internet from your own IP, not to your LAN, not to the Docker bridge. They stop
earning; they never leak. Copies in one tunnel still share its loopback, so one
can reach a listener another opened on 127.0.0.1; that never leaves the tunnel.

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
- a name that resolves to a private address on the proxy's own network
  (`172-25-0-4.nip.io`) does not reach that address;
- an address in `100.64.0.0/10` on the tunnel's own loopback is not reachable;
- `docker inspect` of the tunnel shows no proxy password.

`scripts/proxy_shared_tunnel_lab.sh` runs the same kind of checks with two
earners in one tunnel, and drives the worker's own code with 1 and 7 copies;
see [One tunnel per proxy](#one-tunnel-per-proxy).

After a reboot or a Docker restart, Docker starts the tunnel but never the
earners: a container that shares another's namespace could join it before the
tunnel's firewall is loaded. The worker starts the earners on its next
heartbeat, once the tunnel has written its ready file, which happens only
after the firewall is in and an exit through the tunnel was seen. The same
happens when an earner itself crashes. A copy you stopped, or the traffic cap
stopped, stays stopped: the worker writes each stop down in its data folder
(`.proxied_held`), because the tunnel keeps running for the other copies.

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

### One tunnel per proxy

Copies through the same proxy already leave from the same exit IP, so a tunnel
each bought them nothing, and a tunnel costs more memory than most earners: a
Tailscale tunnel holds about 20 MB of heap in tailscaled whatever the traffic,
plus its own copy of the binaries on storage drivers that do not share page
cache between containers (btrfs). With seven copies through one exit node we
measured the seven tunnels at 339 MB of cgroup memory, carrying 190 MB of
earners. One tunnel per proxy per box costs what one of those tunnels cost,
however many copies it carries, and is one tailnet device instead of seven.

What stays the same: the firewall, the ready file, the heartbeat gate, the
hardening of both containers and everything you set up. What changes:

- **The traffic shown and capped is per proxy per box**, not per copy. Every
  copy in a tunnel moves its bytes over the same interface, so the counters
  cannot be split between them. The cap counts each tunnel once.
- **Copies in one tunnel share a network namespace.** Each can see the other
  copies' sockets in `/proc/net` and reach anything another copy listens on at
  `127.0.0.1`. None of them can read another's traffic or change the firewall:
  no proxied earner gets `NET_ADMIN`, `NET_RAW` or `SYS_ADMIN`. If you do not
  want two providers' software side by side like that, run them through
  different proxies.
- **One tunnel failure stops every copy on that proxy on that box.** It fails
  closed, as above. They already depended on the same proxy.
- **An edited proxy restarts the tunnel in place.** A start with new settings
  (see [Editing a proxy](#editing-a-proxy)) first proves them in a throwaway
  Test tunnel. Only once that tunnel reaches the internet are they written into
  the proxy's tunnel, which restarts; its copies restart inside it. Settings
  that cannot reach the internet cost the running copies nothing. If the new
  settings pass the test and then fail in the tunnel, the old ones go back.
- **Copies are recreated as rarely as possible.** A copy keeps whatever its
  provider wrote inside the container (several write a device id there), and a
  recreated container starts without it, so the provider sees a new device. An
  edit, a worker update and a reboot never recreate a copy. The tunnel keeps
  the image it was created with until it is replaced, which happens only when
  you redeploy the only copy in it, or when Docker can no longer start it at
  all. In that last case a new tunnel proves its exit first, then every copy is
  recreated inside it (same image, environment, labels and limits, from what
  Docker recorded), because a container's network namespace is fixed when it
  is created.
- **A move never loses a copy.** While a copy is recreated, its old container
  is kept under `<name>-moving` until the new one holds the name and runs. A
  move that fails puts the old container back. If the worker stops in the
  middle, it finishes or undoes the move when it starts again or, at the
  latest, at a heartbeat about five minutes later.
- **The tunnel stops when the last copy that should run stops**, and is
  removed with its settings volume when the last copy is removed.

Upgrading a worker from one tunnel per copy needs nothing from you. At start
the worker moves each proxy's copies into one tunnel, reusing the settings of
a running tunnel of that proxy, then removes the old tunnels. Each copy is
down for a few seconds, once, and is recreated, so a provider that keeps its
device id inside the container sees a new device once and the old one goes
offline. Copies you had stopped stay stopped. A proxy
with no running tunnel at that moment moves on the next start of one of its
copies; until then its old tunnels keep working as before.

`scripts/proxy_shared_tunnel_lab.sh` proves this against a local headscale
tailnet. With two earners in one tunnel: both reach the internet and none of it
leaves the tunnel's interface in the clear; stopping one earner does not
interrupt the other; neither reaches another tailnet node; a lookup of a random
name never shows on the tunnel's interface; while the tunnel restarts neither
has an interface to send on; and with the exit node stopped, tailscaled frozen
or killed, or no exit node set, neither reaches the internet or the LAN and a
capture sees no packet. Three negative controls must turn those checks red: the
firewall deleted, a copy created on the bridge instead of inside the tunnel,
and a tunnel image whose output policy is accept. It then drives the worker's
own code with 1 and 7 copies, checks there is one tunnel, that every copy
reaches the internet and none does with the exit node stopped, measures the
memory, and moves copies deployed by the previous release into one tunnel.

## DNS

Name lookups from the earner never leave the box directly. tun2proxy sends
each one as DNS over TCP, port 53, through the proxy, so the name is resolved
from the proxy's side and the answer is a real address. The tunnel's firewall
then judges that address like any other: a name that points at a private,
loopback or tailnet address is dropped before it leaves the tunnel, so a
name cannot be used to reach your LAN or the proxy's own network.

Many HTTP proxies allow connections to port 443 only, and some SOCKS5
providers block port 53. The tunnel checks this when it starts: when names do
not resolve but the proxy carries a connection to an address, it lets the
proxy resolve names instead, as before, and says so in its log. The earner
keeps earning, but a name that points at the proxy's own network is then not
filtered. Allow TCP port 53 on the proxy, or use another proxy, to close that.

The earner cannot talk to the proxy itself either. It shares the tunnel's
network, but the firewall lets out to the proxy only the tunnel's own
connections, told apart by their cgroup. Otherwise an earner could open its
own session to a proxy that trusts the box's IP and ask for the proxy's own
network. A host without cgroup v2, or a kernel that cannot match on it, keeps
the older rule and the tunnel's log says so.

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

### Commercial proxy services

A copy that CashPilot starts can still earn nothing, because the proxy
service decides what it will carry. Many commercial residential and ISP
proxy services refuse to connect to other bandwidth-sharing services, so
the earner never reaches its own servers. Some also connect only to ports 80
and 443, and several earners talk to their servers on other ports.

**Test** checks that the tunnel reaches the internet through the proxy with a
public exit IP that is not the worker's own. It does not check that a given
earner's servers can be reached. After you start a copy, read its logs. An
earner that keeps retrying its login or connection earns nothing: the proxy
refusing it is one cause, wrong earner credentials are another, so read the
error before blaming either.

A Tailscale exit node on a connection you own has none of the proxy service's
limits: it carries any port, UDP included. The exit's own network can still
block a port, the same as for an earner running there.

#### Probe an earner's servers through the proxy

Do this before you rely on a copy, and again whenever one earns nothing. You
need the host and port the earner connects to. Its log usually names them
(`docker logs cashpilot-<service>-p<proxy id>`), or the provider's docs do.

**Before you deploy, from any machine.** Ask the proxy directly. curl prints
the proxy's answer to its `CONNECT` request. An `http://` proxy and a
`socks5h://` proxy both receive your user and password unencrypted (only the
connection to the earner's server is TLS), exactly as they do from the
tunnel, so probe from a network you trust.

```bash
# HTTP CONNECT proxy; curl asks for the password, so it stays out of your shell history
curl -v -m 15 -o /dev/null --noproxy '' -x 'http://gate.example.net:8080' --proxy-user USER https://earner-host.example:443/
# SOCKS5 proxy, name resolved by the proxy
curl -v -m 15 -o /dev/null --noproxy '' -x 'socks5h://gate.example.net:7000' --proxy-user USER https://earner-host.example:443/
```

For an HTTP proxy, `-v` makes curl print the `Proxy-Authorization` header it
sends, and that header holds your user and password in Base64, which anyone
can decode. Delete that line before you share the output.

A `403`, `Access violation`, `connection not allowed by ruleset` or a closed
connection right after the `CONNECT` means the proxy refuses that host or
port. A `200` to the `CONNECT` means the proxy let it through, so a TLS
error after that comes from the far server or the protocol, not the proxy.
Try the earner's real port, not only 443: a proxy that allows 443 and nothing
else passes a 443 test. These probes speak HTTPS; for an earner whose server
speaks something else, curl fails on both paths below whatever the proxy does,
so use a client for that protocol that needs an answer from the server.

**After you deploy, through the proxy's tunnel.** Join the tunnel's
network namespace with a throwaway container. Run the same probe once from
the box's own network as the control, so you know what an answer looks like:

```bash
TUN=cashpilot-tunnel-p<proxy id>
URL=https://earner-host.example:443/

# Control: straight from the box
docker run --rm --cap-drop ALL curlimages/curl:8.10.1 --noproxy '*' -sS -m 10 -o /dev/null -w '%{http_code}\n' "$URL"
# Through the proxy
docker run --rm --cap-drop ALL --network "container:$TUN" curlimages/curl:8.10.1 --noproxy '*' -sS -m 10 -o /dev/null -w '%{http_code}\n' "$URL"

# What the proxy answered, if it refused, in the last minute only
docker logs --since 1m "$TUN" 2>&1 | grep -i 'replied with\|failed\|error'
```

Any HTTP status from the far server, even `404`, means the path works. A
TLS error such as `SSL_ERROR_SYSCALL`, `Connection reset by peer` or `Empty
reply from server` through the tunnel, where the control got a status, means
something closed the connection. If the proxy refused it, the tunnel's log has
a line such as `Server replied with 403 [Reason: Access violation]`, naming the
port, for an HTTP proxy, or `SOCKS connection failed: ...` for a SOCKS5 proxy.
The address in it is a placeholder from the tunnel's DNS, not the real
one. The earner's own traffic shares this log, so match the port and the time
of your probe. With no such line, the earner's server may be refusing the proxy's exit
IP rather than the proxy refusing the server, since the control and the
tunnel leave from different addresses.

!!! warning "A plain port check proves nothing through the tunnel"

    `nc -z` and other connect-only checks report the port open through a
    tunnel even when the proxy refused, and even for an address where nothing
    exists. The tunnel accepts the connection locally first, then asks the
    proxy. Use a probe that needs an answer from the far server, as above.

#### A new device the provider accepts only later

Some providers add a new device to your account only after its client has
been connecting for a while. [ProxyRack](https://peer.proxyrack.com/ref/mpwiok3xlaxeycnn5znqlg7ipjeutxyxr6xl7vmn)
knows a new device about five minutes after it first connects, so an add
right at deploy is refused. This holds for a proxied copy as much as for a
deploy on the box. When the provider says "not yet", CashPilot keeps the
device and tries again: first after 6 minutes, then at doubling intervals up
to 4 hours apart. After 24 hours without success it stops and sends a notice,
to the bell and to your notification channel, with the manual step. It needs that provider's credentials saved in CashPilot.
While it is still trying, the dashboard does not ask you to add the device by
hand. A redeploy after CashPilot gave up starts a new 24 hours; a redeploy
while it is still trying keeps the current window.

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

The copies on a box keep the settings their tunnel was last started with. An
edit (a new password, host, port, type, auth key or exit node) reaches them the
next time any copy through that proxy on that box is started from the page or
by a cap reset. If the tunnel is stopped, the worker writes the proxy's current
settings into it and starts it. If it is running for other copies, the worker
tests the new settings in a throwaway tunnel, then writes them into the running
one and restarts it with its copies (see
[One tunnel per proxy](#one-tunnel-per-proxy)). To apply an edit now, press
**Stop**, then **Start** on one copy on each box. A restart that Docker does on
its own, after a reboot or a Docker restart, uses the settings of the last
start.

This needs a worker at least as new as the UI; an older worker only looks the
host name up again, and a copy on it keeps the rest until you remove it and run
it again.

## Traffic cap

Optional, off by default. Set a cap in GB (10^9 bytes, the unit providers
sell), the percentage to stop at (90 by default), and a reset day (1 to 28) or
none for resetting by hand.

Traffic is counted from the tunnel container's own interface, which every byte
of every earner in it crosses, so on each box it is one count for all the copies
through that proxy. That count includes TCP, TLS and WireGuard overhead, so
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
   refused". If your tailnet has device approval turned on, make the key
   **pre-approved** too, or every start waits for you in the admin console.
3. On the exit node's machine, turn on **Run as exit node**, and approve it in
   the admin console.
4. Add the proxy here with the key and the exit node's 100.x address. Not its
   name: the tunnel sets the exit node while Tailscale is still starting, when
   names do not resolve yet, and the start then fails with "the auth key was
   refused".

Each box joins your tailnet once per proxy, as one ephemeral node that asks
for the name `cashpilot-p<id>`, however many copies it carries. Tailscale
gives each device a name of its own, so when two boxes carry copies through
the same proxy, the second one shows as `cashpilot-p<id>-1`. A Test joins as
a node of its own for the length of the test. When a tunnel stops (a removal,
a restart, the end of a Test, the box shutting down cleanly) it logs out
first, which deletes its device at once and frees its name. It usually comes
back under that name, unless another box on the same proxy took it meanwhile.
The logout needs nothing more from the key, but it needs to reach Tailscale:
a tunnel killed without a stop (a power cut, an out-of-memory kill), or one
that cannot reach Tailscale as it stops, leaves its device behind. Tailscale
removes an ephemeral device once it has been offline a while, and until then
the next start gets a `-1` name. Keys expire (90 days at most). A copy still
starts in a tunnel that is already running, but a tunnel that has to join
the tailnet again (after a stop, a restart or a settings change) fails the
same way as a wrong key. Create a new key, paste it into the proxy's
settings, then press **Start** on each copy (see [Editing a proxy](#editing-a-proxy)).
A leaked reusable key lets anyone join your tailnet as that tag,
which is why it must be ephemeral, tagged and used for nothing else.

### A second site as an exit node instead of a worker

If you have a machine at a second site (a relative's house, a holiday flat)
you can run a worker and earners there, or only make it a Tailscale exit node
and run the earners elsewhere as proxied copies that leave through it. The
second way suits a small box: an exit node only forwards packets, while each
earner is a container with its own memory and CPU.

It makes sense when:

- the box is short on memory or CPU, or does other work you do not want to
  slow down;
- what you want from that site is its residential IP, not its hardware;
- you would rather keep containers and updates on one machine you look after.

What changes:

- **Only services that can run as a proxied copy move.** Anything that needs
  published ports, volumes, devices or extra capabilities stays where it runs
  ([What cannot run through a proxy](#what-cannot-run-through-a-proxy)).
  That rules out Mysterium and the storage nodes, for example. Earners whose
  terms forbid proxies or VPNs are refused too.
- **The per-IP limits move with the IP.** A copy through the exit node counts
  against that site's public IP. If the box there still runs a service with a
  limit of one device per IP, a copy of the same service through its exit
  earns nothing. The page warns only once the copy is running, since that is
  when it learns the exit IP
  ([Exit IPs and grouping](#exit-ips-and-grouping)). Move each service, do
  not double it: stop it on the second site's worker before you start its
  copy.
- **The traffic crosses both connections.** The earner's traffic goes from
  the box running the copy, over the tailnet, to the exit node, and out from
  there. The exit's connection carries it in both directions, and the copy's
  own box carries it too, encrypted. Check both upload allowances.
- **The exit node still does work.** It encrypts and forwards every packet, so
  its CPU rises with the traffic. Measure it under load (see
  [Budgeting a small box](fleet.md#budgeting-a-small-box)).
- **The box that runs the copies holds one tunnel per proxy**, shared by every
  copy through it, plus one container per earner (and one tunnel more per
  service routed through it at deploy). The tunnel joins the tailnet
  as that box's ephemeral node for the proxy; the earners share its network
  and never join it.
- **The path to the exit node is over the internet.** With
  [LAN isolation](isolation.md#lan-isolation-by-default) on, the tunnel reaches
  the exit node over its public endpoints or a DERP relay, never a LAN path. A
  relay carries the traffic further and slower; a direct connection between
  the two sites avoids it.

On a Linux machine, the exit node also needs IP forwarding turned on before
Tailscale lets it advertise itself; Tailscale's
[exit node guide](https://tailscale.com/kb/1103/exit-nodes) has the commands
per system. Then set it up with the steps in [Tailscale exit nodes](#tailscale-exit-nodes).
For each service you move, the simplest way is to remove it from the second
site's worker and deploy it on the worker that will run it, with the exit node
as its **Route** ([Route a service at deploy](#route-a-service-at-deploy)).
To keep it running there as well, add a proxied copy instead:

1. Deploy it on the worker that will run the copy, if it is not there yet: a
   copy runs with that worker's deployment of the service and is refused
   without one.
2. Remove it from the second site's worker, if one still runs there. That also
   removes any proxied copies of it on that worker, so note them first and add
   them again on another worker.
3. Add its copy through the exit node.

## From the command line or an agent

Everything on the page goes through the UI's API, so a script or an agent such
as Claude Code can do the same with the admin key (`CASHPILOT_ADMIN_API_KEY` in
the UI's environment). The proxy's secrets go in once and never come back out.
The example needs bash or zsh (for `read -s`) and `jq`. The admin key and the
proxy key never appear on a command line, where other users of the machine
could read them in the process list.

```bash
( # a subshell, so the trap below removes the key file however it ends
UI=http://localhost:8080
WORKER=1  # the box's worker id, from GET /api/workers
AUTH=$(mktemp) || exit 1  # the admin key goes to curl from this file, not as an argument
trap 'rm -f "$AUTH"' EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
printf 'Authorization: Bearer %s\n' "$CASHPILOT_ADMIN_API_KEY" >"$AUTH"

# 1. Add the proxy (for SOCKS5: "kind": "socks5", "host", "port", "username", "password").
#    The key is read without echo and sent on stdin.
read -rs TS_AUTH_KEY
PROXY=$(printf '{"name": "Exit at home", "kind": "tailscale", "auth_key": "%s", "exit_node": "100.101.102.103"}' \
  "$TS_AUTH_KEY" | curl -sf -H @"$AUTH" -H 'Content-Type: application/json' -X POST "$UI/api/proxies" --data @- |
  jq -er .id) || { echo "the proxy was not added" >&2; exit 1; }

# 2. Test it from the box: the exit IP it gets.
curl -s -H @"$AUTH" -X POST "$UI/api/proxies/$PROXY/test?worker_id=$WORKER"

# 3. Run copies of services already deployed on that box. The first starts the
#    tunnel; the others join it.
for slug in repocket earnfm traffmonetizer; do
  curl -s -H @"$AUTH" -H 'Content-Type: application/json' -X POST "$UI/api/proxies/$PROXY/copies" \
    -d "{\"worker_id\": $WORKER, \"slug\": \"$slug\"}"
done

# 4. See them, with the exit IP and the traffic per proxy.
curl -s -H @"$AUTH" "$UI/api/proxies"

# Stop, start or remove one copy.
curl -s -H @"$AUTH" -X POST "$UI/api/proxies/$PROXY/copies/$WORKER/earnfm/stop"
curl -s -H @"$AUTH" -X POST "$UI/api/proxies/$PROXY/copies/$WORKER/earnfm/start"
curl -s -H @"$AUTH" -X DELETE "$UI/api/proxies/$PROXY/copies/$WORKER/earnfm"
)
```

On the box itself, `docker ps -a --filter label=cashpilot.proxy=<id>` lists the tunnel
and every copy through that proxy; each copy's `docker inspect` shows
`"NetworkMode": "container:<the tunnel's id>"`.

