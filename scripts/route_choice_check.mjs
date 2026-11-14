// A service routed through a proxy from its deploy runs only as a proxied copy,
// so the worker reports it under system_info.proxied, not containers. The
// dashboard must still count it as running on that box, show its route, and
// send the Route choice with a deploy. Browser-free: the real functions are
// lifted out of app.js and run against stubs, as in setup_preselect_check.mjs.
//
//   node scripts/route_choice_check.mjs
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
function domWith(value) {
  return { getElementById: id => (id === 'route-select-honeygain' && value !== null ? { value } : null) };
}
for (const [value, want] of [['3', 3], ['', undefined], [null, undefined], ['0', 0], ['-1', undefined], ['x', undefined]]) {
  const { _routeChoice } = fns(['_routeChoice'], ['document'], [domWith(value)]);
  assert.equal(_routeChoice('honeygain'), want, `select value ${JSON.stringify(value)} sends ${want}`);
}

// The deploy loop puts the choice in the body. Lifted whole and run with a stub api.
const sent = [];
const api = async (path, opts) => { sent.push({ path, body: opts.body }); return {}; };
const statusEl = { textContent: '', style: {}, innerHTML: '' };
const document = {
  getElementById: id => (id === 'route-select-honeygain' ? { value: '3' } : id.startsWith('deploy-status') ? statusEl : null),
  querySelectorAll: () => [],
};
const deploy = new Function(
  'escapeHtml', 'document', 'api', 'toast', '_confirmPreflight', '_imageChoice', '_instancesFor', '_showDeviceLink', 'wizardState',
  `${grab('_routeChoice')}\n${grab('_deployToWorkers')}\nreturn _deployToWorkers;`,
)(escapeHtml, document, api, () => {}, async () => true, () => undefined, () => undefined, () => {}, { deployed: [] });
await deploy('honeygain', [1]);
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
assert.match(grab('loadWizardSetupForms'), /loadRouteChoices\(svc\.slug\)/, 'and fills it with the proxies');
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
