# MystNodes

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://mystnodes.com](https://mystnodes.com)

## Description

MystNodes (Mysterium Network) is a decentralized VPN and proxy network built on blockchain technology. You earn MYST tokens by running a node that provides VPN, proxy, and data scraping services to users. Requires NET_ADMIN capability and host networking for full functionality. Includes a built-in web UI for node management. Works on both residential and VPS connections.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $10 (estimate) |
| Per | device |
| Minimum payout | $2 |
| Payout frequency | On request |
| Payment methods | Crypto |

> Earnings in MYST tokens. Residential IPs earn significantly more. Node WebUI at port 4449 for management. VPS accepted. Important: after first run, set your beneficiary (settlement) wallet via the node WebUI or CLI to match your mystnodes.com account -- this links on-chain earnings to your cloud dashboard.

> **One node per public IP.** Mysterium strictly enforces one active node per public IP address. Additional nodes on the same IP show as offline and earn nothing. Do not run on a phone if a Docker node is already running on the same network. Use separate public IPs (e.g. dual WAN, different locations) for additional nodes.

> **Port forwarding recommended.** Forward **UDP 56000-56100** to maximize earnings. Without this, nodes get "Strict NAT" status — many VPN/proxy sessions fail to connect, severely reducing income. Alternatives: enable UPnP on your router (Mysterium uses it automatically), or as last resort, use DMZ. The Docker image runs with `--net host` and `NET_ADMIN` capability.

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
- **Platforms:** linux/amd64, linux/arm64

### Environment Variables

No environment variables required.

## Troubleshooting

### "Running but not earning" — monitoring failed, quality 0

**Symptom.** The container is up and its logs look healthy. MystNodes emails you
*"we're temporarily unable to track its status"*. The dashboard shows no quality
score, and earnings stay flat.

**Cause.** The node cannot bring up its wireguard interface. There are two ways
that happens, and they look identical from outside — the node still starts, still
registers, and still advertises itself to the network, it simply cannot carry any
traffic:

1. **`/dev/net/tun` is missing from the container.**
2. **The container runs with `no-new-privileges:true`.** The node configures the
   interface by shelling out to `sudo ip address replace dev myst0 10.182.0.1/24`,
   and `no_new_privs` permanently prevents `sudo` from elevating. The device can be
   present and correct and the node still cannot use it.

**Confirm it.** Ask the node itself, on the host running it:

```bash
curl -s http://127.0.0.1:4050/node/monitoring-agent-statuses
```

A TUN problem looks like this:

```json
{"statuses":{"data_transfer":{"tun_device_problem":14},
             "scraping":{"tun_device_problem":14},
             "monitoring":{"connect_fail":5,"tun_device_problem":1}}}
```

And `curl -s http://127.0.0.1:4050/node/monitoring-status` returns
`{"status":"failed"}`.

The `no-new-privileges` variant instead shows up in the container log, once per
attempted session:

```
ERR Session failed, disconnecting error="cannot get provider config for session ...:
    could not start provider wg connection endpoint: could not configure device:
    failed to create TUN device: failed to assign IP address:
    \"ip address replace dev myst0 10.182.0.1/24\": exit status 1
    output: sudo: PERM_SUDOERS: setresuid(-1, 1, -1): Operation not permitted"
```

**Check whether the device reached the container:**

```bash
docker exec cashpilot-mysterium ls -l /dev/net/tun
# "No such file or directory" means it did not
```

**Fix.** The container needs the device mapped in, alongside `NET_ADMIN`:

```bash
docker run -d --name cashpilot-mysterium \
  --network host --restart unless-stopped \
  --cap-drop ALL --cap-add NET_ADMIN \
  --device /dev/net/tun \
  -v /path/to/your/myst/data:/var/lib/mysterium-node \
  mysteriumnetwork/myst:latest \
  --ui.address=0.0.0.0 --tequilapi.address=0.0.0.0 service --agreed-terms-and-conditions
```

Verify it took:

```bash
docker inspect cashpilot-mysterium --format '{{.HostConfig.SecurityOpt}}'   # expect []
docker exec cashpilot-mysterium ls -l /dev/net/tun                          # expect the device
docker logs cashpilot-mysterium 2>&1 | grep -i wireguard | tail -3   # expect "Wireguard: started"
```

Check `SecurityOpt` with `docker inspect`, not by running `sudo` through
`docker exec`. `exec` starts a fresh process that does **not** inherit the
container's `no_new_privs` bit, so `docker exec ... sudo true` and
`docker exec ... ip tuntap add` both succeed on a container whose own node
process cannot do either. They cannot detect this failure.

**Your identity is safe.** It lives in the mounted data directory
(`/var/lib/mysterium-node/keystore/`), not in the container, so recreating the
container keeps the same node identity and its accumulated reputation. Confirm
with `curl -s http://127.0.0.1:4050/identities` — the address must be unchanged.

**On the host**, `/dev/net/tun` must exist (`ls -l /dev/net/tun`). If it does
not, load the module with `modprobe tun`.

MystNodes' own monitoring takes a while to re-score a node after the fix — allow
several hours before judging it by the dashboard rather than by the node's own
`monitoring-agent-statuses`.

> **Fixed in v1.5.1+.** The catalog now declares `/dev/net/tun` for Mysterium, so
> a container CashPilot deploys gets the device automatically. The manual steps
> above are only needed for a container deployed before that, or one created
> outside CashPilot. Redeploy from the UI and the device comes with it.

