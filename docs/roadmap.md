# Direction and Roadmap

This page describes what CashPilot is today, what we intend it to become, and the
avenues we are weighing to get there — including the ones we have decided against
and why. It is written to be argued with. If a trade-off here looks wrong, open an
issue; the reasoning is laid out precisely so it can be challenged.

## What CashPilot is today

CashPilot is a **self-hosted dashboard for passive-income services**. You run it on
your own hardware — a home server, a NAS, a VPS — and it does three things:

1. **Deploys** Docker containers for services that pay you for idle resources:
   bandwidth sharing, DePIN nodes, storage, and compute.
2. **Collects** your earnings from those services' own APIs and dashboards, and
   stores the history locally in SQLite.
3. **Shows** it in one place, across every machine you run, with per-service and
   per-server drill-down.

Architecturally it is two components, always separate:

- The **UI** — the single dashboard. Collects earnings, schedules work, manages
  users. It has **no Docker socket** and cannot touch containers directly.
- One **Worker** per machine — holds the Docker socket, manages local containers,
  reports back over an authenticated heartbeat.

The catalog of services is plain YAML under `services/`, and it is the single source
of truth: the UI, the deployment path, the collectors and the docs all derive from
it. Credentials are encrypted at rest. Deployed containers run with all Linux
capabilities dropped, `no-new-privileges`, and a PID limit.

**What it is not.** It is not a hosted service, not a wallet, not an exchange, and
not a way to make meaningful money. Realistic earnings for a home setup are a few
euros a month per service. Anyone promising otherwise is selling something.

## What we want it to become

> **The tool that makes running earning services on your own hardware safe,
> honest, and boring.**

Three words, each load-bearing:

**Safe.** Several of these services generate cryptographic material — a node
identity, a relay key, a wallet — that lives in a container volume and cannot be
recovered if it is destroyed. Today CashPilot deploys that software without knowing
those secrets exist. Making that impossible to lose by accident is the single most
valuable thing we can build.

**Honest.** The passive-income space is full of inflated earnings claims, dead
services still listed as live, and referral links dressed up as recommendations. We
publish earnings ranges that start at zero, mark services dead when they die, and
check the catalog against reality on a schedule.

**Boring.** Set it up, and it should keep working without you. Credentials that
expire should say so before they break. A service that stops earning should raise an
alert, not silently return zero.

## Where we fall short today

Being specific about the gaps, because they set the roadmap.

### Deployment is stateless

Every redeploy rebuilds the container specification from the catalog YAML. Nothing
records what was *actually* deployed. If the running container differs from what the
catalog describes — a bind mount where the catalog declares a named volume, an
environment variable that was substituted at deploy time — the redeploy silently
produces a *different* container.

For a stateless bandwidth service that is harmless. For a service holding a node
identity it is destructive: the new container gets a fresh, empty volume, and the
key that represented months of accrued reputation or a held payout balance is no
longer attached to anything.

This is the root cause of the most serious class of bug in the project, and it is
not a key-management problem — it is a **memory** problem.

### Nothing knows which state is irreplaceable

Of the services in the catalog, only a handful hold something unrecoverable:

| What it holds | Consequence of loss |
|---|---|
| Node identity / keystore | New identity: registration, reputation and vetting progress reset |
| Storage node identity | Forfeits the accrued held-back payout balance |
| Relay keys | New relay fingerprint; any locked stake is stranded |
| A generated wallet | The volume *is* the money; there is no recovery |

The catalog documents some of this in prose, which is read by humans and by nothing
else. No code path treats those volumes differently from a cache directory.

### Volume deletion is unguarded

Removing a service can optionally delete its named volumes. That path force-deletes
without asking whether the volume held anything irreplaceable. The browser UI does
not currently offer it, which is fortunate rather than deliberate.

### Collectors are fragile by nature

Some services expose a clean API. Others require scraping a dashboard, or a session
cookie copied out of a browser that expires in hours. When a provider redesigns a
page, the collector silently reports "cannot parse" and earnings stop being recorded
even though the service is still earning. This is inherent to the domain, but the
*handling* of it can be much better than it is.

## Avenues

Each avenue below is a direction we could take, with the case for and against.

### A. Make deployment stateful

Record the specification that was actually deployed, and redeploy from that record —
with the catalog supplying only the image and defaults.

**For.** Removes the root cause of accidental state loss rather than detecting it.
Smaller than most alternatives. Fixes the related annoyance where a user must retype
paths from memory on every redeploy. Gives an audit trail of what was deployed when.

**Against.** The record can drift from reality if a container is edited outside
CashPilot. It does not help when a disk fails.

**Risk.** Low. The main hazard is trusting a stale record, which argues for pairing
it with a check against the live container rather than replacing that check.

**Verdict: do this first.** It is the highest ratio of harm removed to code written.

### B. Guard the destructive paths

Mark volumes that hold irreplaceable state in the catalog. Before a redeploy
destroys a container, compare its existing mounts to the incoming specification and
**refuse** if a flagged mount would be dropped or replaced — showing the difference
and requiring an explicit override. Apply the same guard to volume deletion.

**For.** Catches drift from any source, including containers created outside
CashPilot. Costs no new privilege: mount metadata is already available to the
Worker. Prevents the one genuinely irreversible operation in the codebase.

**Against.** Adds friction to a routine action. Users learn to click past warnings.

**Risk.** Low, provided it **blocks rather than warns**. A warning at the end of a
long day is not a safety mechanism.

