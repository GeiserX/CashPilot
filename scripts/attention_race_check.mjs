// Run the real renderAttention and refreshAttentionOnAlertChange with requests
// that answer in a chosen order, and check that only the newest draw writes:
//
// - a bell redraw never discards a services response still in flight (it used
//   to, and the list kept showing a box that had recovered);
// - of two bell redraws, the older one answering last does not write;
// - of two services refreshes, the older one answering last does not write;
// - a bell redraw built on old services does not overwrite a newer services
//   response;
// - on the first load, a bell poll that lands while the services response
//   waits on credential health is drawn once that response commits (it was
//   lost: the first poll only recorded its alerts, and the list stayed empty);
// - a poll sent before a services read is older: its alerts do not overwrite
//   that read's list, whichever answers first.
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
const api = path => new Promise((resolve, reject) => pending.push({path, resolve, reject}));
const answer = async (index, value) => {
  const [req] = pending.splice(index, 1);
  req.resolve(value);
  for (let i = 0; i < 20; i++) await Promise.resolve();
};
const fail = async index => {
  const [req] = pending.splice(index, 1);
  req.reject(new Error('down'));
  for (let i = 0; i < 20; i++) await Promise.resolve();
};
const settle = async () => {
  for (let i = 0; i < 20; i++) await Promise.resolve();
};

const run = new Function(
  'document', 'escapeHtml', 'api', 'fmtTimestamp',
  `let _attentionSeq = 0; let _attentionDrawSeq = 0; let _attentionReads = 0; let _attentionLatestAlerts = null; let _attentionLatestRead = 0; let _attentionDrawnKey = null; let _attentionDrawnRead = 0;
   let _canWrite = true; let _isOwner = true;
   const DOCKER_LOST_DOC = 'https://example.invalid/doc';
   const _attentionCount = {problems: 0, payouts: 0, services: null, workers: null};
   function updateAttentionSummary(services, workers) {
     if (services) { _attentionCount.services = services; _attentionCount.workers = workers; }
   }
   ${grab('function instanceState')}
   ${grab('function copyState')}
   ${grab('function copyWords')}
   ${grab('function attentionAlertsKey')}
   ${grab('async function renderAttention')}
   ${grab('function refreshAttentionOnAlertChange')}
   return {
     renderAttention, refreshAttentionOnAlertChange,
     services: (s, w) => renderAttention(s, w, ++_attentionSeq),
     snapshot: () => _attentionCount.services,
     drawn: () => _attentionDrawnKey,
     reset: () => { _attentionSeq = 0; _attentionDrawSeq = 0; _attentionReads = 0; _attentionLatestAlerts = null; _attentionLatestRead = 0;
                    _attentionDrawnKey = null; _attentionDrawnRead = 0;
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
check('the services response read the docker alert, so the list shows it', list.innerHTML.includes('Docker unreachable'));
check('and the list records the alerts it was drawn with', run.drawn() === JSON.stringify([['docker', 'nas', 'cannot reach Docker']]));

// 1b. Same, but the services response read older alerts than the redraw: it
// commits, then draws again at once with the alerts the bell saw last.
await start();
const fresh2 = run.services(NEW, workers);
await settle();
const redraw2 = run.refreshAttentionOnAlertChange(docker);
await settle();
await answer(1, []);
await redraw2;
await answer(0, {alerts: []});
await answer(0, []);
await fresh2;
await settle();
// pending: [the follow-up redraw's credentials]
check('a services response that read older alerts asks for a redraw', pending.length === 1);
if (pending.length) await answer(0, []);
check('the redraw draws the alerts the bell saw last on the newer services', run.snapshot() === NEW
  && !list.innerHTML.includes('OLD-STATE') && list.innerHTML.includes('Docker unreachable'));

// 2. Two bell redraws; the older answers last and does not write.
const docker2 = [{kind: 'docker', platform: 'nas', error: 'NEWER-ALERT'}];
await start();
const older = run.refreshAttentionOnAlertChange(docker);
await settle();
const newer = run.refreshAttentionOnAlertChange(docker2);
await settle();
await answer(1, []);
await newer;
await answer(0, []);
await older;
check('the older of two bell redraws does not write', list.innerHTML.includes('NEWER-ALERT') && !list.innerHTML.includes('cannot reach Docker'));

// 2b. A redraw in flight, then a poll with the alerts the list already shows: the redraw does not write.
await start();
const outdated = run.refreshAttentionOnAlertChange(docker);
await settle();
check('a poll matching the drawn list starts no redraw', run.refreshAttentionOnAlertChange([]) === null);
await answer(0, []);
await outdated;
check('and the redraw it outdated does not write', !list.innerHTML.includes('Docker unreachable'));

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

// 5. First load: the services response reads no alerts and waits on credential
// health; the first bell poll sees the docker alert during that wait.
run.reset();
list.innerHTML = '';
pending.length = 0;
const load = run.services(NEW, workers);
await settle();
await answer(0, {alerts: []});
// pending: [services credentials]
check('the first bell poll cannot draw yet: there are no services', run.refreshAttentionOnAlertChange(docker) === null);
await answer(0, []);
await load;
await settle();
if (pending.length) await answer(0, []);
check('the alert the first poll saw is drawn once the services response commits', list.innerHTML.includes('Docker unreachable'));
// And a later identical poll leaves the list as it is.
check('an identical later poll does not redraw', run.refreshAttentionOnAlertChange(docker) === null);

// 6. The bell last saw a docker alert, which then cleared. A services refresh
// (after a start, say) reads no alerts: its fresh list is not redrawn with the
// older poll's alert.
await start();
const shown = run.refreshAttentionOnAlertChange(docker);
await settle();
await answer(0, []);
await shown;
const after = run.services(NEW, workers);
await settle();
await answer(0, {alerts: []});
await answer(0, []);
await after;
await settle();
while (pending.length) await answer(0, []);
check('a fresh services read is not overwritten by an older bell poll (a cleared alert stays gone)', !list.innerHTML.includes('Docker unreachable'));

// 7. The reverse: the services read finds a new alert the last poll did not have.
await start();
const found = run.services(NEW, workers);
await settle();
await answer(0, {alerts: docker});
await answer(0, []);
await found;
await settle();
while (pending.length) await answer(0, []);
check('a new alert the services read found is not hidden by an older bell poll', list.innerHTML.includes('Docker unreachable'));

// 8. A poll sent before the services read but answered after it commits is older: it does not redraw.
await start();
const late = run.services(NEW, workers);
await settle();
await answer(0, {alerts: []});
await answer(0, []);
await late;
await settle();
check('a poll older than the drawn list starts no redraw', run.refreshAttentionOnAlertChange(docker, 0) === null && pending.length === 0);

// 9. The services read of the alerts fails: the list falls back to what the bell saw last.
await start();
const seen = run.refreshAttentionOnAlertChange(docker);
await settle();
await answer(0, []);
await seen;
const blind = run.services(NEW, workers);
await settle();
await fail(0);
await answer(0, []);
await blind;
await settle();
while (pending.length) await answer(0, []);
check('a services draw that could not read the alerts draws the ones the bell saw last', list.innerHTML.includes('Docker unreachable'));

if (bad) {
  console.error(`${bad} check(s) failed`);
  process.exit(1);
}
console.log('Only the newest draw writes the attention list, and a bell redraw never discards a services response.');
