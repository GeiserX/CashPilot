# Three UI proposals for CashPilot

The current web UI looks generated: violet-tinted borders, rose and cyan gradients, glows, letter avatars, pill badges, and a card around every block. It also hides what matters. The dashboard gives "Active Services 10" the same weight as the balance, and a stopped container shows as "Running 2x".

Three branches each restyle every page against the same seeded demo data (three fake machines, eight services, one exited IPRoyal copy, one pending payout question). The screenshots below are full-page, dark theme, 1440 px wide, plus the dashboard at 390 px.

| Proposal | Branch | Pitch |
|---|---|---|
| Calm | `ui/proposal-calm` | A quiet app with one blue. Each page opens with a sentence, and detail stays folded until asked for. |
| Ledger | `ui/proposal-ledger` | A bank statement. One big "earned to date" figure, then a list of what needs you, then a plain money table. Amber is the only colour. |
| Console | `ui/proposal-console` | An operator console. Problems first, a service by machine placement grid, dense mono values, top bar instead of a sidebar. |

The baseline screenshots live on `ui/unslop-baseline`.

## Recommendation: Calm, with three ideas grafted from the others

Calm is the only proposal where every page got a new structure, not just new colours. Settings leads with the two expired credentials and folds the ten healthy ones. Payouts shows the 8 deployed services instead of 52 rows. Fleet folds power settings under each machine. The service modal folds the deploy form once a service runs. The text is the largest of the three (15 px root), and it needed no test re-pins. It scores highest (50 of 60).

Its weak spot is the dashboard. It hides per-service earnings and shows no money figure beyond the balance. Ledger does that part better, so graft these:

1. **From Ledger: the "Next payout" column and cash-out items.** "$1.43 to go, minimum $10.00, about 8 days" and "Ready to cash out" answer the question the app exists for. Add "MystNodes can be cashed out" to Calm's health line. Ledger also fixed two bugs that are on main today: "Next payout" reads `--` on every row because it reads the wrong field, and clicking an expandable dashboard row throws. Ship those two fixes to main on their own, whichever design wins.
2. **From Console: the placement grid** (one row per service, one column per machine, a state square per copy, an "up of total" count). It is the fastest way to see where a failure sits. It fits on Calm's Machines page, above the machine list.
3. **From Console: the exit code next to a stopped container** ("iproyal exited, exit code 137") on the Machines page.

Before any of them ships, fix the backend bug all three made more visible. [`app/main.py:1902`](../app/main.py) counts a pending payout alert as a collector failure, so Traffmonetizer shows "can't read balance" in every design.

## Scores

Each criterion is out of 10, total out of 60. "Cost to ship" is scored so that higher means cheaper.

| Criterion | Calm | Ledger | Console |
|---|---|---|---|
| Slop removed | 8 | 9 | 8 |
| First glance: how much, what is broken, what needs me | 8 | 8 | 7 |
| Legibility and contrast | 9 | 8 | 6 |
| Consistency across pages | 9 | 7 | 7 |
| Mobile | 8 | 8 | 5 |
| Cost to ship | 8 | 6 | 7 |
| **Total** | **50** | **46** | **40** |

Contrast of the muted text on its page background, computed from each branch's tokens: Calm `#9a9286` on `#191816` is 5.8:1, Ledger `#908d87` on `#141517` is 5.5:1, Console `#8d949d` on `#15171a` is 5.9:1. All three pass WCAG AA (4.5:1). Legibility differs by size, and Console is the smallest. It sets body text at 13 px and labels at 11 px in a condensed face.

## Calm

**Pitch.** A quiet app on a warm neutral dark background with one blue. Every page opens with a plain sentence that says how much you made and what is wrong. Technical detail stays folded until you ask for it.

**Principles.**

- Colour is state only: blue means act here, green running, amber look at this, red broken.
- A sentence instead of a row of tiles: "$34.32 in your accounts", "3 of 3 machines online", "8 of 52 services deployed".
- One blue primary button per page.
- One fold style everywhere: technical columns, the deploy form of a running service, power settings, healthy credentials, environment variables.
- Only three things get a tinted surface: the health line, the payout question and the warnings.
- Status is a dot and a word. A partial failure is named: "1 of 2 running".
- Plain nav labels: Overview, Services, Machines, Payouts, Settings, Add a service.

