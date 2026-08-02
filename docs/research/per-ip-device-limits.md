# Per-IP device limits: what providers actually document

Research backing `devices_per_ip` in the catalog (CashPilot-4qv), which drives the
egress-conflict warning. Recorded here because the value is only as good as its
source, and a future contributor needs to see the evidence rather than trust a
number someone once typed.

**The rule this table exists to enforce:** write a number only where the provider
states one. Where they do not, leave the key ABSENT — the preflight then tells
the user to check the terms, which is honest. A guessed number tells them
something false with full confidence.

Snapshot date: 2026-08-02. These terms change without changelogs; re-check before
relying on any row.

## Documented by the provider

| Service | devices_per_ip | Kind | Source |
|---|---|---|---|
| honeygain | **1** | hard limit | Help centre: "Users may connect 1 device per one IP/Network." Extra devices trigger a "Network overused" error. |
| iproyal (Pawns.app) | **1** | hard limit | Terms of Use: "Pawns.app limits the number of devices per single IP address to one (1)." |
| earnfm | **1** | hard limit | Help centre: "One Device Per Network: Each device should be connected to a unique IP or network." |
| ebesucher | **1** | hard limit | Official blog: multi-device is allowed only if "each device ... has to be connected to the Internet through a unique IP address." |

## Documented as sharing, with no number

These state that devices behind one IP split one allocation. That is real and
worth warning about, but it is not a device count, so the key stays ABSENT and
the effect belongs in `requirements.note`.

| Service | What the provider says |
|---|---|
| earnapp | Extra devices on one IP "will get less priority for traffic" and do not increase earnings beyond the per-IP cap. |
| spide | Terms: "traffic sent through a single public IP address will be distributed between devices utilizing the same IP address." |
| storj | Nodes in the same /24 subnet share allocation (already captured in that file's `note`). |

## Not documented anywhere official

`bitping`, `urnetwork`, `packetstream`, `proxyrack`, `repocket`.

Two of these have a number that circulates widely and traces to **no provider
source at all**:

- **repocket — "2 devices per IP"**. Repeated across review blogs. Repocket's own
  Terms state only a per-ACCOUNT limit ("up to five (5) devices ... and a maximum
  of five (5) active sessions"), which is a different thing.
  **The catalog currently declares `devices_per_ip: 2` for repocket on this
  basis.** It predates this research and should be re-sourced or removed.
- **proxyrack — "2 devices per IP"**. Same pattern. Proxyrack's two device-limit
  help articles (the newer dated 2026-02-23) mention only a 500-per-account cap.

## VPS / datacenter acceptance

| Service | Policy |
|---|---|
| honeygain | Datacentre IP types blocked outright ("Unusable network"); VMs discouraged. |
| earnapp | "Installing EarnApp on Virtual Machines (VMs), Docker containers, or hosting services is strictly prohibited"; DCH IPs blocked. |
| iproyal (Pawns.app) | Residential only; "does not allow the use of any servers, VPNs, or proxy services". |
| spide | Residential only; servers/VPN/proxy not allowed. |
| ebesucher | "Using the surfbar on a virtual server is not allowed." |
| proxyrack | Allowed, but reclassified to a lower datacentre rate. |
| bitping | Allowed; servers and Docker explicitly supported. |
| earnfm | Allowed; datacentre connections are their own uncapped category. |
| repocket | Ambiguous — the ToS VPS clause sits in the fraud/offer-abuse section, so whether it covers bandwidth sharing is unclear. Not resolved. |
| urnetwork, packetstream | No statement found either way. |
