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

if (bad) {
  console.error(`\n${bad} check(s) failed`);
  process.exit(1);
}
console.log('\nrestore preview: all checks passed');
