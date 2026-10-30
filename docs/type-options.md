# Type options for the web UI

The Console redesign has two type problems. It sets all UI text in IBM Plex Sans Condensed, which keeps the full letter height and narrows the letters, so every line reads tall and tight. And the text is small: body text is 14px and labels go down to 12px.

Each option below fixes both. It swaps the face for a regular-width one and raises the size scale, and every face is shown at two sizes, a 15px body and a 16px body. All four faces are free under the SIL Open Font License and can be self-hosted.

## Pick

**IBM Plex Sans at 16px.** Plex Sans fixes the tall look with one font token and keeps IBM Plex Mono, the number face the Console design is built around, so every figure keeps its shape. At 16px the smallest text is 14px, the size body text is today, and every page still fits at 1440 and at 390. 15px is the safer step if we want to keep more rows on screen. Geist is the runner-up face if we want a fresher look.

Whichever we pick, two fixes go with it, both already on every branch. The chart font now follows `--font-mono`, and the catalog estimate wraps on phones.

## Branches

| Face | 15px body | 16px body | UI face | Number face |
|---|---|---|---|---|
| Current, 14px | `main` | | IBM Plex Sans Condensed | IBM Plex Mono |
| 1. IBM Plex Sans | `ui/type-plex-sans` | `ui/type-plex-sans-16` | IBM Plex Sans | IBM Plex Mono, unchanged |
| 2. Inter | `ui/type-inter` | `ui/type-inter-16` | Inter | JetBrains Mono |
| 3. Geist | `ui/type-geist` | `ui/type-geist-16` | Geist | Geist Mono |
| 4. System | `ui/type-system` | `ui/type-system-16` | system-ui: SF Pro on macOS, Segoe UI on Windows | ui-monospace: SF Mono or Menlo, Consolas |

Each `-16` branch is the 15px branch plus one commit that changes the size tokens.

## What every option changes

The same edits on each branch, nothing else:

- `--font-ui` and `--font-mono` in [`app/static/css/style.css`](../app/static/css/style.css).
- The size scale, every token scaled by the same ratio as the body, rounded to whole pixels:

  | Token | Used for | Current | 15px | 16px |
  |---|---|---|---|---|
  | `--fs-1` | keys, counts, smallest meta | 12px | 13px | 14px |
  | `--fs-2` | labels, table heads, secondary lines | 13px | 14px | 15px |
  | `--fs-3` | body, table cells, buttons | **14px** | **15px** | **16px** |
  | `--fs-4` | section and modal titles | 16px | 17px | 18px |
  | `--fs-5` | page titles | 20px | 21px | 23px |
  | `--fs-figure` | today and this month | 24px | 26px | 27px |
  | `--fs-money` | the balance | 34px | 36px | 39px |

  The root size follows `--fs-3`, so the few sizes set in rem grow with it. The chart axis labels go from 11px to 12px.
- Body `line-height` from 1.45 to 1.4, the same on every branch.
- The Google Fonts link in [`base.html`](../app/templates/base.html), [`auth.html`](../app/templates/auth.html) and [`onboarding.html`](../app/templates/onboarding.html) loads the new families. The system option drops the link, so the page loads no web font at all.
- The "Earned per day" chart had `family: 'IBM Plex Mono'` written into [`app/static/js/app.js`](../app/static/js/app.js), so with any other font loaded its axis fell back to the browser's serif. The chart now reads `--font-mono` from the stylesheet.
- On phones the catalog's "Est. per month" cell may wrap, `.catalog-table .cat-est { white-space: normal; }`. Before that, the bigger type pushed the catalog 1 to 10px past the 390 edge, because "$0-500 / GPU-hour" never wrapped.

## Width and fit

Row width is the longest line in the dashboard's "Needs attention" list, measured in the running app at 1440. Fit means a script opened all eight mobile pages at 390, from login and onboarding through dashboard, catalog, setup, fleet, payouts and settings, and checked that none is wider than the screen. The desktop dashboard got the same check at 1440.

| Face | Size | Row width | vs today | 1440 | 390, all eight pages |
|---|---|---|---|---|---|
| Current | 14px | 662px | | fits | fits |
| 1. IBM Plex Sans | 15px | 786px | +19% | fits | fits |
| 1. IBM Plex Sans | 16px | 838px | +27% | fits | fits |
| 2. Inter | 15px | 826px | +25% | fits | fits |
| 2. Inter | 16px | 881px | +33% | fits | fits |
| 3. Geist | 15px | 797px | +20% | fits | fits |
| 3. Geist | 16px | 850px | +28% | fits | fits |
| 4. System | 15px | 798px | +21% | fits | fits |
| 4. System | 16px | 844px | +27% | fits | fits |

The three web mono faces, Plex Mono, JetBrains Mono and Geist Mono, are the same width at the same size, so the number columns take the same room whichever of them we pick. The mobile nav scrolls sideways at every size, as it does today. At 16px the mobile catalog gets longer because descriptions wrap onto more lines.

## 1. IBM Plex Sans

The UI face drops the condensed cut and nothing else about the look moves. The number face stays IBM Plex Mono, so every figure keeps its shape. It ties with Geist and the system font for the narrowest lines.

