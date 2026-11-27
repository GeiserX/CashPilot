// A service routed through a proxy from its deploy runs only as a proxied copy,
// so the worker reports it under system_info.proxied, not containers. The
// dashboard must still count it as running on that box, show its route, and
// send the Route choice with a deploy. Browser-free: the real functions are
// lifted out of app.js and run against stubs, as in setup_preselect_check.mjs.
//
//   node scripts/route_choice_check.mjs
import './i18n_stub.mjs';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync('app/static/js/app.js', 'utf8');
const escapeHtml = value => String(value).replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;');
const grab = name => {
  const offset = src.search(new RegExp(`  (?:async )?function ${name}\\(`));
  assert.ok(offset >= 0, `${name} is in app.js`);
  const rest = src.slice(offset);
  const next = rest.search(/\n  (?:async )?function /);
  return next >= 0 ? rest.slice(0, next) : rest;
};

const fns = (names, args = [], values = []) => new Function(
  'escapeHtml', ...args,
  `${names.map(grab).join('\n')}\nreturn { ${names.join(', ')} };`,
)(escapeHtml, ...values);

const { runsOn, workerCopies, routeBadge, routeChoiceSection } = fns(
  ['runsOn', 'workerCopies', 'routeBadge', 'routeChoiceSection'],
);

// ---- A routed copy counts as the service on that box -------------------------
const routedBox = {
  id: 1, name: 'box1', containers: [],
  system_info: {
    proxied: [
      { slug: 'honeygain', proxy_id: 3, status: 'running', routed: true, exit_ip: '203.0.113.9', exit_country: 'DE' },
      // A copy beside a direct deploy is not the service itself: its own page lists it.
      { slug: 'earnapp', proxy_id: 3, status: 'running', exit_ip: '203.0.113.9' },
    ],
  },
};
assert.equal(runsOn(routedBox, 'honeygain'), true, 'a routed service runs on its box');
assert.equal(runsOn(routedBox, 'earnapp'), false, 'an ordinary proxied copy is not the service');
assert.equal(runsOn({ id: 2, containers: [{ slug: 'honeygain' }] }, 'honeygain'), true, 'a direct container still counts');
assert.equal(runsOn({ id: 3, system_info: { proxied: null } }, 'honeygain'), false, 'an unreadable list is no copy');
const [copy] = workerCopies(routedBox, 'honeygain');
assert.deepEqual(copy.route, { proxy_id: 3, exit_ip: '203.0.113.9', exit_country: 'DE' });
assert.equal(copy.instance, 1, 'a routed copy is the box\'s first copy, so its buttons act on it');

// ---- Its badge names the exit, escaped ----------------------------------------
assert.match(routeBadge(copy), /via proxy 203\.0\.113\.9 \(DE\)/);
assert.equal(routeBadge({ slug: 'x' }), '', 'a direct copy has no badge');
const hostile = routeBadge({ route: { exit_ip: '<img src=x>', exit_country: '"' } });
assert.doesNotMatch(hostile, /<img/, 'the exit IP is escaped');

