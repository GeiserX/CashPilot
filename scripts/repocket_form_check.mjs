// Exercise the shared field builder used by the wizard and service detail.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync('app/static/js/app.js', 'utf8');
const start = src.indexOf('  function envInputFields(');
const end = src.indexOf('\n  function workerCheckboxList(', start);
const escapeHtml = value => String(value).replaceAll('&', '&amp;').replaceAll('"', '&quot;');
const render = new Function('escapeHtml', `${src.slice(start, end)}\nreturn envInputFields;`)(escapeHtml);
const envs = [{ key: 'RP_API_KEY', label: 'API Key', secret: true, required: true, pattern: '[a-f0-9-]+' }];
for (const withId of [true, false]) {
  const html = render({ slug: 'repocket' }, envs, { withId });
  assert.match(html, /type="password"/);
  assert.match(html, /autocomplete="new-password"/);
  assert.match(html, /pattern="\[a-f0-9-\]\+"/);
  assert.match(html, /value=""/);
  assert.match(html, /data-key="RP_API_KEY"/);
}
console.log('Repocket fields request a new secret and expose the catalog constraint in both forms.');

const grab = name => {
  const marker = new RegExp(`  (?:async )?function ${name}\\(`);
  const offset = src.search(marker);
  assert.ok(offset >= 0, name);
  const rest = src.slice(offset);
  const next = rest.search(/\n  (?:async )?function /);
  return next >= 0 ? rest.slice(0, next) : rest;
};
const workers = [{ id: 1, name: 'Worker', containers: [{ slug: 'repocket' }, { slug: 'honeygain' }] }];
const workerList = new Function('escapeHtml', `${grab('workerCheckboxList')}\nreturn workerCheckboxList;`)(escapeHtml);
for (const checkboxClass of ['setup-deploy-worker-cb', 'deploy-worker-cb']) {
  const list = workerList({ slug: 'repocket' }, workers, checkboxClass);
  assert.equal(list.allDeployed, false);
  assert.doesNotMatch(list.rows, /disabled|checked/);
  assert.match(list.rows, /select to update API key/);
}
assert.match(workerList({ slug: 'honeygain' }, workers, 'deploy-worker-cb').rows, /disabled checked/);
const formFunctions = ['envInputFields', 'workerCheckboxList', 'renderServiceSetupForm', 'renderServiceDetail'].map(grab).join('\n');
const forms = new Function('escapeHtml', 'capFirst', 'collectorCredentialsNotice', '_isOwner', '_canWrite',
  `${formFunctions}\nreturn [renderServiceSetupForm, renderServiceDetail];`)(escapeHtml, value => value, () => '', true, true);
for (const form of forms) {
  const html = form({ slug: 'repocket', name: 'Repocket', deployed: true, docker: { image: 'repocket/repocket', env: envs } },
    workers.map(worker => ({ ...worker, status: 'online' })));
  assert.match(html, /Deploy \/ Update API key/);
  assert.doesNotMatch(html, /Deployed on all nodes/);
}

let inputs = [];
let reports = 0;
let preflights = 0;
const requests = [];
const document = { getElementById: () => null, querySelectorAll: () => inputs };
const api = async (...args) => { requests.push(args); return {}; };
const deploy = new Function('document', 'api', 'toast', '_confirmPreflight', 'wizardState',
  `${grab('_deployToWorkers')}\nreturn _deployToWorkers;`)(document, api, () => {},
  async () => { preflights++; return true; }, { deployed: [] });
const input = (value, valid) => ({ value, required: true, pattern: '[a-f0-9-]+',
  dataset: { key: 'RP_API_KEY' }, style: {}, checkValidity: () => valid,
  reportValidity: () => { reports++; } });
inputs = [input('account-password', false)];
await deploy('repocket', [1]);
assert.equal(reports, 1);
assert.equal(preflights, 0);
assert.equal(requests.length, 0);
inputs = [input('', false)];
await deploy('repocket', [1]);
assert.equal(requests.length, 1);
assert.equal(requests[0][1].body.env.RP_API_KEY, '');
inputs = [input(' 12345678-1234-4abc-8def-123456789abc ', true)];
await deploy('repocket', [1]);
assert.equal(requests[1][1].body.env.RP_API_KEY, '12345678-1234-4abc-8def-123456789abc');
inputs = [input('', false)];
await deploy('honeygain', [1]);
assert.equal(requests.length, 2);
console.log('Existing Repocket workers can be selected; invalid typed keys stop before preflight; blank keys reach server validation.');
