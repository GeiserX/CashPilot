# r/passive_income Post Draft

**Title:** I made a free self-hosted tool to manage all your bandwidth-sharing services from one dashboard

**Body:**

I've been running bandwidth-sharing services (Honeygain, EarnApp, Mysterium, etc.) on a home server for a while now. The biggest annoyance was managing 10+ different dashboards, checking earnings on each one separately, and manually setting up Docker containers for each service.

So I built CashPilot -- a self-hosted web dashboard that lets you:

- **Browse 49 passive income services** across bandwidth sharing, DePIN, storage, and GPU compute
- **Deploy Docker containers with one click** -- no terminal needed, a setup wizard walks you through each service
- **Track earnings across all services** in a unified dashboard with historical charts
- **Manage multiple servers** from one UI (I run 3 servers from a single dashboard)

It runs as two Docker containers (a UI and a worker) and takes about 2 minutes to set up:

```
docker compose up -d
# Open http://localhost:8080
```

**What I actually earn:** Running 10-15 services on a single residential server, I see around $30-50/month. It's not life-changing money, but it's completely passive once set up. CashPilot just makes the setup and monitoring part painless.

**It's free and open source** (GPL-3.0): https://github.com/GeiserX/CashPilot

Happy to answer any questions about the tool or bandwidth sharing in general.

---

**Subreddit notes:**
- r/passive_income (~300K subs) -- focuses on passive income methods
- Post during US business hours (2-4 PM ET) for max visibility
- Engage with every comment in the first 2 hours
