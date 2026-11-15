// Run the real "Restore from a backup" preview against stub data (issue #741).
//
// The preview is the last thing the owner reads before a node identity or a
// wallet goes onto a box, so only running it shows what reaches the page: the
// volumes it creates, the box list with the ones that cannot take it disabled,
// the typed-name box for a file this CashPilot did not make, a refusal when
// the identity already runs elsewhere, and markup in any name staying text.
// This executes the real function from app/static/js/app.js.
//
//   node scripts/restore_preview_check.mjs
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
const stamp = slice('function fmtTimestamp(', '\n  }\n') + '\n  }\n';
const preview = slice('function restorePreviewHtml(', 'async function checkRestoreFile(');
const {restorePreviewHtml} = new Function(`${escape}\n${stamp}\n${preview}\nreturn {restorePreviewHtml};`)();

let bad = 0;
const check = (label, cond, detail) => {
  console.log(`  ${cond ? 'ok  ' : 'FAIL'} ${label}${cond ? '' : `  <- ${detail}`}`);
  if (!cond) bad++;
};

const base = {
  upload_id: 'u1',
  slug: 'mysterium',
  service: 'Mysterium',
  container: 'cashpilot-mysterium',
  creates: [{target: '/var/lib/mysterium-node', volume: 'mysterium-data'}],
  known: false,
  history: [],
  live_on: [],
  workers: [
    {id: 1, name: 'box-a', ok: true, why: '', plain_http: false},
    {id: 2, name: 'box-b', ok: false, why: 'it already runs Mysterium', plain_http: false},
    {id: 3, name: 'box-c', ok: true, why: '', plain_http: true},
  ],
};

// --- what it creates, and where it may go ------------------------------------
let html = restorePreviewHtml(base);
check('names the container', html.includes('cashpilot-mysterium'), html);
check('names the volume and folder', html.includes('mysterium-data') && html.includes('/var/lib/mysterium-node'), html);
check('a box that cannot take it is disabled with the reason',
  /<option value="2" disabled>box-b \(it already runs Mysterium\)/.test(html), html);
