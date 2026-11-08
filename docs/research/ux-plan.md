# CashPilot UX plan: clicks, keyboard, terminal and agents

Status: proposal. Based on origin/main at 94788d55 (v2.1.1 plus fixes). Every `file:line` below refers to that tree. Screenshot names (such as `05-owner-bad-token.png`) refer to a throwaway walkthrough run with fake data, in dark mode. Those screenshots are not committed. The mockups in `ux-mockups/` are committed, and their own notes cite the tree they were drawn on, one or two commits earlier.

## 1. The problem

CashPilot already does the hard parts well. Copies run behind a fail-closed tunnel. Each copy gets its own device ID. It checks LAN isolation and caps proxy traffic. But a user still leaves the app, or reaches for the mouse, at the moments that matter most:

- **First login needs a terminal, and the page points at the wrong line.** The README's `grep -i "setup token"` works. But the welcome page and its error tell you to look for a line beginning "Setup token to create the owner account", and that line does not exist (`app/templates/onboarding.html:107`, `:202-203` against `app/main.py:2125-2126`).
- **Choosing services needs a mouse.** The wizard's service cards cannot be chosen from the keyboard at all. They are click-only `<div>`s (`app/static/js/app.js:3078`, `app/static/js/delegate.js:17`).
- **Deleting a volume is the default.** Removing a stateful node takes two native confirms, and pressing Enter twice deletes its data volume (`app.js:4172-4174`).
- **Proxies come one at a time.** Ten proxies from a vendor take about 80 field entries, because nothing accepts `socks5://user:pass@host:port` (`fleet.html:93-111`). Putting 9 services behind 10 proxies takes about 450 actions, one copy per form submit (`fleet.html:115-124`).
- **"Test" does not mean "earns".** A proxy that blocks vendor domains passes Test, and its copies earn nothing (`tunnel/cp-probe:8-14`).
- **Push alerts need a shell.** They can only be set through env vars and a restart, with no test button (`app/notify.py:14-16`, `:71-80`).
- **Redeploying by keyboard is slow.** It takes about 70 keystrokes to redeploy one service on one box. Closed modals leave 9 invisible Tab stops on every page (`style.css:730-745`).
- **The dashboard goes stale.** It reloads once an hour, while the bell reloads every minute (`app.js:284-291` against `:4837`).
- **A Mysterium node is finished outside the app.** It still needs one ssh tunnel, a router session and about 6 clicks in the node's own web UI before it is reachable and claimed (`services/bandwidth/mysterium.yml:47-60`, `:88-99`, `:184`).
- **Other people cannot be managed from the UI.** The API can list users, change roles and delete users, but no page calls those routes (`app/routers/users.py:22`, `:32`, `:59`).

Terminal and agent users have no CLI. They also have no API schema (`app/main.py:2320-2322`), and the only token for scripts is an owner key that can read stored credentials (`app/auth.py:172-174`).

## 2. Principles we will hold

