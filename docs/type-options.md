# Type options for the web UI

The Console redesign has two type problems. It sets all UI text in IBM Plex Sans Condensed, which keeps the full letter height and narrows the letters, so every line reads tall and tight. And the text is small: body text is 14px and labels go down to 12px.

Each option fixes both. It swaps the face for a regular-width one and raises the whole size scale one step, body text from 14px to 15px.

Four options, each on its own branch. All of them are free under the SIL Open Font License and can be self-hosted.

| Option | Branch | UI face | Number face |
|---|---|---|---|
| Current | `main` | IBM Plex Sans Condensed | IBM Plex Mono |
| 1. Plex Sans | `ui/type-plex-sans` | IBM Plex Sans | IBM Plex Mono, unchanged |
| 2. Inter | `ui/type-inter` | Inter | JetBrains Mono |
| 3. Geist | `ui/type-geist` | Geist | Geist Mono |
| 4. System | `ui/type-system` | system-ui: SF Pro on macOS, Segoe UI on Windows | ui-monospace: SF Mono or Menlo, Consolas |

## What every option changes

The same edits on each branch, nothing else:

- `--font-ui` and `--font-mono` in [`app/static/css/style.css`](../app/static/css/style.css).
- The size scale, one step up on every token:

  | Token | Used for | Before | After |
  |---|---|---|---|
  | `--fs-1` | keys, counts, smallest meta | 12px | 13px |
  | `--fs-2` | labels, table heads, secondary lines | 13px | 14px |
  | `--fs-3` | body, table cells, buttons | **14px** | **15px** |
  | `--fs-4` | section and modal titles | 16px | 17px |
  | `--fs-5` | page titles | 20px | 22px |
  | `--fs-figure` | today and this month | 24px | 26px |
  | `--fs-money` | the balance | 34px | 36px |

  The root size follows `--fs-3`, so the few sizes set in rem grow with it. The chart axis labels go from 11px to 12px.
- Body `line-height` from 1.45 to 1.4. The wider faces need a little less space between lines. It is the same on all four, so it does not favour any of them.
- The Google Fonts link in [`base.html`](../app/templates/base.html), [`auth.html`](../app/templates/auth.html) and [`onboarding.html`](../app/templates/onboarding.html) loads the new families. Option 4 drops the link, so the page loads no web font at all.

Every branch also fixes one bug the comparison found. The "Earned per day" chart had `family: 'IBM Plex Mono'` written into [`app/static/js/app.js`](../app/static/js/app.js), so with any other font loaded its axis fell back to the browser's serif. On the option branches the chart reads `--font-mono` from the stylesheet. That fix belongs on `main` whichever option wins.

## Does it still fit

Yes, with one fix. A script opened all eight mobile pages at 390px on every branch, from login and onboarding through dashboard, catalog, setup, fleet, payouts and settings, and compared the page width with the screen. On `main` all eight fit. With the bigger type, only the catalog overflowed, by 1 to 10px depending on the face: its "Est. per month" cell never wraps, and "$0-500 / GPU-hour" at 14px pushed the table past the edge. On phones that cell now wraps, `.catalog-table .cat-est { white-space: normal; }`, and all eight pages fit on all four branches. The top nav on mobile scrolls sideways, as it does today. The 1440 desktop shots fit with room to spare.

How much wider each face makes a line, measured in Chrome on the longest attention sentence of the dashboard:

| | Size | Sentence width | vs today |
|---|---|---|---|
| Current, Plex Sans Condensed | 14px | 662px | |
| 1. Plex Sans | 15px | 786px | +19% |
| 2. Inter | 15px | 812px | +23% |
| 3. Geist | 15px | 787px | +19% |
| 4. System, SF Pro on macOS | 15px | 787px | +19% |

The three web mono faces, Plex Mono, JetBrains Mono and Geist Mono, are exactly the same width at the same size, so the number columns take the same room whichever of them we pick.

## Close-up: dashboard header

Same crop of the dashboard on each branch, 1:1 pixels.

**Current**

![current](type-options/current/dashboard-closeup.png)

**1. Plex Sans**

![plex-sans](type-options/plex-sans/dashboard-closeup.png)

**2. Inter**

![inter](type-options/inter/dashboard-closeup.png)

**3. Geist**

![geist](type-options/geist/dashboard-closeup.png)

**4. System**

![system](type-options/system/dashboard-closeup.png)

## Dashboard, desktop, 1440 wide

| Current | 1. Plex Sans |
|---|---|
| ![](type-options/current/dashboard.png) | ![](type-options/plex-sans/dashboard.png) |

| 2. Inter | 3. Geist | 4. System |
|---|---|---|
| ![](type-options/inter/dashboard.png) | ![](type-options/geist/dashboard.png) | ![](type-options/system/dashboard.png) |

