// Measure, in a real browser, whether the Fleet page fits its window.
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
// It fails when, at any of the widths below, the document scrolls sideways or
// any element on the page shows its own horizontal scrollbar.
//
//   ./scripts/fleet_overflow_check.sh            (boots Chrome and the demo UI)
//   SHOTS=/tmp/shots ./scripts/fleet_overflow_check.sh   (also saves screenshots)
//
// Exits 1 on overflow, 2 when the browser or the UI cannot be reached:
// "could not run" must never read as "passed".

import fs from "node:fs";

const CDP = `http://127.0.0.1:${process.env.CHROME_DEBUG_PORT || 9224}`;
const BASE = process.env.UI_URL || "http://127.0.0.1:8110";
const USER = process.env.UI_USER || "demo";
const PASS = process.env.UI_PASS || "demo-password-1";
const SHOTS = process.env.SHOTS || "";
const WIDTHS = [320, 375, 768, 1024, 1440, 2560];

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
    last_heartbeat: now, url: "http://averyveryverylongservernamewithoutanyseparatorswhatsoever.mango-alpha.ts.net:8081",
    enrollment: "incomplete", version_skew: true, ui_version: "1.57.0", system_info: sys(),
    containers: LONG_SLUGS.map((slug, i) => ({ slug, name: `cashpilot-${slug}`, status: i === 3 ? "exited" : "running", exit_code: i === 3 ? 137 : null })),
  },
  {
    id: 9003, client_id: "b7e1", name: "averyveryverylongservernamewithoutanyseparatorswhatsoever", status: "offline",
    last_heartbeat: "2026-10-29 08:00:00", url: "http://192.168.10.110:8081", enrollment: "pending", system_info: sys({ version: undefined }),
    containers: LONG_SLUGS.slice(0, 6).map((slug) => ({ slug, status: "running" })),
  },
];
const FIXTURE_MACHINES = FIXTURE_WORKERS.map((w) => ({
  machine: w.name, verdict: "losing_money", monthly_gross: 17.76, monthly_cost: 120.5, monthly_net: -102.74,
  summary: `${w.name} earned 17.76 last month and its electricity cost more than that.`,
}));

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
    try {
      const { body, base64Encoded } = await send("Fetch.getResponseBody", { requestId });
      const data = JSON.parse(base64Encoded ? Buffer.from(body, "base64").toString("utf8") : body);
      if (request.url.includes("/api/workers")) data.push(...FIXTURE_WORKERS);
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

  await send("Fetch.enable", {
    patterns: [
      { urlPattern: "*/api/workers", requestStage: "Response" },
      { urlPattern: "*/api/fleet/economics", requestStage: "Response" },
    ],
  });
  await send("Page.navigate", { url: `${BASE}/fleet` });
  await waitFor(`!!document.querySelector('.fleet-table') && document.body.textContent.includes('motorola motorola one fusion+')`);
  await waitFor(`!!document.querySelector('.economics-row')`);
  await sleep(500);
  if (injected < 2) {
    console.error(`FAIL  the fixture reached ${injected} of 2 endpoints, so the long names were not on the page`);
    process.exit(2);
  }
  const rows = await evaluate("document.querySelectorAll('.fleet-table .worker-row').length");

  const MEASURE = `(() => {
    const de = document.documentElement;
    const scrollers = [];
    for (const el of document.querySelectorAll('body *')) {
      const ox = getComputedStyle(el).overflowX;
      if ((ox === 'auto' || ox === 'scroll') && el.scrollWidth > el.clientWidth + 1 && el.getClientRects().length) {
        scrollers.push(el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + '.' + String(el.className).trim().replace(/\\s+/g, '.') + ' ' + el.scrollWidth + '>' + el.clientWidth);
      }
    }
    // The innermost elements that run past the window, to say what overflows.
    const vw = de.clientWidth, wide = [];
    for (const el of document.querySelectorAll('body *')) {
      const b = el.getBoundingClientRect();
      if (b.width && b.right > vw + 1) wide.push(el);
    }
    const past = wide.filter((e) => !wide.some((o) => o !== e && e.contains(o))).slice(0, 8)
      .map((e) => e.tagName.toLowerCase() + '.' + String(e.className).trim().replace(/\\s+/g, '.') + ' right=' + Math.round(e.getBoundingClientRect().right) + ' "' + (e.textContent || '').trim().slice(0, 40) + '"');
    return { scrollWidth: de.scrollWidth, clientWidth: de.clientWidth, scrollers, past };
  })()`;

  let failures = 0;
  for (const w of WIDTHS) {
    await send("Emulation.setDeviceMetricsOverride", { width: w, height: 900, deviceScaleFactor: 1, mobile: false });
    await sleep(300);
    const r = await evaluate(MEASURE);
    const ok = r.scrollWidth <= r.clientWidth && r.scrollers.length === 0;
    if (!ok) failures++;
    console.log(`${ok ? "ok  " : "FAIL"}  ${String(w).padStart(4)} px  scrollWidth ${r.scrollWidth}  clientWidth ${r.clientWidth}  scrollbars inside ${r.scrollers.length}`);
    if (!ok) {
      for (const s of r.scrollers) console.log(`        scrolls sideways: ${s}`);
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
      fs.writeFileSync(`${SHOTS}/fleet-${w}.png`, Buffer.from(shot.data, "base64"));
    }
  }
  console.log(`${WIDTHS.length} widths checked, ${rows} boxes on the page (${FIXTURE_WORKERS.length} long-name fixtures), ${failures} overflowing`);
  await fetch(`${CDP}/json/close/${target.id}`).catch(() => {});
  process.exit(failures ? 1 : 0);
}

main().catch((e) => { console.error(`FAIL  ${e.message}`); process.exit(2); });
