// Full-page screenshots of every CashPilot page and state, for UI review.
//
//   node scripts/ui_screenshots.mjs <baseUrl> <outDir> [dark|light|both]
//
// <baseUrl> is a seeded instance (scripts/ui_demo_seed.py --serve PORT). The
// seed also serves a first-run instance on PORT+1 (no account, /onboarding
// renders) and an empty one on PORT+2 (an account with nothing deployed).
//
// Writes <state>.png for the dark theme and <state>-light.png for the light
// one. Mobile states (390x844) end in -mobile. Exits non-zero if any page
// answered with an error status or logged an uncaught error.
//
// Three answers only a live worker could give are faked with page.route, all
// with invented data: the container logs, an isolation report and the update
// card. Nothing here reaches a worker or a provider.
//
// Needs the `playwright` npm package and Google Chrome (channel "chrome"); set
// PW_CHANNEL="" to use Playwright's own Chromium instead.
// CP_SCALE=2 takes retina shots (the README ones); CP_SHOT_ONLY=<regex> limits
// the run to matching state names.
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

export const USER = process.env.CP_DEMO_USER || 'demo';
export const PASS = process.env.CP_DEMO_PASSWORD || 'demo-password-1';

export const DESKTOP = { width: 1440, height: 900 };
export const MOBILE = { width: 390, height: 844 };

const FAKE_LOGS = [
  '2026-10-29T06:12:01Z INFO  starting pawns-cli 1.21.4',
  '2026-10-29T06:12:02Z INFO  device registered as box-c-iproyal',
  '2026-10-29T06:12:04Z INFO  connected, sharing bandwidth',
  '2026-10-29T14:40:17Z WARN  upstream reset by peer, reconnecting in 5s',
  '2026-10-29T14:40:22Z INFO  connected, sharing bandwidth',
  '2026-10-29T21:03:55Z ERROR out of memory, process killed',
].join('\n');

const FAKE_ISOLATION = {
  status: 'exposed',
  tested_from: { earner: 'cashpilot-honeygain', network: ['bridge'] },
  groups: [
    { label: 'Your LAN', targets: [
      { address: '192.168.1.1', label: 'Router', reachable: true, expected: false },
      { address: '192.168.1.20', label: 'NAS', reachable: false },
    ] },
    { label: 'This host', targets: [{ address: '172.17.0.1', label: 'Docker bridge gateway', reachable: false }] },
    { label: 'Cloud metadata', targets: [{ address: '169.254.169.254', label: 'Metadata service', reachable: false }] },
  ],
  internet: { address: '1.1.1.1', reachable: true },
  findings: [{ exposure: true, detail: 'An earner can reach your router at 192.168.1.1.', docs: 'https://github.com/GeiserX/CashPilot/blob/main/docs/guides/isolation.md' }],
  addresses_left_out: ['172.18.0.1', '172.19.0.1'],
};

const FAKE_UPDATE_INFO = {
  current: '1.9.2', current_display: 'v1.9.2', known: true, latest: '1.10.0',
  worker_image: 'drumsergio/cashpilot-worker:1.9.2', ui_image: 'drumsergio/cashpilot:1.9.2',
  compose_managed: true, patch_available: false, behind: true, updater_running: false,
};

async function fakeWorkerAnswers(ctx) {
  await ctx.route('**/api/services/*/logs*', (r) => r.fulfill({ json: { logs: FAKE_LOGS } }));
  await ctx.route('**/api/workers/*/isolation-check', (r) => r.fulfill({ json: FAKE_ISOLATION }));
  await ctx.route('**/api/update-info*', (r) => r.fulfill({ json: FAKE_UPDATE_INFO }));
}

export async function settle(page) {
  await page.waitForLoadState('networkidle').catch(() => {});
  // Web fonts change text widths; wait for them so two runs compare.
  await page.evaluate(() => document.fonts.ready).catch(() => {});
  // Charts animate in; give them time to finish drawing.
  await page.waitForTimeout(1200);
}

async function waitTitle(page, id) {
  await page.waitForFunction((i) => {
    const t = document.getElementById(i);
    return t && t.textContent && !/^Loading/.test(t.textContent);
  }, id, { timeout: 15000 });
}

