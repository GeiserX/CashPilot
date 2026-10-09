# Sia (hostd)

> **Category:** Storage | **Status:** Active
>
> **Website:** [https://sia.tech](https://sia.tech)

## Description

Sia is a decentralized storage marketplace run by the Sia Foundation (a Swiss non-profit) that has operated since 2015. Run the Foundation's official hostd node to rent out spare disk space and earn Siacoin from storage and bandwidth contracts. hostd ships an official Docker image and a built-in web UI. Hosts lock a small collateral per stored TB that is returned when contracts complete successfully, so a stable, always-on machine is required. Earnings depend on how much data renters actually store on the node; storage prices hover around $0.4-1.5 per TB per month, so it suits machines with large spare disks rather than small VPS slices.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $10 (estimate) |
| Per | TB stored |
| Payout token | Siacoin (SC) |
| Minimum payout | $0 (no threshold — funds land in your own wallet) |
| Payout frequency | On request (self-custodial: earnings accrue in the node's own wallet as contracts pay) |
| Payment methods | Crypto |

There is no provider-side payout step: renters pay into the Sia wallet your node controls, and you sell or spend SC whenever you want. Income starts at zero and grows as renters allocate data to your host, which depends on your offered price, collateral and uptime.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | No |
| VPS allowed | Yes |
| GPU required | No |
| Minimum storage | 256GB |
| Supported platforms | Docker, Linux, Windows, macOS |

What the official documentation recommends for a serious host (you can start smaller, but recommended specs attract more contracts):

- A quad-core CPU and 8GB of RAM.
- A 256GB SSD for hostd itself, plus about 10GB of database per 1TB of hosted renter data.
- At least 4TB of HDD storage offered to renters.

Ports **9981 (TCP)** and **9984 (TCP+UDP)** must be reachable from the internet so renters can form contracts. Datacenter hosting is common on Sia — the network is permissionless and does not reject VPS IPs.

## Setup Instructions

### 1. No account needed

Sia hosting is **permissionless** — no signup, no account, no API key. You run the software, lock a small collateral, and the network finds you.

### 2. Generate a wallet seed

The node's wallet is controlled by a BIP-39 seed phrase. Generate one and back it up — it is the only way to reach the earnings:

```bash
docker run --rm ghcr.io/siafoundation/hostd:latest seed
```

Store the phrase somewhere safe before deploying. Anyone with the seed controls the funds; nothing else (not the volume, not the container) is a recovery path.

### 3. Port forwarding

Forward these ports through your router or firewall to the machine running the node:

- **TCP 9981** — RHP4 storage contracts (required)
- **TCP+UDP 9984** — RHP4 over QUIC (required; the UDP side matches Sia's official compose guide)
- **TCP 9980** — Dashboard/API. Every endpoint sits behind BasicAuth with the dashboard password, but Sia's own Docker guide still binds this port to `127.0.0.1`. CashPilot's port format cannot express a loopback bind, so on a machine with a public address restrict 9980 at your firewall to IPs you control.

### 4. Deploy with CashPilot

In the CashPilot web UI, find **Sia (hostd)** in the service catalog and click **Deploy**. You'll be asked for:

- **Wallet seed phrase** — the BIP-39 phrase from step 2
- **Dashboard password** — any long passphrase, for the web UI and local API (BasicAuth)
- **Storage directory** — host path on your largest disk where renter data is stored (e.g. `/srv/sia`)

CashPilot handles the container with the consensus/host databases on a named volume and renter data on the directory you name.

### 5. Configure the host and wait for contracts

Open the dashboard on port 9980, sign in with the dashboard password, and set your storage folder, prices and collateral inside hostd. A newly announced host earns nothing at first: renters allocate data over days to weeks as your host builds reliability history. Check the logs for `failed to` lines — those usually mean the RHP4 ports are not actually reachable from the internet.

## Docker Configuration

- **Image:** `ghcr.io/siafoundation/hostd` (official, by the Sia Foundation)
- **Platforms:** linux/amd64, linux/arm64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `HOSTD_WALLET_SEED` | Wallet seed phrase | Yes | Yes | BIP-39 seed phrase controlling the host's Siacoin wallet |
| `HOSTD_API_PASSWORD` | Dashboard password | Yes | Yes | Password for the hostd web UI and local API (BasicAuth) |
| `SIA_STORAGE_DIR` | Storage directory | Yes | No | Host path on your largest disk where renter data is stored |

### Important Notes

- **Collateral is locked, not spent.** Hosts lock a small amount of SC per contract; it is returned when the contract completes successfully and lost (with the contract's revenue) if you go offline and fail storage proofs. Keep the machine always-on and the ports reachable.
- **Two kinds of state, two kinds of loss.** The `/data` volume holds the wallet database, host settings and contract state — losing it loses the node's identity; the seed phrase remains the only recovery path for funds. The `/storage` directory holds renter data — losing it fails storage proofs and forfeits the collateral locked against those contracts.
- **One host per seed.** Running several hosts from one /24 subnet splits renter demand between them rather than doubling income.
- **Earnings scale with data stored, not disk offered.** Offering 4TB earns nothing until renters actually fill it; pricing near the market rate ($0.4-1.5/TB/month) attracts more allocation.
- **No collector yet.** hostd exposes a local REST API on port 9980 (`/api/wallet`, `/api/settings`, BasicAuth) that a future CashPilot collector can read the same way Storj's collector reads the storagenode dashboard. Until then the balance is visible in the hostd dashboard at `http://<server>:9980`.

## Sources

- Official Docker setup guide: [docs.sia.tech/provide-storage/setting-up-hostd/docker](https://docs.sia.tech/provide-storage/setting-up-hostd/docker)
- hostd source and releases: [github.com/SiaFoundation/hostd](https://github.com/SiaFoundation/hostd) (MIT; v2.11.0 verified live: image pulls on linux/amd64, node starts from env-only config, syncs mainnet, serves `/api/state`, `/api/wallet`, `/api/settings`)
- Sia Docs: [docs.sia.tech](https://docs.sia.tech)
