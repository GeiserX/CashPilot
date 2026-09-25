# MystNodes

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://mystnodes.com](https://mystnodes.com)

## Description

MystNodes (Mysterium Network) is a decentralized VPN and proxy network built on blockchain technology. You earn MYST tokens by running a node that provides VPN, proxy, and data scraping services to users. Requires NET_ADMIN, SETUID and SETGID capabilities and host networking for full functionality. Includes a built-in web UI for node management. Works on both residential and VPS connections.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $10 (estimate) |
| Per | device |
| Minimum payout | $2 |
| Payout frequency | On request |
| Payment methods | Crypto |

> Earnings in MYST tokens. Residential IPs earn significantly more. Node WebUI at port 4449 for management, bound to the machine it runs on; from another machine open an SSH tunnel first (`ssh -L 4449:127.0.0.1:4449 <host>`, then browse `http://127.0.0.1:4449`), or put a reverse proxy in front (see **WebUI address** below). VPS accepted. Important: after first run, set your beneficiary (settlement) wallet via the node WebUI or CLI to match your mystnodes.com account -- this links on-chain earnings to your cloud dashboard.

> **One node per public IP.** Mysterium strictly enforces one active node per public IP address. Additional nodes on the same IP show as offline and earn nothing. Do not run on a phone if a Docker node is already running on the same network. Use separate public IPs (e.g. dual WAN, different locations) for additional nodes.

> **Port forwarding recommended.** Forward **UDP 56000-56100** to maximize earnings. Without this, nodes get "Strict NAT" status — many VPN/proxy sessions fail to connect, severely reducing income. Alternatives: enable UPnP on your router (Mysterium uses it automatically), or as last resort, use DMZ. The Docker image runs with `--net host` and the `NET_ADMIN`, `SETUID` and `SETGID` capabilities.

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

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **MystNodes** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `mysteriumnetwork/myst`
- **Platforms:** linux/amd64, linux/arm64, linux/arm/v7

### Environment Variables

| Variable | Default | What it does |
|---|---|---|
| `UI_ADDRESS` | `127.0.0.1` | Where the node's WebUI (port 4449) listens. Comma separated, no spaces. |

### WebUI address

The node runs with host networking, so the WebUI listens on the host itself.
By default that is `127.0.0.1` only: nothing outside the machine can reach it,
and CashPilot does not need it (earnings come from the mystnodes.com cloud API).

To put a reverse proxy in front, add the one address the proxy connects to and
keep `127.0.0.1` first, for example `127.0.0.1,172.18.0.1`:

- **Proxy in Docker on the same machine:** the gateway of the proxy's Docker
  network (`docker network inspect <network> --format '{{(index .IPAM.Config 0).Gateway}}'`).
  Only containers on that network can reach it. Create that network before the
  node starts: an address that does not exist yet is skipped, and the node has to
  be restarted to pick it up.
- **Proxy on another machine:** this machine's LAN address. Anything on the LAN
  can then reach the WebUI, so let only the proxy's address in with the host
  firewall.

Never `0.0.0.0`: with host networking that is every interface of the machine.
The Tequila API (4050) always stays on `127.0.0.1`; the WebUI reaches it from
inside the node.

Set it in the deploy form and redeploy that machine's node; each worker keeps
its own value. To go back to loopback only, enter `localhost`: the form treats
the prefilled `127.0.0.1` as untouched and keeps the address recorded for that
machine.

## Troubleshooting

### "Running but not earning" — monitoring failed, quality 0

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
docker run -d --name cashpilot-mysterium \
  --network host --restart unless-stopped \
  --cap-drop ALL --cap-add NET_ADMIN --cap-add SETUID --cap-add SETGID \
  --device /dev/net/tun \
  --security-opt no-new-privileges:true \
  -v /path/to/your/myst/data:/var/lib/mysterium-node \
  mysteriumnetwork/myst:latest \
  --ui.address=127.0.0.1 --tequilapi.address=127.0.0.1 service --agreed-terms-and-conditions
```

If a reverse proxy reaches this node's WebUI, use the same `--ui.address` list
the container has now (`docker inspect cashpilot-mysterium --format '{{json .Config.Cmd}}'`).

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
with `curl -s http://127.0.0.1:4050/identities` — the address must be unchanged.

**On the host**, `/dev/net/tun` must exist (`ls -l /dev/net/tun`). If it does
not, load the module with `modprobe tun`.

MystNodes' own monitoring takes a while to re-score a node after the fix — allow
several hours before judging it by the dashboard rather than by the node's own
`monitoring-agent-statuses`.

> **Fixed in the catalog.** It has declared `/dev/net/tun` since v1.5.1 and the
> `SETUID` and `SETGID` capabilities since v1.36.6, so a container CashPilot
> deploys gets all of it. A container deployed before that keeps its old shape
> until you redeploy it from the UI.

