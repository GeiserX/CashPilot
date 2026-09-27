# Anyone Protocol

> **Category:** DePIN | **Status:** Active
>
> **Website:** [https://anyone.io](https://anyone.io)

## Description

Anyone Protocol (formerly ATOR) is a decentralized onion-routing privacy network. Node operators run relay nodes and earn ANYONE tokens for bandwidth contributed. Think "incentivized Tor." Official Docker images available for amd64 and arm64 including Raspberry Pi. Configuration is file-based via an anonrc file mounted into the container (Nickname, ContactInfo, ORPort, etc.).

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $50 (estimate) |
| Per | relay |
| Minimum payout |  |
| Payout frequency | Epoch-based |
| Payment methods | Crypto |

> Earnings based on bandwidth contributed and uptime. Open source project with active development.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | No |
| Minimum bandwidth | 10 Mbps |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Docker, Linux |

## Setup Instructions

### 1. Create an account

No account creation is needed. Anyone Protocol relays are permissionless -- you just run a node and earn ANYONE tokens based on uptime and bandwidth.

### 2. Configure anonrc

Anyone Protocol requires an `anonrc` configuration file. Create it before deploying:

```
User anond
DataDirectory /var/lib/anon
Log notice file /etc/anon/notices.log
ORPort 9001 IPv4Only
ExitRelay 0
Nickname YourRelayName
ContactInfo your@email.com
AgreeToTerms 1
```

There is no `ControlSocket` in this config on purpose. Nothing uses the control socket: CashPilot reads earnings by relay fingerprint, and the image has no healthcheck that needs it. When it is configured, the relay refuses to create it in a `/run/anon` that other users can read, which is how Docker creates that directory, and it logs two warnings a minute. Over six months that grew `notices.log` to about 150 MB. `IPv4Only` stops an hourly notice about a missing IPv6 address; leave it off if your relay has a public IPv6 address.

**Important:** `AgreeToTerms 1` is required since version 0.4.9.7-live. Without it, the container exits immediately with "User has not agreed to the terms and conditions."

### 3. Port forwarding (required)

**Port TCP 9001 must be forwarded** to the server running the relay. The relay performs a self-test by connecting to its own ORPort from the outside. If the port is not reachable, the relay **will not publish its descriptor** to the network directory — it stays invisible, handles zero traffic, and earns nothing. You'll see repeated warnings in `notices.log`:

> "Your server has not managed to confirm reachability for its ORPort(s). Relays do not publish descriptors until their ORPort and DirPort are reachable."

If running behind a firewall (e.g. ufw), also allow port 9001/tcp inbound.

### 4. Deploy with CashPilot

The deploy creates two named volumes, `anon-config` (mounted at `/etc/anon`) and `anon-data` (the relay identity). CashPilot does not write `anonrc` for you: put it in the config volume on the worker host first, owned by the relay user, or the container exits at once.

```bash
docker volume create anon-config
docker run --rm -i -v anon-config:/etc/anon alpine \
  sh -c 'cat > /etc/anon/anonrc && chown -R 100:101 /etc/anon' < anonrc
```

If you change the volumes in the deploy form to host directories instead, write the file into the directory mounted at `/etc/anon`. Then, in the CashPilot web UI, find **Anyone Protocol** in the service catalog and click **Deploy**. If you change `anonrc` later, `docker kill -s HUP <container>` reloads it without a restart.

## Docker Configuration

- **Image:** `ghcr.io/anyone-protocol/ator-protocol`
- **Platforms:** linux/amd64, linux/arm64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `CONTACT_EMAIL` | Contact Email | No | No | Operator email (set in anonrc ContactInfo if not already present) |

### Required Configuration

The `anonrc` file must contain `AgreeToTerms 1` to accept the [Anyone Protocol Terms](https://www.anyone.io/terms). The entrypoint script only handles Nickname and ContactInfo -- the terms check is in the `anon` binary itself.