// A modal scrolls inside itself; unclamp it (through the CSSOM, which the CSP
// allows) so the shot holds the whole modal.
async function unclampModal(page, overlayId) {
  await page.evaluate((id) => {
    const overlay = document.getElementById(id);
    const modal = overlay.querySelector('.modal');
    const body = overlay.querySelector('.modal-body');
    Object.assign(overlay.style, { position: 'absolute', bottom: 'auto', minHeight: '100%', alignItems: 'flex-start', padding: '48px 0' });
    Object.assign(modal.style, { maxHeight: 'none' });
    if (body) Object.assign(body.style, { maxHeight: 'none', overflow: 'visible' });
    document.body.style.minHeight = overlay.scrollHeight + 96 + 'px';
    window.scrollTo(0, 0);
  }, overlayId);
  await page.waitForTimeout(200);
}

async function wizardTo(page, step) {
  if (step >= 2) {
    // The demo account already picked bandwidth and DePIN; keep bandwidth on.
    const bw = page.locator('.category-card:has(input[value="bandwidth"])');
    if (!(await bw.evaluate((el) => el.classList.contains('selected')))) await bw.click();
    await page.click('#wizard-next');
    await page.waitForSelector('#wizard-services .service-card', { timeout: 15000 });
  }
  if (step >= 3) {
    // Two services not deployed yet, so step 3 shows two setup forms.
    for (const slug of ['bitping', 'proxyrack']) {
      await page.click(`#wizard-services .service-card[data-slug="${slug}"]`);
    }
    await page.click('#wizard-next');
    await page.waitForFunction(() => !document.querySelector('#wizard-setup-forms > .spinner'), null, { timeout: 15000 });
  }
  if (step >= 4) await page.click('#wizard-next');
  await settle(page);
}

// name, server (seed | fresh | empty), path, viewport, optional before(page),
// optional full: false for a viewport-sized shot.
export const STATES = [
  { name: 'login', server: 'seed', path: '/login', auth: false },
  { name: 'login-mobile', server: 'seed', path: '/login', auth: false, viewport: MOBILE },
  { name: 'onboarding', server: 'fresh', path: '/onboarding', auth: false },
  { name: 'onboarding-mobile', server: 'fresh', path: '/onboarding', auth: false, viewport: MOBILE },
  { name: 'dashboard', server: 'seed', path: '/' },
  { name: 'dashboard-mobile', server: 'seed', path: '/', viewport: MOBILE },
  { name: 'dashboard-empty', server: 'empty', path: '/' },
  { name: 'dashboard-expanded', server: 'seed', path: '/', before: async (p) => {
    await p.click('.breakdown-row.expandable[data-slug="iproyal"] td:nth-child(2)');
    await p.waitForTimeout(200);
  } },
  { name: 'notifications', server: 'seed', path: '/', full: false, before: async (p) => {
    await p.click('#notify-toggle');
    await p.waitForTimeout(300);
  } },
  { name: 'credential-modal', server: 'seed', path: '/', element: '#cred-modal .modal', before: async (p) => {
    await p.click('.breakdown-row[data-slug="repocket"] [data-action="openCredentialModal"].btn-icon');
    await waitTitle(p, 'cred-modal-title');
    await settle(p);
    await unclampModal(p, 'cred-modal');
  } },
  { name: 'claim-modal', server: 'seed', path: '/', element: '#claim-modal .modal', before: async (p) => {
    await p.click('.breakdown-row[data-slug="mysterium"] [data-action="openClaimModal"]');
    await waitTitle(p, 'claim-modal-title');
    await settle(p);
    await unclampModal(p, 'claim-modal');
  } },
  { name: 'logs-modal', server: 'seed', path: '/', full: false, before: async (p) => {
    await p.click('.attn-row [data-action="viewLogs"]');
    await p.waitForTimeout(800);
  } },
  { name: 'catalog', server: 'seed', path: '/catalog' },
  { name: 'catalog-mobile', server: 'seed', path: '/catalog', viewport: MOBILE },
  { name: 'service_detail', server: 'seed', path: '/catalog', element: '#service-detail-modal .modal', before: async (p) => {
    await p.click('[data-action="openServiceDetail"][data-a1="honeygain"]');
    await waitTitle(p, 'service-detail-title');
    await settle(p);
    await unclampModal(p, 'service-detail-modal');
  } },
  { name: 'setup', server: 'seed', path: '/setup' },
  { name: 'setup-mobile', server: 'seed', path: '/setup', viewport: MOBILE },
  { name: 'setup-2', server: 'seed', path: '/setup', before: (p) => wizardTo(p, 2) },
  { name: 'setup-3', server: 'seed', path: '/setup', before: (p) => wizardTo(p, 3) },
  { name: 'setup-4', server: 'seed', path: '/setup', before: (p) => wizardTo(p, 4) },
  { name: 'fleet', server: 'seed', path: '/fleet' },
  { name: 'fleet-mobile', server: 'seed', path: '/fleet', viewport: MOBILE },
  { name: 'fleet-isolation', server: 'seed', path: '/fleet', before: async (p) => {
    await p.click('.btn-isolation-check >> nth=0');
    await p.waitForSelector('.worker-detail', { timeout: 15000 });
    await p.waitForTimeout(300);
  } },
  { name: 'payouts', server: 'seed', path: '/payouts' },
  { name: 'payouts-mobile', server: 'seed', path: '/payouts', viewport: MOBILE },
  { name: 'settings', server: 'seed', path: '/settings', before: async (p) => {
    await p.click('#collector-repocket > summary').catch(() => {});
    await p.waitForTimeout(200);
  } },
  { name: 'settings-mobile', server: 'seed', path: '/settings', viewport: MOBILE },
];