## Dashboard, mobile, 390 wide

| Current | 1. Plex Sans | 2. Inter | 3. Geist | 4. System |
|---|---|---|---|---|
| ![](type-options/current/dashboard-mobile.png) | ![](type-options/plex-sans/dashboard-mobile.png) | ![](type-options/inter/dashboard-mobile.png) | ![](type-options/geist/dashboard-mobile.png) | ![](type-options/system/dashboard-mobile.png) |

## Other pages

Click a cell to open the full-size image.

| Page | Current | 1. Plex Sans | 2. Inter | 3. Geist | 4. System |
|---|---|---|---|---|---|
| Fleet | ![](type-options/current/fleet.png) | ![](type-options/plex-sans/fleet.png) | ![](type-options/inter/fleet.png) | ![](type-options/geist/fleet.png) | ![](type-options/system/fleet.png) |
| Payouts | ![](type-options/current/payouts.png) | ![](type-options/plex-sans/payouts.png) | ![](type-options/inter/payouts.png) | ![](type-options/geist/payouts.png) | ![](type-options/system/payouts.png) |
| Catalog | ![](type-options/current/catalog.png) | ![](type-options/plex-sans/catalog.png) | ![](type-options/inter/catalog.png) | ![](type-options/geist/catalog.png) | ![](type-options/system/catalog.png) |
| Catalog, mobile | ![](type-options/current/catalog-mobile.png) | ![](type-options/plex-sans/catalog-mobile.png) | ![](type-options/inter/catalog-mobile.png) | ![](type-options/geist/catalog-mobile.png) | ![](type-options/system/catalog-mobile.png) |
| Fleet, mobile | ![](type-options/current/fleet-mobile.png) | ![](type-options/plex-sans/fleet-mobile.png) | ![](type-options/inter/fleet-mobile.png) | ![](type-options/geist/fleet-mobile.png) | ![](type-options/system/fleet-mobile.png) |
| Payouts, mobile | ![](type-options/current/payouts-mobile.png) | ![](type-options/plex-sans/payouts-mobile.png) | ![](type-options/inter/payouts-mobile.png) | ![](type-options/geist/payouts-mobile.png) | ![](type-options/system/payouts-mobile.png) |
| Settings, mobile | ![](type-options/current/settings-mobile.png) | ![](type-options/plex-sans/settings-mobile.png) | ![](type-options/inter/settings-mobile.png) | ![](type-options/geist/settings-mobile.png) | ![](type-options/system/settings-mobile.png) |
| Login | ![](type-options/current/login.png) | ![](type-options/plex-sans/login.png) | ![](type-options/inter/login.png) | ![](type-options/geist/login.png) | ![](type-options/system/login.png) |

## The options

### 1. IBM Plex Sans

The UI face drops the condensed cut and nothing else moves. The number face stays IBM Plex Mono, so every figure on the dashboard looks exactly as it does today.

This is the smallest change of the four, and the page still looks like the Console design. It ties with Geist and the system font for the narrowest lines.

### 2. Inter with JetBrains Mono

Both faces change. Inter reads well at 13 to 15px, which is where most of this UI lives.

It is the widest of the four, about 3% wider than the others. JetBrains Mono has tall lowercase letters, so the CPU, memory and disk figures look bigger than with the other mono faces, though they take the same width. Inter is also the face of a great many web apps, and it pulls the page furthest from the Console look.

### 3. Geist with Geist Mono

Both faces change, to one family whose sans and mono were drawn to match.

It is compact and reads clean at small sizes. Geist came out in 2023 and its look is tied to Vercel's products.

### 4. System font stack

Both faces come from the operating system and the page loads no web font. The Google Fonts links go away, and with them a request to Google on every page load of a self-hosted app.

It is the fastest and the most private option. The cost is consistency. These screenshots show macOS, so SF Pro and SF Mono. Windows gets Segoe UI and Consolas, and Linux gets whatever the desktop ships.

## Pick

**Option 1, IBM Plex Sans, at 15px.** It fixes the tall look with one font token, keeps the number face that the Console design is built around, and with the size step every figure is a little bigger without changing shape. Option 3, Geist, is the runner-up if we want a fresher look.

Whichever we pick, the chart font fix and the catalog wrap go with it. After that we should self-host the two woff2 files instead of loading them from Google Fonts.

If 15px still reads small, 16px is one more step on the same tokens. It would need a second look at the 390 tables.

## How the screenshots were made

[`scripts/ui_demo_seed.py`](../scripts/ui_demo_seed.py) `--serve` with its invented demo data, then [`scripts/ui_screenshots.mjs`](../scripts/ui_screenshots.mjs) in dark mode at 1440x900 and 390x844, Google Chrome on macOS, all five branches on the same day so the demo figures match. The close-ups are crops of the dashboard shot.
