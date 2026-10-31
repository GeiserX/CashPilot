// Measure, in a real browser, whether the Fleet page (and the other pages a
// phone opens most) fits its window.
//
// Box names come from the device and can be any length ("motorola motorola one
// fusion+ (1414f972)"), a worker URL is a full tailnet hostname, and a box can
// run thirty containers. Every cell of the fleet table used to be nowrap, so
// the table was 1771 px wide on a 2560 px screen and the containers column sat
// in a sideways scroll at every width. Whether something overflows is a
// property of the rendered page, so only a browser can tell.
//
// The page is the real one: the demo UI from scripts/ui_demo_seed.py, logged
// in, with the real fleet.html and style.css. Its /api/workers and
// /api/fleet/economics answers get extra boxes with the worst names we know
// of appended, so the check covers long data the demo seed does not have.
//
// It fails when, at any of the widths below, the document scrolls sideways,
// any element shows its own horizontal scrollbar, anything sticks out past the
// right edge of the window, an element that hides its overflow
// (overflow-x: hidden or clip) has content wider than itself, a table cell's
// text runs out of the cell, or any element's own text runs out of its box.
// The last four catch a page that "fits" only because a wrapper cuts the
// overflow off or one box writes over its neighbour.
//
// The dashboard (/) also gets two services whose provider disabled the
// account, one with a long provider name, so its "Account disabled" card is
// measured at every width. v1.58.0 shipped that card with a tag wider than its
// column (it wrote over the provider name at 1440 px) and a "Contact ..."
// button that pushed the page to 352 px at 320 px.
//
//   ./scripts/fleet_overflow_check.sh            (boots Chrome and the demo UI)
//   SHOTS=/tmp/shots ./scripts/fleet_overflow_check.sh   (also saves screenshots)
//   THEME=classic ./scripts/fleet_overflow_check.sh      (in another theme)
//
// Exits 1 on overflow, 2 when the browser or the UI cannot be reached:
// "could not run" must never read as "passed".

import fs from "node:fs";

const CDP = `http://127.0.0.1:${process.env.CHROME_DEBUG_PORT || 9224}`;
const BASE = process.env.UI_URL || "http://127.0.0.1:8110";
const USER = process.env.UI_USER || "demo";
const PASS = process.env.UI_PASS || "demo-password-1";
const SHOTS = process.env.SHOTS || "";
const THEME = process.env.THEME || "dark";
// 1100 and 1101 sit either side of the fleet table's stacked layout.
const FLEET_WIDTHS = [320, 375, 768, 1024, 1100, 1101, 1440, 2560];
// The whole dashboard at every width, services table included: it used to be
// wider than a 1024 px window (1220 px in a 968 px wrapper) and scrolled in
// its own box, and its image names were cut with an ellipsis.
// 768/769 and 1100/1101 sit either side of the phone and the stacked-services
// layouts; /catalog scrolled at 769 px.
const ALL_WIDTHS = [320, 340, 360, 375, 768, 769, 1024, 1100, 1101, 1440, 2560];
const PAGES = [
  ["/fleet", FLEET_WIDTHS],
  ["/", ALL_WIDTHS],
  ["/catalog", ALL_WIDTHS],
  ["/setup", ALL_WIDTHS],
  ["/payouts", ALL_WIDTHS],
];

