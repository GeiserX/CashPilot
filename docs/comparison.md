# How CashPilot compares

There are several good open-source projects in this space, and the honest summary is that they overlap more than they differ. [money4band](https://github.com/MRColorR/money4band) is the most mature of them: it supports 20+ apps, ships a web dashboard, and is actively developed. If you want to run a handful of bandwidth-sharing apps on one machine, it is a perfectly good choice and has been doing this longer than CashPilot has.

CashPilot is built around three things that shape its whole design:

- **A fleet, not a machine.** One dashboard holds the state for many servers, each running a worker. Earnings are collected centrally exactly once, so nothing is double-counted, and every figure drills down per server and per service.
- **Earnings pulled from the providers themselves.** <!-- n:collectors -->15<!-- /n --> collectors authenticate against provider APIs and dashboards and record real balances into a local history, rather than reporting that a container is running. That is what makes "running but not earning" detectable at all.
- **Breadth beyond bandwidth.** <!-- n:catalogued -->52<!-- /n --> catalogued services spanning bandwidth sharing, DePIN, storage and GPU compute, each with a setup guide, a payout method, and a status that is re-checked weekly in CI.

If none of those matter to you, use whichever tool you prefer — they will all start the same containers.

> **On this section.** It deliberately avoids a feature matrix claiming what other projects lack. Those tables go stale the moment someone ships a release, and a comparison a reader can falsify in thirty seconds is worse than no comparison at all. If anything above is out of date, please open an issue.
