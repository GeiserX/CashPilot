<p align="center">
  <img src="docs/banner.svg" alt="CashPilot" width="100%">
</p>

<p align="center">
  <a href="https://hub.docker.com/r/drumsergio/cashpilot"><img alt="Docker Pulls" src="https://img.shields.io/docker/pulls/drumsergio/cashpilot?style=flat-square&logo=docker"></a>
  <a href="https://github.com/GeiserX/CashPilot/stargazers"><img alt="GitHub Stars" src="https://img.shields.io/github/stars/GeiserX/CashPilot?style=flat-square&logo=github"></a>
  <a href="LICENSE"><img alt="License: GPL-3.0" src="https://img.shields.io/github/license/GeiserX/CashPilot?style=flat-square"></a>
</p>

---

## What is CashPilot?

CashPilot is a self-hosted platform that lets you deploy, manage, and monitor passive income services from a single web interface. Instead of manually setting up dozens of Docker containers, configuring credentials, and checking multiple dashboards, CashPilot handles everything from one place.

The key differentiator: a browser-based setup wizard guides you through account creation and service deployment, orchestrates all containers through Docker, and aggregates your earnings into a unified dashboard with historical tracking.

![Dashboard](docs/screenshot-dashboard.png)

## Features

- **Web-based setup wizard** with guided account creation for each service
- **One-click container deployment** for 25+ passive income services
- **Real-time earnings dashboard** with historical charts and trend analysis
- **Container health monitoring** -- CPU, memory, network, and uptime at a glance
- **Multi-category support** -- bandwidth sharing, DePIN, storage sharing, GPU compute
- **Automatic earnings collection** from service APIs and dashboards
- **Mobile-responsive dark UI** -- manage your fleet from any device
- **Single Docker container** -- no complex setup, no dependencies to install
- **Service catalog** with earning estimates, requirements, and platform details

## Quick Start

With Docker Compose (recommended):

```bash
docker compose up -d
# Open http://localhost:8080
```

Or with `docker run`:

```bash
docker run -d \
  --name cashpilot \
  -p 8080:8080 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v cashpilot_data:/data \
  drumsergio/cashpilot:latest
```

