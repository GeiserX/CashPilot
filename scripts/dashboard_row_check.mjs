// Run the real dashboard-row code: the Payout cell, the Payout sort, and the
// click that expands a multi-instance row.
//
// Two bugs this guards, both invisible to a string test:
//
//   * The Payout column showed "--" on every row. The row read the deployed
//     list's cashout block, which is the catalog's raw one and has no
//     min_amount_comparable; only /api/earnings/breakdown carries it. The
//     Payout sort read the same block, so sorting by it did nothing.
//
//   * Clicking an expandable row threw. The row's data-a2="event" reached
//     toggleInstances as the STRING "event" through the delegated click
//     handler, and "event".target.closest(...) is a TypeError.
//
//   node scripts/dashboard_row_check.mjs
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

let bad = 0;
let checksRun = 0;
const check = (label, cond, detail) => {
  checksRun++;
  console.log(`  ${cond ? 'ok  ' : 'FAIL'} ${label}${cond ? '' : `  <- ${detail}`}`);
  if (!cond) bad++;
};

const escapeHtml = s =>
  String(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c]);
const formatCurrency = (v, cur) => `${cur} ${Number(v).toFixed(2)}`;

// ---------------------------------------------------------------- payout
const build = new Function(
  'escapeHtml', 'formatCurrency', 'formatNative', 'diskCell', 'gpuCell', 'sortableGpu', 'sortableFreeBytes',
  'SORT_UNKNOWN', '_isOwner', '_canWrite', 'ICON_RESTART', 'ICON_STOP', 'ICON_LOGS',
  `let _sortCol = 'payout'; let _sortAsc = false;
   ${src.includes('  function cashoutFor(') ? grab('cashoutFor') : ''}
   ${grab('renderServiceRow')}
   ${grab('sortServices')}
   return {renderServiceRow, sortServices, setSort: (c, a) => { _sortCol = c; _sortAsc = a; }};`,
);
const rows = build(escapeHtml, formatCurrency, () => '', () => '', () => '', () => 0, () => 0, Symbol('u'), true, true, '', '', '');

// What /api/services/deployed sends: the catalog's cashout block, raw.
const deployed = (slug, min) => ({
  slug, name: slug, container_status: 'running', instances: 1, instance_details: [],
  cashout: {min_amount: min, method: 'redirect', dashboard_url: `https://example.test/${slug}`},
});
// What /api/earnings/breakdown sends for the same service.
const breakdown = (slug, balance, min) => ({
  platform: slug, balance, balance_adjusted: balance, signup_bonus: 0, currency: 'USD', delta: 0,
  cashout: {
    eligible: balance >= min, min_amount: min, min_amount_comparable: min, min_amount_currency: 'USD',
    method: 'redirect', dashboard_url: `https://example.test/${slug}`, notes: '',
  },
});

const half = rows.renderServiceRow(deployed('honeygain', 20), breakdown('honeygain', 10, 20));
check('a row with a known minimum shows its progress', /payout-label">50%/.test(half), half.match(/<td[^>]*>[^<]*(<span[^>]*>--<\/span>)/)?.[1] || 'no 50% label');

const none = rows.renderServiceRow(deployed('mystery', 5), undefined);
check('a row with no breakdown still says it cannot tell', !/payout-label/.test(none) && /<span class="muted">&mdash;<\/span>/.test(none), 'rendered a bar without a comparable minimum');

const services = [deployed('far', 100), deployed('close', 10), deployed('mid', 20)];
const bmap = {far: breakdown('far', 10, 100), close: breakdown('close', 9, 10), mid: breakdown('mid', 10, 20)};
rows.setSort('payout', false);
rows.sortServices(services, bmap);
const order = services.map(s => s.slug).join(',');
check('sorting by Payout puts the closest to its minimum first', order === 'close,mid,far', order);

// ---------------------------------------------------------------- expand
// Load the real delegate.js against a document that records its listener.
const listeners = {};
const fakeDocument = {
  addEventListener: (type, fn) => { listeners[type] = fn; },
  querySelectorAll: sel => (sel.includes('instance-row') ? subRows : []),
  querySelector: () => mainRow,
};
const subRows = [{style: {display: 'none'}}, {style: {display: 'none'}}];
const mainRow = {classList: {toggle: () => {}}};
const toggleInstances = new Function('document', `${grab('toggleInstances')}; return toggleInstances;`)(fakeDocument);
new Function('document', 'CP', 'window', readFileSync('app/static/js/delegate.js', 'utf8'))(
  fakeDocument, {toggleInstances}, {},
);

// The row element as the delegate sees it.
const row = {
  dataset: {action: 'toggleInstances', a1: 'honeygain', a2: 'event'},
  hasAttribute: () => false,
};
const click = target => ({target, stopPropagation() {}, preventDefault() {}});
// A click on a plain cell: the only element at or above it with data-action is the row.
const cell = {closest: sel => (sel === '[data-action]' ? row : null)};
let threw = null;
try {
  listeners.click(click(cell));
} catch (err) {
  threw = err;
}
check('clicking an expandable row does not throw', threw === null, threw && threw.message);
check('and it opens the instance rows', subRows.every(r => r.style.display === ''), JSON.stringify(subRows));

// The service name is a plain link inside the row: following it must not also
// fold the row, which is what the guard inside toggleInstances is for.
subRows.forEach(r => { r.style.display = 'none'; });
const link = {closest: sel => (sel === '[data-action]' ? row : {tagName: 'A'})};
try {
  listeners.click(click(link));
} catch (err) {
  threw = err;
}
check('clicking the name link inside the row leaves it alone', threw === null && subRows.every(r => r.style.display === 'none'), threw ? threw.message : JSON.stringify(subRows));

console.log(`\n${bad ? `${bad} FAILED` : 'all passed'} (${checksRun} assertions)`);
process.exit(bad ? 1 : 0);