Row width 786px at 15px and 838px at 16px, against 662px today. Every page fits at both sizes.

Close-up of the dashboard header, 1:1 pixels:

**Current, 14px**

![1. IBM Plex Sans Current, 14px](type-options/current/dashboard-closeup.png)

**15px**

![1. IBM Plex Sans 15px](type-options/plex-sans/dashboard-closeup.png)

**16px**

![1. IBM Plex Sans 16px](type-options/plex-sans-16/dashboard-closeup.png)

| Page | Current, 14px | 15px | 16px |
|---|---|---|---|
| Dashboard | ![](type-options/current/dashboard.png) | ![](type-options/plex-sans/dashboard.png) | ![](type-options/plex-sans-16/dashboard.png) |
| Dashboard, mobile | ![](type-options/current/dashboard-mobile.png) | ![](type-options/plex-sans/dashboard-mobile.png) | ![](type-options/plex-sans-16/dashboard-mobile.png) |
| Fleet | ![](type-options/current/fleet.png) | ![](type-options/plex-sans/fleet.png) | ![](type-options/plex-sans-16/fleet.png) |
| Fleet, mobile | ![](type-options/current/fleet-mobile.png) | ![](type-options/plex-sans/fleet-mobile.png) | ![](type-options/plex-sans-16/fleet-mobile.png) |
| Payouts | ![](type-options/current/payouts.png) | ![](type-options/plex-sans/payouts.png) | ![](type-options/plex-sans-16/payouts.png) |
| Payouts, mobile | ![](type-options/current/payouts-mobile.png) | ![](type-options/plex-sans/payouts-mobile.png) | ![](type-options/plex-sans-16/payouts-mobile.png) |
| Catalog | ![](type-options/current/catalog.png) | ![](type-options/plex-sans/catalog.png) | ![](type-options/plex-sans-16/catalog.png) |
| Catalog, mobile | ![](type-options/current/catalog-mobile.png) | ![](type-options/plex-sans/catalog-mobile.png) | ![](type-options/plex-sans-16/catalog-mobile.png) |
| Settings, mobile | ![](type-options/current/settings-mobile.png) | ![](type-options/plex-sans/settings-mobile.png) | ![](type-options/plex-sans-16/settings-mobile.png) |
| Login | ![](type-options/current/login.png) | ![](type-options/plex-sans/login.png) | ![](type-options/plex-sans-16/login.png) |

## 2. Inter

Both faces change. Inter reads well at small sizes and has the largest lowercase letters of the four, so at the same size it looks the biggest. It is also the widest, about 4% wider than the others. JetBrains Mono has tall lowercase letters too, so the CPU, memory and disk figures look bigger, though they take the same width as the other mono faces. Inter is the face of a great many web apps, and it pulls the page furthest from the Console look.

Row width 826px at 15px and 881px at 16px, against 662px today. Every page fits at both sizes.

Close-up of the dashboard header, 1:1 pixels:

**Current, 14px**

![2. Inter Current, 14px](type-options/current/dashboard-closeup.png)

**15px**

![2. Inter 15px](type-options/inter/dashboard-closeup.png)

**16px**

![2. Inter 16px](type-options/inter-16/dashboard-closeup.png)

| Page | Current, 14px | 15px | 16px |
|---|---|---|---|
| Dashboard | ![](type-options/current/dashboard.png) | ![](type-options/inter/dashboard.png) | ![](type-options/inter-16/dashboard.png) |
| Dashboard, mobile | ![](type-options/current/dashboard-mobile.png) | ![](type-options/inter/dashboard-mobile.png) | ![](type-options/inter-16/dashboard-mobile.png) |
| Fleet | ![](type-options/current/fleet.png) | ![](type-options/inter/fleet.png) | ![](type-options/inter-16/fleet.png) |
| Fleet, mobile | ![](type-options/current/fleet-mobile.png) | ![](type-options/inter/fleet-mobile.png) | ![](type-options/inter-16/fleet-mobile.png) |
| Payouts | ![](type-options/current/payouts.png) | ![](type-options/inter/payouts.png) | ![](type-options/inter-16/payouts.png) |
| Payouts, mobile | ![](type-options/current/payouts-mobile.png) | ![](type-options/inter/payouts-mobile.png) | ![](type-options/inter-16/payouts-mobile.png) |
| Catalog | ![](type-options/current/catalog.png) | ![](type-options/inter/catalog.png) | ![](type-options/inter-16/catalog.png) |
| Catalog, mobile | ![](type-options/current/catalog-mobile.png) | ![](type-options/inter/catalog-mobile.png) | ![](type-options/inter-16/catalog-mobile.png) |
| Settings, mobile | ![](type-options/current/settings-mobile.png) | ![](type-options/inter/settings-mobile.png) | ![](type-options/inter-16/settings-mobile.png) |
| Login | ![](type-options/current/login.png) | ![](type-options/inter/login.png) | ![](type-options/inter-16/login.png) |

## 3. Geist

