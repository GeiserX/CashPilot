// Run the real device-id list, the reuse offer and the deploy retry against stubs.
//
// The Settings list and the deploy form's "use one this service had before"
// show device ids that let whoever holds them claim the device. Only running
// the render shows what reaches the page: every value arrives masked from the
// API, a node-reported one says so, and markup in a label stays text. The
// deploy retry must ask once before putting one device id on a second box, and
// never loop. This executes the real functions from app/static/js/app.js.
//
//   node scripts/identity_view_check.mjs
//
// Exits non-zero on any mismatch.
import {readFileSync} from 'node:fs';

const src = readFileSync('app/static/js/app.js', 'utf8');

function slice(from, to) {
  const start = src.indexOf(from);
  const end = src.indexOf(to, start + from.length);
  if (start < 0 || end < 0) {
    console.error(`FAIL: could not find ${from} .. ${to} in app/static/js/app.js`);
    process.exit(1);
  }
  return src.slice(start, end);
}

const escape = slice('function escapeHtml(', 'function sanitizeHint(');
const fields = slice('function isIdentityField(', '// The class is a parameter rather than unified');
const rowsFn = slice('function identityRowsHtml(', 'async function loadIdentities(');
const offersFn = slice('function identityOffersHtml(', 'function _identityPicks(');
const apiFn = slice('async function api(', '// One prompt at a time');

let bad = 0;
const check = (label, cond, detail) => {
  console.log(`  ${cond ? 'ok  ' : 'FAIL'} ${label}${cond ? '' : `  <- ${detail}`}`);
  if (!cond) bad++;
};

const build = (isOwner) => new Function('_isOwner', `${escape}\n${fields}\n${rowsFn}\n${offersFn}\n`
  + 'return {isIdentityField, identityPickButton, identityRowsHtml, identityOffersHtml};')(isOwner);
const owner = build(true);
const viewer = build(false);

// --- which fields get the reuse button ------------------------------------
const svc = {slug: 'earnapp'};
check('a per_device field is an identity field', owner.isIdentityField({key: 'U', per_device: true}), 'false');
check('an identifier field is an identity field', owner.isIdentityField({key: 'N', identifier: true}), 'false');
check('a secret is never one, even if marked', !owner.isIdentityField({key: 'P', secret: true, identifier: true}), 'true');
check('a plain field is not one', !owner.isIdentityField({key: 'E'}), 'true');
check('the owner gets the button', owner.identityPickButton(svc, {key: 'U', per_device: true}).includes('pickPreviousIdentity'), 'missing');
check('anyone else gets no button', viewer.identityPickButton(svc, {key: 'U', per_device: true}) === '', 'shown');

// --- the list --------------------------------------------------------------
const rows = [
  {id: 1, service: 'EarnApp', label: 'Node UUID', masked: '...1234', worker: 'box-a', copy: '', status: 'active', source: 'deploy', readable: true},
  {id: 2, service: 'EarnApp', label: 'Node UUID', masked: '...9999', worker: 'box-b', copy: 'copy 2', status: 'retired', source: 'deploy', forgettable: true, readable: true},
  {id: 3, service: 'Mysterium', label: 'Node identity', masked: '...beef', worker: 'box-c', copy: '', status: 'active', source: 'node', kind: 'node', forgettable: true, readable: true},
  {id: 4, service: 'X', label: '<img src=x onerror=alert(1)>', masked: '...', worker: '<b>w</b>', copy: '', status: 'retired', source: 'deploy', forgettable: true, readable: false},
  {id: 5, service: 'EarnApp', label: 'Node UUID', masked: '...5555', worker: 'box-a', copy: 'deploy not confirmed', status: 'active', source: 'deploy', pending: true, forgettable: true, readable: true},
];
const html = owner.identityRowsHtml(rows);
check('masked values are shown', html.includes('...1234') && html.includes('...9999'), html);
check('each readable row has Show and Copy', (html.match(/data-action="revealIdentity"/g) || []).length === 4, html);
check('only removed, node-reported or unconfirmed ids can be forgotten', (html.match(/data-action="forgetIdentity"/g) || []).length === 4
  && !html.includes('data-action="forgetIdentity" data-a1="1"')
  && html.includes('data-action="forgetIdentity" data-a1="3"')
  && html.includes('data-action="forgetIdentity" data-a1="5"'), html);
check('an unconfirmed hold past its time is forgotten with the hold\'s warning',
  html.includes('data-action="forgetIdentity" data-a1="5" data-a2="pending"') && !html.includes('data-a1="2" data-a2'), html);
