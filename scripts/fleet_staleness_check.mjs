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
// No browser needed: the running-costs check supplies the small DOM it uses.
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
// The REAL fmtTimestamp from app.js, not a stub. fleet.html reaches it through
// the CP namespace, and a stub here would let the formatter break while this
// harness stayed green — which is the whole failure mode these scripts exist to
// catch (CashPilot-2dh).
const appSrc = readFileSync('app/static/js/app.js', 'utf8');
const fnStart = appSrc.indexOf('function fmtTimestamp(');
if (fnStart < 0) throw new Error('fmtTimestamp is gone from app/static/js/app.js');
const fnRest = appSrc.slice(fnStart);
const fmtTimestamp = new Function(
  `${fnRest.slice(0, fnRest.indexOf('\n  }\n') + 4)}; return fmtTimestamp;`,
)();
const CP = {fmtTimestamp};

const source = [extract('staleNote'), extract('renderContainers'), extract('renderApps'), extract('countWorkerNames')].join('\n');
const build = new Function('esc', 'fmtBytes', 'CP', `${source}; return {renderContainers, renderApps, staleNote, countWorkerNames};`);
const {renderContainers, renderApps, staleNote, countWorkerNames} = build(esc, fmtBytes, CP);

const WORKER = {
  name: 'alpha',
  last_heartbeat: '2026-08-04 09:12',
  containers: [{slug: 'honeygain', status: 'running'}, {slug: 'traffmonetizer', status: 'running'}],
};
const APPS = [{slug: 'honeygain', running: true, net_tx_24h: 10, net_rx_24h: 20}];

const failures = [];
// Counted, not asserted. The summary line used to interpolate a hardcoded
// `${20}`, so it reported twenty assertions whether twenty ran or two did --
// a number that looked measured and was not, in a script whose whole job is
// catching exactly that.
let checksRun = 0;
const check = (name, ok, detail) => { checksRun++; if (!ok) failures.push(`${name}: ${detail}`); };

// 0. CashPilot-2dh. The DB stores UTC with no zone designator; rendering it raw
//    made a worker that heartbeated minutes ago look hours stale, right beside
//    "This host is not reachable" and one click from Remove.
const utc = '2026-08-05 04:00:00';
const shown = CP.fmtTimestamp(utc);
check('a UTC stamp is not shown verbatim', shown.text !== utc,
  `rendered "${shown.text}" unchanged, so the viewer reads UTC as local time`);
check('the original UTC is still recoverable', shown.title.includes('UTC'),
  `title was "${shown.title}"`);
check('it is parsed as UTC, not as local time',
  new Date(`${utc.replace(' ', 'T')}Z`).toLocaleString() === shown.text,
  `got "${shown.text}"`);
check('a missing stamp says never', CP.fmtTimestamp(null).text === 'never',
  JSON.stringify(CP.fmtTimestamp(null)));
check('an unreadable stamp is not invented', CP.fmtTimestamp('nonsense').text === 'nonsense',
  JSON.stringify(CP.fmtTimestamp('nonsense')));
check('the stale note uses the formatter', !staleNote(utc).includes(utc),
  staleNote(utc));

// 1. The defect itself. An unreachable host must not paint anything success-green.
const offline = renderContainers(WORKER, false);
check('offline containers are not green', !offline.includes('ctr-ok'),
  'a powered-off host still reports its containers as running');

// 2. The control. Without this, the check above passes if the chips never go
//    green at all — which would be a different bug, not a fix.
const online = renderContainers(WORKER, true);
check('online containers stay green', online.includes('ctr-ok'),
  'a reachable host stopped reporting running containers');

// 3. The state is still shown — it is useful, it just is not a measurement.
check('offline still lists the containers', offline.includes('honeygain'),
  'the container list vanished instead of being marked stale');
check('offline says so in words', offline.includes('Last known state'),
  'nothing on the card says the state is not current');
// The intent is unchanged -- the card must say WHEN this was last true -- but
// the representation is now the viewer's local time rather than raw UTC
// (CashPilot-2dh), so the assertion tracks the formatter instead of a literal.
check('offline names when it was last seen',
  offline.includes(CP.fmtTimestamp(WORKER.last_heartbeat).text),
  'the chip tooltip does not say when this was last true');