// --- Long data the demo seed does not have ---------------------------------
const LONG_SLUGS = [
  "proxybase-markets", "traffmonetizer", "honeygain", "packetstream", "bytebenefit",
  "mysterium", "earnapp", "repocket", "bitping", "earnfm", "proxyrack", "storj",
  "urnetwork", "anyone-protocol", "grass", "titan", "wipter", "nodle", "bytelixir",
  "a-container-slug-that-someone-named-without-any-restraint-at-all",
];
const now = new Date().toISOString().replace("T", " ").slice(0, 19);
const sys = (extra) => ({ os: "Linux", os_version: "6.18.38-Unraid-with-a-very-long-kernel-suffix", arch: "x86_64", version: "1.56.5", features: ["isolation_check"], ...extra });
const FIXTURE_WORKERS = [
  {
    id: 9001, client_id: "1414f972", name: "motorola motorola one fusion+ (1414f972)", status: "online",
    last_heartbeat: now, url: null, enrollment: "complete", version_skew: true, reference_version: "0.4.0",
    system_info: { os: "Android", os_version: "Android 10 (API 29)", arch: "arm64-v8a", version: "0.3.0", device_type: "android" },
    apps: LONG_SLUGS.slice(0, 8).map((slug, i) => ({ slug, running: i % 3 !== 0, net_tx_24h: 1000 * i, net_rx_24h: 2000 * i })),
    containers: [],
  },
  {
    id: 9002, client_id: "a9f3c0d1e2b4a9f3c0d1e2b4a9f3c0d1e2b4a9f3c0d1e2b4", name: "averyveryverylongservernamewithoutanyseparatorswhatsoever", status: "online",
    last_heartbeat: now, url: "http://averyveryverylongservernamewithoutanyseparatorswhatsoever.example.ts.net:8081",
    enrollment: "incomplete", version_skew: true, ui_version: "1.57.0", system_info: sys(),
    containers: LONG_SLUGS.map((slug, i) => ({ slug, name: `cashpilot-${slug}`, status: i === 3 ? "exited" : "running", exit_code: i === 3 ? 137 : null })),
  },
  {
    id: 9003, client_id: "b7e1", name: "averyveryverylongservernamewithoutanyseparatorswhatsoever", status: "offline",
    last_heartbeat: "2026-10-29 08:00:00", url: "http://192.0.2.10:8081", enrollment: "pending", system_info: sys({ version: undefined }),
    containers: LONG_SLUGS.slice(0, 6).map((slug) => ({ slug, status: "running" })),
  },
  {
    // A name of ordinary words, long enough that it only fits a 2560 px window
    // if it wraps at its spaces.
    id: 9004, client_id: "c4d2e0f1", name: "living room media server behind the tv cabinet next to the router, the one with the loud fan that someone unplugs every sunday to vacuum (rev 2)", status: "online",
    last_heartbeat: now, url: "http://192.0.2.11:8081", enrollment: "complete", system_info: sys(),
    containers: LONG_SLUGS.slice(0, 4).map((slug) => ({ slug, status: "running" })),
  },
];
// An isolation report for the second box, so the stacked layout's report row
// (tr.worker-detail) is on the page. Long addresses, a long earner name and a
// long probe container name, every line the report can show.
const ISOLATION_WORKER = 9002;
const ISOLATION_REPORT = {
  status: "exposed", reason: "the earner container cashpilot-a-container-slug-that-someone-named-without-any-restraint-at-all has no shell",
  tested_from: { earner: "cashpilot-a-container-slug-that-someone-named-without-any-restraint-at-all", network: ["cashpilot_default_network_with_a_long_name", "bridge"] },
  groups: [
    { group: "lan", label: "Your LAN", targets: [
      { address: "192.0.2.1", label: "Router", reachable: true, expected: false },
      { address: "192.0.2.10", label: "This host", reachable: true, expected: false },
      { address: "2001:db8:85a3:1234:5678:8a2e:370:7334", label: "IPv6 LAN", reachable: false },
    ] },
    { group: "overlay", label: "Overlay network", targets: [
      { address: "100.100.100.100", label: "Tailscale DNS", reachable: true, expected: true, note: "expected" },
      { address: "averyveryverylongservernamewithoutanyseparatorswhatsoever.example.ts.net", label: "Peer", reachable: false },
    ] },
    { group: "metadata", label: "Cloud metadata", targets: [{ address: "169.254.169.254", label: "Metadata", reachable: false }] },
  ],
  internet: { address: "1.1.1.1", reachable: true },
  findings: [{ exposure: true, detail: "An earner reached 192.0.2.1 and 192.0.2.10 on your LAN through the default bridge cashpilot_default_network_with_a_long_name.", docs: "https://example.com/docs/isolation-check/#2-fix-it-by-platform" }],
  node_firewall: { service: "Mysterium", container: "cashpilot-mysterium-node-with-a-long-container-name", readable: true, blackholed: ["192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24"] },
  addresses_left_out: ["172.17.0.1", "172.18.0.1"],
  leftover_probes: ["cashpilot-isolation-probe-a9f3c0d1e2b4a9f3c0d1e2b4", "cashpilot-isolation-probe-b7e1b7e1b7e1b7e1b7e1"],
  not_answering_from_host: ["198.51.100.7"],
};
const FIXTURE_MACHINES = FIXTURE_WORKERS.map((w) => ({
  machine: w.name, verdict: "losing_money", monthly_gross: 17.76, monthly_cost: 120.5, monthly_net: -102.74,
  summary: `${w.name} earned 17.76 last month and its electricity cost more than that.`,
}));

