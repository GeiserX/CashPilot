# Publishing real earnings benchmarks — design

Status: **proposal** (CashPilot-pbyv). Nothing is published until the first
generated page has been explicitly approved by the maintainer; this document
fixes the venue, the privacy line, and the generator contract that approval
will be judged against.

## Why publish at all

CashPilot's reference fleet holds something the "passive income" content farms
fake: measured, multi-month, per-service earnings. An honest "what these
services actually paid" page is more useful than anything currently ranking,
and every reader lands one click away from the per-service guides — which
carry the referral links that fund this project. Credibility is the moat: the
collection code is open source, the methodology is stated, and the numbers are
labelled approximate on purpose.

## Venue

**Primary: one auto-generated page on this docs site — `/earnings/`.**

* The docs pipeline already builds strict on every PR and auto-deploys on
  merge; publishing is "commit a markdown file", zero new infrastructure.
* A single stable URL accumulates search rank; per-month URLs would split it.
  History lives as a table on the same page.
* Every service row links to its guide (`guides/<slug>.md`), which is where
  the referral links live.
* We control title, description, sitemap and internal links here — none of
  which GitHub Discussions or issues offer.

**Amplifiers, both cheap:** a quarterly narrative post on the maintainer's
blog linking to the canonical page (established domain, and the backlink is
exactly what a young docs page needs), and a GitHub Discussions thread per
report for community numbers and corrections. GitHub pages are crawlable
(github.com's robots.txt blocks only a handful of paths), but a Discussion
controls no metadata and its URL is a number, not a keyword — so Discussions
host the conversation, never the data of record. A pinned issue offers
nothing Discussions don't and clutters the tracker: rejected.

## The privacy line

The generator is **allowlist-only**: it emits exactly the fields below and
nothing else. This is a hard rule with history behind it — this docs site once
published internal working files (including a real node identity) simply
because they existed under `docs/`; a denylist filter fails open, an allowlist
fails closed.

### May be published

1. Per service, per calendar **month**: earnings converted to EUR/USD at
   collection-time rates, **rounded** (nearest unit; 2 significant figures
   under 10) — fiat-paid services only.
2. Per service, per calendar **quarter**, EUR-converted and rounded — for
   anything crypto-paid. Never native-token amounts, never monthly for
   crypto (see the adversarial section).
3. **Normalized rates** as the headline numbers: EUR per GB shared, per
   residential IP per day, per TB stored, per GPU-hour. Most useful to a
   reader, least identifying.
4. Residential vs hosting split — **only** for services whose terms permit
   hosting connections. For residential-only services, totals only, with no
   connection breakdown.
5. Deliberate coarse context, stated once: number of servers, number of
   distinct residential connections, country (Spain), months of data,
   uptime, service status.
6. Methodology: collection interval, delta method, FX sources, rounding
   policy, an explicit "approximate by design" disclaimer.

### Never published

* Wallet addresses, node identities, relay fingerprints, on-chain IDs of any
  kind.
* Native-token amounts, payout counts, payout methods, payout timestamps
  finer than the aggregation period.
* IPs (exact or partial), ISP names, city/region — country only.
* Per-worker/per-server breakdowns, worker names, hostnames, client ids,
  heartbeat contents, `system_info` in any form.
* Balance snapshots or daily series — a balance trajectory is a fingerprint.
* Account identifiers, per-service referral-vs-direct earning splits, device
  counts per IP.
* Screenshots of the dashboard, raw exports, or anything not produced by the
  allowlist generator.

### Why the crypto rules are stricter

Amount-plus-time matching against public chains is a real, documented
deanonymization technique (timing-correlation studies report >95% linkage in
research settings; amount/FIFO heuristics re-link a third of mixer users).
"14.21 MYST paid out in March" is a searchable Polygon transfer that reveals
the wallet — and with it every past and future payout. One network is worse:
its rewards are already public per relay fingerprint, so even a monthly EUR
figure at a known token price could be matched against public reward streams.
Fiat conversion + rounding + quarterly aggregation destroys the join key;
rates instead of totals are safer still. That stack is why crypto never gets
monthly precision.

### Two more adversaries

* **The providers themselves** read these pages. Publishing hosting-side
  earnings for a service whose terms forbid hosting connections is a
  self-incriminating admission with a ban and balance clawback attached —
  the page would destroy the income it documents. Hence allowlist rule 4.
* **Fleet-size and income inference** from totals is unavoidable — public
  per-device benchmarks make division easy. We accept it and disclose the
  coarse fleet shape ourselves (rule 5), so the page controls the narrative;
  the figures involved sit squarely in the indie-hacker revenue-transparency
  norm, which is legal to publish and widely practised. The one practical
  rule: published figures stay approximate and rounded, so the page never
  purports to be an accounting record.

## Generator contract

* A script reads the earnings DB and emits `docs/earnings.md` from a template
  containing only allowlisted aggregates. It runs against the live DB, so it
  executes on the fleet side on demand — never in CI, which must not hold DB
  access.
* **Absent is not zero**: months with no reading for a service render as a
  gap ("no data"), never as 0 — a fabricated zero reports a loss that did not
  happen. A service's first-ever reading contributes nothing (no predecessor).
* The page carries a "generated on" date and the generator's version; hand
  edits are forbidden (regeneration overwrites).
* Tests: allowlist enforcement (a synthetic DB row with a wallet-like string
  anywhere in reachable fields never reaches the output), gap rendering
  (negative control: one reading produces no monthly figure), rounding, and
  crypto-quarterly aggregation.

## Rollout

1. Generator + template + tests land (no page published).
2. First page generated locally from the real DB and reviewed by the
   maintainer — **publication happens only on that explicit approval**.
3. Monthly regeneration becomes routine; quarterly blog post + Discussions
   thread accompany it.