check('and it is no longer the raw UTC string', !offline.includes('2026-08-04 09:12'),
  'the raw stored value is still being shown to the viewer');

// 4. A stopped container on a LIVE host must still read as stopped, not stale.
const stoppedLive = renderContainers({...WORKER, containers: [{slug: 'grass', status: 'exited'}]}, true);
check('a stopped container on a live host is not green', !stoppedLive.includes('ctr-ok'),
  'an exited container rendered as running');
check('a live host carries no staleness note', !stoppedLive.includes('Last known state'),
  'a reachable host is being described as unreachable');

// 5. Android apps take the same rule — the bead named only containers, but the
//    same frozen-heartbeat colour was applied one function above.
const appsOffline = renderApps(APPS, false, '2026-08-04 09:12');
const appsOnline = renderApps(APPS, true, '2026-08-04 09:12');
check('offline apps are not green', !appsOffline.includes('ctr-ok'),
  'an unreachable phone still reports its apps as running');
check('online apps stay green', appsOnline.includes('ctr-ok'),
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
const ordinary = countWorkerNames(named(['charlie', 'charlie', 'alpha']));
check('an ordinary duplicate is counted', ordinary['charlie'] === 2,
  `expected 2, got ${JSON.stringify(ordinary['charlie'])}`);
check('a unique name is counted once', ordinary['alpha'] === 1,
  `expected 1, got ${JSON.stringify(ordinary['alpha'])}`);

for (const hostile of ['__proto__', 'toString', 'constructor', 'valueOf', 'hasOwnProperty']) {
  const counts = countWorkerNames(named([hostile, hostile]));
  check(`duplicate "${hostile}" is flagged`, counts[hostile] === 2,
    `count was ${JSON.stringify(counts[hostile])} — a plain {} makes this unusable`);
}
check('a single hostile name is not flagged', countWorkerNames(named(['__proto__']))['__proto__'] === 1,
  'a lone worker was reported as a duplicate');
check('no workers is not a crash', Object.keys(countWorkerNames([])).length === 0, 'empty input misbehaved');
check('undefined is not a crash', Object.keys(countWorkerNames(undefined)).length === 0, 'undefined misbehaved');

const economicsSource = html.slice(
  html.indexOf('  // Running costs: per machine,'),
  html.indexOf('  // How many workers share each display name.'),
);
const saveSource = html.slice(
  html.indexOf("  document.getElementById('fleet-economics-body').addEventListener('submit'"),
  html.indexOf("  document.getElementById('fleet-workers').addEventListener('click'"),
);
const buildEconomics = new Function(
  'document', 'CP', 'brk', '_isOwner',
  economicsSource + saveSource + '\nreturn loadFleetEconomics;',
);

function deviceFixture() {
  let stored = '10', markup = '', editor, submit, pendingNet;
  const card = {style: {}};
  const body = {
    querySelectorAll: selector => selector === '.power-device-watts' && editor ? [editor] : [],
    addEventListener: (type, handler) => { if (type === 'submit') submit = handler; },
    set innerHTML(value) {
      markup = value;
      const raw = value.match(/data-slug="ocean" value="([^"]*)"/)?.[1];
      const button = {disabled: false};
      const form = {
        querySelector: selector => selector === 'button' ? button : editor,
        matches: () => false,
        closest: () => form,
      };
      editor = {value: raw, defaultValue: raw, dataset: {slug: 'ocean'}, form};
    },
  };
  const document = {getElementById(id) {
    return {'fleet-economics-card': card, 'fleet-economics-body': body}[id];
  }};
  const api = async (path, options) => {
    if (path === '/api/config') {
      stored = options.body.data.power_device_ocean_watts;
      return {};
    }
    if (path === '/api/fleet/economics') {
      return {
        machines: [{kind: 'device', slug: 'ocean', machine: 'OCEAN', watts: stored, gross_basis: 'accrued'}],
        lan_miners: [{watts: 2.65}],
      };
    }
    const pending = pendingNet;
    pendingNet = null;
    return pending ?? {services: []};
  };
  const refresh = buildEconomics(document, {api, formatCurrency: String, toast() {}}, String, true);
  return {
    refresh, editor: () => editor, markup: () => markup, setStored: value => { stored = value; },
    stored: () => stored,
    submit: () => submit({target: editor.form, preventDefault() {}}),
    holdNextNet(promise) { pendingNet = promise; },
  };
}

