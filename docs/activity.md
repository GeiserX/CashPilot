# Activity: what each earner does on the network

Bandwidth earners carry other people's traffic through your connection. The
Activity page shows what each earner container actually does with it: how many
connections it opens and how many fail, how many are open at once, which ports
and networks it talks to, the country those networks are registered in, and
whether it tries to reach your own network or send mail.

It is **off by default**. You switch it on per box, on the Activity page
(owner only). Switching it off deletes that box's remote addresses at once.

## What is read, and what is not

Every 5 minutes, a box with Activity switched on starts one short-lived helper
container per earner. The helper joins the earner's network namespace and reads
three things from the kernel, nothing more:

- the socket tables in `/proc/net/tcp`, `tcp6`, `udp` and `udp6`: which local
  port is connected to which remote address and port, and in what state. It
  takes 5 snapshots over 8 seconds.
- the TCP and UDP counters in `/proc/net/snmp` and `/proc/net/snmp6`:
  connections opened (by the earner, and towards it), failed connection
  attempts, resets, datagrams (IPv4 and IPv6).
- the namespace's identity, so a recreated container is never compared with
  the old one.

It never reads what is inside the traffic: no packet capture, no names looked
up, no TLS server names, no URLs. It never changes the earner container.

Traffic in and out over time comes from the counters CashPilot already keeps
for the dashboard's usage graphs; Activity stores no second byte counter.

## What the numbers mean

- **Opens** and **Failed** are complete counts for the 5 minutes, from the
  kernel's counters. The first window after switching on, after a container
  is recreated, or after a skipped round has no recent reading to compare
  with, so it shows a dash, never 0.
- **Peak open** is the most established TCP connections seen at once.
- **Destinations** are *sampled*: a connection that opens and closes between
  two snapshots is counted in Opens but may be missing from the list. A `+`
  means there were more than the list keeps (40 outbound and 20 inbound per
  earner per window).
- A connection to a port the earner listens on is **inbound**; every other one
  is **outbound**.
- **Kind of destination**: `internet`, `DNS / Docker` (Docker's resolver, or
  port 53 or 853 to the bridge gateway, a configured resolver, Tailscale's
  100.100.100.100 or any private address, which is where the resolver Docker
  copies from the host usually sits), `another earner` (an earner on the same
  bridge network), `another container` (any other container on that bridge: on
  Docker's default bridge, every service you run), `your LAN` (private
  ranges, and the subnet of a macvlan or ipvlan network), `tailnet`
  (100.64.0.0/10), `Docker host` (the bridge gateway on any port but 53),
  `cloud metadata` (169.254.169.254), `link-local` and `multicast`. Inbound
  rows read "from …"; only outbound ones mark a container in red.
- **Network of this container, used by …**: the earner shares the network of
  a container that is not an earner (a VPN or Tailscale sidecar), which other
  apps may share too. Only the counters are kept for it: no destinations, no
  alerts, so nothing of those other apps is recorded.
- **Network** is the autonomous system (ASN) the address belongs to, and
  **Country (registered)** is where that network is registered, which is not
  where the address is: a global provider registered in one country reads
  that country everywhere.

## Limits

- **Host network** (Mysterium, for example): the earner shares the machine's
  socket table, so reading `/proc/net` would show every socket on the machine.
  Its helper joins the host network instead and asks the kernel for the socket
  list over `sock_diag`, which reports the cgroup each socket was created in.
  It keeps only the sockets of the earner's own cgroup (found by its container
  id under the read-only `/sys/fs/cgroup`, which is why the helper also joins
  the host's cgroup namespace). This needs no extra privilege. What that row
  cannot show, and says so:
  - connections already closing (TIME_WAIT) carry no cgroup, so a finished
    connection may be missed; the helper does not even ask for them, so a
    busy host does not run it out of memory;
  - when the kernel answers only part of the socket list (one without UDP
    socket listing, for example) or the list passes 200,000 sockets, the row
    keeps what it read and shows the `+`, so it never passes as complete;
  - the connection counters are the machine's, so opens and failures show a
    dash;
  - traffic an earner forwards for VPN customers is routed by the kernel, not
    opened by the earner, so it is not shown. Seeing it would need the kernel's
    connection tracking table, which needs `CAP_NET_ADMIN` on the host network
    or root, and the helper gets neither.

  When the cgroup cannot be found the row reads "host network: cannot be told
  apart" with the reason: cgroup v1 (the machine needs cgroup v2), the cgroup
  was not found (rootless Docker or Podman can hide it), the kernel refused the
  socket list, or the kernel does not report a socket's cgroup. The mail and
  LAN alerts apply to a matched host row like any other.