1. **Every action is reachable by keyboard.** Every action has a palette entry, and the frequent ones also have a shortcut. Nothing is mouse-only.
2. **Every manual step gets one of three treatments.** (a) The app does it. (b) The app generates the exact command, file or router rule with a copy button. (c) If it must stay manual, the app checks it afterwards with a "Check again" button and a live status.
3. **No dead ends.** Every error names the box, the service and the cause, and offers the fix as a button or a copyable line. Errors stay until dismissed. They never fade out as a toast.
4. **Safe is the default.** For anything that touches identity, volumes or uptime, focus starts on the safe button. Data deletion needs the slug typed in. Stateful redeploys show a plan first, and the server computes that plan (X22).
5. **One source of truth.** Findings, actions, plans and scopes are defined once on the server. The UI, CLI, API, MCP server and docs all render from that one place, so they cannot drift.
6. **Freshness is visible.** Every live view says when it was read.
7. **One noun per thing.** The UI, docs, CLI and API all say "box" (one box runs one worker), and services always appear by display name, never by slug. New API parameters use `box`. `worker` stays as an alias. In the CLI and API, "egress" means any way out (the box's own IP, a proxy, a VPN, a tailnet exit). The UI labels it "Proxies & VPNs".
8. **Small PRs on the current stack.** No frontend rewrite. Use native `<dialog>`, `<form>` and ARIA patterns on top of the existing Jinja templates and `app.js`.
9. **Referral links stay.** Every vendor link uses the catalog's referral or dashboard URL from `services/**/*.yml`, never a bare URL.
10. **Secrets stay out of URLs and argv.** Tokens and passwords never go in a query string, a log URL or a command line.

## 3. Ranked roadmap

Effort: S is up to a day, M is a few days, L is a week or more. An item marked "split" ships as the numbered PRs listed. Every other item ships as one PR.

### Wave 1: now (foundations and quick wins)

**N1. First login without guessing**

- Task: create the owner account.
- Today: 1 terminal step. The README grep finds the line. But the page quotes text that does not exist, so anyone following the page instead of the README is stuck. Then a paste and about 6 clicks.
- After: the page quotes the real line and offers a copyable `docker exec cashpilot-ui cashpilot setup-token`, which prints only the token.
- Change:
    - Share one constant between `logger.warning` and the template, so the page quotes the real line.
    - Add a tiny `setup-token` entry point in the image.
    - Keep the token out of URLs. This is a deliberate choice in `app/main.py:2126-2128`. If a one-click link is wanted, log `/register#token=…` (a fragment is never sent to the server or a proxy) and strip it with `history.replaceState` on load.
    - Show per-platform "where your logs are" steps (Compose, Unraid, Portainer).
    - Trim pasted whitespace and check the token's shape before submit.
- Evidence: `app/templates/onboarding.html:105-110`, `:201-203`; `app/main.py:2124-2129`; `README.md:44-48`; `app/setup_token.py:1-18`; screenshot 05-owner-bad-token.png.
- Impact: high. Effort: S. Dependencies: none.

**N2. Modals become native dialogs**

- Task: open, use and close any modal (Logs, service detail, credentials, payout claim, password).
- Today: closed modals keep 9 hidden Tab stops on every page. After opening one, focus stays behind the overlay. Escape leaves log polling running every 5 s.
- After: focus moves into the dialog and is trapped there. Escape closes only the top dialog, runs its cleanup, and returns focus to the button that opened it.
- Change:
    - Migrate `openModal`/`closeModal` to `<dialog>.showModal()`, built from one Jinja macro with `aria-labelledby` and a labelled close button.
    - Use a modal stack instead of `closeAllModals`.
    - Run `stopLogPolling` on the dialog's `close` event.
    - Replace the global key handler's "bail while any modal is open" rule (`app.js:175`) with layer-aware handling.
    - As an interim fix, add `visibility:hidden` and `inert` to closed overlays.
- Evidence: `app/static/css/style.css:730-745`; `app.js:142-162`, `:175`, `:2463`, `:2788`; `base.html:176-249`, `:180`; `dashboard.html:156`, `:171`; screenshot 35-kbd-modal.png.
- Impact: high. Effort: M. Dependencies: none. Blocks N3, X1 and X3.

**N3. One safe confirm dialog**

- Task: stop, remove or redeploy a stateful node.
- Today: Enter, Enter removes the container and deletes its volume. Stop on the dashboard has no confirm at all (`app.js:2687-2696`).
- After: focus starts on "Keep data". Deletion needs the slug typed in. Stop on a stateful node names the risk ("downtime counts against Storj uptime"), and the toast offers "Start again".
- Change: add `CP.confirm({title, body, danger, confirmLabel, requireType})` and replace all 23 `confirm()` calls. Every confirm names the box. The redeploy variant shows the X22 plan once X22 lands. Until then it lists the saved settings it keeps.
- Evidence: 15 in `app.js` (among them `:4172`, `:4174`, `:2710`, `:2737`, `:2750`, `:3736`, `:3760`, `:4139`, `:4155`, `:4684`); 5 in `fleet.html` (`:533`, `:551`, `:793`, `:1134`, `:1144`); 2 in `activity.html`; 1 in `import.js:205`. Stop without a confirm: `app.js:2065`, `:2687-2696`.
- Impact: high. Effort: M. Dependencies: N2.

![M8: remove dialog that keeps data by default](ux-mockups/m8-fold.png)

**N4. Wizard works from the keyboard and on one box** (split: 2 PRs)

- Task: deploy the first services.
- Today: Tab cannot reach the cards. On a one-box install the box checkbox starts unticked, so Deploy fails. The summary then blames an offline worker. "No workers online" has no link.
- After: Space toggles a card, the arrow keys move through the grid, and Enter goes to Next. One "Deploy to: [boxes]" selector sits at the top of step 3, ticked when only one box fits. The summary gives the cause for each service, with a "Go back and fix" button.
- Change:
    1. Cards become `<label>` elements wrapping real checkboxes, using the same pattern as step 1 (`setup.html:47-74`), with a roving tabindex.
    2. Auto-tick the box when only one fits. Give the cause per service in the summary. Replace "No workers online." with a status line: box name, last seen, and [Open Fleet] [Copy logs command] [Retry]. Generate the EarnApp UUID in the browser.
- Evidence: `app.js:3078`, `:1800`, `:3328`, `:2968`, `:3255-3257`, `:3866`; `services/bandwidth/earnapp.yml:30-36`; screenshots 12-deploy-no-worker-no-creds.png and 13-setup-summary.png.
- Impact: high. Effort: M (S each). Dependencies: none.
- Mockup: M6, full page at [m6-full.png](ux-mockups/m6-full.png).

**N5. Paste proxies, one per line**

- Task: add proxies from a vendor.
- Today: about 8 actions per proxy. A pasted URL is refused with a toast.
- After: paste N lines and see a preview table with masked passwords. Errors show per line. One button adds them all. Ten proxies take about 3 actions.
- Change:
    - Add a textarea that accepts `socks5|socks5h|http://user:pass@host:port`, `host:port:user:pass` and `user:pass@host:port`.
    - One shared cap, reset day and rotating setting applies to the whole batch.
    - The API accepts `{url}` as well as the split fields, plus a batch create.
    - On create, the form shows no "unchanged if empty" placeholders and no remove checkboxes (EG-17).
- Evidence: `fleet.html:89-113`, `:100-104`; `app/proxies.py:96-98`; screenshot 25-proxy-pasted-url.png. Formats used elsewhere: https://raw.githubusercontent.com/engageub/InternetIncome/main/proxies.txt and https://raw.githubusercontent.com/MRColorR/money4band/main/docs/proxy-setup.md
- Impact: high. Effort: M. Dependencies: none.

![M1: paste-many dialog with per-line errors](ux-mockups/m1-paste.png)

**N6. Test a proxy where you are, on the box you mean**

- Task: check that a proxy works.
- Today: Test silently runs on the box chosen in a different form (`#copy-worker`). Progress is a 45 s toast. A failed row still says "not tested".
- After: Test opens a popover with a box picker. The row carries a status chip: Untested, Testing (with elapsed seconds), Works (exit IP and country), or Failed (short reason, with Details). A Test button inside the add form lets you test before saving.
- Change: show the box picker and status chip in the UI. Add `ok`, `error` and `box_id` to the existing `{exit_ip, country, ms}` response, and store the last result per box.
- Evidence: `fleet.html:1148-1152`, `:998`; `docs/proxies.md:27-30`; screenshots 26-proxy-tested.png and 30-proxy-test-viewport.png.
- Impact: medium. Effort: S. Dependencies: none.

**N7. Pending device links never vanish**

- Task: link a new EarnApp or ProxyRack device, including a proxied copy, to the vendor account.
- Today: one toast that fades in seconds. Nothing shows the pending link for 24 h, and after that it appears only in the bell.
- After: the cell gets an amber chain chip. A Needs attention item stays until the device is linked, with [Copy id], [Open <vendor> devices] using the referral or dashboard URL, and [I linked it, check now].
- Change: store pending links on the deployment or copy record (a schema change), and reuse `_showDeviceLink`.
- Evidence: `app.js:3394`, `:3425`, `:3742-3744`, `:3362-3395`; `fleet.html:1117-1124`; `app/main.py:1366-1430`, `:4536-4541`.
- Impact: high. Effort: M. Dependencies: none (N9 makes it cleaner).

**N8. Add a box that actually joins**

- Task: add a second box.
- Today: Fleet, scroll to the bottom, expand a `<details>`, Reveal, and Copy 3 env vars. The docs need 6, plus a compose file. On the new host it is about 4 terminal steps. On the default install the copied UI URL is loopback. Nothing shows progress.
- After: an "+ Add a box" button in the Boxes header and in the + menu opens a dialog that:
    - asks for the name and the address this UI is reachable on, warning when that address is loopback or the UI is bound to 127.0.0.1, and showing the exact `.env` line;
    - shows complete copy blocks in tabs: compose, `docker run`, and Unraid values;
    - waits live: "Waiting for <name>…" turns green on the first heartbeat, or names the likely cause after 2 minutes.

    On the new host this leaves one paste.
- Change:
    - Generate the full 6-variable snippet.
    - Rename "Reveal API Key" to "Enrolment key", with a pointer to API tokens (cli-16).
    - Settings shows "Generated, managed on Fleet" instead of "Not set".
- Evidence: `fleet.html:36-44`, `:128-155`, `:171`; `docs/fleet.md:110-136`, `:245`; `docker-compose.yml:35-36`; `app/main.py:7153`; screenshot 40-fleet-add-box.png.
- Impact: high. Effort: M. Dependencies: N2. One-time join tokens come later (X10).

![M4: address step with the loopback warning](ux-mockups/m4-screen2.png)

![M4: complete compose block and the live wait](ux-mockups/m4-screen3.png)

**N9. One server-side findings list** (split: 3 PRs)

- Task: see everything that needs you.
- Today: Needs attention keeps only "missing" alerts. Quiet balances, device give-ups, proxy caps and activity alerts sit only in the bell, headed by a slug. "Nothing needs you" can sit beside a red bell.
- After: one list in both places. Each item carries a kind, severity, display name, box, one sentence and typed actions (start, redeploy, forget, link_device, renew_credential, snooze 24 h, ignore).
- Change:
    1. Add `GET /api/findings`. Port the logic of `renderAttention` and the bell kinds to the server. The bell becomes a counter for the same list.
    2. Add typed actions plus snooze and ignore, stored per finding id.
    3. `drift.py` returns codes and parameters instead of joined prose (D11). Build on `move_advice()` (`app/drift.py:138-188`), which returns a structured `{action, warning, redeploy}` since #677.
- Evidence: `app.js:1500-1664`, `:1611-1622`, `:1710-1715`, `:4974-5022`; `app/main.py:1392-1405`; `app/drift.py:216-324`.
- Impact: high. Effort: L (M, S, M). Dependencies: none. Blocks X2, X6 and the CLI's `status`.
- Mockup: M5, full page at [m5-full.png](ux-mockups/m5-full.png).

**N10. Dashboard freshness**

- Task: trust what the dashboard says.
- Today: it reloads hourly with no timestamp.
- After: Placement and Needs attention reload every 60 s while the tab is visible. An "updated 12 s ago" label turns amber after 3 minutes and shows "last good read hh:mm" on a failed reload.
- Evidence: `app.js:284-291`, `:4837`; `fleet.html:955`, `:1164`.
- Impact: medium. Effort: S. Dependencies: none.

**N11. A disabled account looks disabled**

- Task: recognise a vendor ban.
- Today: the grid shows red "exited" on every box and says nothing more.
- After: a hatched cell with a lock across the whole row, "account off" in place of Up x/y, and an "Account disabled" badge.
- Change:
    - Read `svc.account_disabled` in `renderPlacement`.
    - Add `account_disabled` health signals to more catalog entries.
    - When every box exits with the same last log line, show "probably the account", worded as a guess.
- Evidence: `app.js:1447-1486`, `:1518-1523`; `services/bandwidth/iproyal.yml:57-62`.
- Impact: high. Effort: S. Dependencies: none.

![M2: Placement with glyphs, egress columns, an account-off row and freshness](ux-mockups/m2-grid.png)

**N12. "Set address" on unpaid payouts**

- Task: fix a payout address marked "Not set".
- Today: a red panel with no button. The fix (a redeploy with the address variable) takes 4-6 clicks found by trial.
- After: a [Set address] button opens a dialog with the one catalog field, pattern-validated, lists the boxes it applies to, and redeploys only that variable.
- Evidence: `app/templates/payouts.html:47-54`, `:289-305`; `app/payout_registry.py:15-20`.
- Impact: high. Effort: S. Dependencies: N3.

**N13. API schema behind auth**

- Task: find what a script or agent can call.
- Today: read 8,311 lines of `main.py`.
- After: `/api/openapi.json` and a dark `/api/docs` page for authenticated owners, plus a static schema on the docs site for each release.
- Change: serve the schema behind auth. Tagging every route with `x-cashpilot-scope` (read, operate, deploy, proxies, admin) ships with the tokens in X7, together with the test that fails on an untagged route.
- Evidence: `app/main.py:2312-2323`; `tests/route_enumeration.py:1-25`.
- Impact: high. Effort: S. Dependencies: none. Blocks the token, CLI and MCP work.

**N14. Shortcut help, skip link and labels**

- Task: learn the shortcuts and get to the content.
- Today: one footer hint that is partly wrong (Activity is `g n`). 11 Tabs before any content. Repeated buttons read "Remove, Remove, Remove".
- After:
    - `?` opens the shortcuts overlay (section 4).
    - A skip link leads to `<main id="main">`.
    - The active nav link has `aria-current="page"`, and focus lands on the `h1` after a `g` jump.
    - Buttons get object labels ("Restart Honeygain on box-2"), and toggle groups get `aria-pressed`.
    - The catalog search field gets a label.
- Evidence: `base.html:45-171`, `:84`, `:96`; `app.js:184-187`, `:2054-2062`, `:3998`; `fleet.html:445`, `:1005-1013`; `catalog.html:11-21`; `setup.html:9-28`.
- Impact: medium. Effort: S. Dependencies: none.

![M3: the ? overlay, built from the same registry as the palette](ux-mockups/m3-screen4.png)

**N15. Enter saves every form; messages are announced and stay**

- Task: save credentials, prices or wattage, and read the result.
- Today: Enter does nothing outside the password and proxy forms. Toasts vanish after 4 s, errors included, and screen readers never hear them. Activity uses `alert()`.
- After:
    - Every editable block is a `<form>`, and Ctrl/Cmd+Enter saves and closes.
    - The toast region is `aria-live`, and errors use `role=alert` and stay until dismissed.
    - Hovering or focusing a toast pauses it.
    - The last 20 messages are listed under the bell.
- Evidence: `app.js:44-69`, `:793`, `:2311`, `:3120`, `:5140-5149`; `fleet.html:58-68`, `:435`; `activity.html:328-354`.
- Impact: medium. Effort: S. Dependencies: none.

**N16. Explain what cannot run behind a proxy, before submit**

- Task: pick a service for a proxied copy.
- Today: every slug is listed, 8 of the 17 are refused after submit, and an empty box list gives no reason.
- After: refused services are disabled and show their reason on hover or focus. An empty box list names the fix ("<box> runs 1.9: update it").
- Change: send `can_proxy` and the refusal text with the catalog.
- Evidence: `fleet.html:1030-1042`, `:122`; `app/proxies.py:192-218`; `app/worker_api.py:677`.
- Impact: medium. Effort: S. Dependencies: none.

**N17. The quickstart writes `CASHPILOT_COMPOSE_DIR`**

- Task: run the first in-app update.
- Today: the update is refused on every README install, and fixing it takes 2 terminal steps.
- After: the README quickstart writes the line before `up -d`. The About card warns before Update and copies the missing line.
- Evidence: `README.md:44-48`; `app/orchestrator.py:2674-2690`.
- Impact: medium. Effort: S. Dependencies: none.

**N18. Settings that do nothing stop pretending**

- Task: change a setting.
- Today: Environment shows editable inputs that "do not take effect".
- After: the card is read-only and has a [Copy as .env] button. Runtime settings move to real controls, and a "pending restart" badge appears where a restart is needed.
- Evidence: `app/templates/settings.html:51-61`; `app/main.py:7140-7196`.
- Impact: medium. Effort: S. Dependencies: none.

**N19. Isolation off is a finding**

- Task: notice that earners can reach the LAN.
- Today: with isolation off, the dashboard says "Nothing needs you". Only a manual click shows the problem.
- After: the check runs after enrolment, after each deploy, after a worker restart or Docker version change, and daily. A per-box chip reads "checked 3 h ago ✓". A failure becomes a Needs attention item, with the `.env` fix to copy and a [Check again] button.
- Evidence: `fleet.html:439-448`, `:683-699`; `docs/isolation-check.md:435-442`; screenshots 18-dashboard.png and 39-fleet-check-isolation-off.png.
- Impact: high. Effort: M. Dependencies: N9.

**N20. Users and roles in Settings**

- Task: give a partner a read-only login, change someone's role, or remove them.
- Today: the API exists, but no page calls it. Each change is 1-2 curl calls with the owner session, and nobody knows the routes exist.
- After: Settings > People lists users with their role. It has [Add person] (name, password or one-time link, role), a role select, Reset password and Remove. Every change goes through `CP.confirm`. Owners cannot remove the last owner.
- Evidence: `app/routers/users.py:22`, `:32`, `:59`; `app/routers/auth.py:119-134`; `app/main.py:7418`.
- Impact: medium. Effort: S. Dependencies: N3.

### Wave 2: next

**X1. Command palette** (Cmd/Ctrl+K and `:`) (split: 2 PRs)

- Task: run any action.
- Today: about 70 keystrokes to redeploy one service on one box.
- After: about 12 keystrokes (Cmd+K, `rede hon box2`, Enter, Enter).
- Change:
    1. `GET /api/actions` serves one registry of `{id, label, keywords, scope, params, route, danger, shortcut}`, filtered by the caller's role. A `<dialog>` holds a combobox fed by it. The first PR covers pages, services and settings.
    2. Parameterised actions. Parameters are asked for step by step (service, then box, then confirm), with recent entries on top. Dangerous entries go through N3 and show the X22 plan.
    - The same registry feeds `?`, the list keys and `cashpilot actions --json`.
- Evidence: `app.js:164-194`; `base.html:77-96`.
- Impact: high. Effort: L. Dependencies: N2, N3 (X22 for plans).

![M3: Cmd+K with fuzzy actions](ux-mockups/m3-screen1.png)

![M3: box step, then the plan](ux-mockups/m3-screen2.png)

**X2a. Placement grid you can act on**

- Task: fix the red cell you are looking at.
- Today: the cell is a `<span>`. A fix takes a scroll, a visual search and 2-3 clicks, and the keyboard cannot reach the cell at all.
- After:
    - The grid is `role=grid`. Arrow keys move between cells, and Enter opens a popover with the status in words, the last 20 log lines, and Start, Restart, Stop, Logs and Redeploy.
    - Each state has a glyph (✓ ! × ? ·). Unknown and not-placed are raised to 3:1 contrast.
    - Box names are middle-truncated.
- Evidence: `app.js:1421-1497`, `:1468`, `:2086-2148`; `style.css:1429-1437`; `dashboard.html:77-83`; screenshot e08-placement.png.
- Impact: high. Effort: M. Dependencies: N3, N9.

![M2: cell popover with the cause and the actions](ux-mockups/m2-popover.png)

**X2b. Proxied copies in Placement**

- Task: see proxied copies next to everything else.
- Today: proxied copies are missing from Placement, Up x/y and Needs attention. The worker drops them from the heartbeat's container list.
- After: each box gets egress sub-columns ("box-a via isp-1") with dashed borders. An empty egress cell opens "place a copy", prefilled. A dead copy becomes a finding.
- Change: add proxied copies to the heartbeat as their own list, and read that list in `placement.py`.
- Evidence: `app/orchestrator.py:3038-3042`; `app/worker_api.py:715-718`; `app/placement.py:96-107`; `fleet.html:980-1023`.
- Impact: high. Effort: M. Dependencies: X2a.

![M2: place a copy from an empty egress cell](ux-mockups/m2-place.png)

**X3. "Proxies & VPNs" page and "Add egress" wizard** (section 5)

- Task: find proxies and VPNs at all, and add them.
- Today: owner-only, near the bottom of Fleet, with no entry point anywhere else.
- After:
    - A nav item labelled "Proxies & VPNs" on `g e`. The box's own IP is the first row.
    - CTAs from Placement ("Each service earns once per IP"), from the same-IP warning, from catalog "Runs behind a proxy" badges and from wizard step 3.
    - Palette keywords: proxy, vpn, wireguard, exit node, egress, IP.
- Evidence: `fleet.html:78-124`, `:992`; `base.html:77-89`; screenshots e01-fleet-full-empty.png and 19-fleet.png.
- Impact: high. Effort: M. Dependencies: N2, N5, N6.

![M1: the Proxies & VPNs page](ux-mockups/m1-page.png)

**X4. Vendor reach test, IP type and rotation detection** (split: 3 PRs)

- Task: know whether a proxy will earn before placing copies on it.
- Today: impossible in the app. You read crash loops after deploying.
- After: Test runs a matrix through the throwaway tunnel and shows one row per service: OK, blocked (403), port closed, or DNS refused. Placement only offers services that passed. A daily re-probe raises a finding when a vendor becomes blocked.
- Change:
    1. Vendor reach: add an optional `docker.egress: [{host, port}]` list to the catalog, seeded from the ports Activity has observed and reviewed by a maintainer, and extend `cp-probe`.
    2. IP type and ASN chip (Residential, ISP, Datacenter or Mobile), matched to `residential_ip: true`.
    3. Rotation from 3 samples about 20 s apart, which sets "rotating" automatically, plus the daily re-probe.
- Evidence: `tunnel/cp-probe:1-15`; `app/proxy_tunnel.py:773-781`; `app/main.py:4353-4400`; `docs/proxies.md:175-190`; `app/worker_api.py:475-493`; `app/activity.py:1-20`.
- Impact: high. Effort: L (M, S, S). Dependencies: N6, N9.

![M1: test result with vendor reach and IP type](ux-mockups/m1-test.png)

**X5. Placement matrix for proxied copies**

- Task: run several services through several proxies.
- Today: about 5 actions per cell, so 9 services × 10 proxies is about 450 actions.
- After: rows are services and columns are egresses. Cells that passed X4 start ticked. Cells that break a `devices_per_ip` limit start unticked, with the reason. One [Start 27 copies] button runs them, with a progress state per cell. Space and the arrow keys toggle cells. A toggle on an egress, "run every eligible service here", keeps it filled.
- Change: add a batch endpoint.
- Evidence: `fleet.html:115-124`, `:1108-1126`; `app/main.py:4450`. Bulk placement elsewhere: https://github.com/XternA/income-generator and https://raw.githubusercontent.com/MRColorR/money4band/main/docs/proxy-setup.md
- Impact: high. Effort: M. Dependencies: X4 (first PR).

**X6. Alerts in Settings, with a test button and deep links** (split: 3 PRs)

- Task: get pushed when something breaks.
- Today: 2-3 terminal steps and no test.
- After and change:
    1. Settings > Alerts: add an ntfy, Telegram (with a "find my chat id" helper) or webhook channel. [Send test] shows the delivery result inline. Secrets are encrypted like other credentials, and env vars appear as locked overrides. The dashboard shows a "No alert channel yet" card until one exists.
    2. Toggle each event type and set quiet hours.
    3. A public base URL setting lets every push carry a link to the finding or service.
- Evidence: `app/notify.py:7-17`, `:71-105`; `app/main.py:2130-2140`; `app/importers/parse.py:387`.
- Impact: high. Effort: L (M, S, S). Dependencies: N9 (for event kinds), X9 (for link targets).

**X7. API tokens, wider read scope, boxes by name, error envelope** (split: 2 PRs)

- Task: give a script or agent its own credential.
- Today: 5 terminal steps and a restart. The only choices are all-or-nothing owner, or a read-only key that cannot read alerts or logs.
- After and change:
    1. Tokens and scope. Settings > API & CLI: create a named, scoped token with an expiry and an optional box allowlist. It is shown once as `cp_<id>_<secret>` and stored as a keyed hash, with last-used time and IP and a Revoke button. The token name appears in Activity. Every route gets an `x-cashpilot-scope` tag, and a test fails on any untagged route. The read scope covers every GET that returns no secret, with logs redacted, and a test seeds known secrets and asserts none of them leak.
    2. Names and errors. Every route accepts `box=<name|client_id|id>`, with `worker` kept as an alias. Errors use one envelope: `{error, message, hint, docs_url, retryable}`.
- Evidence: `app/auth.py:153-183`; `app/deps.py:72-104`; `app/main.py:332-346`, `:4907-4913`, `:2660`, `:5002`, `:5144`, `:5235`, `:8227`; `app.js:24-28`; `docs/configuration.md:29-31`.
- Impact: high. Effort: M (M, S). Dependencies: N13.

![M7: Settings > API & CLI](ux-mockups/m7-fold.png)

**X8. `cashpilot` CLI** (split: 2 PRs)

- Task: operate CashPilot from a terminal.
- Today: there is no CLI.
- After: see section 6.
    1. CLI v1, read and proxies: `status`, `finding ls|run`, `service ls|logs`, `egress add|import|test`, `box ls|add --print-compose`, `setup-token`, `token ls|create|revoke`.
    2. Lifecycle: `service deploy|start|stop|rm`, `copy apply`, `update`. Each accepts `--dry-run` and prints the X22 plan.
- Evidence: `pyproject.toml:1-6`; `app/main.py:3169-3179`, `:3265`, `:3884-3892`, `:6455`, `:6512-6589`; `AGENTS.md:56-150`.
- Impact: high. Effort: L (M, M). Dependencies: N9, N13, X7 (X22 for the second PR).

![M1: the egress commands in a terminal](ux-mockups/m1-cli.png)

**X9. A URL for every service**

- Task: open a service's management view from the dashboard, a push or the docs.
- Today: Catalog, search, Manage. The dashboard name links out to the vendor instead.
- After: `/services/<slug>?box=<id>` opens the same view, and the dashboard name opens it. The vendor link becomes an icon and keeps its referral URL.
- Evidence: `app.js:1853-1858`, `:3556`, `:3563`, `:3998`; `app/routers/pages.py:39-118`.
- Impact: medium. Effort: S. Dependencies: none.

**X10. Add a box, part 2**

- Task: add a box safely, with no repeated typing.
- After:
    - A one-time join token per box replaces the shared key. It expires and is stored hashed.
    - A live checklist runs after the first heartbeat: UI can reach worker URL, versions match, socket proxy on, LAN fence on, isolation passed. Each line has a [Check again] button.
    - `cashpilot box add --print-compose` gives the same result.
- Evidence: see N8; `fleet.html:910-944`.
- Impact: medium. Effort: M. Dependencies: N8.

![M4: the checklist after the first heartbeat](ux-mockups/m4-screen4.png)

**X11. Deploy credentials feed the balance collector**

- Task: see a balance after deploying.
- Today: the same email and password are typed twice, in 2 forms, about 6 extra clicks. The link says "Settings → Collectors", but that section is called "Earnings collection".
- After: an "Also use these to show my balance" checkbox, ticked by default. The result shows ✓ or ✗ inline. Fields the collector needs that the deploy form does not have appear in the same card.
- Change: add a catalog mapping from collector field to env key.
- Evidence: `app.js:3162-3175`, `:2425`, `:3881`; `services/bandwidth/honeygain.yml:22-32`, `:96`.
- Impact: high. Effort: M. Dependencies: none.

**X12. Deploy progress and failures that stay**

- Task: understand a deploy.
- Today: a native confirm holds the preflight findings. A spinner runs with no pull progress. A failure can leave nothing on screen, and custom services skip preflight with a swallowed 404.
- After: preflight findings and failures are listed inline in the card, with fix links. The modal shows streamed steps (pulling with MB done, creating, starting). A failure becomes a finding with [Retry]. Preflight resolves custom services.
- Evidence: `app.js:3311`, `:3320-3322`, `:3405-3408`, `:3422`; `app/main.py:5400-5409`; screenshots 17-custom-deployed.png and 18-dashboard.png.
- Impact: high. Effort: M (inline results and custom preflight first, streamed progress second). Dependencies: N2, N9.

**X13. Lists you can drive with the keyboard**

- Task: work through services, boxes, proxies and findings.
- Today: 30-60 Tabs to reach the 10th row.
- After: each list takes one tab stop. j/k move, Enter opens, o expands, and action keys apply to the current row (section 4).
- Evidence: `app.js:2031`, `:2054-2069`; `activity.html:197`; `fleet.html:435-445`.
- Impact: high. Effort: M. Dependencies: X1 (shared action registry), N3.

**X14. Grouped drift fixes in plain words**

- Task: fix drift on many copies at once.
- Today: 8 drifted copies take 16 clicks, and each confirm says "this box" without naming it.
- After: findings are grouped by cause, with [Redeploy all safe ones]. One confirm lists every service and box and flags the stateful ones. Fixes run one at a time and stop on the first failure. Each finding shows a "What changes" list, with the raw details folded away. Fleet's held items get [Redeploy here].
- Evidence: `app.js:1577-1604`, `:1673-1678`, `:3724-3736`; `app/drift.py:216-324`; `fleet.html:485-525`, `:497-501`.
- Impact: medium. Effort: M. Dependencies: N3, N9, X22.

**X15. Update all boxes from the banner**

- Task: update the UI and every box.
- Today: about 5 clicks and a manual reload per box, from Settings.
- After: [Update] in the banner and on each out-of-date Fleet row, plus [Update all (N boxes)]. Boxes update one after another, with per-box progress taken from the heartbeat. On failure the helper's log tail is shown. A series move shows the tag diff with "Apply (keeps .bak)".
- Evidence: `app.js:4379-4477`, `:4869-4883`; `fleet.html:403-409`; `app/main.py:7102-7137`.
- Impact: high. Effort: M (the series-move apply is a follow-up). Dependencies: N17.

**X16. Bind-mount preflight**

- Task: deploy Storj or Sia with a host folder.
- Today: Deploy is refused, followed by 3 terminal steps and a second deploy.
- After: when the path field is filled, the box reports whether the folder is allowed. If it is not, the exact merged `CASHPILOT_PROXY_BIND_MOUNTS=…` line and the restart command appear with copy buttons and a [Check again]. Deploy stays disabled, with the reason shown.
- Evidence: `app/orchestrator.py:226-233`, `:2571-2598`, `:2697`, `:2818`; `UPGRADING.md:275-290`.
- Impact: medium. Effort: S. Dependencies: none.

**X17. Docs for humans and agents** (section 6)

- Change:
    - An "Automate" nav section.
    - `docs/agents.md`.
    - Contributor material split out of `AGENTS.md`.
    - `llms.txt` and `llms-full.txt` generated from the nav.
    - Top task pages with Web UI | CLI | API tabs.
- Evidence: `AGENTS.md:1-48`, `:230-311`; `zensical.toml:45-59`, `:128`, `:218`; `docs/proxies.md:1-300`.
- Impact: high. Effort: S-M. Dependencies: N13 (API tabs), X8 (CLI tabs).

**X18. Importers bring proxies across**

- Task: switch from InternetIncome or money4band.
- Today: proxies are dropped on import, and so are the device lines of old copies.
- After: imported proxies go through the N5 preview. "One copy per proxy per service" keeps device line N for proxy N.
- Evidence: `app/importers/parse.py:210-231`, `:425-430`; `app/templates/import.html:21`.
- Impact: high. Effort: M. Dependencies: N5, X5.

**X19. Tailscale exit picker**

- Task: route copies through another site.
- Today: 4 manual steps in another console, a free-text field, and a 90-day key cliff.
- After: [Connect Tailscale] once with an OAuth client. CashPilot mints short-lived tagged keys per tunnel and offers a picker of exit nodes (online, last seen, exit IP and country). A dry-run checks the policy grant and shows the JSON to paste when the grant is missing. A pasted key gets a warning 14 days before it expires.
- Evidence: `fleet.html:104-106`; `docs/proxies.md:281-300`; https://tailscale.com/kb/1103/exit-nodes and https://tailscale.com/kb/1392/auto-exit-nodes
- Impact: high. Effort: L (the key-expiry warning can ship alone as S). Dependencies: X3.

![M1: Tailscale exit-node picker and the missing-grant state](ux-mockups/m1-tailscale.png)

**X20. Small egress fixes**

- An edit to a proxy prompts "Apply to 6 running copies now?", and copies still on old settings show a "stale settings" badge (EG-16).
- Catalog gets a "Deployable on my boxes" filter, sort by estimate or grade, a proxy-capable tag and a legend for the grades (W16).
- Evidence: `docs/proxies.md:216-227`; `fleet.html:1087-1106`; `catalog.html:9-24`.
- Impact: medium. Effort: S each. Dependencies: none.

**X21. Name why a container stopped**

- Task: understand exit code 137.
- After: the box sends `OOMKilled`, `Error`, `RestartCount` and the last 5 log lines. The UI turns them into a sentence plus an action ("Ran out of memory at its 768 MB limit: [Raise to 1 GB and restart]").
- Evidence: `app/orchestrator.py:250-273`; `app/main.py:551-571`.
- Impact: medium. Effort: S. Dependencies: N9.

**X22. Server-side plans for deploy, remove and update**

- Task: know what a stateful change will do before it happens, from the UI, the CLI or an agent.
- Today: `POST /api/deploy/{slug}` applies at once. The pieces exist as separate routes (deploy-risk, drift, payout-registry backup state), and a careful operator calls 3-4 of them by hand.
- After: `?dry_run=1` on deploy, remove, box commands and update returns a plan: whether the container is recreated, the env diff, volumes kept, created or deleted, critical volumes touched, the age of the last confirmed backup, and a short-lived `plan_id`. Applying a plan that recreates a stateful node needs a backup confirmed within N days or an explicit skip.
- Evidence: `app/main.py:3169-3179`, `:3265`, `:3884-3892`, `:6455`, `:6512-6589`; `AGENTS.md:56-150`.
- Impact: high. Effort: M. Dependencies: none. Blocks X8 (second PR), X14, L2 step 5 and the L5 MCP two-step. N3 and X1 render the plans.
- Mockup: M8, full page at [m8-full.png](ux-mockups/m8-full.png) (redeploy diff and the plan in a terminal).

### Wave 3: later

**L1. WireGuard egress, then OpenVPN, with provider presets**

- Change: add a `wireguard` tunnel kind with an endpoint-only nft rule, so it fails closed the same way proxies do. Accept a dropped or pasted `.conf`, with the private key stored write-only. Add provider presets with a country picker. The leak test covers the new kind before release.
- Evidence: `app/proxies.py:24`; `tunnel/cp-tunnel:44-69`. Providers elsewhere: https://github.com/qdm12/gluetun and https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/custom.md
- Effort: L. Dependencies: X3, X4 (datacenter warning).

**L2. Finish a Mysterium node inside the app**

- Change: a post-deploy checklist:
    1. a reachability panel with the exact router rule as copyable fields, [Check again now] running the windowed scan, and a live state;
    2. "Pick a free range" from `/proc/net/udp`, plus "Reset to default";
    3. "Link to my MystNodes account" (the API key is used once, never stored);
    4. "Set payout wallet", read back to confirm;
    5. "Edit settings on <box>", with a diff (X22) before an identity-preserving redeploy.

    Every new exec is allow-listed in `socket_policy.py`. Identity and keystore actions stay out of scope.
- Evidence: `services/bandwidth/mysterium.yml:46-63`, `:88-99`, `:142-163`, `:184`, `:267-277`; `app/orchestrator.py:1252-1284`; `app.js:1553-1557`, `:1800`, `:3735-3738`; `app/main.py:1919-1945`; `app/payout_read.py:1-18`; `fleet.html:532-545`; `app/drift.py:138-188` (`move_advice()`).
- Effort: L (ship as 4-5 PRs). Dependencies: N3, N9, X22.

**L3. Storj**

- Change: an optional "Create identity" job, CPU-capped, with a progress bar, which never overwrites an existing identity. A pre-deploy check that ADDRESS resolves to the box's public IP. The reachability panel on 28967 TCP and UDP, driven by `quicStatus`.
- Evidence: `services/storage/storj.yml:60`, `:67-71`, `:143`; `docs/guides/storj.md:44-88`.
- Effort: L. Dependencies: X16, L2's panel.

**L4. Back up CashPilot itself, and verify and restore node backups**

- Change: Settings > Backup downloads a sealed SQLite snapshot plus `.fernet_key`, reusing `state_backup`, with a "last backed up" date. Onboarding offers "Restore from backup". On node backups: [Verify a file], [Restore to this box] with a typed confirm and a read-back of the node id, and a browser-generated X25519 key pair.
- Evidence: `docs/backup-restore.md:6-124`; `app/state_backup.py`; `app/worker_api.py:2166-2200`; `app/templates/payouts.html:253`; `docs/backup.md:40`, `:100-147`.
- Effort: M each (3 PRs). Dependencies: N3.

**L5. MCP server, Claude Code skill, and "copy as CLI"** (section 6)

- Effort: M, S and M. Dependencies: X7, X8, X22.

**L6. Egress economics and proof**

- Change:
    - An optional price per egress, with a cost per GB against earnings per GB verdict (EG-13).
    - A "kill switch" chip fed by the heartbeat: nft table present, drop counter, last probe.
    - A [Prove it] button that runs the leak test's control on the live copy (EG-15).
- Evidence: `fleet.html:46-76`, `:995`; `app/proxies.py:316-345`; `docs/proxies.md:68-100`.
- Effort: M each. Dependencies: X2b, X3.

**L7. Guided start, cash-out checklist, housekeeping**

- A "Recommended for your boxes" preset replaces the category step (FR-08: `setup.html:31-83`, `app.js:2911-2915`).
- A "Ready to cash out" card with a checklist that records each withdrawal (D14: `app.js:1997-2004`, `:2564-2667`, `:792-826`).
- An install script with `--yes --bind` (FR-02).
- An upgrade leftovers card (H16: `UPGRADING.md:196-217`).
- A hardening checklist and memory peak per box (H17: `app/worker_api.py:2203-2215`).
- Canonical routes, with the legacy ones marked deprecated in the schema (cli-09: `app/main.py:3874-3892`, `:4881-4922`, `:8160-8180`).

## 4. Keyboard model

**Layers.** There are three. Global keys work everywhere except inside text fields. Page keys depend on the current page. List keys apply to the list that has focus. Esc always closes the top layer first: menu, then dialog, then palette. Today the handler ignores every key while any modal is open (`app.js:175`). N2 replaces that with this layer model.

**Shortcuts**

| Key | Scope | Action |
|---|---|---|
| Cmd/Ctrl+K, `:` | Global | Command palette |
| `?` | Global | Shortcut help overlay |
| `/` | Global | Focus the page filter, or open the palette when the page has none |
| `g d` / `g f` / `g c` / `g p` / `g n` / `g s` / `g a` | Global | Dashboard, Fleet, Catalog, Payouts, Activity, Settings, Add service (existing letters, `base.html:77-96`) |
| `g e` | Global | Proxies & VPNs (new page) |
| `g b` (also `g !`) | Global | Open the alerts and findings list (`g b` works on every keyboard layout) |
| `r` | Page | Refresh this page's data (today Dashboard only) |
| `n` | Page | Add in context: a service on Dashboard and Catalog, a box on Fleet, an egress on Proxies & VPNs, a person on Settings > People |
| j / k, ↓ / ↑ | List | Move the current row |
| Home / End | List | First or last row |
| Enter | List | Open the row's detail or popover, or run a finding's primary action |
| o or Space | List | Expand the row, or toggle a selection in the wizard and matrix |
| `l` | List | Logs |
| `s` | List | Start a stopped copy |
| Shift+R | List | Restart (confirms if stateful) |
| `x` | List | Stop (confirms if stateful) |
| `d` | List | Redeploy (always confirms, shows the plan) |
| `e` | List | Edit credentials or settings |
| `z` | Findings list | Snooze 24 h (the row menu offers 7 days and Ignore) |
| `.` or the ContextMenu key | List | Open the row's ⋯ menu |
| `c` | List, dialog | Copy as CLI (wave 3, L5) |
| `y` | List | Copy the row's id |
| `i` | Fleet list | Check isolation on this box |
| `t` | Egress list | Test this egress |
| Arrow keys | Placement grid, matrix | Move between cells; Enter opens the cell popover |
| Ctrl/Cmd+Enter | Dialog | Save and close |
| Esc | Any layer | Close the top layer and return focus to its trigger |

**Palette coverage.** Besides pages, services and boxes, the registry must name these, so no action is mouse-only:

- Payouts: Set address, Record a cash-out, Open claim, Confirm backup, Export backup.
- Settings: theme, currency, alert channels, tokens, Change password, Log out, People (add, change role, remove).
- Import: Import from InternetIncome or money4band.
- Activity: Open Activity for a service.
- Earnings: 7 or 30 days.
- Findings: Snooze, Ignore, Redeploy all safe ones.
- Messages: Recent messages.

**Rules**

- One registry, served by `GET /api/actions` and filtered by role and token scope, backs the palette, the list keys, the `?` overlay and `cashpilot actions --json`. A key and a palette entry run the same code path.
- Every destructive action, by any route, opens `CP.confirm` (N3). Single keys never skip it.
- Every nav link shows its chord on hover and focus (`<kbd>` plus `aria-keyshortcuts`).
- Focus:
    - On page jump, focus goes to the `h1`.
    - On dialog open, it goes to the first field, or to the heading for read-only dialogs.
    - On close, it goes back to the trigger.
    - Menus put focus on their first item and close on Esc or Tab out.
- Closed layers are `inert`. Nothing invisible ever takes focus.
- Single-letter list keys are off by default for one release, behind a setting (open question 5). The palette and `?` always work.
- Contrast:
    - Muted text is raised to at least 4.5:1 on every surface, about `#9aa1aa`.
    - Control borders are raised to at least 3:1.
    - A CI check measures the token pairs of every theme in `themes.json` (`style.css:13-38`, `:1294-1297`, `:1533`, `:1594`).

## 5. Egress: proxies, VPNs and exit nodes from the UI

**Design.** Egress gets its own page, labelled "Proxies & VPNs" (`g e`), that lists every way out. The first row is the box's own IP, followed by proxies, VPNs and tailnet exits. One "Add egress" wizard has four tabs:

1. **Paste.** URLs or vendor lines, one per line, or a dropped proxies.txt.
2. **WireGuard/OpenVPN file or provider preset.**
3. **Tailscale.** Connect once, then pick an exit node.
4. **Enter by hand.** The current form, as a fallback.

Every new egress is tested before anything is placed on it. The test shows the exit IP, country, IP type and ASN, and whether the exit rotates. It also produces a vendor reach row for every catalog service. The last step is the placement matrix, which only pre-ticks cells that passed. Each egress row then shows its copies, traffic against the cap, an optional cost per GB against earnings per GB, and a kill-switch chip. Copies appear in the main Placement grid as egress sub-columns.

**Comparison**

| | CashPilot today | money4band https://github.com/MRColorR/money4band | InternetIncome https://github.com/engageub/InternetIncome | income-generator https://github.com/XternA/income-generator | Gluetun https://github.com/qdm12/gluetun | Unraid VPN Manager https://docs.unraid.net/unraid-os/system-administration/secure-your-server/secure-your-outgoing-comms/ | Tailscale picker https://tailscale.com/kb/1103/exit-nodes | CashPilot after this plan |
|---|---|---|---|---|---|---|---|---|
| Paste a list of proxy URLs | No | Yes | Yes (proxies.txt) | Yes | n/a | n/a | n/a | Yes, with per-line preview and test |
| One copy per proxy for every app | No (one form per copy) | Yes | Yes | Yes, with install limits | n/a | n/a | n/a | Matrix, pre-ticked by test and limits |
| WireGuard/OpenVPN, presets | No | No | No | No | Yes, many named providers plus custom | Import .conf | n/a | WireGuard first, then OpenVPN, with presets |
| Exit-node picker | Free text | No | No | No | No | No | Yes, with Recommended | Picker with online state, IP and country |
| Fails closed if the tunnel drops | Yes (nft, endpoint only) | Privileged tun container | No fence | No fence | VPN kill switch only | Per tunnel | n/a | Yes, plus a live chip and "Prove it" |
| Stable device ID per copy | Yes | No | Keeps device lines | No | n/a | n/a | n/a | Yes, and imported IDs are kept |
| Traffic cap with reset day | Yes | No | No | No | No | No | No | Yes |
| Checks the vendor can be reached through the exit | No | No | No | No | No | No | No | Yes, per service, re-probed daily |
| Shows IP type (residential, datacenter) | No | No | No | No | No | No | No | Yes, matched to the catalog's `residential_ip` |
| Cost against earnings per egress | No | No | No | No | No | No | No | Yes (optional) |
| Refuses services whose terms forbid proxies | Yes | No | No | No | n/a | n/a | n/a | Yes, shown before submit |
| CLI next to the UI | No | `m4b proxy` | Scripts | `igm` TUI | Env vars | No | `tailscale` CLI | `cashpilot egress …`, declarative `apply` |

**Why our design is better**

- **It proves the exit earns, not only that it connects.** No other project checks vendor reach. That check is what catches commercial gateways that pass only ports 80 and 443, or that answer 403 to proxyware domains.
- **It keeps the safety we already have and makes it visible.** That covers fail-closed tunnels, derived device IDs, caps, same-IP grouping and terms refusals. Today none of this is visible in the UI.
- **Placement is one decision, not N×M forms.** The matrix respects limits and test results by default.
- **One page, many routes in.** Egress can be found from Placement, the wizard, the catalog, findings and the palette, so users find it without docs. The nav label uses the words users already search for.
- **Terminal and agent users get the same model.** `cashpilot egress import`, `cashpilot egress test --vendors --json` and a plan-then-apply `cashpilot egress apply egress.yml`.

## 6. Beyond the browser

**Shipping order**

1. **Schema and the ground rules for scripts** (N13 S; X7 M). This covers the schema behind auth, scope tags, boxes by name and stable error codes.
2. **API tokens from the UI** (X7, M). Scoped, revocable and shown once. The env keys stay as a bootstrap, labelled "legacy".
3. **Server-side plans** (X22, M). Every stateful verb gets `dry_run` and a `plan_id`.
4. **`cashpilot` CLI** (X8, two PRs). A thin httpx client, installed with `uv tool install cashpilot` / `uvx`. It is also shipped inside the UI image as `docker exec cashpilot-ui cashpilot …`, already authenticated locally, so a first-time user needs no token.
    - Nouns follow principle 7: `box`, `service`, `egress`, `copy`, `finding`, `token`, `actions`. Plural aliases are accepted.
    - First commands: `status` (exit 0/1/2 for ok/warn/fail), `finding ls|run <id> --dry-run`, `setup-token`, `service ls|deploy|start|stop|logs|rm`, `box ls|add --print-compose|isolation-check`, `egress add|import|test|apply`, `copy apply`, `token ls|create|revoke`.
    - Global flags: `--json`, `--jq`, `--box <name>`, `--dry-run`, `--yes`, `--profile`.
    - Secrets come from stdin or a file, never from argv.
    - The verbs are idempotent: when nothing needs to change, the result is `changed:false` with exit 0.
    - Exit codes (the single source; the mockups follow this table): 0 ok, 1 error, 2 usage, 3 auth or scope, 4 not found, 5 refused by a safety guard (including a preflight or a stateful change without `--yes`), 6 box offline, 7 partial, 8 conflict.
5. **Docs for humans and agents** (X17, S-M):
    - An "Automate" section, with a CLI reference generated from `--help` and an API reference generated from the schema.
    - Task pages with Web UI | CLI | API tabs, checked in CI.
    - `docs/agents.md`, which says:
        - use a scoped token;
        - run `status` and `finding ls` first;
        - always `--dry-run`, then show the plan;
        - back up before touching a stateful node;
        - never delete volumes or allow critical deletes without the human's explicit yes;
        - never bulk-redeploy;
        - never replace referral signup URLs.
    - `AGENTS.md` keeps contributor rules and links to it.
    - `llms.txt` and `llms-full.txt` are generated at build time. The running app also serves `/llms.txt` with its live version and the CLI install line.
6. **MCP server** (L5, M). `cashpilot mcp` over stdio first, reusing the CLI client. Tools are generated from the canonical routes:
    - Read tools carry `readOnlyHint`.
    - Deploy, remove, update and copy tools carry `destructiveHint` and run in two steps (plan returns a `plan_id` from X22, apply needs it).
    - The token's scope caps the tool list.

    Streamable HTTP at `/mcp` comes later. Prior art: https://www.home-assistant.io/integrations/mcp_server/ , https://github.com/grafana/mcp-grafana and https://github.com/portainer/portainer-mcp
7. **Claude Code skill and plugin** (L5, S). A `cashpilot-operator` skill in `contrib/agents/` with the same guardrails, tested against the demo seed (`scripts/ui_demo_seed.py`).
8. **"Copy as CLI" and "Copy as curl"** on every action menu, plus "Equivalent command" in the deploy and proxy dialogs (L5, M). The single `api()` helper (`app.js:14-38`) records the last call with secrets masked. A route-to-command map exported by the server builds the string, so it cannot drift. Settings > API & CLI lists the last 10 actions as commands.

## 7. Out of scope and open questions

**Out of scope**

- Any frontend framework rewrite.
- Creating, deleting or moving node identities and keystores from the UI, beyond restoring into an empty volume behind a typed confirm.
- Changing router settings for the user, except UPnP/NAT-PMP where the router offers it, which stays opt-in.
- Mobile-specific layouts.
- Desktop and Android companion changes. They should reuse the CLI and API vocabulary later.

**Open questions**

1. **Vendor reach hosts.** Do we curate `docker.egress` by hand per service, or seed it from Activity and have a maintainer review it? Neither is fully reliable alone.
2. **IP type lookup.** A third-party ASN lookup leaks the exit IP to that service. Do we prefer an offline ASN database shipped in the image?
3. **Token storage.** bcrypt makes per-request checks slow. Do we use a fast keyed hash (HMAC with the secret key) for tokens instead?
4. **Generated vs hand-written MCP tools.** Generating them from the schema is complete but noisy. Do we start with a curated set of about 15 tools?
5. **Palette vs list keys.** Shift+R and `x` could surprise users. Do we ship list keys off by default, with a setting, for one release? (Section 4 assumes yes.)
6. **WireGuard on the box.** Do all supported hosts load the `wireguard` kernel module, or do we need a userspace fallback?
7. **Serving `/llms.txt` and the schema from the running app.** Is that acceptable on installs exposed behind a reverse proxy? Our proposal is owner auth for the schema, while `llms.txt` stays public because it contains no instance data.
8. **One-click first login.** Is a `#token=` fragment link worth having, given that it still lands in browser history until `replaceState` runs? Or is `cashpilot setup-token` enough?

## Mockups

Each mockup is a self-contained HTML page in the default dark theme, with fake data only, rendered at 1440 px plus a 390 px phone view. Open the HTML file for the numbered notes and their citations. The CLI output shown in every mockup is proposed; no `cashpilot` CLI exists yet. "Copy as CLI" buttons ship in wave 3 (L5).

### M1. Proxies & VPNs page and Add egress wizard

The egress list with the box's own IP first, the paste-many dialog with per-line errors, the vendor reach and IP-type test result, and the Tailscale exit-node picker (X3, N5, N6, X4, X19). Source: [m1.html](ux-mockups/m1.html).

![M1 page](ux-mockups/m1-page.png)
![M1 empty state](ux-mockups/m1-empty.png)
![M1 paste dialog](ux-mockups/m1-paste.png)
![M1 test result](ux-mockups/m1-test.png)
![M1 Tailscale picker](ux-mockups/m1-tailscale.png)
![M1 terminal](ux-mockups/m1-cli.png)
![M1 phone](ux-mockups/m1-mobile.png)

### M2. Actionable Placement grid

Glyph cells, egress sub-columns, the account-off row, a pending link chip, a cell popover with actions, and prefilled "place a copy" (X2a, X2b, N7, N10, N11, X21). Source: [m2.html](ux-mockups/m2.html).

![M2 grid](ux-mockups/m2-grid.png)
![M2 popover](ux-mockups/m2-popover.png)
![M2 place a copy](ux-mockups/m2-place.png)
![M2 terminal](ux-mockups/m2-cli.png)
![M2 phone](ux-mockups/m2-mobile.png)

### M3. Command palette

Cmd+K with fuzzy actions, step-by-step box choice, a confirm with a plan, and the `?` overlay generated from the same registry (X1, N14). Sources: [m3.html](ux-mockups/m3.html), [m3-mobile.html](ux-mockups/m3-mobile.html).

![M3 palette](ux-mockups/m3-screen1.png)
![M3 box step and plan](ux-mockups/m3-screen2.png)
![M3 other actions](ux-mockups/m3-screen3.png)
![M3 shortcut overlay](ux-mockups/m3-screen4.png)
![M3 terminal](ux-mockups/m3-screen5.png)
![M3 phone](ux-mockups/m3-mobile.png)

### M4. Add a box

Detected addresses with a loopback warning, complete compose / docker run / Unraid blocks, and a live "waiting for heartbeat" checklist with fixes (N8, X10). Sources: [m4.html](ux-mockups/m4.html), [m4-mobile.html](ux-mockups/m4-mobile.html).

![M4 entry point](ux-mockups/m4-screen1.png)
![M4 address step](ux-mockups/m4-screen2.png)
![M4 install step](ux-mockups/m4-screen3.png)
![M4 checklist](ux-mockups/m4-screen4.png)
![M4 no heartbeat](ux-mockups/m4-screen5.png)
![M4 terminal](ux-mockups/m4-screen6.png)
![M4 phone](ux-mockups/m4-mobile.png)

### M5. One findings list

Grouped Needs attention with typed actions, the bell showing the same list, a bulk redeploy that stops on the first failure, and snooze with undo (N9, N19, X14). Source: [m5.html](ux-mockups/m5.html).

![M5 full page](ux-mockups/m5-full.png)
![M5 phone](ux-mockups/m5-mobile.png)

### M6. Keyboard-first wizard

Checkbox cards, one auto-ticked "Deploy to" bar, credentials reused for balances, inline preflight, and streamed deploy progress (N4, X11, X12). Source: [m6.html](ux-mockups/m6.html).

![M6 full page](ux-mockups/m6-full.png)
![M6 phone](ux-mockups/m6-mobile.png)

### M7. API & CLI settings

Scoped tokens shown once, terminal install, agent setup (agents.md, llms.txt, MCP), and the last actions as commands (X7, N13, X17, L5). Source: [m7.html](ux-mockups/m7.html).

![M7 first screen](ux-mockups/m7-fold.png)
![M7 full page](ux-mockups/m7-full.png)
![M7 phone](ux-mockups/m7-mobile.png)

### M8. Safe confirm

A remove dialog that defaults to keeping data and needs the slug typed to delete, a stateful Stop with "Start again", and a redeploy diff (N3, X22). Source: [m8.html](ux-mockups/m8.html).

![M8 first screen](ux-mockups/m8-fold.png)
![M8 full page](ux-mockups/m8-full.png)
![M8 phone](ux-mockups/m8-mobile.png)