// Services whose provider disabled the account. The demo's iproyal gets the
// flag (it has a box to stop, so both buttons show), and a copy of it gets the
// longest provider name we could think of.
const LONG_PROVIDER = "Exceptionally Long Provider Name Bandwidth Sharing Network International";
// A digest-pinned image reference, the longest kind the Service cell shows.
const LONG_IMAGE = "ghcr.io/an-exceptionally-long-organisation-name/proxybase-markets-earner-image@sha256:3f1d0c9a7b6e5d4c3b2a19f8e7d6c5b4a39281706f5e4d3c2b1a09f8e7d6c5b4";
function withDisabledAccounts(services) {
  const base = services.find((s) => s.slug === "iproyal") || services[0];
  if (!base) return services;
  const disabled = (extra) => ({
    ...base, account_disabled: true, collector_disconnected: false, collector_needs_setup: false,
    balance: 7.62, balance_known: true, currency: "USD",
    support_url: "https://example.com/support/contact-us", ...extra,
  });
  const out = services.map((s) => (s === base ? disabled({}) : s));
  out.push(disabled({ slug: "long-provider-fixture", name: LONG_PROVIDER, balance: 1234.56, image: LONG_IMAGE }));
  return out;
}

// The [path, widths, scope] entries above: scope limits the element checks to
// one part of the page; the document itself must still never scroll sideways.

// --- Minimal CDP client -----------------------------------------------------
let ws, seq = 0;
const pending = new Map();
const listeners = [];
function send(method, params = {}) {
  const id = ++seq;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject, method }));
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function evaluate(expression) {
  const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(`page threw: ${JSON.stringify(r.exceptionDetails).slice(0, 300)}`);
  return r.result.value;
}
async function waitFor(expression, ms = 20000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    try { if (await evaluate(expression)) return; } catch { /* page navigating */ }
    await sleep(200);
  }
  throw new Error(`timed out waiting for: ${expression}`);
}

