# Sia (hostd)

> **Category:** Storage | **Status:** Active
>
> **Website:** [https://sia.tech](https://sia.tech)

## Description

Sia is a decentralized storage marketplace run by the Sia Foundation, a Swiss non-profit, and it has operated since 2015. You run the Foundation's official hostd node to rent out spare disk space and earn Siacoin (SC) from storage and bandwidth contracts. hostd ships an official Docker image and a built-in web UI.

You must buy some Siacoin before the node earns anything. Hosts lock collateral against every contract and pay a small fee for each storage proof. The collateral comes back when a contract completes, and it is burned if the node goes offline or loses data. That makes Sia a fit for an always-on machine with a large spare disk, not a small VPS slice.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $2 per TB stored (estimate) |
| Payout token | Siacoin (SC) |
| Minimum payout | $0 (no threshold, funds land in your own wallet) |
| Payout frequency | Continuous: revenue reaches the node's wallet as contracts complete |
| Payment methods | Crypto |

You set your own prices. Sia recommends $1 per TB stored per month and more than $5 per TB downloaded, and 3.9% of every contract payout goes to Siafund holders. A new host stores nothing at first. Renters pick hosts by price, collateral and uptime, so income grows over weeks, not days. There is no provider-side payout step: renters pay into the wallet your node controls, and you sell or spend the SC whenever you want.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | No |
| VPS allowed | Yes |
| GPU required | No |
| Minimum storage | 256GB |
| Siacoin up front | Yes, for collateral and proof fees |
| Supported platforms | Docker, Linux, Windows, macOS |

The official Docker guide recommends, for a host that attracts contracts:

- A quad-core CPU and 8GB of RAM.
- A 256GB SSD for hostd itself, plus about 10GB of database per 1TB of hosted renter data.
- At least 4TB of HDD storage offered to renters.

Uptime matters more than hardware. Sia cuts a host's score steeply below 98% uptime and says that a host which cannot keep 95% should not host at all. Below 80% you start losing collateral.

## Setup Instructions

### 1. No account needed

Sia hosting is permissionless. There is no signup, no account and no API key, and there is no referral programme for hosts either.

### 2. Generate a wallet seed

A 12-word BIP-39 seed phrase controls the node's wallet. Generate one and back it up, because it is the only way to reach the earnings:

```bash
docker run --rm ghcr.io/siafoundation/hostd seed
```

The command prints the phrase and the wallet address. Anyone with the seed controls the funds. The volume and the container are not a recovery path.

### 3. Port forwarding

Forward these ports through your router or firewall to the machine running the node:

- **TCP 9981**: Sia consensus, the node's peer-to-peer sync with the network.
- **TCP and UDP 9984**: RHP4, the protocol renters use to form contracts and move data (SiaMux on TCP, QUIC on UDP).

Do not forward 9980. CashPilot binds the dashboard to `127.0.0.1` on the host, as Sia's own Docker guide does, because its API can spend the wallet.

### 4. Deploy with CashPilot

In the CashPilot web UI, find **Sia (hostd)** in the service catalog and click **Deploy**. It asks for:

- **Wallet seed phrase**: the phrase from step 2.
- **Dashboard password**: any long passphrase. It protects the web UI and the local API.
- **Storage directory**: a host path on your largest disk where renter data will live, for example `/srv/sia`.

CashPilot keeps the consensus and host databases on a named volume and mounts the storage directory at `/storage` in the container.

### 5. Fund the wallet, configure the host and wait

Open the dashboard through an SSH tunnel from your own computer:

```bash
ssh -L 9980:127.0.0.1:9980 you@your-server
```

Then browse to `http://localhost:9980` and sign in with the dashboard password. Wait for the node to finish syncing the blockchain, then:

1. Send some Siacoin to the wallet address from step 2, to cover collateral and proof fees.
2. Add a storage volume at `/storage`, the path the container sees.
3. Set your prices and collateral. Sia's recommended starting values are on its [configuring your host](https://docs.sia.tech/provide-storage/configuring-your-host) page.
4. Announce the host.

Renters start sending data over days to weeks as your host builds a reliability history. If no contracts form after a few days, check that 9981 and 9984 are reachable from the internet.

## Docker Configuration

- **Image:** `ghcr.io/siafoundation/hostd` (official, by the Sia Foundation)
- **Platforms:** linux/amd64, linux/arm64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `HOSTD_WALLET_SEED` | Wallet seed phrase | Yes | Yes | BIP-39 seed phrase controlling the host's Siacoin wallet |
| `HOSTD_API_PASSWORD` | Dashboard password | Yes | Yes | Password for the hostd web UI and local API |
| `SIA_STORAGE_DIR` | Storage directory | Yes | No | Host path on your largest disk where renter data is stored |

### Important Notes

- **Collateral is locked, not spent.** It returns when a contract completes. If the node goes offline or loses renter data and misses a storage proof, it loses that contract's collateral and its revenue. Keep a small SC balance in the wallet too: a proof that cannot pay its fee is a missed proof.
- **Two kinds of state, two kinds of loss.** The `/data` volume holds the wallet database, host settings and contract state. Losing it loses the node's identity, and the seed phrase stays the only recovery path for funds. The `/storage` directory holds renter data. Losing it fails storage proofs and forfeits the collateral locked against those contracts.
- **Earnings scale with data stored, not disk offered.** Offering 4TB earns nothing until renters fill it.
- **No collector yet.** hostd exposes a local REST API on port 9980 (`/api/wallet`, `/api/metrics`, `/api/settings`) that a future CashPilot collector can read, the same way the Storj collector reads the storagenode dashboard. Until then the balance is in the hostd dashboard.

## Sources

- Official Docker setup guide: [docs.sia.tech/provide-storage/setting-up-hostd/docker](https://docs.sia.tech/provide-storage/setting-up-hostd/docker)
- Pricing, collateral and uptime: [docs.sia.tech/provide-storage/configuring-your-host](https://docs.sia.tech/provide-storage/configuring-your-host) and [about hosting on Sia](https://docs.sia.tech/provide-storage/about-hosting-on-sia)
- hostd source and releases: [github.com/SiaFoundation/hostd](https://github.com/SiaFoundation/hostd) (MIT, v2.11.0 released 2026-09-21)
- Sia Docs: [docs.sia.tech](https://docs.sia.tech)
