// Measure, in a real browser, whether the UI can actually be READ.
// CashPilot-5ekm.
//
// The repo has thousands of tests and none of them would have caught this:
// the claim modal's "Go to Dashboard" button rendered as cyan #22d3ee text on
// its own green #22c55e background, underlined, because `.modal-body a`
// (specificity 0,1,1) outranked `.btn-success` (0,1,0). Every existing test
// reads values; none of them looks at the result.
//
// The obvious test -- asserting style.css contains ":not(.btn)" -- is worthless
// and this repo has already been bitten twice by tests matching their own
// prose. A string proves a rule was typed, not that a button is legible, and it
// would keep passing if a later rule re-broke the cascade.
//
// So this computes, from the browser's own getComputedStyle:
//   * the WCAG contrast ratio between each button's text and the background it
//     is actually painted on (walking ancestors through transparency), and
//   * whether a button is underlined, which for a filled control means the
//     link styling has leaked into it.
//
// The fixture is generated from the STYLESHEET'S OWN `.btn-*` classes, so a
// variant added next year is covered the day it is added rather than the day
// someone remembers to add it here.
//
//   ./scripts/legibility_check.sh
//
// Exits non-zero on an unreadable control, and exits non-zero if no browser is
// available -- "skipped" must never read as "passed".

import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(import.meta.dirname, "..");
const CSS = path.join(ROOT, "app", "static", "css", "style.css");
const PORT = process.env.CHROME_DEBUG_PORT || 9222;

// WCAG 2.1 minimum for normal text. Buttons carry the action, so if the label
// cannot be read the control cannot be used.
const MIN_CONTRAST = 4.5;

const css = fs.readFileSync(CSS, "utf8");

// Colour variants only. btn-sm / btn-lg are sizes and change no colour, so
// asserting on them would just duplicate the base .btn result.
const SIZES = new Set(["btn-sm", "btn-lg"]);
const variants = [...new Set([...css.matchAll(/^\.(btn-[a-z-]+)/gm)].map((m) => m[1]))]
  .filter((v) => !SIZES.has(v))
  .sort();

if (variants.length === 0) {
  console.error("FAIL  found no .btn-* variants in style.css -- the fixture would be empty");
  process.exit(1);
}

// Each variant is rendered twice: bare, and inside .modal-body. The modal case
// is the one that regressed, and it is exactly the context a crawl of the live
// pages would miss, because modal markup is injected by JS on demand.
const buttons = variants
  .map(
    (v) => `
      <div class="card" style="padding:16px;margin:8px">
        <button class="btn ${v}" data-probe="${v}|card">${v}</button>
      </div>
      <div class="modal-body" style="padding:16px;margin:8px">
        <button class="btn ${v}" data-probe="${v}|modal-body">${v}</button>
        <a href="#" class="btn ${v}" data-probe="${v}|modal-body-anchor">${v} as anchor</a>
      </div>`,
  )
  .join("");

const fixtureFor = (theme) => `<!DOCTYPE html><html${theme === "light" ? ' data-theme="light"' : ""}><head><meta charset="utf-8">
<link rel="stylesheet" href="file://${CSS}"></head>
<body>
  <div class="card" style="padding:16px;margin:8px">
    <button class="btn" data-probe="btn-base|card">base</button>
  </div>
  ${buttons}
  <div class="modal-body" style="padding:16px;margin:8px">
    <p data-probe-text="modal-prose">Prose with <a href="#" data-probe-link="modal-link">a real link</a> in it.</p>
  </div>

  <!-- Real components, populated as the app populates them. Buttons were only
       where the FIRST bug happened; the update banner then turned out to be
       pale blue on pale lavender in the light theme, because its colours were
       hardcoded for the dark one and had no counterpart. A check that only ever
       looked at .btn would have missed it entirely. -->
  <div class="update-banner">
    <span data-probe-fg="update-banner-text">CashPilot 1.23.2 is available - you are running 1.14.1.</span>
    <a href="#" data-probe-fg="update-banner-link">Release notes</a>
    <button type="button" data-probe-fg="update-banner-dismiss">&times;</button>
  </div>
</body></html>`;

