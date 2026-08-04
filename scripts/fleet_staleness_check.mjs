// Run the REAL fleet.html chip renderers and check what colour they claim.
//
// CashPilot-1m8: a worker whose host is powered off still rendered a row of
// success-green container chips, coloured from the status frozen into its last
// heartbeat. The only counter-signal was a grey dot elsewhere on the card, and
// green is the louder signal — the user reads "honeygain, traffmonetizer" as
// running on a machine CashPilot has not heard from in hours.
//
// pytest cannot see this. The renderers live inside a <script> block in a Jinja
// template, and a text assertion on the template would only prove the source
// contains a variable name, not what colour a given worker produces. So the
// functions are extracted and run for real, on both an online and an offline
// worker, and the OUTPUT is inspected.
//
// No browser needed: these renderers build strings and touch no DOM.
//   node scripts/fleet_staleness_check.mjs
// Exits non-zero on any mismatch.
import {readFileSync} from 'node:fs';

const html = readFileSync('app/templates/fleet.html', 'utf8');

function extract(name) {
  const start = html.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`fleet.html no longer defines ${name}() — this check is stale`);
  // Walk braces from the first { after the signature to find the real end.
  let i = html.indexOf('{', start), depth = 0;
  for (let j = i; j < html.length; j++) {
    if (html[j] === '{') depth++;
    else if (html[j] === '}' && --depth === 0) return html.slice(start, j + 1);
  }
  throw new Error(`unbalanced braces reading ${name}()`);
}

const esc = s => String(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const fmtBytes = b => `${b}B`;
const source = [extract('staleNote'), extract('renderContainers'), extract('renderApps'), extract('countWorkerNames')].join('\n');
const build = new Function('esc', 'fmtBytes', `${source}; return {renderContainers, renderApps, staleNote, countWorkerNames};`);
const {renderContainers, renderApps, countWorkerNames} = build(esc, fmtBytes);

const WORKER = {
  name: 'geiserback',
  last_heartbeat: '2026-08-04 09:12',
  containers: [{slug: 'honeygain', status: 'running'}, {slug: 'traffmonetizer', status: 'running'}],
};
const APPS = [{slug: 'honeygain', running: true, net_tx_24h: 10, net_rx_24h: 20}];

const failures = [];
const check = (name, ok, detail) => { if (!ok) failures.push(`${name}: ${detail}`); };

// 1. The defect itself. An unreachable host must not paint anything success-green.
const offline = renderContainers(WORKER, false);
check('offline containers are not green', !offline.includes('var(--success)'),
  'a powered-off host still reports its containers as running');

// 2. The control. Without this, the check above passes if the chips never go
//    green at all — which would be a different bug, not a fix.
const online = renderContainers(WORKER, true);
check('online containers stay green', online.includes('var(--success)'),
  'a reachable host stopped reporting running containers');

// 3. The state is still shown — it is useful, it just is not a measurement.
check('offline still lists the containers', offline.includes('honeygain'),
  'the container list vanished instead of being marked stale');
check('offline says so in words', offline.includes('Last known state'),
  'nothing on the card says the state is not current');
check('offline names when it was last seen', offline.includes('2026-08-04 09:12'),
  'the chip tooltip does not say when this was last true');

// 4. A stopped container on a LIVE host must still read as stopped, not stale.
const stoppedLive = renderContainers({...WORKER, containers: [{slug: 'grass', status: 'exited'}]}, true);
check('a stopped container on a live host is not green', !stoppedLive.includes('var(--success)'),
  'an exited container rendered as running');
check('a live host carries no staleness note', !stoppedLive.includes('Last known state'),
  'a reachable host is being described as unreachable');

// 5. Android apps take the same rule — the bead named only containers, but the
//    same frozen-heartbeat colour was applied one function above.
const appsOffline = renderApps(APPS, false, '2026-08-04 09:12');
const appsOnline = renderApps(APPS, true, '2026-08-04 09:12');
check('offline apps are not green', !appsOffline.includes('var(--success)'),
  'an unreachable phone still reports its apps as running');
check('online apps stay green', appsOnline.includes('var(--success)'),
  'a reachable phone stopped reporting running apps');
check('app traffic tooltip survives', appsOnline.includes('24h:'),
  'the traffic tooltip was lost while adding the staleness one');
check('offline apps keep both tooltips', appsOffline.includes('Last reported') && appsOffline.includes('24h:'),
  'the staleness note replaced the traffic figures instead of joining them');

// 6. Duplicate display names, including names that collide with Object's own
//    keys. A worker name is user-controlled (CASHPILOT_WORKER_NAME), and on a
//    plain {} a name of "__proto__" or "toString" makes the count unusable —
//    so two such workers are never flagged, which is the one case the feature
//    exists for. This cannot be seen from the source; it has to be run.
const named = names => names.map(n => ({name: n}));
const ordinary = countWorkerNames(named(['watchtower', 'watchtower', 'geiserback']));
check('an ordinary duplicate is counted', ordinary['watchtower'] === 2,
  `expected 2, got ${JSON.stringify(ordinary['watchtower'])}`);
check('a unique name is counted once', ordinary['geiserback'] === 1,
  `expected 1, got ${JSON.stringify(ordinary['geiserback'])}`);

for (const hostile of ['__proto__', 'toString', 'constructor', 'valueOf', 'hasOwnProperty']) {
  const counts = countWorkerNames(named([hostile, hostile]));
  check(`duplicate "${hostile}" is flagged`, counts[hostile] === 2,
    `count was ${JSON.stringify(counts[hostile])} — a plain {} makes this unusable`);
}
check('a single hostile name is not flagged', countWorkerNames(named(['__proto__']))['__proto__'] === 1,
  'a lone worker was reported as a duplicate');
check('no workers is not a crash', Object.keys(countWorkerNames([])).length === 0, 'empty input misbehaved');
check('undefined is not a crash', Object.keys(countWorkerNames(undefined)).length === 0, 'undefined misbehaved');

if (failures.length) {
  console.error('fleet staleness check FAILED:');
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}
console.log(`fleet staleness check passed (${20} assertions)`);
