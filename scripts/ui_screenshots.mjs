// Full-page dark-mode screenshots of every CashPilot page, for UI review.
//
//   node scripts/ui_screenshots.mjs <baseUrl> <outDir> [firstRunUrl]
//
// <baseUrl> is a seeded instance (scripts/ui_demo_seed.py --serve PORT).
// [firstRunUrl] is an instance with no users, where /onboarding renders; it
// defaults to <baseUrl> with the port plus one, which is what --serve starts.
//
// Needs the `playwright` npm package and Google Chrome (channel "chrome"); set
// PW_CHANNEL="" to use Playwright's own Chromium instead. Writes <page>.png for
// each page below plus dashboard-mobile.png, and exits non-zero if any page
// answered with an error status or logged an uncaught error.
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

const [, , baseArg, outDir, freshArg] = process.argv;
if (!baseArg || !outDir) {
  console.error('usage: node ui_screenshots.mjs <baseUrl> <outDir> [firstRunUrl]');
  process.exit(2);
}
const base = baseArg.replace(/\/$/, '');
const fresh = (freshArg || (() => {
  const u = new URL(base);
  u.port = String(Number(u.port || 80) + 1);
  return u.origin;
})()).replace(/\/$/, '');
const USER = process.env.CP_DEMO_USER || 'demo';
const PASS = process.env.CP_DEMO_PASSWORD || 'demo-password-1';
const channel = process.env.PW_CHANNEL ?? 'chrome';

mkdirSync(outDir, { recursive: true });
const browser = await chromium.launch({ channel: channel || undefined, headless: true });
const problems = [];

async function newContext(viewport) {
  const ctx = await browser.newContext({ viewport, colorScheme: 'dark', deviceScaleFactor: 1 });
  // The app reads its theme from localStorage before first paint.
  await ctx.addInitScript(() => localStorage.setItem('cp-theme', 'dark'));
  return ctx;
}

function watch(page, name) {
  page.on('pageerror', (e) => problems.push(`${name}: ${e.message}`));
  page.on('console', (m) => {
    if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) problems.push(`${name}: ${m.text()}`);
  });
}

async function settle(page) {
  await page.waitForLoadState('networkidle').catch(() => {});
  // Charts animate in; give them time to finish drawing.
  await page.waitForTimeout(1500);
}

async function shoot(page, name, path, { fullPage = true, before, element } = {}) {
  watch(page, name);
  const res = await page.goto(base + path, { waitUntil: 'domcontentloaded' });
  if (!res || res.status() >= 400) problems.push(`${name}: HTTP ${res && res.status()}`);
  await settle(page);
  if (before) await before(page);
  const file = join(outDir, `${name}.png`);
  if (element) await page.locator(element).screenshot({ path: file });
  else await page.screenshot({ path: file, fullPage });
  console.log(`${name}.png  ${path}`);
}

// Login page first, before there is a session.
{
  const ctx = await newContext({ width: 1440, height: 900 });
  const page = await ctx.newPage();
  await shoot(page, 'login', '/login');
  await page.fill('#username', USER);
  await page.fill('#password', PASS);
  await Promise.all([page.waitForURL(base + '/'), page.click('button[type="submit"]')]);
  const state = await ctx.storageState();
  await ctx.close();

  const desk = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'dark', storageState: state });
  await desk.addInitScript(() => localStorage.setItem('cp-theme', 'dark'));
  for (const [name, path] of [
    ['dashboard', '/'],
    ['catalog', '/catalog'],
    ['setup', '/setup'],
    ['fleet', '/fleet'],
    ['payouts', '/payouts'],
    ['settings', '/settings'],
  ]) {
    const p = await desk.newPage();
    await shoot(p, name, path);
    await p.close();
  }

  // Service detail is a modal opened from the catalog. The modal scrolls
  // inside itself, so it is unclamped (through the CSSOM, which the CSP allows)
  // and the shot is the whole modal element.
  const p = await desk.newPage();
  await shoot(p, 'service_detail', '/catalog', {
    element: '#service-detail-modal .modal',
    before: async (pg) => {
      await pg.click('[data-action="openServiceDetail"][data-a1="honeygain"]');
      await pg.waitForFunction(() => {
        const t = document.getElementById('service-detail-title');
        return t && t.textContent && t.textContent !== 'Loading...';
      }, null, { timeout: 15000 });
      await settle(pg);
      await pg.evaluate(() => {
        const overlay = document.getElementById('service-detail-modal');
        const modal = overlay.querySelector('.modal');
        const body = document.getElementById('service-detail-body');
        Object.assign(overlay.style, { position: 'absolute', bottom: 'auto', minHeight: '100%', alignItems: 'flex-start', padding: '48px 0' });
        Object.assign(modal.style, { maxHeight: 'none' });
        Object.assign(body.style, { maxHeight: 'none', overflow: 'visible' });
        const h = overlay.scrollHeight;
        document.body.style.minHeight = h + 'px';
      });
      await pg.waitForTimeout(300);
    },
  });
  await p.close();
  await desk.close();

  const mob = await browser.newContext({
    viewport: { width: 390, height: 844 }, colorScheme: 'dark', storageState: state,
    isMobile: true, hasTouch: true, deviceScaleFactor: 1,
  });
  await mob.addInitScript(() => localStorage.setItem('cp-theme', 'dark'));
  const mp = await mob.newPage();
  await shoot(mp, 'dashboard-mobile', '/');
  await mob.close();
}

// Onboarding only renders while no account exists: the first-run instance.
{
  const ctx = await newContext({ width: 1440, height: 900 });
  const page = await ctx.newPage();
  watch(page, 'onboarding');
  const res = await page.goto(fresh + '/onboarding', { waitUntil: 'domcontentloaded' });
  if (!res || res.status() >= 400) problems.push(`onboarding: HTTP ${res && res.status()}`);
  await settle(page);
  await page.screenshot({ path: join(outDir, 'onboarding.png'), fullPage: true });
  console.log(`onboarding.png  ${fresh}/onboarding`);
  await ctx.close();
}

await browser.close();
if (problems.length) {
  console.error('problems:\n  ' + problems.join('\n  '));
  process.exit(1);
}