// ---- The Route box -------------------------------------------------------------
assert.match(routeChoiceSection({ slug: 'honeygain' }), /<select[^>]*id="route-select-honeygain"/);
assert.match(routeChoiceSection({ slug: 'honeygain' }), /<option value="">Direct: the box's own IP<\/option>/);
const refused = routeChoiceSection({ slug: 'storj', route_refusal: 'Storj publishes a port <on the host>.' });
assert.doesNotMatch(refused, /<select/, 'a service the catalog cannot route has no Route box');
assert.match(refused, /publishes a port &lt;on the host>/, 'and says why, escaped');
console.log('Routed copies: counted on their box, badged with their exit, and the Route box only where allowed.');

// ---- What a deploy sends -------------------------------------------------------
// A form root: its Route box is found inside it, never by a document-wide id.
const formRoot = select => ({
  querySelector: sel => (sel === 'select[id="route-select-honeygain"]' ? select : null),
});
// Another form's box, which a document-wide lookup by id would find instead.
const elsewhere = { getElementById: () => ({ value: '9' }) };
for (const [value, want] of [['3', 3], ['', undefined], [null, undefined], ['0', 0], ['-1', undefined], ['x', undefined]]) {
  const { _routeChoice } = fns(['_routeSelect', '_routeChoice'], ['document'], [elsewhere]);
  const root = formRoot(value === null ? null : { value });
  assert.equal(_routeChoice(root, 'honeygain'), want, `select value ${JSON.stringify(value)} sends ${want}`);
}
assert.equal(
  fns(['_routeSelect', '_routeChoice'], ['document'], [elsewhere])._routeChoice(null, 'honeygain'), undefined,
  'no form: no route',
);

// The deploy loop puts the choice in the body. Lifted whole and run with a stub api.
const sent = [];
const api = async (path, opts) => { sent.push({ path, body: opts.body }); return {}; };
const statusEl = { textContent: '', style: {}, innerHTML: '' };
const document = {
  getElementById: id => (id.startsWith('deploy-status') ? statusEl : null),
  querySelectorAll: () => [],
};
const deploy = new Function(
  'escapeHtml', 'document', 'api', 'toast', '_confirmPreflight', '_imageChoice', '_instancesFor', '_showDeviceLink', 'wizardState',
  '_confirmDeviceRenames',
  `${grab('_routeSelect')}\n${grab('_routeChoice')}\nconst _walletRequest = () => undefined;\n${grab('_deployToWorkers')}\nreturn _deployToWorkers;`,
)(escapeHtml, document, api, () => {}, async () => true, () => undefined, () => undefined, () => {}, { deployed: [] },
  async () => false);
await deploy('honeygain', [1], { routeRoot: formRoot({ value: '3' }) });
assert.equal(sent.length, 1);
assert.equal(sent[0].path, '/api/deploy/honeygain?worker_id=1');
assert.equal(sent[0].body.route, 3, 'the chosen proxy goes with the deploy');
console.log('Deploy: the chosen route is sent; the box\'s own IP sends none.');

// ---- Leaving a route: Direct is its own choice where the service is routed ----
const routedForm = routeChoiceSection({ slug: 'honeygain', routes: { 1: 3 } });
assert.match(routedForm, /<option value="">Keep the route each box has/, 'the default keeps the route');
assert.match(routedForm, /<option value="0">Direct: the box's own IP<\/option>/, 'Direct sends 0, which leaves it');
assert.doesNotMatch(
  routeChoiceSection({ slug: 'honeygain', routes: {} }), /value="0"/, 'nothing routed: Direct is the default, no 0',
);
console.log('Route box: where a service is routed, Direct is a choice that leaves the route.');

// ---- The setup wizard offers the Route box too ---------------------------------
assert.match(grab('renderServiceSetupForm'), /routeChoiceSection\(svc\)/, 'the wizard form has the Route box');
assert.match(grab('loadWizardSetupForms'), /loadRouteChoices\(svc\.slug, container\)/, 'and fills its own form\'s box with the proxies');
assert.match(grab('openServiceDetail'), /loadRouteChoices\(svc\.slug, body\)/, 'the service page fills its own box');
console.log('Setup wizard: the Route box is shown and filled.');

// ---- An image update reaches the boxes where the service is routed --------------
for (const name of ['imageChoiceSection', 'redeployWithImage']) {
  const body = grab(name);
  assert.match(body, /runsOn\(w, (svc\.)?slug\)/, `${name} counts a routed box`);
  assert.doesNotMatch(body, /\(w\.containers \|\| \[\]\)\.some/, `${name} does not look at containers alone`);
}
const { imageChoiceSection } = fns(['runsOn', 'workerCopies', 'imageChoiceSection'], ['_isOwner'], [true]);
const imageBox = imageChoiceSection({ slug: 'honeygain', name: 'Honeygain', docker: { image: 'h/h' } }, [
  { ...routedBox, status: 'online' },
]);
assert.match(imageBox, /redeployWithImage/, 'a routed-only box gets the image update button');
console.log('Image update: a box where the service runs through a proxy is included.');

// ---- Changing the route of a box that already runs it routed --------------------
// The real form: the worker rows and the Route box, the Route box's change
// handler, and the Deploy action, against a small DOM of the rendered checkboxes.
function formDom(rowsHtml, routeValue) {
  const boxes = [...rowsHtml.matchAll(/<input type="checkbox" ([^>]*)>/g)].map(([, attrText]) => {
    const attrs = {};
    for (const [, k, v] of attrText.matchAll(/([\w-]+)(?:="([^"]*)")?/g)) attrs[k] = v ?? '';
    const dataset = {};
    for (const [k, v] of Object.entries(attrs)) {
      if (k.startsWith('data-')) dataset[k.slice(5).replace(/-(\w)/g, (_, c) => c.toUpperCase())] = v;
    }
    return { attrs, dataset, classes: new Set((attrs.class || '').split(/\s+/)), disabled: 'disabled' in attrs, checked: 'checked' in attrs };
  });
  const matches = (el, selector) => {
    let rest = selector;
    const take = re => { const m = rest.match(re); if (m) rest = rest.slice(m[0].length); return m; };
    while (rest) {
      let m;
      if (take(/^input/)) continue;
      if ((m = take(/^\.([\w-]+)/))) { if (!el.classes.has(m[1])) return false; continue; }
      if ((m = take(/^\[([\w-]+)(?:="([^"]*)")?\]/))) {
        if (!(m[1] in el.attrs) || (m[2] !== undefined && el.attrs[m[1]] !== m[2])) return false;
        continue;
      }
      if (take(/^:checked/)) { if (!el.checked) return false; continue; }
      if (take(/^:not\(:disabled\)/)) { if (el.disabled) return false; continue; }
      if ((m = take(/^:not\(\[([\w-]+)\]\)/))) { if (m[1] in el.attrs) return false; continue; }
      throw new Error(`the form check cannot read the selector ${selector}`);
    }
    return true;
  };
  const select = { value: routeValue, dataset: { slug: 'honeygain' }, closest: () => null };
  // The setup wizard's own Route box, hidden but still in the DOM and first in
  // it: a document-wide lookup by id finds this one, on the box's own IP.
  const wizardSelect = { value: '', dataset: { slug: 'honeygain' }, closest: () => null };
  const sent = [];
  const doc = {
    boxes,
    select,
    wizardSelect,
    sent,
    querySelectorAll: sel => (sel.startsWith('.instances-input') ? [] : boxes.filter(el => matches(el, sel))),
    getElementById: id => (id === 'route-select-honeygain' ? wizardSelect
      : id === 'service-detail-body' ? formRoot(select)
        : id === 'wizard-setup-forms' ? formRoot(wizardSelect) : null),
  };
  return doc;
}

const routedSvc = { slug: 'honeygain', name: 'Honeygain', routes: { 1: 3 }, max_instances: 1 };
const directBox = { id: 2, name: 'box2', containers: [{ slug: 'honeygain' }], system_info: {} };
const newBox = { id: 4, name: 'box4', containers: [], system_info: {} };
const { workerCheckboxList } = fns(['workerCopies', 'isDesktopWorker', 'workerCheckboxList']);

// A joined Desktop that takes commands is a deploy target, and says it is a Desktop.
{
  const desktop = { id: 5, name: 'my-pc', url: 'http://192.168.1.30:8086', containers: [], system_info: { device_type: 'desktop' } };
  const html = workerCheckboxList(routedSvc, [desktop, newBox], 'deploy-worker-cb').rows;
  assert.match(html, /data-wid="5"[^>]*>\s*<span class="worker-pick-name">my-pc<\/span>\s*<span class="badge"[^>]*>Desktop<\/span>/, 'the Desktop row carries a Desktop badge');
  assert.equal((html.match(/>Desktop</g) || []).length, 1, 'a Docker box carries no Desktop badge');
}

// Routed on its only box: the form stays, so the Route box is there to change it.
assert.equal(workerCheckboxList(routedSvc, [routedBox]).allDeployed, false, 'a routed box keeps the form on screen');
assert.equal(
  workerCheckboxList({ ...routedSvc, routes: {} }, [directBox]).allDeployed, true,
  'a box running it direct, with nothing to switch, still hides it',
);

const { rows } = workerCheckboxList(routedSvc, [routedBox, directBox, newBox], 'deploy-worker-cb');
async function pick(routeValue, tick = []) {
  const dom = formDom(rows, routeValue);
  const calls = [];
  const api = async (path, opts) => { calls.push({ path, route: opts.body.route }); return {}; };
  const live = new Function(
    'escapeHtml', 'document', 'api', 'toast', '_confirmPreflight', '_imageChoice', '_instancesFor', '_showDeviceLink',
    'wizardState', '_confirmDeviceRenames',
    ['_routeSwitchBoxes', '_routeSelect', '_routeChoice', '_selectedWorkerIds', '_rescaledWorkerIds', '_deployToWorkers',
      'deployServiceToWorkers'].map(grab).join('\n') + '\nconst _walletRequest = () => undefined;'
      + '\nreturn { _routeSwitchBoxes, deployServiceToWorkers };',
  )(escapeHtml, dom, api, () => {}, async () => true, () => undefined, () => undefined, () => {}, { deployed: [] },
    async () => false);
  live._routeSwitchBoxes(dom.select);
  for (const wid of tick) {
    const box = dom.boxes.find(b => b.dataset.wid === String(wid));
    if (!box.disabled) box.checked = true;
  }
  await live.deployServiceToWorkers('honeygain');
  return { dom, calls };
}
const box1 = dom => dom.boxes.find(b => b.dataset.wid === '1');

let run = await pick('', [1]);
assert.equal(box1(run.dom).disabled, true, 'on the default the routed box stays locked');
assert.equal(box1(run.dom).checked, true, 'and ticked, as any deployed box');
assert.deepEqual(run.calls, [], 'so a plain Deploy never touches it, and never asks to leave its route');

run = await pick('0', [1]);
assert.equal(box1(run.dom).disabled, false, 'Direct unlocks the routed box');
assert.deepEqual(run.calls, [{ path: '/api/deploy/honeygain?worker_id=1', route: 0 }], 'ticked, it gets route 0');
assert.equal(
  run.dom.boxes.find(b => b.dataset.wid === '2').disabled, true, 'a box running it direct stays locked',
);

run = await pick('0');
assert.equal(box1(run.dom).checked, false, 'unlocked unticked: the switch needs a tick of its own');
assert.deepEqual(run.calls, [], 'nothing ticked, nothing sent');

run = await pick('7', [1, 4]);
assert.equal(box1(run.dom).disabled, true, 'another proxy keeps the routed box locked: the server refuses that move');
assert.deepEqual(
  run.calls.map(c => [c.path, c.route]),
  [['/api/deploy/honeygain?worker_id=4', 7]],
  'another proxy goes to the new box only, never to the routed one',
);

run = await pick('', []);
run.dom.select.value = '0';
const again = new Function('document', `${grab('_routeSwitchBoxes')}\nreturn _routeSwitchBoxes;`)(run.dom);
again(run.dom.select);
assert.equal(box1(run.dom).disabled, false);
run.dom.select.value = '';
again(run.dom.select);
assert.equal(box1(run.dom).disabled, true, 'back on the default it is locked again');
assert.equal(box1(run.dom).checked, true, 'and ticked again');
console.log('Route change: a routed box is selectable only once Direct is chosen, and sends it.');

// ---- A changed Instances count never moves a routed box off its route -----------
// Direct unlocks the routed box unticked; its Instances box can still change.
for (const [routeValue, want] of [['0', []], ['', [{ path: '/api/deploy/honeygain?worker_id=1', route: undefined }]]]) {
  const dom = formDom(rows, routeValue);
  const instances = [{ dataset: { slug: 'honeygain', wid: '1', current: '1' }, value: '2', disabled: false }];
  const boxesOnly = dom.querySelectorAll;
  dom.querySelectorAll = sel => (sel.startsWith('.instances-input') ? instances : boxesOnly(sel));
  const calls = [];
  const api = async (path, opts) => { calls.push({ path, route: opts.body.route }); return {}; };
  const live = new Function(
    'escapeHtml', 'document', 'api', 'toast', '_confirmPreflight', '_imageChoice', '_instancesFor', '_showDeviceLink',
    'wizardState', '_confirmDeviceRenames', 'window',
    ['_routeSwitchBoxes', '_routeSelect', '_routeChoice', '_selectedWorkerIds', '_rescaledWorkerIds', '_deployToWorkers',
      'deployServiceToWorkers'].map(grab).join('\n') + '\nconst _walletRequest = () => undefined;'
      + '\nreturn { _routeSwitchBoxes, deployServiceToWorkers };',
  )(escapeHtml, dom, api, () => {}, async () => true, () => undefined, () => undefined, () => {}, { deployed: [] },
    async () => false, { confirm: () => true });
  live._routeSwitchBoxes(dom.select);
  await live.deployServiceToWorkers('honeygain');
  assert.deepEqual(
    calls, want,
    routeValue === '0'
      ? 'Direct with the routed box unticked: its new count sends nothing, so it keeps its route'
      : 'control: on the default a new count rescales it and keeps its route',
  );
}
console.log('Instances: a changed count rescales a routed box on its route, never off it.');

// ---- Two forms in the DOM: each deploy reads its own Route box ------------------
// The wizard's form stays in the DOM, hidden, while the service page is open.
{
  const dom = formDom(rows, '7');
  const calls = [];
  const api = async (path, opts) => { calls.push({ path, route: opts.body.route }); return {}; };
  const live = new Function(
    'escapeHtml', 'document', 'api', 'toast', '_confirmPreflight', '_imageChoice', '_instancesFor', '_showDeviceLink',
    'wizardState', '_confirmDeviceRenames',
    ['_routeSelect', '_routeChoice', '_selectedWorkerIds', '_rescaledWorkerIds', '_deployToWorkers',
      'deployServiceToWorkers', 'deployService'].map(grab).join('\n') + '\nconst _walletRequest = () => undefined;'
      + '\nreturn { deployServiceToWorkers, deployService };',
  )(escapeHtml, dom, api, () => {}, async () => true, () => undefined, () => undefined, () => {}, { deployed: [] },
    async () => false);
  dom.boxes.find(b => b.dataset.wid === '4').checked = true;
  await live.deployServiceToWorkers('honeygain');
  assert.deepEqual(calls, [{ path: '/api/deploy/honeygain?worker_id=4', route: 7 }],
    'the service page sends its own Route box, not the hidden wizard one');
}

// ---- The route is read once for every box of one deploy -------------------------
{
  const select = { value: '7' };
  const calls = [];
  // The owner switches the Route box back while the first box deploys.
  const api = async (path, opts) => { calls.push({ path, route: opts.body.route }); select.value = ''; return {}; };
  const deploy = new Function(
    'escapeHtml', 'document', 'api', 'toast', '_confirmPreflight', '_imageChoice', '_instancesFor', '_showDeviceLink',
    'wizardState', '_confirmDeviceRenames',
    `${grab('_routeSelect')}\n${grab('_routeChoice')}\nconst _walletRequest = () => undefined;\n${grab('_deployToWorkers')}\nreturn _deployToWorkers;`,
  )(escapeHtml, { getElementById: () => null, querySelectorAll: () => [] }, api, () => {},
    async () => { select.value = '7'; return true; }, () => undefined, () => undefined, () => {}, { deployed: [] },
    async () => false);
  // A change before the first wait is still this deploy's choice; after it, never.
  select.value = '7';
  await deploy('honeygain', [1, 4], { routeRoot: formRoot(select) });
  assert.deepEqual(calls.map(c => c.route), [7, 7], 'every box of one deploy gets the route it started with');
}

// ---- Each form's Route box is filled with the proxies ---------------------------
{
  const made = [];
  const mk = () => ({ value: '', children: [], listeners: 0, addEventListener() { this.listeners++; },
    appendChild(o) { this.children.push(o); } });
  const wizard = mk();
  const detail = mk();
  const document = {
    getElementById: id => (id === 'route-select-honeygain' ? wizard : null),
    createElement: () => { const o = {}; made.push(o); return o; },
  };
  const { loadRouteChoices } = fns(
    ['_routeSelect', 'loadRouteChoices'], ['document', 'api', '_isOwner', '_routeSwitchBoxes'],
    [document, async () => ({ proxies: [{ id: 7, name: 'Home' }] }), true, () => {}],
  );
  await loadRouteChoices('honeygain', formRoot(detail));
  assert.equal(detail.children.length, 1, 'the service page Route box gets the proxies');
  assert.equal(detail.listeners, 1, 'and its change handler');
  assert.equal(wizard.children.length + wizard.listeners, 0, 'the hidden wizard box is not touched');
}
console.log('Two forms: each deploy and each fill uses the Route box of its own form, read once per deploy.');

// ---- The device-name checks reach a box that runs only the routed service -------
// A pending copy (p9) beside the routed service (p4) on a box with no direct
// container gets its rename button only if the check asks about that box.
{
  const workers = [
    { id: 1, status: 'online', containers: [], system_info: { proxied: [{ slug: 'honeygain', proxy_id: 4, routed: true }] } },
    { id: 2, status: 'online', containers: [{ slug: 'honeygain' }] },
    { id: 3, status: 'offline', containers: [{ slug: 'honeygain' }] },
    { id: 5, status: 'online', containers: [], system_info: { proxied: [{ slug: 'honeygain', proxy_id: 4 }] } },
  ];
  const { _runningWorkerIds } = fns(['runsOn', 'workerCopies', '_runningWorkerIds'], ['_detailWorkers'], [workers]);
  assert.deepEqual(_runningWorkerIds('honeygain'), [1, 2], 'a routed-only box is checked for device names');
}
console.log('Device names: a box that runs only the routed service is checked too.');

// ---- A routed start or stop the worker could not make durable shows its warning --
// The worker answers 2xx with a warning when the copy started or stopped but its
// record may not survive a power cut. Every Start, Stop and Restart path shows it.
{
  const warning = 'cashpilot-honeygain-p3 was stopped, but the stop may not survive a power cut.';
  const names = ['startService', 'stopService', 'restartService', 'workerAction', 'stopEverywhere'];
  for (const name of names) {
    const toasts = [];
    const api = async url => (url === '/api/services/deployed'
      ? [{ slug: 'honeygain', name: 'Honeygain' }]
      : { status: 'stopped', durable: false, warning });
    const { [name]: fn } = fns(
      [name],
      ['api', 'toast', 'loadServicesTable', 'openServiceDetail', '_instanceQuery', 'stoppableCopies', 'confirm'],
      [api, (msg, kind) => toasts.push([kind, msg]), () => {}, () => {}, () => '',
        () => [{ worker_id: 1, instance: 1, node: 'box1' }], () => true],
    );
    await (name === 'workerAction' ? fn('honeygain', 'stop', 1, 1) : fn('honeygain', 1, 1));
    assert.ok(
      toasts.some(([kind, msg]) => kind === 'warning' && msg.includes(warning)),
      `${name} shows the worker's warning (got ${JSON.stringify(toasts)})`,
    );
  }
}
console.log('Durable warnings: every routed Start, Stop and Restart path shows the worker warning.');
