---
hide:
  - navigation
---

# CashPilot { .cp-visually-hidden }

<p align="center">
  <img src="images/banner.svg" alt="CashPilot" width="100%">
</p>

<p align="center">
  <a href="https://hub.docker.com/r/drumsergio/cashpilot"><img alt="Docker Pulls" src="https://img.shields.io/docker/pulls/drumsergio/cashpilot?style=flat-square&logo=docker"></a>
  <a href="https://github.com/GeiserX/CashPilot/stargazers"><img alt="GitHub Stars" src="https://img.shields.io/github/stars/GeiserX/CashPilot?style=flat-square&logo=github"></a>
  <a href="https://github.com/GeiserX/CashPilot/blob/main/LICENSE"><img alt="License: GPL-3.0" src="https://img.shields.io/github/license/GeiserX/CashPilot?style=flat-square"></a>
</p>

---

**CashPilot** is a self-hosted platform that lets you deploy, manage, and monitor passive income services from a single web interface. Instead of manually setting up dozens of Docker containers, configuring credentials, and checking multiple dashboards, CashPilot handles everything from one place.

It supports both **Docker-based services** (deployed and managed automatically) and **browser extension / desktop-only services** (tracked via the web UI with signup links, earning estimates, and balance monitoring). Whether a service runs in a container or in your browser, CashPilot aggregates all your earnings into a unified dashboard with historical tracking.

## Features

<div class="grid cards" markdown>

-   :material-wizard-hat: **Web-Based Setup Wizard**

    ---

    Guided account creation for each service. No CLI or YAML editing needed.

-   :material-rocket-launch: **One-Click Container Deployment**

    ---

    Deploy 16 passive income services with a single click from the browser.

-   :material-chart-line: **Real-Time Earnings Dashboard**

    ---

    Historical charts, trend analysis, and per-service breakdowns with progress toward payout.

-   :material-heart-pulse: **Container Health Monitoring**

    ---

    CPU, memory, network, uptime, and health scores at a glance.

-   :material-server-network: **Multi-Node Fleet Management**

    ---

    Run services across multiple servers. One UI aggregates everything.

-   :material-shield-lock: **Credential Encryption**

    ---

    All credentials encrypted at rest with Fernet symmetric encryption.

-   :material-view-grid: **39 Active Services, 4 Categories**

    ---

    Bandwidth sharing, DePIN, storage, and GPU compute; 50 catalogued in total, each with a setup guide.

-   :material-cellphone: **Mobile-Responsive Dark UI**

    ---

    Manage your fleet from any device with a modern dark theme.

</div>

## Dashboard

![CashPilot Dashboard](images/screenshots/dashboard.png)

## Quick Start

```bash
curl -fsSLO https://raw.githubusercontent.com/GeiserX/CashPilot/main/docker-compose.yml
docker compose up -d
docker compose logs cashpilot-ui | grep -i "setup token"   # then open http://localhost:8080
```

This starts two containers:

- **cashpilot-ui**: web dashboard, earnings collection, service catalog (port 8080)
- **cashpilot-worker**: Docker agent that deploys and monitors service containers (port 8081)

Then open [http://localhost:8080](http://localhost:8080), enter the one-time setup token from the log to create the owner account, and follow the setup wizard.

!!! note
    The worker container requires access to the Docker socket (`/var/run/docker.sock`) to deploy and manage service containers. Both containers are required for full functionality.

[Get Started](getting-started.md){ .md-button .md-button--primary }
[View on GitHub](https://github.com/GeiserX/CashPilot){ .md-button }

## Documentation

- [Getting started](getting-started.md): install, first run, updating
- [Configuration](configuration.md): every setting and which source wins
    - [Multi-node fleet management](fleet.md), [running on ARM](arm.md)
    - [Protecting your home network](home-network-security.md), [security defaults](security-defaults.md), [network isolation](isolation.md)
- [Service guides](guides/index.md): one page per service, plus [Prometheus metrics](guides/prometheus-metrics.md)
- Operations: [backup and restore](backup-restore.md), [backing up node identities](backup.md), [upgrade to v1.0.0](upgrade-v1.md)
- [How it works](how-it-works.md): the UI and worker split
- [FAQ](faq.md)
- [Development](development.md): adding a service, running the tests
- [Related projects](related.md)
- Reference: [how CashPilot compares](comparison.md), [discontinued services](discontinued-services.md), [direction and roadmap](roadmap.md), [what "idle" looks like on the wire](research/idle-network-traffic.md), [per-IP device limits](research/per-ip-device-limits.md), [self-hosting operability review](research/self-hosting-operability.md), [fleet upgrades and onboarding](research/fleet-upgrades-and-onboarding.md), [earnings benchmarks](research/earnings-benchmarks.md)

## FAQ

??? question "Is bandwidth sharing safe?"
    Bandwidth sharing services generally route legitimate traffic (market research, ad verification, price comparison, content delivery) through your connection. That said, you are sharing your IP address, so review each service's terms of service and privacy policy carefully before signing up. Running these on a VPS rather than residential IP is an option for some services. **This is not legal advice.**

??? question "How much can I earn?"
    Earnings vary widely based on location, number of devices, and which services you run. A realistic expectation for a single residential server running 10-15 services is **$30 - $100/month**. Adding more servers or GPU compute services can increase this significantly. The dashboard shows your actual earnings over time so you can optimize.

??? question "Can I run on a VPS or cloud server?"
    Some services require a residential IP and will not pay (or will ban) VPS/datacenter IPs. These are marked as "Residential Only" in the service catalog. Services that work on VPS are a good way to scale up without additional home hardware.

??? question "How are credentials stored?"
    All service credentials are encrypted at rest in the SQLite database with a Fernet key kept at `/data/.fernet_key`. `CASHPILOT_ENCRYPTION_KEY` is adopted only when that file is absent — the file always wins, so on an instance that already has a key the variable changes nothing. This is not `CASHPILOT_SECRET_KEY`, which only signs login sessions. The database file lives in the mounted Docker volume. No credentials are ever sent anywhere except to the service containers themselves.

??? question "What about security?"
    Every service CashPilot deploys runs in its own container with every Linux capability dropped (a few services add back only the ones they declare) and `no-new-privileges` set. Credentials are encrypted at rest, and only the worker touches the Docker socket. A container can still reach your home network by default, though: Docker does not block that. To close it, follow [Protecting Your Home Network](home-network-security.md), which puts the earners on a firewalled bridge that can reach the internet but not your LAN, router or host. That bridge does not cover a service on host networking (Mysterium, today); the guide says what to do about those.

??? question "What happens if a service container crashes?"
    CashPilot monitors container health continuously. If a service container exits unexpectedly, it is automatically restarted. The dashboard shows uptime and health status for every running service.

## Disclosure

The signup links in CashPilot and in these docs are referral links. If you sign up through one, the maintainer may earn a commission, at no cost to you. To avoid them, sign up on the provider's own website instead.

## License

[GPL-3.0-or-later](https://github.com/GeiserX/CashPilot/blob/main/LICENSE) · Sergio Fernandez, 2026