// A fresh hold: the deploy may still land, so no Forget, and the row says why.
const fresh = owner.identityRowsHtml([{...rows[4], id: 6, forgettable: false}]);
check('a fresh unconfirmed hold offers no Forget', !fresh.includes('forgetIdentity'), fresh);
check('a fresh unconfirmed hold says the box may still start it', fresh.includes('may still start with this id'), fresh);
const backupRow = {id: 7, service: 'Mysterium', label: 'Backup file (SHA-256)', masked: '...', worker: 'box-a', copy: '',
  status: 'active', kind: 'backup', source: 'pending', readable: true};
const sentRestore = owner.identityRowsHtml([{...backupRow, forgettable: false}]);
check('a restore with no answer yet offers no Forget and says why', !sentRestore.includes('forgetIdentity')
  && sentRestore.includes('may still finish') && sentRestore.includes('6 h after the restore'), sentRestore);
const agedRestore = owner.identityRowsHtml([{...backupRow, forgettable: true}]);
check('once its time is up it can be forgotten', agedRestore.includes('data-a1="7">Forget')
  && !agedRestore.includes('may still finish'), agedRestore);
const removedHold = owner.identityRowsHtml([{...rows[4], id: 9, status: 'retired', forgettable: true}]);
check('a retired hold is forgotten like any removed id', removedHold.includes('data-a1="9">Forget')
  && !removedHold.includes('may still start'), removedHold);
check('a node-reported id says so', html.includes('Reported by the node itself'), html);
check('markup in a label stays text', !html.includes('<img') && html.includes('&lt;img'), html);
check('markup in a worker name stays text', !html.includes('<b>w</b>'), html);
check('an unreadable value offers no Show', !html.includes('data-a1="4">Show'), html);
check('an empty list says what fills it', owner.identityRowsHtml([]).includes('No device ids yet'), owner.identityRowsHtml([]));

// --- the Forget confirm -----------------------------------------------------
// A hold's Forget names the risk the shared-id 409 names: the box may still
// start the id, and then nothing warns before a second box takes it.
const forgetFn = slice('async function forgetIdentity(', "// The deploy form's");
async function forget(kind) {
  const texts = [];
  const window = {confirm: (text) => { texts.push(text); return false; }};
  const run = new Function('window', 'api', 'loadIdentities', 'toast', `${forgetFn}; return forgetIdentity;`)(
    window, async () => {}, () => {}, () => {});
  await run(5, kind);
  return texts[0] || '';
}
let text = await forget('pending');
check('a hold\'s Forget warns the box may still start it', text.includes('may still start with it')
  && text.includes('another box'), text);
text = await forget(undefined);
check('a removed id\'s Forget keeps its own text', !text.includes('may still start') && text.includes('offer it again'), text);

// --- the reuse offer -------------------------------------------------------
const offers = owner.identityOffersHtml('earnapp', 'EARNAPP_UUID', [
  {id: 7, masked: '...aaaa', worker: 'box-a', copy: '', in_use_on: []},
  {id: 8, masked: '...bbbb', worker: 'box-b', copy: '', in_use_on: ['box-c', 'box-d']},
]);
check('each offer has a Use button', (offers.match(/data-action="useIdentity"/g) || []).length === 2, offers);
check('an id in use says where', offers.includes('In use on box-c, box-d'), offers);
check('the Use button carries where it runs, for the warning', offers.includes('data-a4="box-c, box-d"'), offers);
check('a free id carries no warning', offers.includes('data-a3="7" data-a4=""'), offers);
check('no offer says so', owner.identityOffersHtml('s', 'k', []).includes('no earlier id'), '');

// --- the reuse offer leaves out the box being deployed to ------------------
// The server leaves ``worker_id`` out of "in use on", as the deploy's shared-id
// check does, so the offer warns about the same boxes the deploy refuses.
const pickFn = slice('async function pickPreviousIdentity(', 'async function useIdentity(');
async function pick(checked) {
  const asked = [];
  const document = {querySelectorAll: (sel) => {
    if (sel.includes('worker-cb')) {
      return sel.split(',').some(part => part.includes('earnapp')) ? checked.map(wid => ({dataset: {wid: String(wid)}})) : [];
    }
    return [];
  }};
  const api = async (path) => { asked.push(path); return []; };
  const run = new Function('document', 'api', 'identityOffersHtml', '_identityPicks', 'toast', '_selectedWorkerIds',
    '_rescaledWorkerIds', `${pickFn}; return pickPreviousIdentity;`)(
    document, api, () => '', () => [], () => {},
    (sel) => Array.from(document.querySelectorAll(sel)).map(cb => parseInt(cb.dataset.wid)),
    () => []);
  await run('earnapp', 'EARNAPP_UUID');
  return asked[0] || '';
}
let asked = await pick([2]);
check('one box picked: the offer asks without it', asked.includes('worker_id=2'), asked);
asked = await pick([2, 3]);
check('two boxes picked: the offer leaves none out', !asked.includes('worker_id'), asked);
asked = await pick([]);
check('no box picked: the offer leaves none out', !asked.includes('worker_id'), asked);