#### Dashboard

| Baseline | Calm |
|---|---|
| ![Baseline dashboard](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/unslop-baseline/docs/images/ui-proposals/baseline/dashboard.png) | ![Calm dashboard](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/proposal-calm/docs/images/ui-proposals/calm/dashboard.png) |

#### Dashboard, mobile 390 px

| Baseline | Calm |
|---|---|
| ![Baseline dashboard, mobile 390 px](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/unslop-baseline/docs/images/ui-proposals/baseline/dashboard-mobile.png) | ![Calm dashboard, mobile 390 px](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/proposal-calm/docs/images/ui-proposals/calm/dashboard-mobile.png) |

#### Catalog

| Baseline | Calm |
|---|---|
| ![Baseline catalog](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/unslop-baseline/docs/images/ui-proposals/baseline/catalog.png) | ![Calm catalog](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/proposal-calm/docs/images/ui-proposals/calm/catalog.png) |

#### Service detail (Honeygain)

| Baseline | Calm |
|---|---|
| ![Baseline service detail (honeygain)](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/unslop-baseline/docs/images/ui-proposals/baseline/service_detail.png) | ![Calm service detail (honeygain)](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/proposal-calm/docs/images/ui-proposals/calm/service_detail.png) |

#### Fleet

| Baseline | Calm |
|---|---|
| ![Baseline fleet](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/unslop-baseline/docs/images/ui-proposals/baseline/fleet.png) | ![Calm fleet](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/proposal-calm/docs/images/ui-proposals/calm/fleet.png) |

#### Payouts

| Baseline | Calm |
|---|---|
| ![Baseline payouts](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/unslop-baseline/docs/images/ui-proposals/baseline/payouts.png) | ![Calm payouts](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/proposal-calm/docs/images/ui-proposals/calm/payouts.png) |

#### Settings

| Baseline | Calm |
|---|---|
| ![Baseline settings](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/unslop-baseline/docs/images/ui-proposals/baseline/settings.png) | ![Calm settings](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/proposal-calm/docs/images/ui-proposals/calm/settings.png) |

#### Setup, step 1

| Baseline | Calm |
|---|---|
| ![Baseline setup, step 1](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/unslop-baseline/docs/images/ui-proposals/baseline/setup.png) | ![Calm setup, step 1](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/proposal-calm/docs/images/ui-proposals/calm/setup.png) |


| Criterion | Score | Why |
|---|---|---|
| Slop removed | 8 | Gradients, glow, violet, letter avatars, badge soup and uppercase labels are gone. The sidebar keeps its decorative icons, and the tinted blocks have 12 px rounded corners, so some card feel stays. |
| First glance | 8 | "$34.32 in your accounts", then "3 things need a look", then the payout question. Per-service earnings are hidden: the table shows balance and last change only. |
| Legibility | 9 | 15 px root, the largest text of the three; muted text 5.8:1. |
| Consistency | 9 | Every page opens the same way (heading, sentence, sections) and uses the same fold. |
| Mobile | 8 | Clean, and the balance column survives. No earnings per row, and "Outside CashPilot" wraps on the Grass row. |
| Cost to ship | 8 | 21 files, no test re-pins. Risks: technical columns rely on CSS `:has()`, light theme not reviewed, full test suite only run until the first git-dependent failure. |

**Flaws seen in the screenshots.**

- Dashboard: Grass still shows its points twice ("32308.51 GRASS" over "32308.5052 GRASS"), on desktop and on mobile. Ledger and Console fixed this.
- Dashboard: the chart bars are the brand blue, the colour that is meant to mean "act here".
- Dashboard: the health line and the payout block are about 760 px wide on a 1040 px column, so the right third of the top of the page is empty.
- Dashboard: no "ready to cash out" item, although MystNodes and Repocket are over their minimum (Ledger lists both).
- Machines: the stopped iproyal is red ("iproyal exited"), while the dashboard shows the same fault in amber ("1 of 2 running").
- Machines: the running-costs section still lists every machine a second time.
- Services: "Manage" and "Deploy" are buttons, "Visit" is plain text, so the right edge of the list is ragged.
- Setup: step 1 is better than the baseline, but the selected tiles are still bordered cards with icons.
- Login keeps a bordered card, the only page that does.

