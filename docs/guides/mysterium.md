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

> **Port forwarding recommended.** Forward the node's UDP range to maximize earnings; see **Port forwarding** below. Without it many VPN and proxy sessions fail to connect, which cuts income. The node runs behind CashPilot's LAN fence, on its fenced bridge or your own network (see [Isolation](../isolation.md)), with the `NET_ADMIN`, `SETUID` and `SETGID` capabilities.

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

Give that machine a fixed LAN address (a DHCP reservation), or the rule points
at the wrong host after a lease change. UPnP does not work: the node sits behind
the LAN fence, which drops the router, so it cannot ask the router for a
forward. Forward the range by hand. DMZ is the last resort.

The node runs on CashPilot's fenced bridge, and the worker publishes the range
1:1 on the machine (`23000/udp` to `23000/udp`, and so on), so the forward on
the router is the same as when the node shared the host's network.

Keep the range below 32768. Ports 32768 to 60999 are Linux's ephemeral range: any program on the machine (a DNS lookup, a game client, a browser) can hold one of them for a moment. On the host's network the node just skipped a taken port, but Docker publishes the range as a whole, so one taken port fails the node's start. The worker then puts the previous node back and says which port was taken.

Each session takes about two ports, so the default 30 ports carry about 15
sessions at once, more than a home node gets. Every published port costs about
2.5 MB of memory on the machine (Docker starts two small proxy processes per
port; 101 ports measured about 250 MB), so a wider range only costs more. A
range of 20 to 30 ports is enough. The default was `56000:56100` through
2.0.6 and `56000:56029` in 2.0.7 and 2.1.0, both inside the ephemeral range. A node keeps
the range it has on record on a redeploy. To move it, set `UDP_PORTS` to a
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

**Check it.** After a few sessions, on the machine running the node:

```bash
docker logs cashpilot-mysterium 2>&1 | grep -o 'Method:[a-z]* Success:[a-z]*' | sort | uniq -c
```

`Method:manual Success:true` means sessions reach the node through the forward.
Only `Method:manual Success:false` lines, each followed by
`Method:holepunching`, mean they do not. The node's `/nat/type` keeps
reporting `prcone` even when forwarding works, so don't go by it.

CashPilot checks this too, every 30 minutes. When a node has had at least five
failed direct connections and not one successful one in the last 6 hours, the
dashboard lists it under **Needs fixing** with the range and address to forward.
The item clears by itself once a session connects directly. A node with no
sessions yet is not flagged. The dashboard reloads its list every hour, or when
you open it.

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

**Confirm it.** Ask the node itself, on the host running it:

```bash
curl -s http://127.0.0.1:4050/node/monitoring-agent-statuses
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

In both cases `curl -s http://127.0.0.1:4050/node/monitoring-status` returns
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