- **Sandboxed runtimes**: gVisor with its own network stack (a `runsc`
  runtime without `--network=host`) keeps the earner's sockets inside the
  sandbox, and other runtimes CashPilot does not know may too. A helper would
  read an empty table there, so they show "sandboxed" instead. gVisor with
  `--network=host` (the `runsc-hostnet` runtimes in
  [Protecting your home network](home-network-security.md#7-gvisor-optional))
  keeps its sockets in the container's namespace and is sampled like any
  other earner; the worker reads which is which from `docker info`.
- **A shared namespace** (`network_mode: container:<other>`, for example behind
  gluetun): one helper reads the namespace once and the row names every
  container in it. The numbers belong to the group.
- **UDP**: a socket that sends to many peers without connecting (WireGuard,
  QUIC, dVPN) shows a bound port and no destination. It is counted as bound.
- **Docker Desktop and rootless Docker**: the helper works the same way, but
  "Docker host" and "your LAN" are judged from inside Docker's VM or the
  rootless network, not from your real LAN.

## The helper

The helper is the worker's own image, so nothing new is pulled. It runs with
the same floor as the [isolation check](isolation-check.md)'s probes, and
lower: user 65534, no capabilities, read-only filesystem, no new privileges,
32 processes and 48 MB at most, a 64 KB tmpfs at `/data` so no volume is
created, and the labels `cashpilot.probe=activity` and
`cashpilot.probe.worker=<worker id>`. Its name carries a short hash of the
worker id too, so two workers on one Docker host never collide. It is removed
on every path. At start and before every round the worker removes any helper
of its own that is left, any finished helper of another worker (its log still
holds that round's addresses), and any stopped helper from an older release
that labelled no worker. It never touches another worker's running helper. A
helper Docker refuses to remove is named on the page.

The helper for a host-network earner runs with `network_mode: host` and the
host's cgroup namespace, with every other limit above unchanged.

With 12 earners that is about 144 short-lived containers an hour. They can
flash by in the Unraid Docker tab and in `docker events`.

Rounds run on the worker beside its heartbeat, never inside it: a failed round
is a missing window on this page, never a worker reported as unhealthy.

## Retention

| Data | Kept |
|---|---|
| Remote addresses (the "last 24 hours" list) | 24 hours. Purged on every window received and every hour; deleted rows are overwritten in the database file. The write-ahead log (`cashpilot.db-wal`) is emptied by the hourly purge; when the dashboard holds it busy, a warning is logged and the next hour tries again. |
| Counts per window, per container | 35 days |
| Totals per hour by port, network, country, kind and direction (no addresses) | 35 days |

Switching a box off deletes its remote addresses at once. **Delete data**
deletes everything of that box, and removing a box from the fleet does too.

A backup of the UI's `/data` taken inside the 24-hour window carries the
remote addresses of that day. Treat it accordingly, or switch Activity off and
wait for the purge before taking a backup you will share.

Nothing leaves the server: the page and the alerts never name a remote
address, and no address is sent anywhere to be looked up.

## Network names and countries

The UI downloads the [iptoasn.com](https://iptoasn.com/) `ip2asn-combined`
table (about 11 MB) into `/data/ipgeo.sqlite` and looks every address up
locally. It refreshes the table once a week while at least one box has
Activity switched on, and the page has a **Download now** button.

The table is "Licensed under Public Domain (PDDL v1.0)", in iptoasn.com's own
words, so it carries no attribution duty.

`CASHPILOT_ACTIVITY_ASN_URL` sets where the table comes from; empty disables
the download (see [Configuration](configuration.md)). Without the table every
network and country reads as unknown. To place it by hand, build
`/data/ipgeo.sqlite` from the same TSV file on another machine with
`python -c "import gzip,sys; from app import ipgeo; print(ipgeo.build(gzip.open(sys.argv[1], 'rb')))" ip2asn-combined.tsv.gz`
run in a CashPilot checkout with `CASHPILOT_DATA_DIR` pointing where it should
land, then copy the file into the UI's `/data`.

## Alerts

Alerts go to the bell (shown to the owner only) and, for the first two, to your notification channels
(ntfy, webhook, Telegram). They name the box, the container, the kind of
destination or port, and counts. They never name an address or a network.

| Alert | When | Repeats at most |
|---|---|---|
| Mail | Outbound TCP to an internet address on port 25, 465, 587 or 2525, in any state (connecting, connected, or just finished: a short send is mostly seen closing). An earner has no reason to send mail, and this is how an exit node gets your address listed as a spam source. | once a day per container |
| Your network | Any outbound connection to your LAN, your tailnet, the Docker host, a container on its bridge that is not an earner, cloud metadata or a link-local address. DNS to the resolvers above and other earners on its bridge never count. "Still pending" means no answer came, which usually means a firewall dropped it. | every 6 hours per container and kind |
| Unusual hour (bell only) | The last full hour received or sent more than 10 times the median hour of the past week and more than 1 GiB, or opened more than 10 times the median and more than 2,000 connections. Needs 72 hours of history; hours without a reading are skipped, never counted as 0. | every 12 hours |

Failed connection attempts are shown, not alerted on: proxy earners fail
against dead peers all the time.