for (const draft of ['25', '']) {
  const fixture = deviceFixture();
  await fixture.refresh();
  check('Fleet renders stored watts', fixture.editor().value === '10', fixture.markup());
  fixture.editor().value = draft;
  await fixture.refresh();
  check('a Fleet refresh preserves the device draft ' + JSON.stringify(draft),
    fixture.editor().value === draft, 'fresh markup replaced the draft');
  await fixture.submit();
  check('Save posts the device draft ' + JSON.stringify(draft),
    fixture.stored() === draft, 'Save posted ' + fixture.stored());
}

const racing = deviceFixture();
let finishOlder;
racing.holdNextNet(new Promise(resolve => { finishOlder = resolve; }));
const older = racing.refresh();
racing.setStored('25');
await racing.refresh();
check('a newer refresh shows the saved watts', racing.editor().value === '25', racing.markup());
finishOlder({services: []});
await older;
check('an older response cannot restore stale watts', racing.editor().value === '25', racing.markup());
check('the gross tooltip describes period accruals', racing.markup().includes('Accrued at the pool during this period'),
  'the tooltip asserts that past accruals still await payout');
check('miner watts suggest a starting point without filling the wall draw',
  racing.markup().includes('Use the miner readings above as a starting point') && racing.editor().value === '25',
  racing.markup());

const renderMiners = new Function('esc', 'brk', extract('renderMiners') + '; return renderMiners;')(esc, esc);
const miner = {
  target: 'axeos://10.0.0.4', protocol: 'axeos', ok: true, read_at: new Date().toISOString(),
  hashrate_ghs: 1000, watts: 10, best_diff: 483000, model: '<img src=x>', pool_user: '<payout>',
};
const onlineBox = {status: 'online'};
const renderMiner = (device, worker = onlineBox) => renderMiners(worker, {devices: [device], errors: []});
const readings = renderMiner(miner);
check('current miner shows rates, power and difficulty', ['cell-ok', '1 TH/s', '10 J/TH', '483k'].every(text => readings.includes(text)), readings);
check('miner model and user are escaped', readings.includes('&lt;img src=x&gt;') && readings.includes('&lt;payout&gt;'), readings);
const old = renderMiner({...miner, read_at: new Date(Date.now() - 240000).toISOString()});
const offlineMiner = renderMiner(miner, {status: 'offline'});
check('stale and offline miners show the last read in grey', [old, offlineMiner].every(row => row.includes('cell-unknown') && row.includes('Last read')), old + offlineMiner);
const ahead = renderMiner({...miner, read_at: new Date(Date.now() + 1800000).toISOString()});
check('a future miner timestamp is grey with a clock hint', ahead.includes('cell-unknown') && ahead.includes('Reading time is ahead'), ahead);
const missed = renderMiner({...miner, ok: false, error: 'timed out'});
check('a failed reading has no figures', missed.includes('timed out') && !missed.includes('TH/s') && !missed.includes(' J/TH'), missed);
check('a worker with no configuration has no miner panel', renderMiners(onlineBox, undefined) === '', 'unexpected miner panel');

