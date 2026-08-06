# Heimdall app submission

Everything needed to list CashPilot on [Heimdall](https://apps.heimdall.site/)
as an **enhanced** app — a tile showing live earnings and running-service count,
not just a link.

These files are kept here rather than in a fork so they stay versioned with the
API they call. Nothing here is used at runtime.

## Why enhanced rather than foundation

Heimdall apps build their own HTTP request attributes, so they can send an
`Authorization` header — 25 apps in their repo already do. CashPilot already
accepts Bearer auth (`app/auth.py`, checked before the session cookie), so an
enhanced tile needs **no server change at all**.

Verified against a live instance: `GET /api/earnings/summary` with a Bearer
token returned `total_adjusted`, `active_services` and `has_readings`.

## The rule these files exist to respect

The tile must not turn our uncertainty into the user's loss:

- `has_readings` is false on a fresh install **and** on one whose collection has
  silently stopped. `$0.00` there asserts a measurement nobody took, so the tile
  shows an em dash.
- `active_services` is deliberately **null** when the count could not be taken —
  the worker query failed while containers are in fact running. `0` there reads
  as "nothing is running", the opposite of the truth. Also an em dash.

Heimdall's blade templates print raw values, so this handling has to live in
`livestats()`. It does.

## Submitting it

Their process requires a **request first**, and warns that poorly made requests
are deleted. Steps 1–2 are a web form and cannot be scripted.

1. Go to <https://apps.heimdall.site/> and click **Request a new application**.
   CashPilot is not among their 660 apps, so a request is required. Fill in:

   | Field | Value |
   |---|---|
   | Name | `CashPilot` |
   | Website | `https://github.com/GeiserX/CashPilot` |
   | Licence | `GNU General Public License v3.0 only` |
   | Description | Self-hosted passive income orchestrator. Deploy, manage and monitor bandwidth-sharing, DePIN, storage and GPU compute containers from one dashboard, with earnings tracked across 49 services. |
   | Enhanced | yes |
   | Tile background | `dark` |
   | Icon | `docs/icon.svg` from this repository — 256×256, square, no excess whitespace |

2. Once the request exists, use the **Enhanced** download button on their site to
   get the scaffold. It carries a generated `appid`, which is why the files here
   do not include an `app.json` — that value must come from them.

3. Fork `linuxserver/Heimdall-Apps`, make a branch named for the app, extract the
   scaffold into it, then replace the generated stubs with the three files here.
   Add the icon as `cashpilot.svg` and reference it from `app.json`.

4. Open the PR against their master.

## Before you submit

Set `CASHPILOT_ADMIN_API_KEY` on the instance you test against, or use the fleet
key. On the live server the admin key is **not** set today, which is why the
verification above used the fleet key.

Be aware, and it is stated in the config help too: CashPilot has no read-only
token, so whichever key is used grants more than the tile needs. That gap is
tracked separately.
