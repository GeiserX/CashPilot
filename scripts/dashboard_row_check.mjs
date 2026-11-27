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
import './i18n_stub.mjs';
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
   const capFirst = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : '');
   ${grab('statusLabelOf')}
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

// ---------------------------------------------------------------- route
// A service routed through a proxy from its deploy shows where it leaves
// from, as the service page does: on the row itself for one copy, and on the
// copy's own row once there are several. docs/proxies.md promises it.
const routedRows = new Function(
  'escapeHtml', 'formatCurrency', 'formatNative', 'diskCell', 'gpuCell', 'diskCellForHosts', 'gpuCellForHosts',
  'hostForWorker', 'fmtNetBytes', '_isOwner', '_canWrite', 'ICON_RESTART', 'ICON_STOP', 'ICON_LOGS',
  `${grab('instanceState')}
   ${grab('routeBadge')}
   ${src.includes('  function cashoutFor(') ? grab('cashoutFor') : ''}
   const capFirst = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : '');
   ${grab('statusLabelOf')}
   ${grab('renderServiceRow')}
   return renderServiceRow;`,
)(escapeHtml, formatCurrency, () => '', () => '', () => '', () => '', () => '', () => [], () => '', true, true, '', '', '');
const copy = (node, workerId, route) => ({
  node, worker_id: workerId, status: 'running', cpu: '1.00', memory: '10.0 MB', container_name: '',
  has_docker: true, can_command: true, is_android: false, instance: 1, ...(route ? {route} : {}),
});
const routedSvc = details => ({
  slug: 'honeygain', name: 'Honeygain', container_status: 'running', instances: details.length,
  cpu: '1.00', memory: '10.0 MB', instance_details: details, cashout: {},
});
const exit = {proxy_id: 3, exit_ip: '203.0.113.9', exit_country: 'DE'};

const single = routedRows(routedSvc([copy('box', 1, exit)]), undefined);
check('a routed service with one copy shows its exit on the row', /badge-routed[^>]*>via proxy 203\.0\.113\.9 \(DE\)</.test(single), 'no "via proxy 203.0.113.9 (DE)" badge');

const multi = routedRows(routedSvc([copy('box', 1, exit), copy('other', 2)]), undefined);
const subRowsHtml = multi.split('class="instance-row"').slice(1);
check('the routed copy row shows its exit', subRowsHtml.length === 2 && /via proxy 203\.0\.113\.9 \(DE\)/.test(subRowsHtml[0]), subRowsHtml[0] || 'no instance rows');
check('the direct copy row shows none', subRowsHtml.length === 2 && !/badge-routed/.test(subRowsHtml[1]), subRowsHtml[1] || 'no instance rows');

const direct = routedRows(routedSvc([copy('box', 1)]), undefined);
check('a direct service shows no route', !/badge-routed/.test(direct), 'rendered a route badge without a route');

const hostile = routedRows(routedSvc([copy('box', 1, {proxy_id: 3, exit_ip: '<img src=x onerror=alert(1)>', exit_country: '"><b>'})]), undefined);
check('the exit is escaped', !/<img|<b>/.test(hostile) && /&lt;img/.test(hostile), 'an exit IP reached the row as HTML');

// ---------------------------------------------------------------- joined Desktop
// A joined Desktop never reports docker_available, so has_docker is false on its
// copies. One that reports a command URL takes start, stop, restart and logs all the
// same (can_command); one without a URL only reports, and its row says so.
const desktopCopy = (canCommand) => ({
  ...copy('my-pc', 5), has_docker: false, can_command: canCommand, desktop_report_only: !canCommand,
});
const stopBtn = html => (html.match(/<button[^>]*data-action="stopService"[^>]*>/) || [''])[0];
// A browser keeps the FIRST of two title attributes, so the reason must come first.
const shownTitle = tag => (tag.match(/title="([^"]*)"/) || [])[1];
const commanded = routedRows(routedSvc([desktopCopy(true)]), undefined);
check('a Desktop that takes commands has a live Stop button', stopBtn(commanded) && !/disabled/.test(stopBtn(commanded)), stopBtn(commanded) || 'no Stop button');
const reporting = routedRows(routedSvc([desktopCopy(false)]), undefined);
check('a Desktop that only reports has Stop off, and says why', /disabled/.test(stopBtn(reporting)) && /^This Desktop only reports/.test(shownTitle(stopBtn(reporting)) || ''), stopBtn(reporting) || 'no Stop button');
// The switch is not the only reason a Desktop sends no URL: on Windows it waits for
// the firewall rule, and it needs a private network or Tailscale address.
check('the reason names the switch, the firewall and the address', ['switch', 'Windows Firewall', 'Tailscale address'].every(w => (shownTitle(stopBtn(reporting)) || '').includes(w)), shownTitle(stopBtn(reporting)) || 'no title');
const noDocker = routedRows(routedSvc([{...copy('nas', 1), has_docker: false, can_command: false}]), undefined);
check('a Docker box without Docker still shows its own reason', shownTitle(stopBtn(noDocker)) === 'No Docker access', stopBtn(noDocker) || 'no Stop button');
const mixed = routedRows(routedSvc([desktopCopy(true), {...copy('nas', 1)}]), undefined).split('class="instance-row"').slice(1);
check('a Desktop copy row in a multi-copy service has a live Stop button', mixed.length === 2 && stopBtn(mixed[0]) && !/disabled/.test(stopBtn(mixed[0])), mixed[0] || 'no instance rows');
const stoppable = new Function(`${grab('stoppableCopies')}; return stoppableCopies;`)();
check('Stop on all servers includes a Desktop that takes commands', stoppable({instance_details: [desktopCopy(true), desktopCopy(false)]}).length === 1, 'wrong count');

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
