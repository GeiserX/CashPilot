// Run the real resource-use panel renderer from app/static/js/app.js.
//
// What it guards: a figure with no reading renders as a dash, never as 0. A
// host-network container has no traffic counters, and "0 B" would call the
// busiest earner on the fleet idle.
//
//   node scripts/usage_panel_check.mjs
//
// Exits non-zero on any mismatch.
import {readFileSync} from 'node:fs';

const src = readFileSync('app/static/js/app.js', 'utf8');

function grab(name) {
  const i = src.indexOf(`  function ${name}(`);
  if (i < 0) {
    console.error(`FAIL: ${name} is not defined in app/static/js/app.js; this harness is testing nothing.`);
    process.exit(1);
  }
  const rest = src.slice(i);
  const end = rest.indexOf('\n  }\n');
  return rest.slice(0, end + 4);
}

const constLine = src.match(/\n  const USAGE_DASH = [^\n]+\n/);
if (!constLine) {
  console.error('FAIL: USAGE_DASH is not defined in app/static/js/app.js');
  process.exit(1);
}
const names = ['escapeHtml', 'fmtBytes', 'effectiveDisplayCurrency', 'formatCurrency', 'usageBytes', 'usagePair',
  'usageCpu', 'usageMem', 'usageMoney', 'renderUsagePanel'];
const body = constLine[0] + names.map(grab).join('\n') + '\nreturn renderUsagePanel;';
const render = new Function('_displayCurrency', '_exchangeRates', body)('USD', {fiat: {USD: 1}, crypto_usd: {}});

let bad = 0;
const check = (label, cond, detail) => {
  console.log(`  ${cond ? 'ok  ' : 'FAIL'} ${label}${cond ? '' : `  <- ${detail}`}`);
  if (!cond) bad++;
};

const GB = 1024 ** 3;
const html = render({
  window_days: 3,
  since: '2026-10-28',
  servers: [{
    worker_id: 1, name: 'watchtower', status: 'online',
    services: [
      {slug: 'honeygain', name: 'Honeygain', cpu_percent: 1.25, memory_mb: 48, rx_today: 2 * GB, tx_today: GB,
        rx: 5 * GB, tx: 3 * GB, earned_usd: 1.2, usd_per_gb: 0.15, usd_per_gb_ram: 25.6},
      {slug: 'mysterium', name: 'Mysterium', cpu_percent: 8, memory_mb: 2048, rx_today: null, tx_today: null,
        rx: null, tx: null, earned_usd: null, usd_per_gb: null, usd_per_gb_ram: null},
    ],
    total: {cpu_percent: 9.25, memory_mb: 2096, rx_today: 2 * GB, tx_today: GB, rx: 5 * GB, tx: 3 * GB, traffic_partial: true},
  }],
});

const rows = html.split('<tr').slice(1);
const myst = rows.find(r => r.includes('Mysterium')) || '';
const hg = rows.find(r => r.includes('Honeygain')) || '';
check('server name is shown', html.includes('watchtower'), html.slice(0, 200));
check('window header says 3 days', html.includes('>3 days<'), 'header');
check('measured traffic renders in GB', hg.includes('5.0 GB') && hg.includes('3.0 GB'), hg);
check('per-GB money gets three decimals', hg.includes('$0.150'), hg);
check('memory over 1 GB renders in GB', myst.includes('2.00 GB'), myst);
check('no traffic counters renders a dash', (myst.match(/\u2014/g) || []).length >= 5, myst);
check('no traffic counters never renders 0 B', !/\b0 B\b/.test(myst), myst);
check('a row with no counters explains the dash', myst.includes('No traffic counters'), myst);
check('earned keeps two decimals', hg.includes('$1.20'), hg);
check('a total row is present', html.includes('usage-total'), html);
const total = rows.find(r => r.includes('usage-total')) || '';
check('a partial traffic total is marked as a minimum', total.includes('\u2265') && total.includes('minimum'), total);

const empty = render({servers: [], window_days: 0});
check('no readings yet says so', empty.includes('No readings yet'), empty);

if (bad) {
  console.error(`${bad} check(s) failed`);
  process.exit(1);
}
console.log('all usage panel checks passed');
