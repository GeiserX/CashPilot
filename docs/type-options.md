# Type options for the web UI

The Console redesign sets all UI text in IBM Plex Sans Condensed. A condensed face keeps the full letter height and narrows the letters, so every line reads tall and tight. The size scale is ordinary, 14px for body text and 12 to 20px for the rest, and so is the 1.45 line height. The face is the cause, so each option swaps the face and leaves the scale alone.

Four options, each on its own branch. All of them are free under the SIL Open Font License and can be self-hosted.

| Option | Branch | UI face | Number face |
|---|---|---|---|
| Current | `main` | IBM Plex Sans Condensed | IBM Plex Mono |
| 1. Plex Sans | `ui/type-plex-sans` | IBM Plex Sans | IBM Plex Mono, unchanged |
| 2. Inter | `ui/type-inter` | Inter | JetBrains Mono |
| 3. Geist | `ui/type-geist` | Geist | Geist Mono |
| 4. System | `ui/type-system` | system-ui: SF Pro on macOS, Segoe UI on Windows | ui-monospace: SF Mono, Consolas |

## What every option changes

The same three edits on each branch, nothing else:

- `--font-ui` and `--font-mono` in [`app/static/css/style.css`](../app/static/css/style.css).
- Body `line-height` from 1.45 to 1.4. The wider faces need a little less space between lines; this is the same on all four, so it does not favour any of them.
- The Google Fonts link in [`base.html`](../app/templates/base.html), [`auth.html`](../app/templates/auth.html) and [`onboarding.html`](../app/templates/onboarding.html) loads the new families. Option 4 drops the link, so the page loads no web font at all.

Every branch also fixes one bug the comparison found. The "Earned per day" chart had `family: 'IBM Plex Mono'` written into [`app/static/js/app.js`](../app/static/js/app.js), so with any other font loaded its axis fell back to the browser's serif. On the option branches the chart reads `--font-mono` from the stylesheet. That fix belongs on `main` whichever option wins.

The size scale, `--fs-1` to `--fs-money`, is unchanged. The wider faces already make 14px look bigger than it does now. Every shot below fits its width, 1440 or 390, with no horizontal overflow. The top nav on mobile scrolls sideways as it does today.

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
| Login | ![](type-options/current/login.png) | ![](type-options/plex-sans/login.png) | ![](type-options/inter/login.png) | ![](type-options/geist/login.png) | ![](type-options/system/login.png) |

## The options

### 1. IBM Plex Sans

The UI face drops the condensed cut and nothing else moves. The number face stays IBM Plex Mono, so every figure on the dashboard looks exactly as it does today.

This is the smallest change of the four, and the page still looks like the Console design. Of the four it adds the least width: the longest attention row ends at 1101px, against 1030px today, 1112px with Geist, 1120px with the system font and 1138px with Inter.

### 2. Inter with JetBrains Mono

Both faces change. Inter reads well at 12 to 14px, which is where most of this UI lives.

JetBrains Mono is the widest number face here, so the CPU, memory and disk figures grow more than anything else on the page. Inter is also the face of a great many web apps, and it pulls the page furthest from the Console look.

### 3. Geist with Geist Mono

Both faces change, to one family whose sans and mono were drawn to match.

It is compact. Geist Mono is the narrowest number face of the four, so the tables stay tight. Geist came out in 2023 and its look is tied to Vercel's products.

### 4. System font stack

Both faces come from the operating system and the page loads no web font. The Google Fonts links go away, and with them a request to Google on every page load of a self-hosted app.

It is the fastest and the most private option. The cost is consistency. These screenshots show macOS, so SF Pro and SF Mono. Windows gets Segoe UI and Consolas, and Linux gets whatever the desktop ships.

## Pick

**Option 1, IBM Plex Sans.** It fixes the tall look with one font token, keeps the number face that the Console design is built around, and leaves every figure on the page as it is now. Option 3, Geist, is the runner-up if we want a fresher look with tighter tables.

Whichever we pick, we should then self-host the two woff2 files instead of loading them from Google Fonts, and ship the chart font fix to `main`.

## How the screenshots were made

[`scripts/ui_demo_seed.py`](../scripts/ui_demo_seed.py) `--serve` with its invented demo data, then [`scripts/ui_screenshots.mjs`](../scripts/ui_screenshots.mjs) in dark mode at 1440x900 and 390x844, Google Chrome on macOS, one run per branch. The close-ups are crops of the dashboard shot.
