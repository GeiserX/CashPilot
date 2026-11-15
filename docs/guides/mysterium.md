# MystNodes

> **Category:** Bandwidth Sharing | **Status:** Active
>
> **Website:** [https://mystnodes.com](https://mystnodes.com)

## Description

MystNodes (Mysterium Network) is a decentralized VPN and proxy network built on blockchain technology. You earn MYST tokens by running a node that provides VPN, proxy, and data scraping services to users. Requires NET_ADMIN, SETUID and SETGID capabilities and a TUN device, which it uses inside its own network namespace on the fenced earner bridge. Includes a built-in web UI for node management. Works on both residential and VPS connections.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $10 (estimate) |
| Per | device |
| Minimum payout | 5 MYST |
| Payout frequency | Automatic on-chain settlement each time a node holds 5 MYST unsettled |
| Payment methods | Crypto |

> Earnings in MYST tokens. Residential IPs earn significantly more. Node WebUI at port 4449 for management, published on the machine it runs on only (127.0.0.1); from another machine open an SSH tunnel first (`ssh -L 4449:127.0.0.1:4449 <host>`, then browse `http://127.0.0.1:4449`), or put a reverse proxy in front (see **WebUI address** below). VPS accepted. Important: after first run, set your beneficiary (settlement) wallet via the node WebUI or CLI to match your mystnodes.com account -- this links on-chain earnings to your cloud dashboard.

> **One node per public IP.** Mysterium strictly enforces one active node per public IP address. Additional nodes on the same IP show as offline and earn nothing. Do not run on a phone if a Docker node is already running on the same network. Use separate public IPs (e.g. dual WAN, different locations) for additional nodes. Fleet warns before a second node is deployed behind an address that already has one.

> **Port forwarding recommended.** Forward the node's UDP range to maximize earnings; see **Port forwarding** below. Without it many VPN and proxy sessions fail to connect, which cuts income. The node runs on CashPilot's fenced bridge, or on your own network (`CASHPILOT_CONTAINER_NETWORK`), where the firewall rules are yours to supply (see [Isolation](../isolation.md)), with the `NET_ADMIN`, `SETUID` and `SETGID` capabilities.

## Cashing out

No button to press. Each node settles on Polygon by itself once it holds 5 MYST unsettled, and about 21% goes in fees (the 20% Hermes fee plus a small transaction fee), so roughly 3.9 MYST reaches the beneficiary wallet per settlement. Each node's TequilAPI lists its settlements at /transactor/settle/history. The "total earnings" figure on MystNodes covers the last 30 days only; it is neither a balance nor a lifetime total. Bonus MYST from the MystNodes rewards program does not settle by itself: claim it on the Rewards page, within 30 days of distribution according to the MystNodes help center.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | No |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Docker, Windows, Macos, Linux, Android, Browser-Extension |

## Setup Instructions

### 1. Create an account

Sign up at [MystNodes](https://mystnodes.co/?referral_code=do7v7YOoBBpbOstKQovX2pUvZYKia4ZhH3QIdNtE).

<small>Referral link: the CashPilot maintainer may earn a commission from it.</small>

### 2. Get your credentials

The node itself needs no credentials, and both of its settings have defaults. CashPilot logs in to MystNodes with your account email and password, under **Settings → Earnings collection**; the balance and lifetime figures come from the node itself, which the worker reads.

### 3. Deploy with CashPilot

In the CashPilot web UI, open **Catalog** and click **Add** on the **MystNodes** row, or click **+ Add service** in the top bar and pick it there. Both fields have working defaults, so you can click **Deploy MystNodes** as is.

## Docker Configuration

- **Image:** `mysteriumnetwork/myst`
- **Platforms:** linux/amd64, linux/arm64, linux/arm/v7

### Environment Variables

| Variable | Default | What it does |
|---|---|---|
| `UI_ADDRESS` | `127.0.0.1` | The host addresses the node's WebUI (port 4449) is published on. Comma separated, no spaces. |
| `UDP_PORTS` | `23000:23029` | The UDP ports the node uses for sessions, as `start:end`. Forward the same range. Keep it below 32768 (see *Port forwarding*). To go back to the default after changing it, remove the service from that machine (its data volume stays) and deploy again. |

### Port forwarding

Each session first tries to reach the node directly on its UDP range, and falls
back to hole punching when it cannot, which many buyers fail at. The node uses
only the range in `UDP_PORTS` (default `23000:23029`), so forward exactly that
range. Create one rule on your router:

| Field | Value |
|---|---|
| Protocol | UDP |
| External ports | 23000-23029 (your `UDP_PORTS`) |
| Internal ports | the same, 23000-23029 |
| Internal IP | the LAN address of the machine running the node |

Before you pick a range, read
[Choosing the UDP port range](../mysterium-fence.md#choosing-the-udp-port-range):
one port in it held by another program stops the node from starting, and a
range inside Linux's ephemeral port range can be taken at random. Moving a
node deployed through 2.0.6? Follow
[Moving your Mysterium node behind the fence](../mysterium-fence.md).

Give that machine a fixed LAN address (a DHCP reservation), or the rule points
at the wrong host after a lease change. UPnP does not work: the node sits behind
the LAN fence, which drops the router, so it cannot ask the router for a
forward. Forward the range by hand. DMZ is the last resort.

The node runs on CashPilot's fenced bridge, and the worker publishes the range
1:1 on the machine (`23000/udp` to `23000/udp`, and so on), so the forward on
the router is the same as when the node shared the host's network.

Keep the range below 32768. Ports 32768 to 60999 are Linux's ephemeral range: any program on the machine (a DNS lookup, a game client, a browser) can hold one of them for a moment. On the host's network the node just skipped a taken port, but Docker publishes the range as a whole, so one taken port fails the node's start. The worker then puts the previous node back and says which port was taken.

Each session takes about two ports, so the default 30 ports carry about 15
sessions at once, more than a home node gets. A range of 20 to 30 ports is
enough. A wider one costs more and fixes nothing. With Docker's default
userland proxy every published port costs about 2.5 MB of memory (Docker
starts two small proxy processes per port; 101 ports measured about 250 MB);
with `"userland-proxy": false` there are no such processes. Either way the
node's start and removal take longer with every port: 101 ports took 3.7 s to
start and 7.1 s to remove, 300 took 11.7 s and 19.2 s, 1,000 took 51 s and
84 s. CashPilot accepts a range of at most 300 ports. A node already running
with a wider one keeps running, and a redeploy of it is refused until the
range is narrowed. A node whose sessions all fail is not short of ports; see
[Routers that rewrite UDP source ports](#routers-that-rewrite-udp-source-ports).
The default was `56000:56100` through
2.0.6 and `56000:56029` in 2.0.7 and 2.1.0, both inside the ephemeral range. A node keeps
the range it has on record on a redeploy, unless that range is wider than
300 ports. To move it, set `UDP_PORTS` to a
free range below 32768 other than the default, such as `23100:23129`, change
the router forward to match, and redeploy. A value equal to the default reads
as a field left as it was, so the recorded range would stay. To take the
default itself, remove the service from that machine (its data volume stays)
and deploy again.

Or keep the range on record and reserve it on the host, so the kernel stops
handing its ports out to other programs, then redeploy without touching the
router. For
`56000:56100`, on the machine running the node, first read
`sysctl net.ipv4.ip_local_reserved_ports`: if it already lists ranges, add
`56000-56100` to them, comma-separated, and use that whole list in both
commands below, or the first one drops the reservations already there.

```bash
sudo sysctl -w net.ipv4.ip_local_reserved_ports=56000-56100
echo 'net.ipv4.ip_local_reserved_ports = 56000-56100' | sudo tee /etc/sysctl.d/90-mysterium-ports.conf
```

The file under `/etc/sysctl.d/` keeps it after a reboot. A reservation only
stops the kernel handing those ports out on its own: a program on the machine
that binds one of them by number still takes it, and the node's start fails as
before. The worker cannot read the host's setting (it runs on its own network,
which has its own copy), so the Fleet warning about the range stays after you
reserve it; once the range is reserved, redeploy anyway.

**Another sysctl file can undo the reservation at boot.** The files are read
in order and the last one to set `net.ipv4.ip_local_reserved_ports` wins. If a
file that sorts later, such as `99-something.conf`, also sets it for another
program, your reservation is gone after the next reboot, with nothing saying
so. Find every file that sets it:

```bash
# The file names are the "# /path" header lines; systemd-sysctl is usually not on PATH
# (older Debian without a merged /usr: /lib/systemd/systemd-sysctl)
/usr/lib/systemd/systemd-sysctl --cat-config | grep -E '^# /|reserved_ports'
# without systemd, as root so no file is skipped:
sudo grep -Rn reserved_ports /etc/sysctl.conf /etc/sysctl.d/ /run/sysctl.d/ \
  /usr/local/lib/sysctl.d/ /usr/lib/sysctl.d/ /lib/sysctl.d/ 2>/dev/null
```

In the first output, the `reserved_ports` line belongs to the header just above it.

Put the whole combined list in one file, comment out the line in every other
file that sets it, and read `sysctl net.ipv4.ip_local_reserved_ports` again
after the next reboot. If the other file belongs to a package or a tool that
rewrites it, your edit will not last: give your file a name that sorts after
it instead, so the combined list is read last. With `systemd-sysctl` (the
first command above), the last file in its output wins; it reads
`/etc/sysctl.conf` only through a `99-sysctl.conf` link, so a file named
after that one, such as `zz-mysterium.conf`, still overrides it. With
`sysctl --system` and no systemd, `/etc/sysctl.conf` is read after every
directory and no file name sorts after it: if the other setter is there, put
the combined list in that line. If a tool rewrites `/etc/sysctl.conf` itself,
set the combined list in that tool's own settings, or the next rewrite drops
your reservation.

**A firewall of your own in `DOCKER-USER` can drop the sessions.** Once the
node is on CashPilot's bridge, customer packets to its UDP range are forwarded
to a container, no longer delivered to the host itself. They pass Docker's
`DOCKER-USER` chain. If yours ends with a rule that drops what comes in from
the internet, such as `-i <wan interface> -j DROP`, every session to the
forwarded range is dropped there. Add a rule directly above that drop,
with your own interface and range, and below any deny rules you already
have, so they keep applying. It returns the packet to Docker's own rules
rather than accepting it, so Docker's filter for unpublished ports still
applies. Find the drop's position with
`sudo iptables -L DOCKER-USER --line-numbers` and insert at that number. `cp-isolated` is the bridge CashPilot creates; on a
network of your own (`CASHPILOT_CONTAINER_NETWORK`), use that network's bridge:

```bash
sudo iptables -I DOCKER-USER <drop's line number> -i <wan interface> -o cp-isolated -p udp --dport <start>:<end> \
  -m conntrack --ctstate DNAT --ctorigdstport <start>:<end> -j RETURN
```

Docker has already rewritten the destination when a packet reaches this
chain, so `--dport` alone would also match another container that maps some
other host port onto a port in this range. The `--ctorigdstport` match checks
the port the packet was sent to as well, and `--ctstate DNAT` that Docker
rewrote it, which only a published port gets. The node publishes its range 1:1 and
holds those host ports, so only its own sessions match.

Then save it wherever your boot loads the rules from (for example
`/etc/iptables/rules.v4` with `netfilter-persistent`), in the same order, or
it is gone after a reboot. Check the saved file against the live chain
(`sudo iptables -S DOCKER-USER`), because they can drift apart, and check the
live chain again after the next reboot.

The node's own check confirms it. Note the time right after the change,
wait for a new session, then read only the log from that time, so an older
success cannot answer for it:

```bash
T=$(date -u +%Y-%m-%dT%H:%M:%SZ)   # right after the change
# ...after a new session:
docker logs --since "$T" cashpilot-mysterium 2>&1 | grep -E 'are reachable|Failed to check manual ports'
```

It should show `All ports [...] are reachable`. That line covers the ports in
its brackets, so compare them with your range.

**Check it.** After a few sessions, on the machine running the node:

```bash
docker logs cashpilot-mysterium 2>&1 | grep -o 'Method:[a-z]* Success:[a-z]*' | sort | uniq -c
```

`Method:manual Success:true` means buyers' packets reach the node through the
forward. It does not prove the sessions work: that also needs the node's
answers to leave from the ports it advertised, and a router that rewrites UDP
source ports breaks that while this line stays `true` (see
[Routers that rewrite UDP source ports](#routers-that-rewrite-udp-source-ports)).
Only `Method:manual Success:false` lines, each followed by
`Method:holepunching`, mean the forward does not work. The node's `/nat/type` keeps
reporting `prcone` whether forwarding works or not, so don't go by it.

CashPilot checks this too, every 30 minutes. When a node has had at least five
failed direct connections and not one successful one in the last 6 hours, the
dashboard lists it under **Needs fixing** with the range and address to forward.
The item clears by itself once a session connects directly. A node with no
sessions yet is not flagged. The dashboard reloads its list every hour, or when
you open it.

On the same 30-minute round the worker also asks the node itself, read-only,
for Mysterium's monitoring status and the five sessions that completed last. It
lists the node under **Needs fixing** when the monitoring status is `failed`,
and when those five sessions each ended after about a minute having carried no data. Once a
missing `/dev/net/tun` or `SETUID`/`SETGID` is ruled out, both point at the
problem in the next section.

### Routers that rewrite UDP source ports

**Symptom.** The node is online, its port check says `All ports [...] are
reachable` and the log shows `Method:manual Success:true`, yet it earns
nothing. Every session ends after about 60 seconds with 0 bytes either way:

```bash
docker exec cashpilot-mysterium wget -qO- \
  'http://127.0.0.1:4050/sessions?direction=Provided&status=Completed&page_size=10' \
  | grep -o '"duration":[0-9]*,"bytes_received":[0-9]*,"bytes_sent":[0-9]*'
```

`/node/monitoring-status` answers `{"status":"failed"}`,
`/node/monitoring-agent-statuses` shows `connect_fail` with no
`tun_device_problem`, the node's STUN check logs `NATType:restricted` where a
working line gives `full`
(`docker logs cashpilot-mysterium 2>&1 | grep -o 'NATType:[a-z]*' | sort | uniq -c`),
and Mysterium's discovery stops offering the node to most buyers. A missing
`SETUID`/`SETGID` or `/dev/net/tun` looks much the same; rule those out first
with [the section below](#running-but-not-earning-monitoring-failed-quality-0).

**Cause.** The router in front of the machine uses an address-dependent
mapping that switches on after inbound traffic. While nothing has come in on
an external port P, outgoing flows from P keep their number. Once any packet
from outside arrives at P, every later outgoing flow from P to a different
address leaves with a rewritten source port. It happens whether or not the
packet reaches anything: ports the host's firewall drops are affected too.

Every Mysterium session does exactly that. Before a session the node's port
check has an echo server send a packet in to the session port, so that port
is now marked. The node then answers the buyer from that port, the router
rewrites the answer's source port, and the buyer's client drops it, since it
came from a port the node never offered. The session is set up, never carries
a byte, and times out. Inbound works throughout, so every check that only
tests inbound passes. A wider `UDP_PORTS` range does not help: each session
marks its own port before it uses it.

Some of these boxes (often an ISP fibre box with a built-in router) also
reserve outgoing UDP ports in pairs: when they map port P they hold P XOR 1
(23000 and 23001, 23002 and 23003), and a later flow from the partner port
leaves with a random port. That is real but secondary. On its own it rewrote
only a few percent of ports, and almost none in a wide range.

**Confirm it.** The decisive test is to send one packet in to a port from
another network, then ask a public STUN server which port it sees for a flow
out from that same port. It needs a second machine outside your home network
(a phone hotspot, a VPS, a friend's line) and a few minutes with the node
stopped, because the node holds every port in `UDP_PORTS`. CashPilot ships a
small script for the STUN half, with no dependencies beyond Python 3:
[`scripts/stun_port_pair.py`](https://github.com/GeiserX/CashPilot/blob/main/scripts/stun_port_pair.py).
Run it on a Linux host with Docker Engine: Docker Desktop (macOS, Windows) puts
its own NAT in front of every container, which rewrites every port whatever
the router does.

1. On the node's machine, fetch the script and the image first, so nothing
   has to download while the router's state is fresh:

    ```bash
    curl -fsSLo /tmp/stun_port_pair.py \
      https://raw.githubusercontent.com/GeiserX/CashPilot/main/scripts/stun_port_pair.py
    docker pull python:3.15.2-alpine
    ```

2. Pick two odd ports in `UDP_PORTS`, say `23011` and `23021`, and stop the
   node with **Stop** on CashPilot's dashboard. A plain `docker stop` is not
   recorded as a stop you meant, so the worker can start the node again in
   the middle of the test. Odd ports, because the script tests the odd port
   of each pair first: its even partner comes second, and the pairing effect
   below can rewrite that one with no packet from outside.
3. From the outside machine, send one packet to `23021` on your public address
   (and nothing to `23011`):
   `echo x | nc -u -w1 <your public IP> 23021`.
   `nc` cannot tell whether the packet arrived. To be sure, watch for it on
   the node's machine while you send it:
   `sudo tcpdump -ni any -c 1 udp port 23021`. If nothing shows, the packet
   went to the wrong address or the forward does not cover that port, and
   two ports that both come back `kept` prove nothing.
4. Within a minute, on the node's machine, run the script on both pairs on
   the host's network:

    ```bash
    docker run --rm --network host -v /tmp/stun_port_pair.py:/t.py:ro \
      python:3.15.2-alpine sh -c 'python /t.py --start 23010 --pairs 1; python /t.py --start 23020 --pairs 1'
    ```

5. Start the node again with **Start** on the dashboard.

Read the two odd ports only. On a router with this mapping, `23021` comes back
`REWRITTEN` and `23011` comes back `kept`. On a working router both keep their
number. If `23011` is rewritten too, run steps 2 to 5 again with two other
odd ports: put the new port in the `nc` and `tcpdump` commands of step 3, and
give each `--start` in step 4 the even number just below one of your two
ports. The same goes when your `UDP_PORTS` range does not hold these ports. If every port comes back rewritten,
something rewrites every port; see below.

Run without the inbound packet, the script finds only the secondary pairing
effect. It still works for that, inside the node's network namespace with the
node running:

```bash
curl -fsSLo /tmp/stun_port_pair.py \
  https://raw.githubusercontent.com/GeiserX/CashPilot/main/scripts/stun_port_pair.py
docker run --rm --network container:cashpilot-mysterium \
  -v /tmp/stun_port_pair.py:/t.py:ro python:3.15.2-alpine python /t.py
```

On a router that also pairs ports, the even port of each pair comes back rewritten:

```
34101 -> 34101  kept
34100 -> 46948  REWRITTEN
34103 -> 34103  kept
34102 -> 46950  REWRITTEN
```

On a working line every port comes back with its own number. When every port
comes back rewritten, the script says so separately: that is a NAT which
rewrites every port (a symmetric NAT, carrier-grade NAT, a VPN, or Docker
Desktop's own NAT). The test only measures ports with no forward, so it does
not say whether your forward of `UDP_PORTS` reaches the node: the node's own
port check does. Behind carrier-grade NAT no forward reaches it; behind a VPN
only one whose provider forwards UDP ports to you.
The script exits
0 when every pair was tested and every port kept its number, 1 when one was
rewritten, 2 when no STUN server answered, and 3 when nothing was rewritten
but some pair could not be tested in full (a port that would not bind or got
no answer), so the result says nothing about pairing; run it again with
another `--start`. It exits 4 when `--start` and `--pairs` do not give real
ports, and 5 when the machine would not open a socket. It tries Google's STUN server first and Cloudflare's when
Google does not answer. It only sends a few packets to a public STUN server; it does
not touch the node. `--start` picks the first port to test (default 34100);
keep it outside `UDP_PORTS`, whose ports the node holds.

**Rule out the host's own NAT.** The container's packets also pass Docker's
NAT on the host before they reach the router. That NAT keeps the source port
unless two flows clash on it, which is rare, but then it picks another one and
the script reports `REWRITTEN` with a router that is fine. The router's
rewrite repeats, a clash does not, so run the script twice. (The decisive test
above runs on the host's network and does not pass Docker's NAT at all.)
To see it directly, look at the host's connection table within a minute of a
run (as root on the host, with the `conntrack` tool installed):

```bash
conntrack -L -p udp --orig-port-src 34100
```

The second half of the line is the answer as the host expects it. When its
`dport=` is still `34100`, the host sent the packet out on its own port and
the rewrite happened past it, at the router. When it differs, the host's NAT
changed it, and the test says nothing about the router.

**Fix.** A wider `UDP_PORTS` range does not help on this kind of router (see
*Cause*). What works:

1. **Bridge mode with your own router.** Put the ISP box in bridge mode (some
   ISPs call it ONT mode or "router off") and do NAT on a router of your own
   that keeps source ports and maps independently of the endpoint (what is
   often called endpoint-independent mapping or "full cone" NAT); most
   Linux-based routers and OpenWrt do. Then forward `UDP_PORTS` on your router
   instead. If the ISP box itself has a setting by one of those names, turning
   it on may be enough. Cost: the whole house goes offline for a few minutes,
   and it may need the ISP's help.

Tried without success: skipping the node's port check. With
`traversal = "holepunching"` in the node's `config-mainnet.toml`, the node
skips the manual method and its port check, and falls back to hole punching.
On an affected node it ran for 90 minutes: every config exchange logged
`Method:holepunching Success:true`, yet no buyer ever acknowledged and no
session started, and monitoring stayed failed. The attempts stopped after the
node's config reply over NATS, before any packet between the peers, so part of
the cause may be on the buyer's side; it is not fully explained yet. We do not
recommend it.

Run the decisive test again after the change. Once a port that got an inbound
packet keeps its number,
Mysterium's monitoring re-scores the node within a few hours, the next sessions
carry data, and the **Needs fixing** item clears by itself.

### WebUI address

The node runs in its own network namespace on CashPilot's fenced bridge. Its
WebUI listens on every address inside that namespace, and the worker publishes
port 4449 on the host addresses in `UI_ADDRESS`. By default that is
`127.0.0.1` only: nothing outside the machine can reach it, and CashPilot does
not need it. The worker reads the node's balance and lifetime from the node's own Tequila API, inside the container.

To put a reverse proxy in front, add the one address the proxy connects to and
keep `127.0.0.1` first, for example `127.0.0.1,172.18.0.1`:

- **Proxy in Docker on the same machine:** the gateway of the proxy's Docker
  network (`docker network inspect <network> --format '{{(index .IPAM.Config 0).Gateway}}'`).
  Only containers on that network can reach it. Create that network before the
  node is deployed: Docker refuses to publish on an address the host does not
  have, and the deploy fails.
- **Proxy on another machine:** this machine's LAN address. Anything on the LAN
  can then reach the WebUI. A published port goes through Docker's forwarding,
  so a host `INPUT` rule does not restrict it; limit it with a rule in the
  `DOCKER-USER` chain, or keep the proxy on the same machine.

Never `0.0.0.0`: that publishes the WebUI on every address of the machine.
The Tequila API (4050) is never published; the WebUI reaches it from inside
the node.

A WebUI page that loads forever from another machine means something on the
path drops the request silently: NAT, a hypervisor without a port forward, or
a firewall. The browser waits until it times out. Check two things. First, is
4449 published on the address you opened (`docker ps` shows the bindings)? If
it is not, a plain LAN shows "connection refused" at once, but a NAT or
firewall in between turns that into the endless wait. Second, if 4449 is
published there, a firewall on the path still drops it: allow it in the
`DOCKER-USER` chain, or forward it on the hypervisor. The SSH tunnel
(`ssh -L 4449:127.0.0.1:4449 <host>`, then browse `http://127.0.0.1:4449`)
avoids both.

The **Node settings** button on my.mystnodes.com links to the local IP the node
reports. For a node on CashPilot's bridge, that is normally the container's
internal address, so the button cannot open the WebUI. Use the SSH tunnel
instead ([mysteriumnetwork/node#3535](https://github.com/mysteriumnetwork/node/issues/3535)).

Set it in the deploy form and redeploy that machine's node; each worker keeps
its own value. To go back to loopback only, enter `localhost`: the form treats
the prefilled `127.0.0.1` as untouched and keeps the address recorded for that
machine.

### Activity page

The node has a network namespace of its own, so the [Activity](../activity.md)
page reads it like any other earner. Traffic the node forwards for VPN
customers is routed by the kernel inside that namespace and does not appear
there.

## Troubleshooting

### "Running but not earning": monitoring failed, quality 0

**Symptom.** The container is up and its logs look healthy. MystNodes emails you
*"we're temporarily unable to track its status"*. The dashboard shows no quality
score, and earnings stay flat.

**Cause.** The node cannot bring up its VPN interface. There are two ways that
happens, and from outside they look the same: the node still starts, still
registers and still advertises itself to the network, and carries no traffic.

1. **`/dev/net/tun` is missing from the container.** Mysterium serves `wireguard`
   and `dvpn` through it.
2. **The container lacks the `SETUID` and `SETGID` capabilities.** The node runs
   as root and still configures its interface and firewall through
   `sudo ip ...` and `sudo iptables ...`. sudo switches uid and gid on the way,
   and a container started with `--cap-drop ALL` cannot do that unless those two
   capabilities are added back. The device can be present and correct and the
   node still cannot use it.

**Confirm it.** Ask the node itself. Its Tequila API (4050) is not published on
the host, so ask from inside the container:

```bash
docker exec cashpilot-mysterium wget -qO- http://127.0.0.1:4050/node/monitoring-agent-statuses
```

A missing device (cause 1) looks like this:

```json
{"statuses":{"data_transfer":{"tun_device_problem":14},
             "scraping":{"tun_device_problem":14},
             "monitoring":{"connect_fail":5,"tun_device_problem":1}}}
```

With the device present and the capabilities missing (cause 2), the node reports
only `connect_fail`:

```json
{"statuses":{"data_transfer":{"connect_fail":2},
             "monitoring":{"connect_fail":2},
             "scraping":{"connect_fail":4}}}
```

In both cases `docker exec cashpilot-mysterium wget -qO- http://127.0.0.1:4050/node/monitoring-status` returns
`{"status":"failed"}`.

Then check each cause. Both commands run inside the container's own limits, so
they fail exactly when the node does:

```bash
docker exec cashpilot-mysterium ls -l /dev/net/tun
# "No such file or directory" means cause 1

docker exec cashpilot-mysterium sudo -n true && echo SUDO_OK
# "sudo: PERM_SUDOERS: setresuid(-1, 1, -1): Operation not permitted" means cause 2
```

Cause 2 also shows in the container log, at startup and once per attempted
session:

```bash
docker logs cashpilot-mysterium 2>&1 | grep -c 'PERM_SUDOERS'   # anything above 0
```

**Fix.** If CashPilot deployed the container, **redeploy Mysterium from the
dashboard** on CashPilot v1.36.6 or newer, with the worker on the same version.
The dashboard lists the node under **Needs fixing** with a **Redeploy** button.
The catalog declares the device and the capabilities, the redeploy applies both,
and the `mysterium-data` volume is reused, so the node keeps its identity.

Check the mount first:
`docker inspect cashpilot-mysterium --format '{{range .Mounts}}{{.Type}} {{.Name}}{{.Source}}{{println}}{{end}}'`.
If it says `bind`, the container was created or changed outside CashPilot and a
redeploy would move it onto the `mysterium-data` volume, which holds a different
identity. Use the manual steps below for that container.

For a container created outside CashPilot, recreate it with the device and the
three capabilities. Mount the **same** data directory or volume the container
uses now (`docker inspect cashpilot-mysterium --format '{{json .Mounts}}'`); a
different one starts a new node identity.

```bash
docker create --name cashpilot-mysterium \
  --network cashpilot-isolated --restart no --runtime runc \
  -p 127.0.0.1:4449:4449 -p 23000-23029:23000-23029/udp \
  --cap-drop ALL --cap-add NET_ADMIN --cap-add SETUID --cap-add SETGID \
  --device /dev/net/tun \
  --security-opt no-new-privileges:true \
  -v /path/to/your/myst/data:/var/lib/mysterium-node \
  mysteriumnetwork/myst:1.39.9-alpine \
  --ui.address=0.0.0.0 --tequilapi.address=127.0.0.1 \
  --firewall.protected.networks=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,127.0.0.0/8,100.64.0.0/10,169.254.0.0/16 \
  --udp.ports=23000:23029 \
  service --agreed-terms-and-conditions
```

If a reverse proxy reaches this node's WebUI, add a `-p <address>:4449:4449` for
each address it connects to. The worker's guard covers only nodes CashPilot
deployed, so this hand-made container is created, not started, and has no
restart policy: Docker must not start it before the worker has put the fence
in place. Start it, now and after every reboot, only when the fence's host
rule is there (nftables backend; on the `iptables-legacy` one, test
`sudo iptables-legacy -t mangle -S CP-IN | grep -q host` instead):

```bash
sudo nft list table ip cashpilot 2>/dev/null | grep -q 'comment "host"' \
  && docker start cashpilot-mysterium || echo "fence not in place: node left stopped"
```

This checks that the table is there, not every rule in it, as the worker
does. A redeploy from the dashboard does not take this container over: behind
the Docker socket proxy the worker cannot stop or remove a container it did
not start, so the redeploy fails until you remove this one yourself. A node
the worker deploys keeps its identity on the `mysterium-data` volume, so it is
a new node unless that volume already holds this node's data.

Verify it took:

```bash
docker exec cashpilot-mysterium sh -c 'ip tuntap add dev probe mode tun && echo TUN_OK && ip link del probe'
docker exec cashpilot-mysterium sudo -n true && echo SUDO_OK
docker logs cashpilot-mysterium 2>&1 | grep -c 'PERM_SUDOERS'        # expect 0
docker logs cashpilot-mysterium 2>&1 | grep -i wireguard | tail -3   # expect "Wireguard: started"
```

**Your identity is safe.** It lives in the mounted data directory
(`/var/lib/mysterium-node/keystore/`), not in the container, so recreating the
container keeps the same node identity and its accumulated reputation. Confirm
with `docker exec cashpilot-mysterium wget -qO- http://127.0.0.1:4050/identities`
(the Tequila API listens only inside the node); the address must be unchanged.

**On the host**, `/dev/net/tun` must exist (`ls -l /dev/net/tun`). If it does
not, load the module with `modprobe tun`.

MystNodes' own monitoring takes a while to re-score a node after the fix. Allow
several hours before judging it by the dashboard rather than by the node's own
`monitoring-agent-statuses`.

> **Fixed in the catalog.** It has declared `/dev/net/tun` since v1.5.1 and the
> `SETUID` and `SETGID` capabilities since v1.36.6, so a container CashPilot
> deploys gets all of it. A container deployed before that keeps its old shape
> until you redeploy it from the UI.