## Ledger

**Pitch.** A bank statement for passive income. The page opens on one figure, earned to date. Next comes a list of what needs your hand, then a plain table with right-aligned money columns. Amber is the only colour, and it marks only what needs action.

**Principles.**

- The money is the interface: "Earned to date" (balance plus confirmed payouts) and a five-line statement beside it.
- Colour means action. Graphite ground, warm-white ink, amber only on things that need a decision or a fix.
- Rules, not boxes: hairlines between sections, no cards, shadows, gradients or glow, 3 px radius on controls only.
- Status reports the worst case: "1 of 2 exited" in amber.
- Tabular, right-aligned figures. Unpriced points are written once in their own unit with "Points, not priced".
- Sentence-case labels and no decorative icons.
- The table holds what you own, the attention list holds what you must do, both from the same payload.

#### Dashboard

| Baseline | Ledger |
|---|---|
| ![Baseline dashboard](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/unslop-baseline/docs/images/ui-proposals/baseline/dashboard.png) | ![Ledger dashboard](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/proposal-ledger/docs/images/ui-proposals/ledger/dashboard.png) |

#### Dashboard, mobile 390 px

| Baseline | Ledger |
|---|---|
| ![Baseline dashboard, mobile 390 px](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/unslop-baseline/docs/images/ui-proposals/baseline/dashboard-mobile.png) | ![Ledger dashboard, mobile 390 px](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/proposal-ledger/docs/images/ui-proposals/ledger/dashboard-mobile.png) |

#### Catalog

| Baseline | Ledger |
|---|---|
| ![Baseline catalog](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/unslop-baseline/docs/images/ui-proposals/baseline/catalog.png) | ![Ledger catalog](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/proposal-ledger/docs/images/ui-proposals/ledger/catalog.png) |

#### Service detail (Honeygain)

| Baseline | Ledger |
|---|---|
| ![Baseline service detail (honeygain)](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/unslop-baseline/docs/images/ui-proposals/baseline/service_detail.png) | ![Ledger service detail (honeygain)](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/proposal-ledger/docs/images/ui-proposals/ledger/service_detail.png) |

#### Fleet

| Baseline | Ledger |
|---|---|
| ![Baseline fleet](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/unslop-baseline/docs/images/ui-proposals/baseline/fleet.png) | ![Ledger fleet](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/proposal-ledger/docs/images/ui-proposals/ledger/fleet.png) |

#### Payouts

| Baseline | Ledger |
|---|---|
| ![Baseline payouts](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/unslop-baseline/docs/images/ui-proposals/baseline/payouts.png) | ![Ledger payouts](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/proposal-ledger/docs/images/ui-proposals/ledger/payouts.png) |

#### Settings

| Baseline | Ledger |
|---|---|
| ![Baseline settings](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/unslop-baseline/docs/images/ui-proposals/baseline/settings.png) | ![Ledger settings](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/proposal-ledger/docs/images/ui-proposals/ledger/settings.png) |

#### Setup, step 1

| Baseline | Ledger |
|---|---|
| ![Baseline setup, step 1](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/unslop-baseline/docs/images/ui-proposals/baseline/setup.png) | ![Ledger setup, step 1](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/proposal-ledger/docs/images/ui-proposals/ledger/setup.png) |


