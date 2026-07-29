# ProxyBase Markets

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://proxybase.xyz](https://proxybase.xyz)

## Description

ProxyBase Markets is a SOCKS5 proxy marketplace built for AI agents. Sellers run a lightweight Rust CLI daemon that connects via WebSocket to relay buyer traffic through their internet connection, earning USDC on Tempo Chain per GB sold. Supports both **direct mode** (sell your own bandwidth) and **upstream mode** (resell external SOCKS5 proxies alongside your own connection). The official multi-arch Docker image (amd64/arm64) handles wallet creation, authentication, and seller startup automatically.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 — $15 (estimate) |
| Per | device |
| Minimum payout | $1 |
| Payout frequency | On request |
| Payment methods | Crypto (USDC on Solana) |

> Earnings are based on GB sold at market rates. VPS/datacenter IPs typically earn less than residential. Multi-upstream mode can combine your own bandwidth with external proxies for additional throughput.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | No — datacenter/VPS is fine |
| VPS/Datacenter IP | Yes |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Docker (amd64/arm64), Linux, macOS, Windows |

## Setup Instructions

### 1. Deploy with CashPilot

In the CashPilot web UI, find **ProxyBase Markets** in the service catalog and click **Deploy**. No account signup or credentials are needed — the container auto-generates a secp256k1 wallet (BIP-39), authenticates via ECDSA challenge-response against the ProxyBase backend, creates a default seller config for direct-only mode, and starts relaying traffic.

### 2. Check the wallet address

On first start, check the container logs for your wallet address:

```
==> No wallet found — creating one...
Wallet created successfully!
Address: 0xb956cb455901fba57a330221bb1caa00c3ec7acb
```

This address receives your seller payouts. Save the mnemonic shown in the logs if you want to back up the wallet.

### 3. (Optional) Add upstream proxies

To resell external SOCKS5 proxies alongside your own bandwidth, run the container with the `--upstream` flag:

```bash
docker run --rm -v proxybase-data:/home/proxybase/.proxybase \
  ghcr.io/proxybasehq/proxybase-cli:latest \
  seller start --foreground \
  --upstream proxy-host:1080 --upstream-user user --upstream-pass pass
```

This saves the upstream config to the volume. Subsequent starts without `--upstream` will reuse the saved config.

## Docker Configuration

- **Image:** `ghcr.io/proxybasehq/proxybase-cli@sha256:9c96a1d149a1d5b18360110be5caf7164a98656e4bb2c25f6b373b91f1c79802` (digest-pinned; the catalog entry is authoritative if they ever differ)
- **Platforms:** linux/amd64, linux/arm64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `BACKEND_URL` | Backend API URL | No | No | Override the backend API URL (default: `https://api.proxybase.xyz`) |

### Volumes

| Mount | Purpose |
|-------|---------|
| `proxybase-data:/home/proxybase/.proxybase` | Persists wallet keyfile, session token, and seller config across restarts |

> The wallet, session token, and seller config are all stored in this volume. If you delete the volume, a new wallet will be generated on next start.

## Payouts

Payouts are managed via the CLI:

```bash
# Check your seller credit balance
docker run --rm -v proxybase-data:/home/proxybase/.proxybase \
  ghcr.io/proxybasehq/proxybase-cli:latest seller status

# Lock earnings for payout (amount in microcredits, tempo_address = your Solana wallet)
docker run --rm -v proxybase-data:/home/proxybase/.proxybase \
  ghcr.io/proxybasehq/proxybase-cli:latest seller payout create --amount 1000000 --tempo-address <your-solana-address>

# List payout history
docker run --rm -v proxybase-data:/home/proxybase/.proxybase \
  ghcr.io/proxybasehq/proxybase-cli:latest seller payout list
```

Payments settle in USDC on Solana via the Micropayments Protocol (MPP / Tempo). Minimum payout is $1.

## Troubleshooting

### Container exits with "No saved seller config"

The entrypoint creates a default `seller_config.json` on first run. If you see this error, the config file may have been deleted from the volume. Run:

```bash
docker run --rm -v proxybase-data:/home/proxybase/.proxybase \
  --entrypoint /bin/bash ghcr.io/proxybasehq/proxybase-cli:latest \
  -c 'echo "{\"upstream_proxies\":[],\"no_direct\":false}" > /home/proxybase/.proxybase/seller_config.json && chown proxybase:proxybase /home/proxybase/.proxybase/seller_config.json'
```

### WebSocket keeps reconnecting

The seller auto-reconnects with exponential backoff (1s → 60s max). If it cycles indefinitely, check that:

1. Your server can reach `api.proxybase.xyz` on port 443 (outbound WebSocket).
2. The session token hasn't expired — the entrypoint re-authenticates on container restart if the token is missing, but long-running containers may hit token expiry. Restart the container to refresh.

### How do I back up my wallet?

The wallet keyfile is stored at `/home/proxybase/.proxybase/wallet/keyfile.enc` inside the volume. For a full backup, save the **mnemonic phrase** printed in the container logs on first start, or back up the entire `proxybase-data` volume.
