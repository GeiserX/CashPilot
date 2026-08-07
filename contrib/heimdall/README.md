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
   | Icon | `docs/logo.svg` from this repository — the official mark, transparent, disc filling the frame edge to edge |

2. Once the request exists, use the **Enhanced** download button on their site to
   get the scaffold.

   An earlier version of this file said the scaffold's `appid` "must come from
   them". **It does not.** The value is simply `sha1(lowercase app name)`:

   ```console
   $ printf 'cashpilot' | sha1sum
   5b7c085bf60518c8e7261473688a98200e60847b
   ```

   That matches the `appid` in `app.json` exactly, and the same relation holds
   for Grafana, Vaultwarden and Home Assistant. Knowing it means the whole
   package can be assembled and **tested locally before submitting anything** —
   see below.

3. Fork `linuxserver/Heimdall-Apps`, make a branch named for the app, extract the
   scaffold into it, then replace the generated stubs with the three files here.
   Add the icon as `cashpilot.svg` and reference it from `app.json`.

4. Open the PR against their master.

## Try it on a real Heimdall first

Because the `appid` is derivable, the whole app can be installed by hand and
exercised before a single word is sent upstream. This was done against a live
Heimdall **2.8.1** on 2026-08-07 and the tile rendered
`Earnings $66.61 / Running 43` from a real server.

**A custom app persists.** Both paths Heimdall loads from are symlinks into the
config bind mount, so a hand-installed app survives a container update:

```
/app/www/app/SupportedApps        -> /config/www/SupportedApps
/app/www/storage/app/public/icons -> /config/www/icons
```

1. Copy `CashPilot.php`, `livestats.blade.php`, `config.blade.php`, `app.json`
   and the icon into `SupportedApps/CashPilot/`, and the icon again into
   `icons/`. The blades must sit **beside** the PHP class: Heimdall registers
   the view namespace as `addNamespace('SupportedApps', app_path('SupportedApps'))`.
   (Enhanced apps such as Jellyfin and UniFi ship blades; non-enhanced ones such
   as Grafana ship none — so a file listing from the wrong app misleads.)
2. Own the files **numerically**, e.g. `chown -R 1000:1000`. On an unRAID host
   `chown abc:users` fails: that user exists only inside the container.
3. Point an item at it — `class` = `App\SupportedApps\CashPilot\CashPilot`,
   `appid` as above, and the settings as **JSON** in `items.description`:
   `{"enabled":"1","url":"...","access_token":"..."}`. `Item::enabled()` reads
   `config->enabled`, so livestats render only when it is set.
4. `php artisan cache:clear`, then request the stats directly:

   ```console
   $ curl http://<host>:8000/get_stats/<item_id>
   {"status":"active","html":"...<strong>$66.61</strong>...<strong>43</strong>..."}
   ```

> **Read the log as well as the response.** `ItemController::getStats` catches
> every exception and returns `{"status":"inactive","html":""}`. A broken app
> therefore looks merely *idle*, never broken, and checking the HTTP response
> alone will read a silent failure as a pass. Confirm `storage/logs/*.log` is
> empty.

`sqlite3` is not in the container; query the database with `php -r` and PDO.

### The rule, exercised against the installed class

Driving the real class against a stub server, so the em-dash handling is proven
rather than asserted:

| server says | Earnings | Running |
|---|---|---|
| `has_readings:true, total_adjusted:66.61, active_services:43` | `$66.61` | `43` |
| `has_readings:false, total_adjusted:0` | **—** | `43` |
| `active_services:null` | `$66.61` | **—** |
| `has_readings:true, total_adjusted:0, active_services:0` | `$0.00` | `0` |

The last row is the one that matters. It carries the same `0` as the second and
renders **differently**, which is what proves the dash follows `has_readings`
rather than the number being zero. Without it the table would also pass against
a tile that simply dashed every zero.

## Which key to use

Use **`CASHPILOT_READONLY_API_KEY`**. It is scoped to reporting endpoints and
cannot deploy, stop or remove anything, which is exactly what a tile needs.

The admin and fleet keys also work, but the admin key grants full container
control and the fleet key is the *enrolment* credential — anything holding it
can enrol a worker. Handing either to a dashboard is far more than showing two
numbers requires.

### A correction worth keeping

An earlier version of this file sent `docs/icon.svg` — a square with its own
dark background plate — and justified it by claiming `logo.svg` carried a white
background. **That was wrong.** The white rect in `logo.svg` sits inside a
`<mask>`, so it is never painted; the file renders fully transparent (top-left
pixel `srgba(0,0,0,0)`).

It matters because their guidance explicitly asks for transparent backgrounds,
and Heimdall paints its own colour behind the icon — a plate fights it. The
lesson is the cheap one: that claim came from reading the markup, and one
render would have settled it.