// One file PER THEME, each with data-theme baked into <html> so the theme is
// in force before a single style is resolved.
//
// Toggling the attribute on a live page and re-measuring does not work in
// headless Chrome: the first getComputedStyle resolves and the later attribute
// change is not re-resolved, so the second theme silently reports the FIRST
// theme's values. That is what made this check pass locally and fail in CI --
// and, worse, what made a passing run meaningless. A fresh document per theme
// has no such state to go stale.
const fixturePaths = {};
for (const theme of ["dark", "light"]) {
  const fp = path.join(process.env.TMPDIR || "/tmp", `cashpilot-legibility-${theme}.html`);
  fs.writeFileSync(fp, fixtureFor(theme));
  fixturePaths[theme] = fp;
}

// ---------------------------------------------------------------------------
// This runs INSIDE the page. It reports measurements; it makes no judgements,
// so the thresholds stay here in one place rather than being scattered.
// ---------------------------------------------------------------------------
const AUDIT = (theme) => `((theme) => {
  const parse = (c) => {
    const m = c.match(/rgba?\\(([^)]+)\\)/);
    if (!m) return null;
    const p = m[1].split(",").map((x) => parseFloat(x));
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  // The background a control is REALLY painted on: its own, or the nearest
  // ancestor that actually paints one. A transparent button (btn-danger,
  // btn-ghost) is legible only relative to whatever shows through it.
  const effectiveBg = (el) => {
    // Collect every painted layer up the tree, then composite them.
    //
    // The first version returned the first layer with alpha > 0 and treated it
    // as opaque. That is wrong for exactly the tokens this codebase uses:
    // --accent-secondary-soft is rgba(34,211,238,0.10), and reading it as solid
    // #22d3ee reported the update banner at 1:1 against its own link colour --
    // a fabricated failure that nearly sent me redesigning a component that was
    // fine. Alpha has to be blended, not ignored.
    const layers = [];
    let n = el;
    while (n) {
      const c = parse(getComputedStyle(n).backgroundColor);
      if (c && c.a > 0) {
        layers.push(c);
        if (c.a >= 1) break; // opaque: nothing below it shows through
      }
      n = n.parentElement;
    }
    let base = { r: 255, g: 255, b: 255 };
    for (const c of layers.reverse()) {
      base = {
        r: c.r * c.a + base.r * (1 - c.a),
        g: c.g * c.a + base.g * (1 - c.a),
        b: c.b * c.a + base.b * (1 - c.a),
      };
    }
    return base;
  };
  const lum = ({ r, g, b }) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  // Text alpha counts too. A negative control caught this: setting the banner
  // text to rgba(232,230,240,0.25) -- nearly invisible -- still measured as a
  // clean 14:1, because only the background was being composited and the
  // foreground's own alpha was thrown away. Blend the text over its background
  // before measuring, exactly as the screen does.
  const ratio = (fgRaw, bg) => {
    const fg = fgRaw.a !== undefined && fgRaw.a < 1
      ? { r: fgRaw.r * fgRaw.a + bg.r * (1 - fgRaw.a),
          g: fgRaw.g * fgRaw.a + bg.g * (1 - fgRaw.a),
          b: fgRaw.b * fgRaw.a + bg.b * (1 - fgRaw.a) }
      : fgRaw;
    const a = lum(fg), b = lum(bg);
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  };

  const out = { theme: document.documentElement.getAttribute("data-theme") || "dark", buttons: [], link: null };
  for (const el of document.querySelectorAll("[data-probe]")) {
    const cs = getComputedStyle(el);
    const fg = parse(cs.color), bg = effectiveBg(el);
    out.buttons.push({
      probe: el.getAttribute("data-probe"),
      color: cs.color,
      bg: "rgb(" + bg.r + "," + bg.g + "," + bg.b + ")",
      contrast: Math.round(ratio(fg, bg) * 100) / 100,
      underlined: cs.textDecorationLine.includes("underline"),
    });
  }
  for (const el of document.querySelectorAll("[data-probe-fg]")) {
    const cs = getComputedStyle(el);
    const fg = parse(cs.color), bg = effectiveBg(el);
    out.buttons.push({
      probe: el.getAttribute("data-probe-fg"),
      color: cs.color,
      bg: "rgb(" + Math.round(bg.r) + "," + Math.round(bg.g) + "," + Math.round(bg.b) + ")",
      contrast: Math.round(ratio(fg, bg) * 100) / 100,
      underlined: false, // an underline is only a defect on a FILLED control
    });
  }
  const link = document.querySelector("[data-probe-link]");
  if (link) {
    const lcs = getComputedStyle(link);
    const pcs = getComputedStyle(document.querySelector("[data-probe-text]"));
    out.link = {
      underlined: lcs.textDecorationLine.includes("underline"),
      distinctFromProse: lcs.color !== pcs.color,
      contrast: Math.round(ratio(parse(lcs.color), effectiveBg(link)) * 100) / 100,
    };
  }
  // Prove the switch actually took effect. A partially-applied theme produced
  // the CI failure this guards against, and silently measuring it is worse than
  // failing: the numbers look authoritative and describe nothing real.
  out.themeApplied = (document.documentElement.getAttribute("data-theme") || "dark") === theme;
  return JSON.stringify(out);
})(${JSON.stringify(theme)})`;