Then open [http://localhost:8080](http://localhost:8080) and follow the setup wizard.

### Running without Docker socket (monitor-only mode)

If you prefer to manage containers yourself (via Portainer, manual compose, etc.), CashPilot works without Docker socket access:

```bash
docker compose -f docker-compose.standalone.yml up -d
```

In this mode CashPilot provides the service catalog, compose file export, earnings dashboard, and credential storage -- but cannot deploy or monitor containers directly. Use the **Export Compose** button in the UI to get ready-to-use `docker-compose.yml` files for any service.

## Supported Services

<!-- SERVICES_TABLE_START — DO NOT EDIT MANUALLY. Run: python scripts/generate_docs.py -->
### Bandwidth Sharing (13 services)

| Service | Docker Image | Residential IP | Referral Link |
|---------|-------------|:--------------:|---------------|
| [Bitping](https://app.bitping.com) | `bitping/bitpingd` | No | [Sign up](https://app.bitping.com) |
| [Earn.fm](https://earn.fm) | `earnfm/earnfm-client` | Yes | [Sign up](https://earn.fm/ref/GEISYB91) |
| [EarnApp](https://earnapp.com) | `fazalfarhan01/earnapp:lite` | Yes | [Sign up](https://earnapp.com/i/TSMD9wSm) |
| [Honeygain](https://www.honeygain.com) | `honeygain/honeygain` | Yes | [Sign up](https://dashboard.honeygain.com/ref/SERGIB4014) |
| [IPRoyal Pawns](https://pawns.app) | `iproyal/pawns-cli` | Yes | [Sign up](https://pawns.app?r=19266874) |
| [MystNodes](https://mystnodes.com) | `mysteriumnetwork/myst` | No | [Sign up](https://mystnodes.co/?referral_code=do7v7YOoBBpbOstKQovX2pUvZYKia4ZhH3QIdNtE) |
| [PacketStream](https://packetstream.io) | `packetstream/psclient` | Yes | [Sign up](https://packetstream.io/?psr=7xgZ) |
| [ProxyLite](https://proxylite.ru) | `proxylite/proxyservice` | No | [Sign up](https://proxylite.ru/?r=KMUPRZIZ) |
| [ProxyRack](https://peer.proxyrack.com) | `proxyrack/pop` | No | [Sign up](https://peer.proxyrack.com/ref/mpwiok3xlaxeycnn5znqlg7ipjeutxyxr6xl7vmn) |
| [Repocket](https://repocket.com) | `repocket/repocket` | No | [Sign up](https://repocket.com/) |
| [SpeedShare](https://speedshare.app) | `mrcolorrain/speedshare` | Yes | [Sign up](https://speedshare.app/?ref={code}) |
| [Traffmonetizer](https://traffmonetizer.com) | `traffmonetizer/cli_v2` | No | [Sign up](https://traffmonetizer.com/?aff=2111758) |

### DePIN (10 services)

| Service | Docker Image | Residential IP | Referral Link |
|---------|-------------|:--------------:|---------------|
| [BlockMesh](https://blockmesh.xyz) | N/A | Yes | [Sign up](https://blockmesh.xyz) |
| [Dawn Internet](https://dawninternet.com) | N/A | Yes | [Sign up](https://dawninternet.com?code={code}) |
| [GagaNode](https://www.gaganode.com) | N/A | No | [Sign up](https://dashboard.gaganode.com/register) |
| [Gradient Network](https://gradient.network) | N/A | Yes | [Sign up](https://app.gradient.network/signup?referralCode=YSKMY7) |
| [Grass](https://www.getgrass.io) | N/A | Yes | [Sign up](https://app.getgrass.io/register/?referralCode=kn8FNEPnUr2tMqE) |
| [Network3](https://network3.io) | N/A | No | [Sign up](https://network3.io) |
| [Nodepay](https://nodepay.ai) | N/A | Yes | [Sign up](https://app.nodepay.ai/register?ref=0wzzyznen64j9zx) |
| [Teneo Protocol](https://teneo.pro) | N/A | Yes | [Sign up](https://dashboard.teneo.pro/?code=CAqef) |
| [Titan Network](https://titannet.io) | N/A | Yes | [Sign up](https://titannet.io) |
| [Wipter](https://wipter.com) | N/A | Yes | [Sign up](https://wipter.com/en/refer-a-friend) |

### Storage Sharing (1 service)

| Service | Docker Image | Residential IP | Referral Link |
|---------|-------------|:--------------:|---------------|
| [Storj](https://www.storj.io) | `storj/storagenode` | No | [Sign up](https://www.storj.io/node) |

### GPU Compute (4 services)

| Service | Docker Image | Residential IP | Referral Link |
|---------|-------------|:--------------:|---------------|
| [Golem Network](https://golem.network) | N/A | No | [Sign up](https://golem.network) |
| [Nosana](https://nosana.io) | N/A | No | [Sign up](https://nosana.io) |
| [Salad](https://salad.io) | N/A | Yes | [Sign up](https://salad.io) |
| [Vast.ai](https://vast.ai) | N/A | No | [Sign up](https://vast.ai) |
<!-- SERVICES_TABLE_END -->

> **Note:** The `generate_docs.py` script auto-generates this table from service YAML definitions. Earnings vary widely by location, hardware, and demand -- see individual guide pages in `docs/guides/` for details.

## How It Works

1. **Deploy CashPilot** -- a single `docker compose up -d` gets you running
2. **Open the web UI** -- browse the full service catalog at `http://localhost:8080`
3. **Browse services** -- filter by category, see earning estimates and requirements
4. **Sign up** -- each service card has a signup link; create accounts as needed
5. **Enter your credentials** -- the setup wizard collects only what each service needs
6. **CashPilot deploys and monitors** -- containers are launched, health-checked, and earnings are tracked automatically

## Architecture

CashPilot is built as a single container that orchestrates everything:

- **Backend:** FastAPI (Python) with async task scheduling
- **Database:** SQLite -- zero configuration, backed up via the mounted volume
- **Container management:** Docker SDK for Python -- deploys and monitors service containers
- **Service definitions:** YAML files in `services/` are the single source of truth for all service metadata, Docker configuration, and earning estimates
- **Frontend:** Server-rendered templates with a responsive dark UI

```
cashpilot/
  app/            # FastAPI application
  services/       # YAML service definitions (source of truth)
    bandwidth/    # Bandwidth sharing services
    depin/        # DePIN services
    storage/      # Storage sharing services
    compute/      # GPU compute services
  scripts/        # Utilities (doc generation, etc.)
  docs/           # Documentation and guides
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TZ` | `UTC` | Timezone for scheduling and display |
| `CASHPILOT_SECRET_KEY` | *(auto-generated)* | Encryption key for stored credentials |
| `CASHPILOT_COLLECTION_INTERVAL` | `3600` | Seconds between earnings collection cycles |
| `CASHPILOT_PORT` | `8080` | Web UI port inside the container |

### Referral Codes

You can set your own referral codes in two ways:

1. **Settings page** -- open the web UI, go to Settings, and enter your codes per service
2. **Environment variables** -- set `CASHPILOT_REF_{SERVICE_SLUG}` (e.g., `CASHPILOT_REF_HONEYGAIN=abc123`)

If no referral code is configured, the default project referral codes are used. You can replace all of them with your own at any time.

## FAQ

**Is bandwidth sharing safe?**

Bandwidth sharing services route only legitimate traffic (market research, ad verification, price comparison, content delivery) through your connection. They do not use your connection for illegal activity. That said, you are sharing your IP address, so review each service's terms and privacy policy. Running these on a VPS rather than residential IP is an option for some services.

**How much can I earn?**

Earnings vary widely based on location, number of devices, and which services you run. A realistic expectation for a single residential server running 10-15 services is **$30 - $100/month**. Adding more servers or GPU compute services can increase this significantly. The dashboard shows your actual earnings over time so you can optimize.

**Can I run on a VPS or cloud server?**

Some services require a residential IP and will not pay (or will ban) VPS/datacenter IPs. These are marked as "Residential Only" in the service catalog. Services that work on VPS are a good way to scale up without additional home hardware.

**How are credentials stored?**

All service credentials are encrypted at rest in the SQLite database using your `CASHPILOT_SECRET_KEY`. The database file lives in the mounted Docker volume (`cashpilot_data:/data`). No credentials are ever sent anywhere except to the service containers themselves.

**What happens if a service container crashes?**

CashPilot monitors container health continuously. If a service container exits unexpectedly, it is automatically restarted. The dashboard shows uptime and health status for every running service.

## Disclosure

> This project contains affiliate/referral links. If you sign up through these links, the project maintainer may earn a small commission at no extra cost to you. This helps support the development of CashPilot. You are free to replace all referral codes with your own in the Settings page.

## Contributing

Contributions are welcome. To add a new service:

1. Create a YAML file in the appropriate `services/` subdirectory following `services/_schema.yml`
2. Run `python scripts/generate_docs.py` to regenerate the README table and guide pages
3. Submit a pull request

**Do not edit the service table in this README directly** — it is auto-generated from the YAML files in `services/`. Edit the YAML source of truth instead, then run the generator.

For bug reports and feature requests, open an issue on GitHub.

## License

[GPL-3.0](LICENSE) -- Sergio Fernandez, 2026