| Criterion | Score | Why |
|---|---|---|
| Slop removed | 9 | The most thorough. No icons in the nav, no cards anywhere, plain catalog table, text links in the footer. Only the brand mark keeps a gradient, because a test pins it. |
| First glance | 8 | The best money answer ("$59.32 earned to date", "Next payout: $1.43 to go, about 8 days"). The attention list is complete but long: six amber rows push the services table below 840 px. |
| Legibility | 8 | 14.5 px root, muted text 5.5:1, IBM Plex with tabular figures. |
| Consistency | 7 | Dashboard, catalog and fleet were rethought. Settings and payouts are the baseline layout with the cards removed. |
| Mobile | 8 | Keeps balance and the CPU and host line under each name; restart and logs are reachable only through the attention list. |
| Cost to ship | 6 | New client-side logic (30-day sum, payout ETA, earned to date) that should move to the server, two re-pinned tests, about 800 lines of old CSS overridden instead of replaced. It also fixed two real bugs, which should ship anyway. |

**Flaws seen in the screenshots.**

- Dashboard: two big numbers disagree at a glance. The top bar says $34.32 and the hero says $59.32. The note under the hero explains it, but only once you read it.
- Dashboard: the payout row reads "traffmonetizer: did you get paid?" with the raw lowercase slug, while every other row uses the display name.
- Dashboard: amber is on every attention row, the Yes button, the Restart button and both "Ready to cash out" links. When everything is amber, the one exited container does not stand out.
- Dashboard: running services have grey dots, so a healthy service and an unknown one look the same.
- Service detail: for a running service the full deploy form (email, password, device name, machine checkboxes) is still open below the facts. The modal is 1,562 px tall, almost the baseline's 1,602.
- Payouts: the warning panel has an "In use 1" group heading inside it for a single row, and "Held by the service" appears twice per row (model column and address column).
- Settings: the update error ("Could not read update state") is still grey body text, not styled as an error.
- Catalog: no earnings estimate column, although the data exists (Console shows it).
- Nav: Fleet is last, after Settings.

## Console

**Pitch.** An operator console. The dashboard opens on what is broken and who must act, then shows where each service runs on each machine. Colour only ever means ok, warn or fail.

**Principles.**

- Colour carries state and nothing else; buttons and links are drawn in the text colour.
- Problems come first: one row per problem with a tag (Down, No reading, Paid?), the service, the machine, why, and the button that fixes it.
- A service by machine placement grid is the memorable element.
- Sections instead of cards, 2 px radius on controls only.
- Dense and keyboard-driven: a 44 px top bar replaces the sidebar, `g` plus a letter jumps to a page, `/` searches, base text 13 px.
- Monospace for values and ids only; UI text in IBM Plex Sans Condensed.
- "1 of 2 up" in red instead of "Running 2x".

#### Dashboard

| Baseline | Console |
|---|---|
| ![Baseline dashboard](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/unslop-baseline/docs/images/ui-proposals/baseline/dashboard.png) | ![Console dashboard](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/proposal-console/docs/images/ui-proposals/console/dashboard.png) |

#### Dashboard, mobile 390 px

| Baseline | Console |
|---|---|
| ![Baseline dashboard, mobile 390 px](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/unslop-baseline/docs/images/ui-proposals/baseline/dashboard-mobile.png) | ![Console dashboard, mobile 390 px](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/proposal-console/docs/images/ui-proposals/console/dashboard-mobile.png) |

#### Catalog

| Baseline | Console |
|---|---|
| ![Baseline catalog](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/unslop-baseline/docs/images/ui-proposals/baseline/catalog.png) | ![Console catalog](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/proposal-console/docs/images/ui-proposals/console/catalog.png) |

#### Service detail (Honeygain)

| Baseline | Console |
|---|---|
| ![Baseline service detail (honeygain)](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/unslop-baseline/docs/images/ui-proposals/baseline/service_detail.png) | ![Console service detail (honeygain)](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/proposal-console/docs/images/ui-proposals/console/service_detail.png) |

#### Fleet

| Baseline | Console |
|---|---|
| ![Baseline fleet](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/unslop-baseline/docs/images/ui-proposals/baseline/fleet.png) | ![Console fleet](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/proposal-console/docs/images/ui-proposals/console/fleet.png) |

#### Payouts

| Baseline | Console |
|---|---|
| ![Baseline payouts](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/unslop-baseline/docs/images/ui-proposals/baseline/payouts.png) | ![Console payouts](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/proposal-console/docs/images/ui-proposals/console/payouts.png) |