// ---------------------------------------------------------------------------
const version = await fetch(`http://127.0.0.1:${PORT}/json/version`).catch(() => null);
if (!version || !version.ok) {
  console.error("FAIL  no headless Chrome on port " + PORT + ".");
  console.error("      This check needs a real browser: contrast is a property of");
  console.error("      the RENDERED page, and no static parse can compute it.");
  console.error("      Run it through ./scripts/legibility_check.sh");
  process.exit(2); // never 0 -- a skipped legibility check must not read as a pass
}

const target = await (
  await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: "PUT" })
).json();
const ws = new WebSocket(target.webSocketDebuggerUrl);
let id = 0;
const pending = new Map();
const send = (method, params = {}) =>
  new Promise((r) => { pending.set(++id, r); ws.send(JSON.stringify({ id, method, params })); });
await new Promise((r) => ws.addEventListener("open", r));
ws.addEventListener("message", (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m.result); pending.delete(m.id); }
});
await send("Page.enable");
await send("Runtime.enable");

let failures = 0;
let checks = 0;
const fail = (msg) => { failures++; console.error("FAIL  " + msg); };

// Both themes. A palette that works in the dark one can be unreadable in the
// other, and the light theme redefines every colour token.
for (const theme of ["dark", "light"]) {
  await send("Page.navigate", { url: "file://" + fixturePaths[theme] });
  await new Promise((r) => setTimeout(r, 400)); // let the stylesheet load
  const res = await send("Runtime.evaluate", { expression: AUDIT(theme), returnByValue: true });
  const data = JSON.parse(res.result.value);
  checks += 1;
  if (!data.themeApplied) {
    fail(`[${theme}] the theme did not apply, so every measurement below is meaningless`);
    continue;
  }

  for (const b of data.buttons) {
    checks += 2;
    if (b.contrast < MIN_CONTRAST) {
      fail(`[${theme}] ${b.probe} contrast ${b.contrast}:1 (need ${MIN_CONTRAST}:1) — ${b.color} on ${b.bg}`);
    }
    // A filled control that is underlined means link styling leaked into it.
    if (b.underlined) {
      fail(`[${theme}] ${b.probe} is underlined — link styling has leaked into a button`);
    }
  }

  // THE CONTROL. Without this the whole check could be satisfied by deleting
  // the modal link styling altogether: buttons would stop being underlined and
  // every assertion above would pass, while real links silently became
  // indistinguishable from prose. Fixing one by breaking the other is not a fix.
  checks += 3;
  if (!data.link) fail(`[${theme}] control link missing from the fixture`);
  else {
    if (!data.link.underlined)
      fail(`[${theme}] a real prose link is NOT underlined — link styling was removed rather than scoped`);
    if (!data.link.distinctFromProse)
      fail(`[${theme}] a real prose link is the same colour as surrounding prose`);
    if (data.link.contrast < MIN_CONTRAST)
      fail(`[${theme}] prose link contrast ${data.link.contrast}:1 (need ${MIN_CONTRAST}:1)`);
  }
  console.log(`${theme.padEnd(5)}: ${data.buttons.length} controls measured, link ok=${!!data.link && data.link.underlined}`);
}

ws.close();
console.log(`${checks - failures}/${checks} legibility checks passed`);
if (failures) process.exit(1);
