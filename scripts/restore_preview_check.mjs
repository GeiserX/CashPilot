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
function runRemove({owner, answers, refusal = 'restore_unfinished'}) {
  const sent = [];
  const asked = [];
  const toasts = [];
  const fetch = async (path, config) => {
    sent.push(`${config.method} ${path}`);
    const ok = sent.length > 1 || !refusal;
    const body = ok ? {status: 'removed'}
      : {detail: {error: refusal, message: 'A restore of mysterium did not finish.'}};
    return {ok, status: ok ? 200 : 409, json: async () => body};
  };
  const confirm = (text) => { asked.push(text); return answers.shift(); };
  const toast = (text, kind) => toasts.push(`${kind}: ${text}`);
  const {removeService} = new Function(
    'fetch', 'confirm', 'toast', 'loadServicesTable', '_isOwner', 'window', 'askStepUp',
    `${apiSrc}\n${removeSrc}\nreturn {removeService};`,
  )(fetch, confirm, toast, () => {}, owner, {confirm}, async () => null);
  return removeService('mysterium').then(() => ({sent, asked, toasts}));
}

let run = await runRemove({owner: true, answers: [true, true]});
check('a refused Remove asks the owner about the half-written data',
  run.asked.length === 2 && /partial restore/.test(run.asked[1]) && /deletes that volume/.test(run.asked[1]), run.asked);
check('and sends it again as the audited critical delete', run.sent.length === 2
  && run.sent[1] === 'DELETE /api/services/mysterium?delete_volumes=true&allow_delete_critical=true', run.sent);
check('and says it was removed', run.toasts.join() === 'success: mysterium removed', run.toasts);
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

if (bad) {
  console.error(`\n${bad} check(s) failed`);
  process.exit(1);
}
console.log('\nrestore preview and remove: all checks passed');
