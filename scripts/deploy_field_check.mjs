// A catalog `pattern` reaches the browser and stops a wrong value before the
// deploy request, in both forms that build env fields (the wizard and the
// service detail page). Browser-free: the functions are lifted out of app.js
// and run against stand-ins, the way currency_check.mjs does it.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync('app/static/js/app.js', 'utf8');
const escapeHtml = value => String(value).replaceAll('&', '&amp;').replaceAll('"', '&quot;');
const grab = name => {
  const offset = src.search(new RegExp(`  (?:async )?function ${name}\\(`));
  assert.ok(offset >= 0, name);
  const rest = src.slice(offset);
  const next = rest.search(/\n  (?:async )?function /);
  return next >= 0 ? rest.slice(0, next) : rest;
};

// A secret field with a pattern renders the pattern and asks the browser for
// a new secret, never a saved one; a plain field renders neither.
const render = new Function('escapeHtml', `${grab('envInputFields')}\nreturn envInputFields;`)(escapeHtml);
const envs = [
  { key: 'API_KEY', label: 'API key', secret: true, required: true, pattern: '[a-f0-9-]+' },
  { key: 'EMAIL', label: 'Email', secret: false, required: true },
];
for (const withId of [true, false]) {
  const html = render({ slug: 'svc' }, envs, { withId });
  assert.match(html, /type="password"[^>]*autocomplete="new-password"[^>]*pattern="\[a-f0-9-\]\+"/s);
  assert.match(html, /data-key="API_KEY"/);
  const email = html.match(/<input[^>]*data-key="EMAIL"[^>]*>/s)[0];
  assert.doesNotMatch(email, /autocomplete|pattern=/);
}
console.log('A patterned secret field carries its pattern and autocomplete="new-password" in both forms.');

// The deploy handler: an invalid typed value is reported and nothing is sent,
// not even the preflight; a valid value is trimmed; a blank required field is
// still refused; a blank optional patterned field passes through untouched.
let inputs = [];
let reports = 0;
let preflights = 0;
let toasts = 0;
const requests = [];
const document = { getElementById: () => null, querySelectorAll: () => inputs };
let deployAnswer = {};
const api = async (...args) => { requests.push(args); return deployAnswer; };
const shownLinks = [];
// _imageChoice and _instancesFor read the form's Advanced box and Instances
// box; undefined is "unchanged", so the request body is the env alone.
const deploy = new Function('document', 'api', 'toast', '_confirmPreflight', 'wizardState', '_imageChoice', '_instancesFor', '_showDeviceLink',
  `${grab('_deployToWorkers')}\nreturn _deployToWorkers;`)(document, api, () => { toasts++; },
  async () => { preflights++; return true; }, { deployed: [] }, () => undefined, () => undefined,
  (slug, statusEl, links) => shownLinks.push(links));
const input = (key, value, { valid, required }) => ({ value, required, pattern: '[a-f0-9-]+',
  dataset: { key }, style: {}, checkValidity: () => valid, reportValidity: () => { reports++; } });

inputs = [input('API_KEY', 'account-password', { valid: false, required: true })];
await deploy('svc', [1]);
assert.equal(reports, 1, 'an invalid value is reported to the user');
assert.equal(preflights, 0, 'no preflight for an invalid value');
assert.equal(requests.length, 0, 'no request for an invalid value');

inputs = [input('API_KEY', '', { valid: false, required: true })];
await deploy('svc', [1]);
assert.equal(requests.length, 0, 'a blank required field is still refused');
assert.equal(toasts, 1, 'and the user is told');

inputs = [input('API_KEY', ' 12345678-1234-4abc-8def-123456789abc ', { valid: true, required: true })];
await deploy('svc', [1]);
assert.equal(preflights, 1);
assert.equal(requests.length, 1);
assert.equal(requests[0][1].body.env.API_KEY, '12345678-1234-4abc-8def-123456789abc', 'a valid value is sent trimmed');

inputs = [input('UI_ADDRESS', '', { valid: false, required: false })];
await deploy('svc', [1]);
assert.equal(requests.length, 2, 'a blank optional patterned field never blocks the deploy');
assert.equal(requests[1][1].body.env.UI_ADDRESS, '');
console.log('An invalid typed value stops before preflight; valid values go out trimmed; blanks keep their old meaning.');

// A deploy whose answer carries a device_link shows the step once per id, even
// when two workers report the same one; an answer without it shows nothing.
const link = { id: 'sdk-node-' + 'a'.repeat(32), url: 'https://earnapp.com/r/x', steps: 'Open this link.' };
deployAnswer = { status: 'deployed', device_link: link };
inputs = [input('API_KEY', '12345678-1234-4abc-8def-123456789abc', { valid: true, required: true })];
shownLinks.length = 0;
await deploy('svc', [1, 2]);
assert.deepEqual(shownLinks.at(-1), [link], 'the step is shown with the id from the deploy answer');
deployAnswer = { status: 'deployed' };
await deploy('svc', [1]);
assert.deepEqual(shownLinks.at(-1), [], 'no device_link, nothing to link');

// The step itself: the id, a copy button and the link, after the status row.
let inserted = '';
const docStub = { getElementById: () => null };
const show = new Function('document', 'escapeHtml', `${grab('_showDeviceLink')}\nreturn _showDeviceLink;`)(docStub, escapeHtml);
show('earnapp', { parentElement: { insertAdjacentHTML: (where, html) => { inserted = `${where}|${html}`; } } }, [link]);
assert.match(inserted, /^afterend\|/);
assert.match(inserted, /Link this device to your account/);
assert.match(inserted, new RegExp(`data-action="copyText" data-a1="${link.id}"`));
assert.match(inserted, /href="https:\/\/earnapp.com\/r\/x"/);
console.log('A deploy that returns a device_link shows the link step with the id, a copy button and the link.');