check('a box that can take it is selectable', /<option value="1">box-a<\/option>/.test(html), html);
check('plain HTTP is called out', /box-c \(plain HTTP/.test(html), html);
check('the Restore button is enabled', /data-action="submitRestore"[^>]*data-a1="u1">/.test(html), html);

// --- a file this CashPilot did not make --------------------------------------
check('asks for the typed name', html.includes('id="restore-confirm"') && html.includes('<strong>Mysterium</strong>'), html);
check('a plain HTTP box asks the owner to accept it', html.includes('id="restore-plain-http"'), html);
html = restorePreviewHtml({...base, runs_on: ['box-b']});
check('names where the service runs now', html.includes('runs now on box-b'), html);
html = restorePreviewHtml({...base, workers: base.workers.filter(w => !w.plain_http)});
check('no plain HTTP box, no question', !html.includes('restore-plain-http'), html);

// --- a file it made ----------------------------------------------------------
html = restorePreviewHtml({...base, known: true,
  history: [{what: 'made here', worker: 'box-a', when: '2026-11-01 10:00:00'}]});
check('a known file asks for no typed name', !html.includes('id="restore-confirm"'), html);
check('says where it was made', html.includes('made here on box-a'), html);
html = restorePreviewHtml({...base, known: true, runs_on: ['box-b'],
  history: [{what: 'made here', worker: 'box-a', when: '2026-11-01 10:00:00'}]});
check('a known file not live anywhere has no runs-now warning', !html.includes('runs now on'), html);

// --- the identity runs elsewhere ---------------------------------------------
const elsewhere = {id: 1, name: 'box-a', ok: false, why: 'this identity already runs on box-z', plain_http: false};
html = restorePreviewHtml({...base, live_on: ['box-z'], workers: [elsewhere]});
check('names the box it runs on', html.includes('may be starting, on box-z'), html);
check('the Restore button is disabled', /data-action="submitRestore"[^>]*disabled>/.test(html), html);
// A restore sent to box-z got no answer: box-z may take it again, no other box may.
html = restorePreviewHtml({...base, live_on: ['box-z'],
  workers: [elsewhere, {id: 9, name: 'box-z', ok: true, why: '', plain_http: false}]});
check('the box a restore was sent to stays selectable', /<option value="9">box-z<\/option>/.test(html), html);
check('and Restore is enabled for it', /data-action="submitRestore"[^>]*data-a1="u1">/.test(html), html);

// --- no box can take it ------------------------------------------------------
html = restorePreviewHtml({...base, workers: [{id: 2, name: 'box-b', ok: false, why: 'offline'}]});
check('no usable box disables Restore', /data-action="submitRestore"[^>]*disabled>/.test(html), html);

// --- markup stays text -------------------------------------------------------
html = restorePreviewHtml({...base, service: '<img src=x onerror=alert(1)>',
  workers: [{id: 1, name: '<b>box</b>', ok: false, why: '<script>x</script>'}],
  creates: [{target: '/x"><i>', volume: '<u>v</u>'}]});
check('no tag from the data reaches the page',
  !/<img|<b>box|<script>|<i>|<u>v/.test(html), html);

// --- Remove after a restore that did not finish ------------------------------
// The real api() and removeService(), against a stub worker. The worker keeps a
// half-written volume marked, so a plain Remove is refused with
// restore_unfinished; the owner is asked, plainly, to delete that data, and
// only then is the remove sent again as the audited critical delete.
const apiSrc = slice('async function api(', '// One prompt at a time');
const removeSrc = slice('async function removeService(', '// Log viewer');
function runRemove({owner, answers, refusal = 'restore_unfinished', box = {worker_id: 1, worker_name: 'box-a'}, args = [], failed = []}) {
  const sent = [];
  const asked = [];
  const toasts = [];
  const reopened = [];
  const fetch = async (path, config) => {
    sent.push(`${config.method} ${path}`);
    const ok = sent.length > 1 || !refusal;
    const body = ok ? {status: 'removed', failed_volumes: failed}
      : {detail: {error: refusal, message: 'A restore of mysterium did not finish.', ...box}};
    return {ok, status: ok ? 200 : 409, json: async () => body};
  };
  const confirm = (text) => { asked.push(text); return answers.shift(); };
  const toast = (text, kind) => toasts.push(`${kind}: ${text}`);
  const {removeService} = new Function(
    'fetch', 'confirm', 'toast', 'loadServicesTable', 'openServiceDetail', '_isOwner', 'window', 'askStepUp',
    `${apiSrc}\n${removeSrc}\nreturn {removeService};`,
  )(fetch, confirm, toast, () => {}, (slug) => reopened.push(slug), owner, {confirm}, async () => null);
  return removeService('mysterium', ...args).then(() => ({sent, asked, toasts, reopened}));
}

const CRITICAL = '&delete_volumes=true&allow_delete_critical=true&only_if_restore_unfinished=true';
let run = await runRemove({owner: true, answers: [true, true]});
check('a refused Remove asks the owner about the half-written data',
  run.asked.length === 2 && /partial restore/.test(run.asked[1]) && /deletes that volume/.test(run.asked[1]), run.asked);
check('and names the box that refused', /on box-a did not finish/.test(run.asked[1]), run.asked);
check('and sends the audited critical delete to that box only', run.sent.length === 2
  && run.sent[0] === 'DELETE /api/services/mysterium'
  && run.sent[1] === `DELETE /api/services/mysterium?worker_id=1${CRITICAL}`, run.sent);
check('and says it was removed', run.toasts.join() === 'success: mysterium removed', run.toasts);
run = await runRemove({owner: true, answers: [true, true], failed: ['mysterium-data']});
check('a volume the box could not delete is not reported as removed', run.toasts.length === 1
  && /^error: /.test(run.toasts[0]) && /mysterium-data could not be deleted/.test(run.toasts[0]), run.toasts);
run = await runRemove({owner: true, answers: [true, true], box: {}});
check('a refusal that names no box deletes nothing', run.sent.length === 1 && run.asked.length === 1
  && /^error: /.test(run.toasts.join()), run);
run = await runRemove({owner: true, answers: [true, true], args: ['2', 'box-b'], box: {worker_id: 2, worker_name: 'box-b'}});
check('Remove from this box asks about that box', /from box-b\?/.test(run.asked[0]) && /on box-b did not finish/.test(run.asked[1]), run.asked);
check('and both requests go to that box', run.sent.join(' | ')
  === `DELETE /api/services/mysterium?worker_id=2 | DELETE /api/services/mysterium?worker_id=2${CRITICAL}`, run.sent);
check('and the service panel is shown again', run.reopened.join() === 'mysterium', run.reopened);
run = await runRemove({owner: true, answers: [true, true], args: ['2', 'box-b'], box: {worker_id: 1, worker_name: 'box-a'}});
check('a box-row Remove never deletes on another box', run.sent.every((r) => r.includes('worker_id=2')), run.sent);
run = await runRemove({owner: true, answers: [true, false]});
check('an owner who says no deletes nothing', run.sent.length === 1 && run.toasts.length === 0, run);
run = await runRemove({owner: false, answers: [true]});
check('a writer is not offered the delete', run.sent.length === 1 && run.asked.length === 1
  && /Only the owner/.test(run.toasts.join()), run);
run = await runRemove({owner: true, answers: [true], refusal: 'something_else'});
check('any other refusal is shown and not retried', run.sent.length === 1 && run.asked.length === 1
  && /^error: /.test(run.toasts.join()), run);
run = await runRemove({owner: true, answers: [true], refusal: null});
check('a Remove the worker takes asks nothing more', run.sent.length === 1
  && run.sent[0] === 'DELETE /api/services/mysterium' && run.asked.length === 1, run);

// A catalog service has a Remove on each box's row of its panel, as a custom
// one does, so a fleet with several boxes online can reach it.
const rowLine = src.split('\n').find((l) => l.includes('>Remove from this box</button>'));
check('every box row of a service panel offers Remove from this box',
  !!rowLine && /svc\.custom \? 'removeCustomFromBox' : 'removeService'/.test(rowLine)
  && !/\$\{svc\.custom &&/.test(rowLine), rowLine);

// A box that holds only the half-written volume and its helper lists no
// container of the service, so its row comes from the worker's heartbeat list.
const leftoverSrc = slice('function restoreLeftoverRows(', '// -----------------------------------------------------------');
function leftover(workers, instances = [], canWrite = true) {
  const {restoreLeftoverRows} = new Function('_canWrite', `${escape}\n${leftoverSrc}\nreturn {restoreLeftoverRows};`)(canWrite);
  return restoreLeftoverRows({slug: 'mysterium'}, workers, instances);
}
const boxA = {id: 1, name: 'box-a', system_info: {restore_unfinished: ['proxybase-xyz']}};
const boxB = {id: 2, name: 'box-b<i>', system_info: {restore_unfinished: ['mysterium']}};
let rows = leftover([boxA, boxB]);
check('a box with only a partial restore gets Remove from this box',
  /data-action="removeService" data-a1="mysterium" data-a2="2" data-a3="box-b&lt;i&gt;">Remove from this box</.test(rows), rows);
check('and no other box does', !/data-a2="1"/.test(rows), rows);
check('and its name stays text', !/<i>/.test(rows), rows);
check('a box already listed with a container gets no second row',
  leftover([boxB], [{worker: boxB, container: {slug: 'mysterium'}}]) === '');
check('a list that is not an array is ignored',
  leftover([{id: 3, name: 'c', system_info: {restore_unfinished: 'xmysteriumx'}}]) === '');
check('a viewer gets the row but no button', !/<button/.test(leftover([boxB], [], false)));

// --- two files chosen one after the other ------------------------------------
// The answer for the first file can arrive after the second's: the preview
// must stay the second file's, or Restore would send the first file's upload.
const checkSrc = slice('function checkRestoreFile(', 'async function submitRestore(');
async function chooseTwo(firstAnswersLast) {
  const input = {files: [null]};
  const out = {innerHTML: ''};
  const document = {getElementById: (id) => (id === 'restore-file' ? input : id === 'restore-preview' ? out : null)};
  const answers = [];
  const fetch = () => new Promise((resolve) => answers.push(resolve));
  const {checkRestoreFile} = new Function('document', 'fetch',
    `${escape}\n${stamp}\n${preview}\nasync ${checkSrc}\nreturn {checkRestoreFile};`)(document, fetch);
  const reply = (id) => ({ok: true, status: 200, json: async () => ({...base, upload_id: id})});
  input.files = [{name: 'first.cpbackup'}];
  const first = checkRestoreFile();
  input.files = [{name: 'second.cpbackup'}];
  const second = checkRestoreFile();
  const order = firstAnswersLast ? [1, 0] : [0, 1];
  for (const i of order) {
    answers[i](reply(i === 0 ? 'first-upload' : 'second-upload'));
    await (i === 0 ? first : second);
  }
  return out.innerHTML;
}
html = await chooseTwo(true);
check('a slower answer for an earlier file leaves the newer preview',
  html.includes('data-a1="second-upload"') && !html.includes('first-upload'), html);
html = await chooseTwo(false);
check('answers in order show the newer file', html.includes('data-a1="second-upload"'), html);

// --- a restore that finishes after the owner checked another file ------------
// Its success clears the preview and the file input only if no newer file was
// checked meanwhile; otherwise it would wipe the newer file's preview.
const submitSrc = slice('function submitRestore(', '// Exported for the harness');
async function restoreThenCheck(checkAnother) {
  const input = {files: [{name: 'first.cpbackup'}], value: 'first.cpbackup'};
  const out = {innerHTML: ''};
  const ids = {'restore-file': input, 'restore-preview': out};
  const document = {getElementById: (id) => ids[id] || null, querySelector: () => null};
  const fetches = [];
  const fetch = () => new Promise((resolve) => fetches.push(resolve));
  let finish;
  const api = () => new Promise((resolve) => { finish = resolve; });
  const {checkRestoreFile, submitRestore} = new Function('document', 'fetch', 'api', 'toast', 'loadIdentities',
    `${escape}\n${stamp}\n${preview}\nasync ${checkSrc}\nasync ${submitSrc}\n`
    + 'return {checkRestoreFile, submitRestore};')(document, fetch, api, () => {}, () => {});
  const reply = (id) => ({ok: true, status: 200, json: async () => ({...base, upload_id: id})});
  const firstCheck = checkRestoreFile();
  fetches[0](reply('first-upload'));
  await firstCheck;
  const restoring = submitRestore('first-upload');
  if (checkAnother) {
    input.files = [{name: 'second.cpbackup'}];
    input.value = 'second.cpbackup';
    const secondCheck = checkRestoreFile();
    fetches[1](reply('second-upload'));
    await secondCheck;
  }
  finish({service: 'Mysterium', worker: 'box-a', files: 3, started: true});
  await restoring;
  return {html: out.innerHTML, value: input.value};
}
let after = await restoreThenCheck(true);
check('a restore that finishes after a newer file was checked keeps that preview',
  after.html.includes('data-a1="second-upload"') && after.value === 'second.cpbackup', after);
after = await restoreThenCheck(false);
check('control: a restore with no newer file clears the preview and the file',
  after.html === '' && after.value === '', after);

// --- another file chosen after the check, without checking it ---------------
// The preview and its Restore button still hold the checked file's upload: a
// Restore then would send that file while the picker shows another one.
async function restoreAfterPicking(pickAnother) {
  const input = {files: [{name: 'first.cpbackup', size: 10, lastModified: 1}], value: 'first.cpbackup'};
  const out = {innerHTML: ''};
  const ids = {'restore-file': input, 'restore-preview': out};
  const document = {getElementById: (id) => ids[id] || null, querySelector: () => null};
  const fetches = [];
  const fetch = () => new Promise((resolve) => fetches.push(resolve));
  const sent = [];
  const toasts = [];
  const api = async (path, opts) => { sent.push(opts.body.upload_id); return {service: 'Mysterium', worker: 'box-a', files: 1, started: true}; };
  const {checkRestoreFile, submitRestore} = new Function('document', 'fetch', 'api', 'toast', 'loadIdentities',
    `${escape}\n${stamp}\n${preview}\nasync ${checkSrc}\nasync ${submitSrc}\n`
    + 'return {checkRestoreFile, submitRestore};')(document, fetch, api, (t, k) => toasts.push(`${k}: ${t}`), () => {});
  const firstCheck = checkRestoreFile();
  fetches[0]({ok: true, status: 200, json: async () => ({...base, upload_id: 'first-upload'})});
  await firstCheck;
  if (pickAnother) {
    input.files = [{name: 'second.cpbackup', size: 12, lastModified: 2}];
    input.value = 'second.cpbackup';
  }
  await submitRestore('first-upload');
  return {sent, toasts};
}
let picked = await restoreAfterPicking(true);
check('a file picked after the check is not restored under the checked one',
  picked.sent.length === 0 && picked.toasts.length === 1 && /^error: .*Check file again/.test(picked.toasts[0]), picked);
picked = await restoreAfterPicking(false);
check('control: the checked file still in the picker restores', picked.sent.join() === 'first-upload', picked);

if (bad) {
  console.error(`\n${bad} check(s) failed`);
  process.exit(1);
}
console.log('\nrestore preview and remove: all checks passed');
