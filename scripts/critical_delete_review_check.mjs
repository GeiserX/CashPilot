// Run the dashboard's real Remove paths against a stub api() and confirm().
//
// A delete of critical data (a node identity, a wallet, a partial restore)
// must show the owner the exact volumes the box named, with the time Docker
// made each, before the password is asked, and send that set back: the box
// deletes those or nothing. Two paths once sent the override with no set (the
// retry after a partial restore, and a custom service's Remove), so the box
// deleted whatever was mounted then. Only running them shows what they send.
//
//   node scripts/critical_delete_review_check.mjs
//
// Exits non-zero on any mismatch.
import {readFileSync} from 'node:fs';

const src = readFileSync('app/static/js/app.js', 'utf8');
const slice = (from, to) => {
  const a = src.indexOf(from);
  const b = src.indexOf(to, a);
  if (a < 0 || b < 0) {
    console.error(`FAIL: ${from.trim()} is missing from app/static/js/app.js`);
    process.exit(1);
  }
  return src.slice(a, b);
};
const code = slice('  function confirmCriticalVolumes(', '  // -----------------------------------------------------------\n  // Log viewer')
  + slice('  async function removeCustomFromBox(', '  async function deployServiceToWorkers(');

const REVIEWED = 'mysterium-data@2026-11-01T10:00:00Z';
const BLOCKED = [{volume: 'mysterium-data', target: '/var/lib/mysterium-node', holds: 'the node identity'}];
const refusal = (error, extra = {}) => Object.assign(new Error(error), {code: error, refusal: {error, ...extra}});

// One run: ``answer(path)`` is what the box says to each request; confirm() says yes.
async function run(fn, args, answer, {yes = () => true} = {}) {
  const events = [];
  const api = async (path, opts) => {
    events.push({kind: 'api', path, body: opts?.body});
    return answer(path);
  };
  const confirm = (text) => { events.push({kind: 'confirm', text}); return yes(text); };
  const toast = (text, type) => events.push({kind: 'toast', text, type});
  const window = {confirm};
  const make = new Function('api', 'confirm', 'toast', 'window', '_isOwner', 'loadServicesTable', 'openServiceDetail',
    `${code}; return {removeService, removeCustomFromBox};`);
  const fns = make(api, confirm, toast, window, true, () => {}, () => {});
  await fns[fn](...args);
  return events;
}

let bad = 0;
const check = (label, cond, detail) => {
  console.log(`  ${cond ? 'ok  ' : 'FAIL'} ${label}${cond ? '' : `  <- ${detail}`}`);
  if (!cond) bad++;
};
const overridden = (e) => e.kind === 'api' && e.path.includes('allow_delete_critical=true');
const sentSet = (e) => new URLSearchParams(e.path.split('?')[1]).get('critical_set');

// What a box answers: a critical refusal naming REVIEWED until the override
// carries a set, then the removal.
const box = (first) => (path) => {
  if (path.includes('allow_delete_critical=true')) return {status: 'removed', deleted_volumes: ['mysterium-data']};
  if (first && !path.includes('delete_volumes=true')) throw first;
  throw refusal('critical_volume', {critical_set: REVIEWED, blocked: BLOCKED});
};

function reviewedBeforeTheOverride(label, events) {
  const at = events.findIndex(overridden);
  check(`${label}: the override is sent`, at >= 0, JSON.stringify(events));
  if (at < 0) return;
  const shown = events.slice(0, at).filter((e) => e.kind === 'confirm').map((e) => e.text).join('\n');
  check(`${label}: the volume and the time Docker made it are shown before the password`,
    shown.includes('mysterium-data') && shown.includes('2026-11-01T10:00:00Z'), shown);
  check(`${label}: the override carries exactly the reviewed set`, sentSet(events[at]) === REVIEWED, events[at].path);
  check(`${label}: every override carries a set`, events.filter(overridden).every((e) => sentSet(e) !== null),
    JSON.stringify(events.filter(overridden)));
}

// --- Remove with its data, on a box that holds a node identity ---------------
reviewedBeforeTheOverride('remove with data', await run('removeService', ['mysterium', 7, 'box-a'], box(null)));

// --- the retry after a partial restore the owner kept the data of -----------
const unfinished = refusal('restore_unfinished', {message: 'A restore did not finish.'});
const keepDataFirst = (text) => !text.startsWith('Also delete the data');
reviewedBeforeTheOverride('partial restore retry',
  await run('removeService', ['mysterium', 7, 'box-a', 'leftover'], box(unfinished), {yes: keepDataFirst}));

// --- a custom service's Remove with its data ---------------------------------
reviewedBeforeTheOverride('custom service', await run('removeCustomFromBox', ['my-app', 7, 'box-a'], box(null)));

// --- the owner cancels the review: no override goes --------------------------
const cancel = (text) => !text.startsWith('These volumes');
const cancelled = await run('removeService', ['mysterium', 7, 'box-a'], box(null), {yes: cancel});
check('a cancelled review sends no override', !cancelled.some(overridden), JSON.stringify(cancelled));

if (bad) {
  console.error(`\n${bad} check(s) failed`);
  process.exit(1);
}
console.log('\nall checks passed');
