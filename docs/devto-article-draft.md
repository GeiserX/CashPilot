---
title: I Built a Dashboard to Track All My Passive Income Docker Containers
published: false
description: CashPilot is a self-hosted web UI to deploy, monitor, and track earnings from bandwidth-sharing and passive income Docker containers across multiple servers.
tags: docker, selfhosted, opensource, tutorial
---

I was running 30+ Docker containers across 3 servers for bandwidth sharing and passive income. Each service had its own dashboard, its own login, and no way to see total earnings at a glance. I wanted a single screen that told me: "You made $X this month across all services." Nothing like that existed, so I built CashPilot to fix it.

[screenshot-dashboard.png]

## What is passive income via bandwidth sharing?

If you have not come across this before, the idea is simple. Services like Honeygain, EarnApp, IPRoyal, and Mysterium let you share your unused internet bandwidth in exchange for money. You install their software -- usually a Docker container on a home server -- and they route legitimate traffic through your connection. Think market research, ad verification, price comparison crawlers. You get paid per gigabyte.

There are also adjacent categories: DePIN (decentralized physical infrastructure networks) that pay crypto tokens for running nodes, storage sharing services like Storj, and GPU compute platforms for people with spare graphics cards. The common thread is that you are renting out idle resources for passive income.

None of these will make you rich. But if you already run a home server for Plex or Home Assistant, spinning up a few of these containers is essentially free money on top of infrastructure you already pay for.

## The problem with managing 10+ services

Once you start running more than a handful of these services, things get messy fast:

- **Different dashboards everywhere.** Honeygain has a web portal. EarnApp has another. Mysterium has its own. PacketStream has another. You end up with a dozen browser tabs.
- **Different credentials.** Some use email/password, some use API keys, some use device UUIDs. Keeping track of all of them is its own project.
- **No unified earnings view.** Want to know your total monthly earnings? Open 10 dashboards, note down each balance, and add them up in a spreadsheet. Every single time.
- **No historical tracking.** Most service dashboards show you a current balance and maybe last month. Want to see trends over 6 months? Good luck.
- **Manual container management.** Deploying a new service means reading their docs, writing a docker-compose entry, figuring out the right environment variables, and debugging when it does not start. Multiply that by 10 services across 3 servers.
- **No fleet-wide visibility.** If a container crashes on server B at 2 AM, you only find out when you happen to check.

I looked at existing tools. money4band generates a docker-compose file from a CLI wizard -- no dashboard, no earnings tracking. CashFactory gives you a bookmark page with links to external dashboards -- better, but still no aggregation. income-generator is another CLI tool. None of them had a real web UI, and none tracked earnings.

## What CashPilot does

CashPilot is a self-hosted web application that centralizes everything into one place:

**Service catalog.** 49 services across bandwidth sharing, DePIN, storage, and GPU compute, each with earning estimates, platform requirements, and signup links. Browse, filter, and decide which services are worth running.

**Guided setup wizard.** Pick a service, and CashPilot walks you through account creation and credential entry. It knows exactly which environment variables each service needs -- no more reading Docker Hub docs.

**One-click container deployment.** Enter your credentials, click deploy, and CashPilot handles the Docker container creation with the right image, ports, volumes, and environment variables. It uses the same container naming and labeling conventions so everything stays organized.

**Earnings dashboard.** This is the core feature. CashPilot has 13 automated earnings collectors that log into service APIs on your behalf and pull your current balance. The dashboard shows total earnings, per-service breakdowns, and historical charts so you can see trends over time. Multi-currency support handles both USD payouts and crypto tokens (MYST, GRASS, STORJ) with automatic exchange rate conversion.

**Multi-node fleet management.** Run one CashPilot UI instance and connect worker agents from each of your servers. The UI aggregates container status, health metrics (CPU, memory, network), and earnings into a single fleet view. If a container goes down on any server, you see it immediately.

**Mobile-responsive dark UI.** Manage your fleet from your phone. The interface is server-rendered (no SPA framework) with a dark theme that does not burn your eyes at 2 AM.

[screenshot-catalog.png]

## Architecture

CashPilot uses a split architecture with two containers:

**UI container** (`drumsergio/cashpilot`). FastAPI backend with Jinja2 templates. Handles the dashboard, service catalog, earnings collection, and credential storage (encrypted at rest with Fernet). This container has no Docker socket access and no privileged permissions. It can run anywhere, including a machine without Docker.

**Worker container** (`drumsergio/cashpilot-worker`). A lightweight agent with Docker socket access. Deploys, monitors, and manages service containers on the host. Reports container status to the UI via heartbeats every 60 seconds. Multiple workers can connect to a single UI instance.

