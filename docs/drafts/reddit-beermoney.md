# r/beermoney Post Draft

**Title:** Automated my bandwidth-sharing setup with a self-hosted dashboard -- here's what I earn

**Body:**

For anyone running bandwidth-sharing apps (Honeygain, EarnApp, IPRoyal Pawns, etc.), I got tired of:

- Logging into 10 different dashboards to check earnings
- Manually setting up Docker containers for each service
- Not knowing which services were actually running or had crashed

I built an open-source tool called CashPilot that handles all of this from one web UI. It supports 49 services across bandwidth sharing, DePIN, storage, and GPU compute.

**My setup:**
- 3 home servers (Unraid)
- ~15 active services per server
- All managed from one CashPilot dashboard

**What I earn:**
- Combined: roughly $30-50/month from bandwidth sharing alone
- The dashboard shows per-service breakdowns so I can see which ones are actually worth running
- Some services earn pennies and aren't worth the electricity -- CashPilot makes it easy to spot and drop those

**How it works:**
1. `docker compose up -d` -- two containers, done
2. Open the web UI, browse the service catalog
3. Click "Deploy" on any service -- it walks you through account creation and handles the Docker setup
4. Earnings are collected automatically and shown on the dashboard

It's completely free and open source: https://github.com/GeiserX/CashPilot

If you're already running some of these services manually, this might save you some time. If you're new to bandwidth sharing, the catalog with guides for each service is a decent starting point.

---

**Subreddit notes:**
- r/beermoney (~1.2M subs) -- focuses on small/side income methods
- Lead with real earnings numbers -- this sub values transparency
- Avoid sounding like an ad -- focus on the problem you solved
- Post Tuesday-Thursday, early afternoon US time
