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
  {id: 2, service: 'EarnApp', label: 'Node UUID', masked: '...9999', worker: 'box-b', copy: 'copy 2', status: 'retired', source: 'deploy', readable: true},
  {id: 3, service: 'Mysterium', label: 'Node identity', masked: '...beef', worker: 'box-c', copy: '', status: 'active', source: 'node', readable: true},
  {id: 4, service: 'X', label: '<img src=x onerror=alert(1)>', masked: '...', worker: '<b>w</b>', copy: '', status: 'retired', source: 'deploy', readable: false},
];
const html = owner.identityRowsHtml(rows);
check('masked values are shown', html.includes('...1234') && html.includes('...9999'), html);
check('each readable row has Show and Copy', (html.match(/data-action="revealIdentity"/g) || []).length === 3, html);
check('only removed ids can be forgotten', (html.match(/data-action="forgetIdentity"/g) || []).length === 2
  && !html.includes('data-action="forgetIdentity" data-a1="1"'), html);
check('a node-reported id says so', html.includes('Reported by the node itself'), html);
check('markup in a label stays text', !html.includes('<img') && html.includes('&lt;img'), html);
check('markup in a worker name stays text', !html.includes('<b>w</b>'), html);
check('an unreadable value offers no Show', !html.includes('data-a1="4">Show'), html);
check('an empty list says what fills it', owner.identityRowsHtml([]).includes('No device ids yet'), owner.identityRowsHtml([]));

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

console.log(bad ? `\nRESULT: FAIL (${bad})` : '\nRESULT: PASS');
process.exit(bad ? 1 : 0);