```
CashPilot UI (dashboard + earnings + catalog)
      ^                ^                ^
      | HTTP           | HTTP           | HTTP
Worker (server-a)  Worker (server-b)  Worker (server-c)
+ Docker socket    + Docker socket    + Docker socket
```

The data layer is SQLite -- zero configuration, backed up via a Docker volume. Service definitions live in YAML files that serve as the single source of truth for everything: Docker image names, required environment variables, earning estimates, referral links, and deployment guides. Adding a new service to CashPilot is literally adding a YAML file.

The separation matters for security. The UI never touches the Docker socket. Workers are stateless executors that receive container specs from the UI and pass them to Docker. Credentials are encrypted in the UI's database and only sent to workers at deployment time as part of the container spec -- the same way Portainer works.

## How it compares

| Feature | CashPilot | money4band | CashFactory | income-generator |
|---------|:---------:|:----------:|:-----------:|:----------------:|
| Web UI with guided setup | Yes | No (CLI) | Partial (links) | No (CLI) |
| One-click container deploy | Yes | No | No | No |
| Earnings dashboard | Yes | No | No | No |
| Historical charts | Yes | No | No | No |
| Multi-node fleet | Yes | No | No | No |
| Service catalog | 49 services | 17 | 8 | 14 |
| Earnings collectors | 13 APIs | 0 | 0 | 0 |
| Credential encryption | Yes | No | No | No |

The key difference is that CashPilot is the only project in this space with a real web UI that goes beyond a list of links. It actually deploys containers, collects earnings, and shows you historical data. The others are compose-file generators or CLI tools.

## Getting started

Clone the repo and bring it up:

```bash
git clone https://github.com/GeiserX/CashPilot.git
cd CashPilot
docker compose up -d
```

That starts two containers -- the UI on port 8080 and a worker on port 8081. Open `http://localhost:8080` and the setup wizard walks you through everything.

Here is the full `docker-compose.yml`:

```yaml
services:
  cashpilot-ui:
    image: drumsergio/cashpilot:latest
    container_name: cashpilot-ui
    ports:
      - "8080:8080"
    volumes:
      - cashpilot_data:/data
    environment:
      - TZ=${TZ:-UTC}
      - CASHPILOT_SECRET_KEY=${CASHPILOT_SECRET_KEY:-}
      - CASHPILOT_API_KEY=${CASHPILOT_API_KEY:-}
    restart: unless-stopped

  cashpilot-worker:
    image: drumsergio/cashpilot-worker:latest
    container_name: cashpilot-worker
    ports:
      - "8081:8081"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - cashpilot_worker_data:/data
    environment:
      - TZ=${TZ:-UTC}
      - CASHPILOT_UI_URL=http://cashpilot-ui:8080
      - CASHPILOT_API_KEY=${CASHPILOT_API_KEY:-}
      - CASHPILOT_WORKER_NAME=local
    restart: unless-stopped

volumes:
  cashpilot_data:
  cashpilot_worker_data:
```

For a multi-server setup, you deploy the UI and a worker on your main server, then drop a worker-only compose file on each additional machine pointing `CASHPILOT_UI_URL` back to the UI. Workers connect outbound over HTTP -- no port forwarding needed on the worker side.

## Realistic earnings expectations

I want to be honest here because most "passive income" content online overpromises. Here is what you can actually expect:

A **single residential server** running 10-15 bandwidth-sharing services will earn roughly **$30-100 per month**. The range depends heavily on your geographic location (US and EU IPs pay more), your ISP's upload speed, and which services you run.

Adding more servers helps, but with diminishing returns -- most services limit one device per IP address. Running on a VPS can work for some services but not all; many require a residential IP and will ban datacenter addresses.

Crypto-paying services (MYST, GRASS, STORJ) add variance since token prices fluctuate. CashPilot handles the conversion automatically using live exchange rates, so your dashboard always shows current USD values.

The sweet spot for most people is a home server you already run for other things -- NAS, media server, Home Assistant. The marginal cost of adding passive income containers is essentially zero, and even $30-50/month covers your electricity bill.

## Try it out

CashPilot is open source under GPL-3.0. The easiest way to contribute is adding new service YAML definitions -- the catalog is designed to be community-driven, and each service is just a single YAML file following a documented schema.

GitHub: [https://github.com/GeiserX/CashPilot](https://github.com/GeiserX/CashPilot)

If you run bandwidth-sharing services and have opinions on which ones are worth it (or not), I would love to hear from you. Drop a comment or open an issue.
