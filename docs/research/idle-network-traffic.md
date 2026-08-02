# What "idle" actually looks like on the wire

Measurements behind `SILENT_BYTES_PER_SEC` in `app/net_activity.py`
(CashPilot-t6y). The bead was explicit that the threshold must come from real
idle traffic rather than from assuming zero, so it does.

**Method.** Every `cashpilot.managed` container on a live host, two readings of
`/proc/net/dev` inside the container 120 seconds apart, rate = delta / 120.
Single host, single 2-minute window — enough to disprove "idle means zero", not
enough to calibrate anything finer. Treat the number as a floor, not a tuned
constant.

Date: 2026-08-02.

| Container | rx B/s | tx B/s |
|---|---:|---:|
| mysterium | 815,589 | 15,275,715 |
| honeygain | 6,709 | 6,773 |
| proxylite | 5,971 | 1,394 |
| anyone-protocol | 2,490 | 2,591 |
| storj | 1,018 | 5,878 |
| earnfm | 546 | 661 |
| repocket | 525 | 571 |
| bitping | 117 | 118 |
| proxyrack | 36 | 22 |
| packetstream | 35 | 12 |
| earnapp | 19 | 12 |
| proxybase | 5.5 | 7.3 |
| **traffmonetizer** | **0.0** | **0.0** |
| **iproyal** | **0.0** | **0.0** |

## What this shows

**Idle is not zero.** Eleven of fourteen containers moved measurable traffic
while earning little or nothing — keepalives, heartbeats, control-plane chatter.
A threshold of zero would have called all of them active.

**Zero does happen, and it means something.** Two containers moved *literally
nothing* in two minutes. That is the only distinction this data supports, so
the threshold sits just above it (2 B/s) and the signal answers one question:
did anything at all cross the wire?

**Traffic volume is not earnings.** Mysterium moved 15 MB/s because it is a
dVPN exit carrying other people's traffic; Storj's 5.9 MB/s tx is customer data
being served. Neither number tells you what was paid. This is why the signal can
only ever weaken confidence in `app/producer_state.py`, never assert PRODUCING.

**Silence is not breakage.** Bandwidth resale is buyer-driven: a healthy node
moves nothing while nobody is buying. Hence SILENT supports IDLE and never
FAILING.

## The trap that shaped the code

Docker's `stats` API omits the `networks` key **entirely** for containers on the
host network — no interfaces, no counters. On this fleet the single busiest
service (mysterium, above) is host-networked, so a naive reading would score the
best earner as zero traffic and call it dead.

The catalog does declare this one — `services/bandwidth/mysterium.yml` sets
`network_mode: "host"` — but the code still decides at RUNTIME from what Docker
actually reports. A container can be started host-networked by an override the
catalog knows nothing about, and the counters are either present or they are
not, whatever any YAML claims.