// --- the deploy retry when an id runs on another box -----------------------
async function runApi(answers, confirmAnswer) {
  const calls = [];
  let asked = 0;
  const fetch = async (path, config) => {
    // A retry that loops must fail this check, not exhaust the heap.
    if (calls.length >= 5) throw new Error('the deploy was sent again and again');
    calls.push(JSON.parse(config.body));
    const [status, body] = answers[Math.min(calls.length - 1, answers.length - 1)];
    return {ok: status < 400, status, json: async () => body};
  };
  const window = {confirm: () => { asked++; return confirmAnswer; }};
  const askStepUp = async () => null;
  const api = new Function('fetch', 'window', 'askStepUp', `${apiFn}; return api;`)(fetch, window, askStepUp);
  let error = null;
  try {
    await api('/api/deploy/earnapp?worker_id=2', {method: 'POST', body: {env: {EARNAPP_UUID: 'x'}}});
  } catch (err) {
    error = err;
  }
  return {calls, asked, error};
}
const inUse = [409, {detail: {error: 'identity_in_use', message: 'The Node UUID already runs on box-a.'}}];
const fine = [200, {status: 'deployed'}];

let r = await runApi([inUse, fine], true);
check('OK sends the deploy again with the owner\'s yes', r.calls.length === 2 && r.calls[1].allow_shared_identity === true
  && r.calls[0].allow_shared_identity === undefined && !r.error, JSON.stringify(r));
check('it asks once', r.asked === 1, r.asked);

r = await runApi([inUse], false);
check('Cancel sends nothing more and shows the reason', r.calls.length === 1 && r.error
  && r.error.message.includes('already runs on box-a'), JSON.stringify(r));

r = await runApi([inUse, inUse], true);
check('a second refusal is shown, never asked again', r.calls.length === 2 && r.asked === 1 && r.error, JSON.stringify(r));

// --- two Use clicks: the later one wins, whichever reveal answers first -------
const useFn = slice('function _identityTargetWorker(', '// Exported for the harness');
{
  const input = {dataset: {slug: 'earnapp', key: 'EARNAPP_UUID'}, value: ''};
  const document = {querySelectorAll: (sel) => (sel.startsWith('input') ? [input] : [])};
  const pending = {};
  const reveal = (id) => new Promise(resolve => { pending[id] = resolve; });
  const useIdentity = new Function('document', 'window', '_revealIdentity', 'toast', '_identityPicks',
    `${useFn}; return useIdentity;`)(document, {confirm: () => true}, reveal, () => {}, () => []);
  const first = useIdentity('earnapp', 'EARNAPP_UUID', 7, '');
  const second = useIdentity('earnapp', 'EARNAPP_UUID', 8, '');
  pending[8]('id-of-8');
  await second;
  pending[7]('id-of-7');
  await first;
  check('a reveal that answers after a later Use leaves the later id', input.value === 'id-of-8', input.value);

  // The owner types another id while the reveal is out: what they typed stays.
  const third = useIdentity('earnapp', 'EARNAPP_UUID', 9, '');
  input.value = 'typed-by-owner';
  pending[9]('id-of-9');
  await third;
  check('a reveal that answers after the owner typed leaves what they typed', input.value === 'typed-by-owner', input.value);

  // The positive control: an untouched field takes the revealed id.
  const fourth = useIdentity('earnapp', 'EARNAPP_UUID', 10, '');
  pending[10]('id-of-10');
  await fourth;
  check('a reveal into an untouched field fills it', input.value === 'id-of-10', input.value);
}

// --- the Settings list loads even when /api/config fails ----------------------
// loadIdentities has its own error path; behind the config call it never ran,
// and the panel said "Loading..." forever.
const loadSettingsFn = slice('async function loadSettings(', '// --- Device ids (issue #740)');
const settingsCalls = [];
const stub = name => () => { settingsCalls.push(name); };
const loadSettings = new Function(
  'populateCurrencyDropdown', 'loadUpdateCard', 'loadIdentities', 'loadCredentialHealth',
  'renderEnvVars', 'renderCollectors', 'settingsPanelsFailed', 'api',
  `${loadSettingsFn}; return loadSettings;`,
)(stub('currency'), stub('update'), stub('identities'), stub('credentials'),
  stub('env'), stub('collectors'), stub('failed'),
  async path => { if (path === '/api/config') throw new Error('401'); return []; });
await loadSettings();
check('a failed /api/config still loads the device ids', settingsCalls.includes('identities')
  && settingsCalls.includes('failed'), JSON.stringify(settingsCalls));

console.log(bad ? `\nRESULT: FAIL (${bad})` : '\nRESULT: PASS');
process.exit(bad ? 1 : 0);