#### Settings

| Baseline | Console |
|---|---|
| ![Baseline settings](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/unslop-baseline/docs/images/ui-proposals/baseline/settings.png) | ![Console settings](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/proposal-console/docs/images/ui-proposals/console/settings.png) |

#### Setup, step 1

| Baseline | Console |
|---|---|
| ![Baseline setup, step 1](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/unslop-baseline/docs/images/ui-proposals/baseline/setup.png) | ![Console setup, step 1](https://raw.githubusercontent.com/GeiserX/CashPilot/ui/proposal-console/docs/images/ui-proposals/console/setup.png) |


| Criterion | Score | Why |
|---|---|---|
| Slop removed | 8 | No gradients, glow, violet, avatars or badge pills. Mono on every number becomes its own decoration, and the footer shortcut hint is chrome nobody asked for. |
| First glance | 7 | The best "what is broken": the attention list is the first thing on the page and the placement grid shows box-c in red. Money is the weakest of the three. The $34.32 balance sits in a small strip under the attention list, at the same size as "Containers up 10", which is the tile problem again. |
| Legibility | 6 | Colour contrast is fine at 5.9:1, but the type is small. Body text is 13 px and labels are 11 px in a condensed face. "No known expiry" in Settings is about 10 px. |
| Consistency | 7 | The app pages match each other closely. Login and onboarding are a bare form in the upper-left third of an empty screen, which looks unfinished. |
| Mobile | 5 | The services table scrolls sideways and the action icons are cut off at the right edge. Six nav tabs squeeze into one line. |
| Cost to ship | 7 | Keeps all 11 columns so few tests move, but removing the sidebar and adding global key handlers is the largest structural change (1,256 lines deleted). |

**Flaws seen in the screenshots.**

- Dashboard: the services table keeps all 11 columns. GPU and Payout are "--" on every row, as in the baseline.
- Dashboard: Grass shows "32308.51 GRASS", unrounded, in a column of dollar amounts.
- Payouts: all 52 rows are listed; 44 of them are "not deployed".
- Catalog: platforms are raw slugs ("browser-extension, macos, ios"), and the Needs column fills empty cells with "nothing special".
- Fleet: the running-costs section lists each machine a second time below the machine table.
- Setup: step 1 is four small tiles in a row and a lone Next button, with 70% of the screen empty.
- Login and onboarding: no vertical centring, no frame, small text; the least finished pages in any proposal.

## What is left to ship the winner

1. **Fix the backend first.** [`app/main.py:1902`](../app/main.py) builds `alert_slugs` from every alert kind except notice and container, so a pending payout marks the service "can't read balance". One line; it ships on its own.
2. **Ship Ledger's two row bugs to main on their own.** The dashboard "Next payout" column reads `svc.cashout` from `/api/services/deployed`, which never carries the minimum, so it is `--` everywhere. Clicking an expandable row throws "Cannot read properties of undefined (reading 'closest')".
3. **Graft into Calm:** the Next payout column and cash-out items from Ledger (computed on the server, not from the 30-day history in the browser); the placement grid and exit codes from Console on the Machines page.
4. **Fix Calm's own flaws:** show Grass once in its unit; give the chart a neutral grey so blue keeps meaning "act"; use amber for a stopped copy on both Overview and Machines; let the health line and payout block use the full column; make Visit a button like Deploy.
5. **Fold the stylesheet.** All three proposals append a new layer to the old 2,200-line [`style.css`](../app/static/css/style.css). Delete the overridden rules so the file says what the app looks like.
6. **Light theme.** Tokens are set and the contrast check passes (120 of 120), but nobody has looked at a light screenshot.
7. **Pages that only got the token pass:** setup steps 2 to 4, the credential, claim and logs modals, the isolation report, the notification dropdown. About 150 inline styles remain in `app.js`.
8. **Run the full test suite** in a checkout with `.git`; Calm stopped at the first git-dependent failure.
9. **CashPilot-Desktop** mirrors this UI. Its renderer needs the same pass, and the deploy-form markup change needs a note in the PR.