async function main() {
  let target;
  try {
    target = await (await fetch(`${CDP}/json/new?about:blank`, { method: "PUT" })).json();
  } catch (e) {
    console.error(`FAIL  no browser at ${CDP}: ${e.message}`);
    process.exit(2);
  }
  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const p = pending.get(msg.id); pending.delete(msg.id);
      if (msg.error) p.reject(new Error(`${p.method}: ${msg.error.message}`)); else p.resolve(msg.result);
    } else if (msg.method) listeners.forEach((fn) => fn(msg));
  };

  // Append the fixture boxes to the real answers.
  let injected = 0;
  listeners.push(async (msg) => {
    if (msg.method !== "Fetch.requestPaused") return;
    const { requestId, request, responseStatusCode } = msg.params;
    if (request.url.includes("/isolation-check")) {
      injected++;
      await send("Fetch.fulfillRequest", {
        requestId, responseCode: 200,
        responseHeaders: [{ name: "Content-Type", value: "application/json" }],
        body: Buffer.from(JSON.stringify(ISOLATION_REPORT)).toString("base64"),
      }).catch((e) => console.error(`could not answer the isolation check: ${e.message}`));
      return;
    }
    try {
      const { body, base64Encoded } = await send("Fetch.getResponseBody", { requestId });
      const data = JSON.parse(base64Encoded ? Buffer.from(body, "base64").toString("utf8") : body);
      if (request.url.includes("/api/workers")) data.push(...FIXTURE_WORKERS);
      else if (request.url.includes("/api/services/deployed")) data.splice(0, data.length, ...withDisabledAccounts(data));
      else if (data && Array.isArray(data.machines)) data.machines.push(...FIXTURE_MACHINES);
      injected++;
      await send("Fetch.fulfillRequest", {
        requestId, responseCode: responseStatusCode || 200,
        responseHeaders: [{ name: "Content-Type", value: "application/json" }],
        body: Buffer.from(JSON.stringify(data)).toString("base64"),
      });
    } catch (e) {
      console.error(`could not inject the fixture into ${request.url}: ${e.message}`);
      await send("Fetch.continueRequest", { requestId }).catch(() => {});
    }
  });

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: "dark" }] });
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });

  // Log in with the demo owner.
  await send("Page.navigate", { url: `${BASE}/login` });
  await waitFor("!!document.querySelector('#username')").catch(() => {
    console.error(`FAIL  no login form at ${BASE}/login -- is the demo UI running?`);
    process.exit(2);
  });
  await evaluate(`(() => {
    document.querySelector('#username').value = ${JSON.stringify(USER)};
    document.querySelector('#password').value = ${JSON.stringify(PASS)};
    document.querySelector('form').submit();
  })()`);
  await waitFor("location.pathname !== '/login' && document.readyState === 'complete'");
  // The pre-paint script reads this key on every page from here on.
  await evaluate(`localStorage.setItem('cp-theme', ${JSON.stringify(THEME)})`);

  await send("Fetch.enable", {
    patterns: [
      { urlPattern: "*/api/workers", requestStage: "Response" },
      { urlPattern: "*/api/fleet/economics", requestStage: "Response" },
      { urlPattern: "*/api/services/deployed", requestStage: "Response" },
      { urlPattern: `*/api/workers/${ISOLATION_WORKER}/isolation-check`, requestStage: "Request" },
    ],
  });
  await send("Page.navigate", { url: `${BASE}/fleet` });
  await waitFor(`!!document.querySelector('.fleet-table') && document.body.textContent.includes('motorola motorola one fusion+')`);
  await waitFor(`!!document.querySelector('.economics-row')`);
  // Open the isolation report of the second box.
  await evaluate(`document.querySelector('.btn-isolation-check[data-worker-id="${ISOLATION_WORKER}"]').click()`);
  await waitFor(`!!document.querySelector('.fleet-table tr.worker-detail .iso-report')`);
  await sleep(500);
  if (injected < 3) {
    console.error(`FAIL  the fixture reached ${injected} of 3 endpoints, so the long names were not on the page`);
    process.exit(2);
  }
  const rows = await evaluate("document.querySelectorAll('.fleet-table .worker-row').length");

  const MEASURE = (scope) => `(() => {
    const root = document.querySelector(${JSON.stringify(scope || "body")});
    const de = document.documentElement;
    const desc = (el) => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + '.' + String(el.className).trim().replace(/\\s+/g, '.');
    const visible = (el) => el.getClientRects().length && !el.closest('.sr-only');
    const scrollers = [], hidden = [], spill = [], text = [];
    // Text that runs out of its own box, over whatever sits next to it: the
    // right edge of each of the element's own text lines against the box's
    // right edge. Inline boxes grow with their text, so only blocks, grid and
    // flex items count.
    for (const el of root.querySelectorAll('*')) {
      if (!visible(el) || getComputedStyle(el).display.startsWith('inline') || el.matches('input, textarea, select')) continue;
      const box = el.getBoundingClientRect();
      if (!box.width) continue;
      for (const n of el.childNodes) {
        if (n.nodeType !== 3 || !n.textContent.trim()) continue;
        const r = document.createRange(); r.selectNodeContents(n);
        const right = Math.max(...[...r.getClientRects()].map((q) => q.right));
        if (right > box.right + 1) { text.push(desc(el) + ' box right=' + Math.round(box.right) + ' text right=' + Math.round(right) + ' "' + n.textContent.trim().slice(0, 40) + '"'); break; }
      }
    }
    for (const el of root.querySelectorAll('*')) {
      if (!visible(el) || el.scrollWidth <= el.clientWidth + 1) continue;
      const ox = getComputedStyle(el).overflowX;
      if (ox === 'auto' || ox === 'scroll') scrollers.push(desc(el) + ' ' + el.scrollWidth + '>' + el.clientWidth);
      // A form field scrolls its own value; that is not the page overflowing.
      else if ((ox === 'hidden' || ox === 'clip') && !el.matches('input, textarea, select')) hidden.push(desc(el) + ' ' + el.scrollWidth + '>' + el.clientWidth);
      // A table cell whose text runs out of it, over the next cell, even if
      // the window edge is still far away.
      else if (el.matches('td, th')) spill.push(desc(el) + ' ' + el.scrollWidth + '>' + el.clientWidth + ' "' + (el.textContent || '').trim().slice(0, 40) + '"');
    }
    // The innermost elements that run past the window, to say what overflows.
    const vw = de.clientWidth, wide = [];
    for (const el of root.querySelectorAll('*')) {
      if (!visible(el)) continue;
      const b = el.getBoundingClientRect();
      if (b.width && b.right > vw + 1) wide.push(el);
    }
    const past = wide.filter((e) => !wide.some((o) => o !== e && e.contains(o))).slice(0, 8)
      .map((e) => desc(e) + ' right=' + Math.round(e.getBoundingClientRect().right) + ' "' + (e.textContent || '').trim().slice(0, 40) + '"');
    return { scrollWidth: de.scrollWidth, clientWidth: de.clientWidth, scrollers, hidden, spill, text, past };
  })()`;

  let failures = 0, checked = 0;
  for (const [page, widths, scope] of PAGES) {
    if (page !== "/fleet") {
      await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
      await send("Page.navigate", { url: `${BASE}${page}` });
      await waitFor(`location.pathname === ${JSON.stringify(page)} && document.readyState === 'complete'`);
      // Most pages fill themselves from the API after load.
      await sleep(2500);
      if (page === "/") {
        await waitFor(`document.querySelectorAll('.attn-row').length && [...document.querySelectorAll('.attn-tag')].filter((t) => t.textContent === 'Account disabled').length === 2`)
          .catch(() => { console.error("FAIL  the two account-disabled fixtures did not reach the dashboard"); process.exit(2); });
      }
    }
    const theme = await evaluate("document.documentElement.getAttribute('data-theme')");
    if (theme !== THEME) {
      console.error(`FAIL  ${page} painted theme ${theme}, not ${THEME}, so this run measures the wrong theme`);
      process.exit(2);
    }
    for (const w of widths) {
      await send("Emulation.setDeviceMetricsOverride", { width: w, height: 900, deviceScaleFactor: 1, mobile: false });
      await sleep(300);
      const r = await evaluate(MEASURE(scope));
      const ok = r.scrollWidth <= r.clientWidth && !r.scrollers.length && !r.hidden.length && !r.spill.length && !r.text.length && !r.past.length;
      checked++;
      if (!ok) failures++;
      console.log(`${ok ? "ok  " : "FAIL"}  ${(page + (scope ? " " + scope : "")).padEnd(19)} ${String(w).padStart(4)} px  scrollWidth ${r.scrollWidth}  clientWidth ${r.clientWidth}  scrollbars inside ${r.scrollers.length}  hidden overflow ${r.hidden.length}  spilling cells ${r.spill.length}  text out of its box ${r.text.length}  past the edge ${r.past.length}`);
      if (!ok) {
        for (const s of r.scrollers) console.log(`        scrolls sideways: ${s}`);
        for (const h of r.hidden) console.log(`        cut off:          ${h}`);
        for (const c of r.spill) console.log(`        spills its cell:  ${c}`);
        for (const t of r.text) console.log(`        text out of box:  ${t}`);
        for (const p of r.past) console.log(`        past the edge:    ${p}`);
      }
      if (SHOTS) {
        await evaluate("window.scrollTo(0, 0)");
        fs.mkdirSync(SHOTS, { recursive: true });
        const { contentSize } = await send("Page.getLayoutMetrics");
        const shot = await send("Page.captureScreenshot", {
          format: "png", captureBeyondViewport: true,
          clip: { x: 0, y: 0, width: w, height: Math.ceil(contentSize.height), scale: 1 },
        });
        const name = page === "/" ? "dashboard" : page.slice(1);
        fs.writeFileSync(`${SHOTS}/${name}-${w}.png`, Buffer.from(shot.data, "base64"));
      }
    }
  }
  console.log(`theme ${THEME}: ${checked} page widths checked, ${rows} boxes on /fleet (${FIXTURE_WORKERS.length} long-name fixtures, one isolation report), ${failures} overflowing`);
  await fetch(`${CDP}/json/close/${target.id}`).catch(() => {});
  process.exit(failures ? 1 : 0);
}

main().catch((e) => { console.error(`FAIL  ${e.message}`); process.exit(2); });