// Heat credit. The form must never prefill months, must refuse a source with
// none, must post the four keys under the row's own prefix, and a touched form
// must survive the Fleet refresh.
function heatFixture({owner = true, row = {}, net = {services: []}} = {}) {
  const posts = [], toasts = [], handlers = {};
  let markup = '', renders = 0, form = null;
  const card = {style: {}};
  const build = value => {
    const block = value.match(/<form class="heat-form"[\s\S]*?<\/form>/)?.[0];
    if (!block) return null;
    const attr = re => block.match(re)?.[1];
    const months = [...block.matchAll(/class="heat-month" value="(\d+)"( checked)?/g)]
      .map(([, value, checked]) => ({value, checked: Boolean(checked)}));
    const fields = {
      '.heat-source': {value: attr(/<option value="(\w+)" selected>/) ?? 'none', classList: {contains: c => c === 'heat-source'}},
      '.heat-cop': {value: attr(/heat-cop" value="([^"]*)"/) ?? ''},
      '.heat-price': {value: attr(/heat-price" value="([^"]*)"/) ?? ''},
      '.heat-cop-field': {hidden: /class="heat-cop-field" hidden/.test(block)},
      '.heat-price-field': {hidden: /class="heat-price-field" hidden/.test(block)},
      button: {disabled: false},
    };
    const f = {
      dataset: {prefix: attr(/data-prefix="([^"]*)"/)},
      months,
      fields,
      querySelector: selector => fields[selector],
      querySelectorAll: selector => selector === '.heat-month' ? months : [],
      matches: () => false,
      closest: selector => selector === '.heat-form' ? f : null,
    };
    for (const field of Object.values(fields)) field.closest = selector => selector === '.heat-form' ? f : null;
    return f;
  };
  const body = {
    querySelectorAll: selector => selector === '.heat-form' && form ? [form] : [],
    addEventListener: (type, handler) => { handlers[type] = handler; },
    set innerHTML(value) { markup = value; renders++; form = build(value); },
  };
  const document = {getElementById: id => ({'fleet-economics-card': card, 'fleet-economics-body': body}[id])};
  const api = async (path, options) => {
    if (path === '/api/config') { posts.push(options.body.data); return {}; }
    if (path === '/api/fleet/economics') {
      return {tariff_currency: 'EUR', tariff_price_per_kwh: 0.25, machines: [{
        kind: 'machine', machine: 'Rig', summary: 'Rig earns.', monthly_gross: 1, monthly_cost: 2,
        monthly_net: 0.5, heat_credit: 1.5, heat: {source: 'heat_pump', months: [11, 12], cop: 3},
        heat_prefix: 'worker_rig', heat_settings: {heat: 'heat_pump', heat_cop: '3', heat_price: '', heat_months: '11,12'},
        break_even_tariff: {price_per_kwh: 0.069, currency: 'EUR'},
        break_even_tariff_heating: {price_per_kwh: 0.104, currency: 'EUR'},
        heat_covers_all_in_season: false,
        ...row,
      }]};
    }
    return net;
  };
  const toast = (message, kind) => toasts.push([message, kind]);
  const refresh = buildEconomics(document, {api, formatCurrency: v => `$${v}`, toast}, String, owner);
  return {
    refresh, posts, toasts, markup: () => markup, renders: () => renders, form: () => form,
    submit: () => handlers.submit({target: form, preventDefault() {}}),
    change: target => handlers.change({target}),
  };
}

const heat = heatFixture();
await heat.refresh();
check('the heat credit is its own term in the figures',
  /<span class="muted">\+<\/span>\s*<span class="econ-heat-credit"[^>]*>\$1\.5</.test(heat.markup()), heat.markup());
check('the heat credit has its own line',
  heat.markup().includes('Heat credit $1.5 a month: its heat replaces a heat pump in Nov, Dec'), heat.markup());
check('the heating-months break-even is shown',
  heat.markup().includes('in your heating months below <strong>0.104 EUR/kWh</strong>'), heat.markup());
check('the saved months come back ticked',
  heat.form().months.filter(m => m.checked).map(m => m.value).join(',') === '11,12', JSON.stringify(heat.form().months));
check('only the COP field shows for a heat pump', !heat.form().fields['.heat-cop-field'].hidden
  && heat.form().fields['.heat-price-field'].hidden, 'wrong field visibility');
heat.form().fields['.heat-source'].value = 'fuel';
heat.change(heat.form().fields['.heat-source']);
check('switching to fuel shows the fuel price field', heat.form().fields['.heat-cop-field'].hidden
  && !heat.form().fields['.heat-price-field'].hidden, 'wrong field visibility');
const rendersBefore = heat.renders();
await heat.refresh();
check('a Fleet refresh keeps a touched heat form', heat.renders() === rendersBefore, 'the draft was re-rendered away');
heat.form().fields['.heat-source'].value = 'heat_pump';
await heat.refresh();
check('an undone heat edit no longer holds the refresh', heat.renders() === rendersBefore + 1,
  'a form back at its saved state still blocked the refresh');
heat.form().fields['.heat-source'].value = 'fuel';
await heat.refresh();
heat.form().fields['.heat-source'].value = 'resistive';
heat.form().months.forEach(m => { m.checked = false; });
await heat.submit();
check('a source with no months is refused', heat.posts.length === 0
  && heat.toasts.some(([message]) => message === 'Pick the months you heat'), JSON.stringify([heat.posts, heat.toasts]));
heat.form().months.find(m => m.value === '6').checked = true;
heat.form().months.find(m => m.value === '7').checked = true;
await heat.submit();
check('Save posts the heat keys under the row prefix', JSON.stringify(heat.posts.at(-1)) === JSON.stringify({
  worker_rig_heat: 'resistive', worker_rig_heat_cop: '3', worker_rig_heat_price: '', worker_rig_heat_months: '6,7',
}), JSON.stringify(heat.posts));
check('a saved heat form re-renders', heat.renders() > rendersBefore + 1, 'the refresh after Save was held');

const fresh = heatFixture({row: {heat: null, heat_credit: undefined,
  heat_settings: {heat: '', heat_cop: '', heat_price: '', heat_months: ''}, break_even_tariff_heating: null}});
await fresh.refresh();
check('months are never prefilled', fresh.form().months.length === 12 && fresh.form().months.every(m => !m.checked),
  JSON.stringify(fresh.form().months));
check('no heat setting, no heat term', !fresh.markup().includes('econ-heat-credit') && !fresh.markup().includes('Heat credit'),
  fresh.markup());
const resistive = heatFixture({row: {heat: {source: 'resistive', months: [1]}, heat_covers_all_in_season: true,
  break_even_tariff_heating: null}});
await resistive.refresh();
check('resistive heat says it covers the electricity in season',
  resistive.markup().includes('in your heating months its heat covers its whole electricity cost'), resistive.markup());
const unknownCost = heatFixture({row: {monthly_cost: null, monthly_net: null, heat_credit: null}});
await unknownCost.refresh();
check('no cost, no heat credit shown', !unknownCost.markup().includes('econ-heat-credit')
  && !unknownCost.markup().includes('Heat credit'), unknownCost.markup());
const fixedPrice = heatFixture({row: {verdict: 'not_metered', monthly_cost: null, monthly_net: null, heat_credit: 0}});
await fixedPrice.refresh();
check('a fixed-price box offers no heat form', !fixedPrice.markup().includes('heat-form'), fixedPrice.markup());
const withService = heatFixture({net: {services: [{platform: 'xmrig', cost_attributable: true, cost: 2, gross: 1, net: -1}]}});
await withService.refresh();
check('per-service figures say they leave out the heat credit',
  withService.markup().includes('Per-service figures leave out the heat credit'), withService.markup());
const noHeatService = heatFixture({row: {heat: null, heat_credit: undefined},
  net: {services: [{platform: 'xmrig', cost_attributable: true, cost: 2, gross: 1, net: -1}]}});
await noHeatService.refresh();
check('no heat credit, no per-service heat note',
  !noHeatService.markup().includes('leave out the heat credit'), noHeatService.markup());
const heatViewer = heatFixture({owner: false});
await heatViewer.refresh();
check('viewers get no heat form', !heatViewer.markup().includes('heat-form'), heatViewer.markup());

const fleetSource = html.slice(
  html.indexOf('  // Lazily fetch the plaintext key'),
  html.indexOf('  // Running costs: per machine,'),
);
const workerSaveSource = html.slice(
  html.indexOf("  document.getElementById('fleet-workers').addEventListener('click'"),
  html.indexOf('  window.copyWorkerEnv = '),
);
const buildWorkerPower = new Function(
  'document', 'CP', 'esc', 'brk', 'CSS', '_isOwner', '_isolation', 'loadFleetEconomics', 'loadPowerSettings',
  [fleetSource, extract('countWorkerNames'), extract('renderWorkers'), extract('renderMiners'), workerSaveSource, 'return loadFleet;'].join('\n'),
);

function workerPowerFixture(owner = true) {
  const stored = {
    id: 1, client_id: 'rig', name: 'Rig', watts: 100, unmetered: false,
    system_info: {miners: {devices: [miner], errors: [], read_at: miner.read_at}},
  };
  const posts = [];
  let fields, button, click, holdWorkers, rendered = '';
  const workers = {
    addEventListener: (_, handler) => { click = handler; },
    querySelectorAll: () => fields ? [fields.unmetered] : [],
    set innerHTML(markup) {
      // loadFleet catches a render that throws and shows this state instead.
      // Fail here, or a missing helper surfaces later as a save that never posted.
      if (markup.includes('Failed to load fleet data')) throw new Error('worker power fixture: ' + markup.trim());
      rendered = markup;
      const billing = markup.match(/class="power-unmetered"[^>]*>/)?.[0] ?? '';
      const checked = /\bchecked\b/.test(billing);
      fields = {
        watts: {value: String(stored.watts)},
        dedicated: {checked: false},
        unmetered: {checked, defaultChecked: checked, dataset: {clientId: stored.client_id}},
      };
      const save = markup.match(/<button[^>]*power-save-worker[^>]*>/)?.[0];
      button = save ? {disabled: /\bdisabled\b/.test(save), dataset: {clientId: stored.client_id}} : null;
    },
  };
  const document = {
    getElementById: id => id === 'fleet-workers' ? workers : {style: {}},
    querySelector: selector => fields[selector.match(/^\.power-(\w+)/)[1]],
  };
  const api = async (path, options) => {
    if (path === '/api/fleet/summary') return {};
    if (path === '/api/workers') {
      const response = [{...stored}];
      const gate = holdWorkers;
      holdWorkers = null;
      if (gate) await gate;
      return response;
    }
    if (path !== '/api/config') throw new Error('unexpected API call ' + path);
    const data = options.body.data;
    posts.push(data);
    if ('worker_rig_unmetered' in data) stored.unmetered = data.worker_rig_unmetered === 'true';
    stored.watts = Number(data.worker_rig_watts);
    return {};
  };
  const refresh = buildWorkerPower(document, {...CP, api, toast() {}}, esc, esc, {escape: String}, owner, {}, () => {}, () => {});
  return {
    refresh, posts, stored, fields: () => fields, button: () => button, markup: () => rendered,
    save: () => click({target: {closest: selector => selector === '.power-save-worker' ? button : null}}),
    holdNextRefresh() {
      let release;
      holdWorkers = new Promise(resolve => { release = resolve; });
      return release;
    },
  };
}

const workerPower = workerPowerFixture();
await workerPower.refresh();
check('a box row shows its miners next to its billing setting',
  workerPower.markup().includes('Miners this worker reads') && workerPower.markup().includes('power-unmetered'),
  workerPower.markup());
workerPower.fields().unmetered.checked = true;
await workerPower.refresh();
check('refresh preserves an unsaved billing edit', workerPower.fields().unmetered.checked, 'the checked draft was lost');
workerPower.fields().unmetered.checked = true;
const finishStaleWorkers = workerPower.holdNextRefresh();
const staleWorkers = workerPower.refresh();
await workerPower.save();
check('Save posts a checked billing setting', workerPower.stored.unmetered, JSON.stringify(workerPower.posts));
finishStaleWorkers();
await staleWorkers;
check('a refresh started before Save cannot revert the checkbox', workerPower.fields().unmetered.checked,
  'the old unchecked response replaced the saved setting');
workerPower.fields().watts.value = '125';
await workerPower.save();
check('a wattage-only save leaves billing alone', workerPower.stored.unmetered && workerPower.stored.watts === 125
  && !('worker_rig_unmetered' in workerPower.posts.at(-1)), JSON.stringify(workerPower.posts));
await workerPower.refresh();
workerPower.fields().unmetered.checked = false;
await workerPower.save();
check('clearing and saving the checkbox posts false', !workerPower.stored.unmetered
  && workerPower.posts.at(-1).worker_rig_unmetered === 'false', JSON.stringify(workerPower.posts));

const viewerPower = workerPowerFixture(false);
await viewerPower.refresh();
check('viewers cannot save power settings', !viewerPower.button() || viewerPower.button().disabled, 'Save is enabled');
await viewerPower.save();
check('viewer clicks cannot post settings', viewerPower.posts.length === 0, JSON.stringify(viewerPower.posts));

if (failures.length) {
  console.error('fleet staleness check FAILED:');
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}
console.log(`fleet staleness check passed (${checksRun} assertions)`);
