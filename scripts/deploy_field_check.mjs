// A catalog `pattern` reaches the browser and stops a wrong value before the
// deploy request, in both forms that build env fields (the wizard and the
// service detail page). Browser-free: the functions are lifted out of app.js
// and run against stand-ins, the way currency_check.mjs does it.
import './i18n_stub.mjs';
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

const fillDeployRisk = new Function('api', 'escapeHtml', `${grab('fillDeployRisk')}\nreturn fillDeployRisk;`)(
  async () => ({
    mining: { dev_fee_percent: 0, dev_fee_source: 'https://example.com/?a=1&b=2', pool_fee_note: '<untrusted>' },
  }),
  value => escapeHtml(value).replaceAll('<', '&lt;').replaceAll('>', '&gt;'),
);
const riskBody = { innerHTML: '' };
const riskCard = { dataset: { slug: 'xmrig' }, style: { display: 'none' }, querySelector: () => riskBody };
await fillDeployRisk(riskCard);
assert.equal(riskCard.style.display, '');
assert.match(riskBody.innerHTML, /Miner fee: 0% of hashing time/);
assert.match(riskBody.innerHTML, /&lt;untrusted&gt;/);
assert.match(riskBody.innerHTML, /https:\/\/example.com\/\?a=1&amp;b=2/);
assert.match(riskBody.innerHTML, /CashPilot lists tracked pool balances as accrued/);
console.log('A miner shows its fee, source and pool note before deploy.');

const fillInternalRisk = new Function('api', 'escapeHtml', `${grab('fillDeployRisk')}\nreturn fillDeployRisk;`)(
  async () => ({
    mining: { dev_fee_percent: 0, dev_fee_source: 'https://example.com/', payout_model: 'internal' },
  }),
  escapeHtml,
);
const internalBody = { innerHTML: '' };
await fillInternalRisk({ dataset: { slug: 'kryptex-pearl' }, style: {}, querySelector: () => internalBody });
assert.match(internalBody.innerHTML, /keeps your balance in its account until you request a withdrawal/);
assert.doesNotMatch(internalBody.innerHTML, /Payouts arrive in your wallet/);
console.log('A pool that holds the balance does not promise wallet payouts.');

const warnings = [];
const confirmPreflight = new Function(
  'api', '_instancesFor', 'window', `${grab('_confirmPreflight')}\nreturn _confirmPreflight;`,
)(
  async () => ({ blocking: false, findings: [
    { verdict: 'check_these', message: 'Routine advice' },
    { verdict: 'check_these', kind: 'hosting_note', message: 'Check your hosting terms.' },
  ] }),
  () => undefined,
  { confirm: text => { warnings.push(text); return true; } },
);
assert.equal(await confirmPreflight('xmrig', [1]), true);
assert.equal(warnings.length, 1);
assert.match(warnings[0], /Check your hosting terms/);
assert.doesNotMatch(warnings[0], /Routine advice/);
console.log('The deploy confirmation shows the hosting terms and lets the user proceed.');

// A secret field with a pattern renders the pattern and asks the browser for
// a new secret, never a saved one; a plain field renders neither.
const render = new Function(
  'escapeHtml', '_isOwner',
  `${grab('isIdentityField')}\n${grab('identityPickButton')}\n${grab('envInputFields')}\nreturn envInputFields;`,
)(escapeHtml, true);
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

const minerInput = render({ slug: 'xmrig', mining: {} }, [
  { key: 'POOL_URL', label: 'Pool', default: 'example.com:9000', required: true },
]);
assert.match(minerInput, /placeholder="example.com:9000"\s+value=""/);
assert.doesNotMatch(minerInput, /\srequired(?:\s|>)/);
console.log('A miner default is a blank suggestion until the user enters it.');

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
let answers = [];
const api = async (...args) => { requests.push(args); return answers.shift() ?? deployAnswer; };
const shownLinks = [];
// _imageChoice, _instancesFor and _routeChoice read the form's Advanced box,
// Instances box and Route box; undefined is "unchanged", so the request body is
// the env alone. _confirmDeviceRenames asks before a redeploy renames a
// provider device; renameAnswer is what the user clicks.
let renameAnswer = false;
const deploy = new Function('document', 'api', 'toast', '_confirmPreflight', 'wizardState', '_imageChoice', '_instancesFor', '_showDeviceLink', '_routeChoice', '_confirmDeviceRenames',
  `const _walletRequest = () => undefined;\n${grab('_deployToWorkers')}\nreturn _deployToWorkers;`)(document, api, () => { toasts++; },
  async () => { preflights++; return true; }, { deployed: [] }, () => undefined, () => undefined,
  (slug, statusEl, links) => shownLinks.push(links), () => undefined, async () => renameAnswer);
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

// A declined rename sends no rename flag; an accepted one sends it on the
// deploy of every worker in the batch.
assert.equal(requests[1][1].body.rename_devices, undefined, 'a declined rename keeps the device name');
renameAnswer = true;
inputs = [input('API_KEY', '12345678-1234-4abc-8def-123456789abc', { valid: true, required: true })];
await deploy('svc', [1, 2]);
assert.equal(requests.length, 4);
assert.equal(requests[2][1].body.rename_devices, true, 'an accepted rename is sent');
assert.equal(requests[3][1].body.rename_devices, true, 'to every worker in the deploy');
renameAnswer = false;
requests.length = 2;
console.log('A device rename is sent only after the user accepts it, to every worker in the deploy.');

// A deploy whose answer carries a device_link shows the step once per id, even
// when two workers report the same one; an answer without it shows nothing.
const link = { id: 'sdk-node-' + 'a'.repeat(32), url: 'https://earnapp.com/r/x', steps: 'Open this link.' };
deployAnswer = { status: 'deployed', device_link: link };
inputs = [input('API_KEY', '12345678-1234-4abc-8def-123456789abc', { valid: true, required: true })];
shownLinks.length = 0;
await deploy('svc', [1, 2]);
assert.deepEqual(shownLinks.at(-1), [link], 'the step is shown with the id from the deploy answer');
answers = [
  { status: 'deployed', device_link: { ...link, id: 'dev-a' } },
  { status: 'deployed', device_link: { ...link, id: 'dev-b' } },
];
await deploy('svc', [1, 2]);
assert.deepEqual(shownLinks.at(-1).map(l => l.id).sort(), ['dev-a', 'dev-b'], 'each worker device id is shown');
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
// A device the deploy already added to the account asks for nothing.
show('proxyrack', { parentElement: { insertAdjacentHTML: (where, html) => { inserted = html; } } }, [{ ...link, registered: true }]);
assert.match(inserted, /Added to your account/);
assert.doesNotMatch(inserted, /Link this device|Open link/);
console.log('A deploy that returns a device_link shows the link step with the id, a copy button and the link.');