export function origins(baseArg) {
  const base = baseArg.replace(/\/$/, '');
  const at = (n) => { const u = new URL(base); u.port = String(Number(u.port || 80) + n); return u.origin; };
  return { seed: base, fresh: at(1), empty: at(2) };
}

// One logged-in storage state per server that has an account.
export async function login(browser, origin) {
  const ctx = await browser.newContext({ viewport: DESKTOP });
  const page = await ctx.newPage();
  await page.goto(origin + '/login');
  await page.fill('#username', USER);
  await page.fill('#password', PASS);
  await Promise.all([page.waitForURL(origin + '/'), page.click('button[type="submit"]')]);
  const state = await ctx.storageState();
  await ctx.close();
  return state;
}

// Open one state in a fresh context and leave it ready to capture.
export async function openState(browser, st, { urls, sessions, theme, problems, setupContext }) {
  const viewport = st.viewport || DESKTOP;
  const mobile = viewport === MOBILE;
  const ctx = await browser.newContext({
    viewport, colorScheme: theme, deviceScaleFactor: Number(process.env.CP_SCALE || 1),
    isMobile: mobile, hasTouch: mobile,
    storageState: st.auth === false ? undefined : sessions[st.server],
  });
  // The app reads its theme from localStorage before first paint.
  await ctx.addInitScript((t) => localStorage.setItem('cp-theme', t), theme);
  await fakeWorkerAnswers(ctx);
  if (setupContext) await setupContext(ctx);
  const page = await ctx.newPage();
  const label = `${st.name} (${theme})`;
  page.on('pageerror', (e) => problems.push(`${label}: ${e.message}`));
  page.on('console', (m) => {
    if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) problems.push(`${label}: ${m.text()}`);
  });
  const res = await page.goto(urls[st.server] + st.path, { waitUntil: 'domcontentloaded' });
  if (!res || res.status() >= 400) problems.push(`${label}: HTTP ${res && res.status()}`);
  await settle(page);
  if (st.before) await st.before(page);
  return { ctx, page };
}

async function main() {
  const [, , baseArg, outDir, themeArg = 'dark'] = process.argv;
  if (!baseArg || !outDir || !['dark', 'light', 'both'].includes(themeArg)) {
    console.error('usage: node ui_screenshots.mjs <baseUrl> <outDir> [dark|light|both]');
    process.exit(2);
  }
  const themes = themeArg === 'both' ? ['dark', 'light'] : [themeArg];
  const urls = origins(baseArg);
  const channel = process.env.PW_CHANNEL ?? 'chrome';
  const only = process.env.CP_SHOT_ONLY ? new RegExp(process.env.CP_SHOT_ONLY) : null;
  mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch({ channel: channel || undefined, headless: true });
  const problems = [];
  const sessions = { seed: await login(browser, urls.seed), empty: await login(browser, urls.empty) };

  for (const theme of themes) {
    for (const st of STATES) {
      if (only && !only.test(st.name)) continue;
      const file = join(outDir, `${st.name}${theme === 'light' ? '-light' : ''}.png`);
      try {
        const { ctx, page } = await openState(browser, st, { urls, sessions, theme, problems });
        if (st.element) await page.locator(st.element).screenshot({ path: file });
        else await page.screenshot({ path: file, fullPage: st.full !== false });
        await ctx.close();
        console.log(`${file}  ${st.path}`);
      } catch (err) {
        problems.push(`${st.name} (${theme}): ${err.message.split('\n')[0]}`);
      }
    }
  }
  await browser.close();
  if (problems.length) {
    console.error('problems:\n  ' + problems.join('\n  '));
    process.exit(1);
  }
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) await main();