Both faces change, to one family whose sans and mono were drawn to match. It is compact and reads clean at small sizes. Geist came out in 2023 and its look is tied to Vercel's products.

Row width 797px at 15px and 850px at 16px, against 662px today. Every page fits at both sizes.

Close-up of the dashboard header, 1:1 pixels:

**Current, 14px**

![3. Geist Current, 14px](type-options/current/dashboard-closeup.png)

**15px**

![3. Geist 15px](type-options/geist/dashboard-closeup.png)

**16px**

![3. Geist 16px](type-options/geist-16/dashboard-closeup.png)

| Page | Current, 14px | 15px | 16px |
|---|---|---|---|
| Dashboard | ![](type-options/current/dashboard.png) | ![](type-options/geist/dashboard.png) | ![](type-options/geist-16/dashboard.png) |
| Dashboard, mobile | ![](type-options/current/dashboard-mobile.png) | ![](type-options/geist/dashboard-mobile.png) | ![](type-options/geist-16/dashboard-mobile.png) |
| Fleet | ![](type-options/current/fleet.png) | ![](type-options/geist/fleet.png) | ![](type-options/geist-16/fleet.png) |
| Fleet, mobile | ![](type-options/current/fleet-mobile.png) | ![](type-options/geist/fleet-mobile.png) | ![](type-options/geist-16/fleet-mobile.png) |
| Payouts | ![](type-options/current/payouts.png) | ![](type-options/geist/payouts.png) | ![](type-options/geist-16/payouts.png) |
| Payouts, mobile | ![](type-options/current/payouts-mobile.png) | ![](type-options/geist/payouts-mobile.png) | ![](type-options/geist-16/payouts-mobile.png) |
| Catalog | ![](type-options/current/catalog.png) | ![](type-options/geist/catalog.png) | ![](type-options/geist-16/catalog.png) |
| Catalog, mobile | ![](type-options/current/catalog-mobile.png) | ![](type-options/geist/catalog-mobile.png) | ![](type-options/geist-16/catalog-mobile.png) |
| Settings, mobile | ![](type-options/current/settings-mobile.png) | ![](type-options/geist/settings-mobile.png) | ![](type-options/geist-16/settings-mobile.png) |
| Login | ![](type-options/current/login.png) | ![](type-options/geist/login.png) | ![](type-options/geist-16/login.png) |

## 4. System

Both faces come from the operating system, and the page loads no web font. The Google Fonts links go away, and with them a request to Google on every page load of a self-hosted app. It is the fastest and the most private option. The cost is consistency. These screenshots show macOS, so SF Pro. Windows gets Segoe UI and Consolas, and Linux gets whatever the desktop ships.

Row width 798px at 15px and 844px at 16px, against 662px today. Every page fits at both sizes.

Close-up of the dashboard header, 1:1 pixels:

**Current, 14px**

![4. System Current, 14px](type-options/current/dashboard-closeup.png)

**15px**

![4. System 15px](type-options/system/dashboard-closeup.png)

**16px**

![4. System 16px](type-options/system-16/dashboard-closeup.png)

| Page | Current, 14px | 15px | 16px |
|---|---|---|---|
| Dashboard | ![](type-options/current/dashboard.png) | ![](type-options/system/dashboard.png) | ![](type-options/system-16/dashboard.png) |
| Dashboard, mobile | ![](type-options/current/dashboard-mobile.png) | ![](type-options/system/dashboard-mobile.png) | ![](type-options/system-16/dashboard-mobile.png) |
| Fleet | ![](type-options/current/fleet.png) | ![](type-options/system/fleet.png) | ![](type-options/system-16/fleet.png) |
| Fleet, mobile | ![](type-options/current/fleet-mobile.png) | ![](type-options/system/fleet-mobile.png) | ![](type-options/system-16/fleet-mobile.png) |
| Payouts | ![](type-options/current/payouts.png) | ![](type-options/system/payouts.png) | ![](type-options/system-16/payouts.png) |
| Payouts, mobile | ![](type-options/current/payouts-mobile.png) | ![](type-options/system/payouts-mobile.png) | ![](type-options/system-16/payouts-mobile.png) |
| Catalog | ![](type-options/current/catalog.png) | ![](type-options/system/catalog.png) | ![](type-options/system-16/catalog.png) |
| Catalog, mobile | ![](type-options/current/catalog-mobile.png) | ![](type-options/system/catalog-mobile.png) | ![](type-options/system-16/catalog-mobile.png) |
| Settings, mobile | ![](type-options/current/settings-mobile.png) | ![](type-options/system/settings-mobile.png) | ![](type-options/system-16/settings-mobile.png) |
| Login | ![](type-options/current/login.png) | ![](type-options/system/login.png) | ![](type-options/system-16/login.png) |

## How the screenshots were made

[`scripts/ui_demo_seed.py`](../scripts/ui_demo_seed.py) `--serve` with its invented demo data, then [`scripts/ui_screenshots.mjs`](../scripts/ui_screenshots.mjs) in dark mode at 1440x900 and 390x844, Google Chrome on macOS. All nine variants ran back to back on the same day, so the demo figures match. Click any thumbnail to open the full-size image.
