// Run the real renderAttention and refreshAttentionOnAlertChange with requests
// that answer in a chosen order, and check that only the newest draw writes:
//
// - a bell redraw never discards a services response still in flight (it used
//   to, and the list kept showing a box that had recovered);
// - of two bell redraws, the older one answering last does not write;
// - of two services refreshes, the older one answering last does not write;
// - a bell redraw built on old services does not overwrite a newer services
//   response.
//
//   node scripts/attention_race_check.mjs
//
// Exits non-zero on any mismatch.
import {readFileSync} from 'node:fs';

const src = readFileSync('app/static/js/app.js', 'utf8');

function grab(sig) {
  const i = src.indexOf(`  ${sig}(`);
  if (i < 0) {
    console.error(`FAIL: ${sig} is not defined in app/static/js/app.js; this harness is testing nothing.`);
    process.exit(1);
  }
  const rest = src.slice(i);
  return rest.slice(0, rest.indexOf('\n  }\n') + 4);
}

const escapeHtml = s =>
  String(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c]);
const list = {innerHTML: ''};
const document = {getElementById: id => (id === 'attention-list' ? list : null)};

// Every request waits until the test answers it, in the order the test picks.
const pending = [];
const api = path => new Promise(resolve => pending.push({path, resolve}));
const answer = async (index, value) => {
  const [req] = pending.splice(index, 1);
  req.resolve(value);
  for (let i = 0; i < 20; i++) await Promise.resolve();
};
const settle = async () => {
  for (let i = 0; i < 20; i++) await Promise.resolve();
};

const run = new Function(
  'document', 'escapeHtml', 'api', 'fmtTimestamp',
  `let _attentionSeq = 0; let _attentionDrawSeq = 0; let _attentionAlertsKey = null;
   let _canWrite = true; let _isOwner = true;
   const DOCKER_LOST_DOC = 'https://example.invalid/doc';
   const _attentionCount = {problems: 0, payouts: 0, services: null, workers: null};
   function updateAttentionSummary(services, workers) {
     if (services) { _attentionCount.services = services; _attentionCount.workers = workers; }
   }
   ${grab('function instanceState')}
   ${grab('function copyState')}
   ${grab('function copyWords')}
   ${grab('async function renderAttention')}
   ${grab('function refreshAttentionOnAlertChange')}
   return {
     renderAttention, refreshAttentionOnAlertChange,
     services: (s, w) => renderAttention(s, w, ++_attentionSeq),
     snapshot: () => _attentionCount.services,
     key: () => _attentionAlertsKey,
     reset: () => { _attentionSeq = 0; _attentionDrawSeq = 0; _attentionAlertsKey = null;
                    _attentionCount.services = null; _attentionCount.workers = null; },
   };`,
)(document, escapeHtml, api, () => ({text: ''}));

let bad = 0;
const check = (label, cond) => {
  console.log(`  ${cond ? 'ok  ' : 'FAIL'} ${label}`);
  if (!cond) bad++;
};

const workers = [{id: 7, name: 'nas', status: 'online'}];
const svc = hint => [{
  slug: 'mysterium', name: 'MystNodes',
  instance_details: [{node: 'nas', worker_id: 7, status: 'running', instance: 1, hints: hint ? [hint] : []}],
}];
const OLD = svc('OLD-STATE');
const NEW = svc(null);
const docker = [{kind: 'docker', platform: 'nas', error: 'cannot reach Docker'}];

async function start() {
  run.reset();
  list.innerHTML = '';
  pending.length = 0;
  // A first services refresh with the old state, answered, so the snapshot exists.
  const first = run.services(OLD, workers);
  await settle();
  await answer(0, {alerts: []});
  await answer(0, []);
  await first;
  // The bell has seen its first poll.
  run.refreshAttentionOnAlertChange([]);
}

// 1. A services response in flight; a bell redraw answers first; the response still commits.
await start();
const fresh = run.services(NEW, workers);
await settle();
const redraw = run.refreshAttentionOnAlertChange(docker);
await settle();
// pending: [services alerts, redraw credentials]
await answer(1, []);
await redraw;
await answer(0, {alerts: docker});
await answer(0, []);
await fresh;
check('a bell redraw does not discard the services response in flight', run.snapshot() === NEW);
check('the newer services state is drawn', !list.innerHTML.includes('OLD-STATE'));
check('the next bell poll draws again, since the redraw read newer alerts', run.key() === '');

// 2. Two bell redraws; the older answers last and does not write.
await start();
const older = run.refreshAttentionOnAlertChange(docker);
await settle();
const newer = run.refreshAttentionOnAlertChange([]);
await settle();
await answer(1, []);
await newer;
await answer(0, []);
await older;
check('the older of two bell redraws does not write', !list.innerHTML.includes('Docker unreachable'));

// 3. Two services refreshes; the older answers last and does not write.
await start();
const s1 = run.services(OLD, workers);
await settle();
const s2 = run.services(NEW, workers);
await settle();
await answer(1, {alerts: []});
await answer(1, []);
await s2;
await answer(0, {alerts: []});
await answer(0, []);
await s1;
check('the older of two services refreshes does not write', !list.innerHTML.includes('OLD-STATE') && run.snapshot() === NEW);

// 4. A bell redraw built on the old services answers after a newer services response.
await start();
const stale = run.refreshAttentionOnAlertChange(docker);
await settle();
const s3 = run.services(NEW, workers);
await settle();
// pending: [redraw credentials, services alerts]
await answer(1, {alerts: docker});
await answer(1, []);
await s3;
await answer(0, []);
await stale;
check('a redraw built on old services does not overwrite a newer services response', !list.innerHTML.includes('OLD-STATE'));

if (bad) {
  console.error(`${bad} check(s) failed`);
  process.exit(1);
}
console.log('Only the newest draw writes the attention list, and a bell redraw never discards a services response.');