**Verdict: do this, and make it a block with an explicit override.**

### C. Encrypted backup and migration

Let the user export the irreplaceable state of a service as an encrypted bundle,
verify a bundle restores correctly, and move a node between machines.

**For.** The only avenue that survives disk failure. Migration between machines is
currently a manual, error-prone process. Users overwhelmingly do not back these
files up on their own, because nothing tells them the files exist.

**Against.** Reading key material out of a container volume is a genuinely new
capability for the Worker — the component that already holds the Docker socket. It
must be designed so that a compromised installation cannot decrypt past exports.

**Risk.** The highest of any avenue, in two directions. Technically, it creates a
path by which secrets can leave the machine. Structurally, a tool that holds keys
invites the assumption that it can recover them.

**Design constraints, non-negotiable if we build it:**

- Encryption happens on the Worker. The UI handles ciphertext only.
- The user supplies the encryption target — a public key, or a passphrase. **The
  installation must not be able to decrypt its own exports.**
- No scheduled or automatic export. A timer needs a stored secret, which
  reintroduces exactly the risk we are avoiding. Alert the user instead.
- No destination other than the response to the authenticated user. No cloud
  upload, no remote sync, no webhook.

**Verdict: worth building, after A and B, and only with the constraints above.**

### D. Keep the catalog honest automatically

A scheduled check already verifies that each service's website, referral link and
container image still resolve, and reports problems that need a human. Extend it to
notice services whose earnings have flatlined, and to distinguish "provider is down
today" from "provider is gone".

**For.** Catalog rot is the most common way a user silently stops earning. Automation
scales where manual review does not.

**Against.** Every automated check risks false positives, and a report that cries
wolf is a report nobody reads.

**Risk.** Low, if the distinction between *confirmed broken* and *could not verify*
is preserved rigorously — a link that redirects somewhere unexpected is not proof of
a dead service.

**Verdict: continue, carefully.**

### E. Make collectors resilient and honest about credentials

Several collectors depend on values a user copies out of a browser. Some expire in
hours. Today nothing tells the user that, so a collector configured in the morning
can be dead by evening with no explanation.

Improvements worth making:

- Ask for the **durable** credential where one exists, not only the short-lived one.
- Show credential age and expected lifetime in the interface.
- Distinguish "your credential expired" from "the provider changed their page" in
  alerts — they need different actions from the user.
- Prefer stable anchors when scraping, and keep older patterns as fallbacks so a
  redesign degrades rather than breaks.

**For.** Directly addresses the most common support burden. Cheap.

**Against.** None of substance.

**Verdict: ongoing work, always worth doing.**

### F. Broaden what can earn

Most catalog services sell **bandwidth**. Adding more of them to one connection has
diminishing returns — they compete for the same upstream, and several providers'
terms forbid running competitors alongside each other.

The genuine growth is in **different resources**: disk (storage nodes), and compute
(GPU rental). These do not cannibalise bandwidth earnings because they sell
something else entirely.

**For.** Higher earnings ceiling than any additional bandwidth service.

**Against.** Compute means real electricity cost, which can exceed revenue depending
on local prices and hardware. Storage means committing disk for months, since payout
balances accrue slowly and are forfeited if a node is abandoned.

**Risk.** Recommending a service that costs a user more in power than it earns would
be a serious breach of the "honest" principle.

**Verdict: expand deliberately, and publish a power-cost calculation alongside any
compute service rather than an earnings range alone.**

### G. What we will not build

**A hosted version that holds users' keys.** This is the clearest line in the
project. Software that runs on the user's own machine, where key material never
leaves it and the maintainers cannot access it, is a fundamentally different thing
from a service that stores other people's secrets. The latter is a regulated
activity with capital, licensing and anti-money-laundering obligations, and it is
not what this project is for. We stay on the side of the line where the user holds
everything.

**Any key recovery service.** If a user loses their passphrase, the data is gone.
Saying so plainly is more honest than implying a safety net that does not exist.

**Automatic multi-account setups.** Several providers forbid multiple accounts per
household, and tooling that makes evasion easy would put users at risk of forfeited
balances.

## How this improves things for users

Concretely, in the order a user would notice:

1. **You stop being able to destroy your own earnings by accident.** The most
   dangerous operations refuse to run without an explicit confirmation that shows
   exactly what would change.
2. **You find out what is precious.** The interface says which services hold
   something unrecoverable and where it lives, so backing it up becomes possible.
3. **Credentials stop failing silently.** You learn a credential is about to expire
   before it does, and when something breaks you are told whether to re-copy a
   cookie or wait for a provider fix.
4. **Moving to a new machine stops being frightening.** Export, verify, restore.
5. **The catalog reflects reality.** Dead services are marked dead; services that
   merely had a bad afternoon are not.
6. **Earnings expectations stay honest.** Ranges start at zero, power costs are
   stated for anything compute-related, and no service is recommended on the
   strength of a referral.

## Principles

When a decision is unclear, these resolve it:

- **The user holds everything.** No key we cannot lose, because we never had it.
- **Irreversible operations must be hard to trigger and easy to understand.**
- **Silence is a bug.** A service that stops earning should say so.
- **Honest numbers, including zero.** Earnings ranges are floors as well as
  ceilings.
- **The catalog is the source of truth**, and it must be checked against reality
  rather than trusted.
- **Third-party containers are untrusted.** They run with minimum privilege, and
  additions to that privilege are justified per service, not granted broadly.
