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
import './i18n_stub.mjs';
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
const code = slice('  function isDesktopWorker(', '  function workerCheckboxList(')
  + slice('  function confirmCriticalVolumes(', '  // -----------------------------------------------------------\n  // Log viewer')
  + slice('  async function removeCustomFromBox(', '  async function deployServiceToWorkers(');

const REVIEWED = 'mysterium-data@2026-11-01T10:00:00Z';
const BLOCKED = [{volume: 'mysterium-data', target: '/var/lib/mysterium-node', holds: 'the node identity'}];
const refusal = (error, extra = {}) => Object.assign(new Error(error), {code: error, refusal: {error, ...extra}});

// One run: ``answer(path)`` is what the box says to each request; confirm() says yes.
// ``workers`` is the service detail's box list (a server box unless told).
async function run(fn, args, answer, {yes = () => true, workers = []} = {}) {
  const events = [];
  const api = async (path, opts) => {
    events.push({kind: 'api', path, body: opts?.body});
    return answer(path);
  };
  const confirm = (text) => { events.push({kind: 'confirm', text}); return yes(text); };
  const toast = (text, type) => events.push({kind: 'toast', text, type});
  const window = {confirm};
  const make = new Function('api', 'confirm', 'toast', 'window', '_isOwner', 'loadServicesTable', 'openServiceDetail',
    '_detailWorkers', `${code}; return {removeService, removeCustomFromBox};`);
  const fns = make(api, confirm, toast, window, true, () => {}, () => {}, workers);
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

// --- a Desktop box: it deletes critical data only on that computer ----------
// So the first refusal is the answer: no review, no override, one error toast.
const DESKTOP = [{id: 7, name: 'box-a', system_info: {device_type: 'desktop'}}];
for (const fn of ['removeService', 'removeCustomFromBox']) {
  const slug = fn === 'removeService' ? 'mysterium' : 'my-app';
  const events = await run(fn, [slug, 7, 'box-a'], box(null), {workers: DESKTOP});
  const deletes = events.filter((e) => e.kind === 'api');
  const toasts = events.filter((e) => e.kind === 'toast');
  check(`${fn} on a Desktop: one DELETE, never the override`,
    deletes.length === 1 && !overridden(deletes[0]), JSON.stringify(deletes));
  check(`${fn} on a Desktop: no volume review`,
    !events.some((e) => e.kind === 'confirm' && e.text.startsWith('These volumes')), JSON.stringify(events));
  check(`${fn} on a Desktop: one error toast that says where the data is deleted`,
    toasts.length === 1 && toasts[0].type === 'error' && toasts[0].text.includes('only on that computer'),
    JSON.stringify(toasts));
}

// --- the owner cancels the review: no override goes --------------------------
const cancel = (text) => !text.startsWith('These volumes');
const cancelled = await run('removeService', ['mysterium', 7, 'box-a'], box(null), {yes: cancel});
check('a cancelled review sends no override', !cancelled.some(overridden), JSON.stringify(cancelled));

// --- what the toast says about a volume that stays -------------------------
// One another client replaced since the review is kept for good: telling the
// owner to Remove again sends them after a row that is gone.
const removedWith = (extra) => (path) => {
  if (path.includes('allow_delete_critical=true')) return {status: 'removed', deleted_volumes: [], ...extra};
  throw refusal('critical_volume', {critical_set: REVIEWED, blocked: BLOCKED});
};
const toastOf = (events) => events.filter((e) => e.kind === 'toast').map((e) => e.text).join('\n');
const replacedToast = toastOf(await run('removeService', ['mysterium', 7, 'box-a'],
  removedWith({failed_volumes: ['mysterium-data'], replaced_volumes: ['mysterium-data']})));
check('a replaced volume is not sent back to Remove again', !replacedToast.includes('Try Remove again'), replacedToast);
check('a replaced volume is named as another client\'s, kept by the box',
  replacedToast.includes('another client replaced its volume mysterium-data'), replacedToast);
// A leftover row's first Remove is a plain DELETE with no review: a volume the
// restore left that another client had replaced is named there too, never a
// plain success.
const leftoverEvents = await run('removeService', ['mysterium', 7, 'box-a', 'leftover'],
  () => ({status: 'removed', deleted_volumes: [], failed_volumes: ['mysterium-data'], replaced_volumes: ['mysterium-data']}));
const leftoverToasts = leftoverEvents.filter((e) => e.kind === 'toast');
check('a leftover Remove that kept a replaced volume is not a success',
  leftoverToasts.length === 1 && leftoverToasts[0].type === 'error', JSON.stringify(leftoverToasts));
check('a leftover Remove names the replaced volume without claiming a review',
  toastOf(leftoverEvents).includes('another client replaced its volume mysterium-data, so the box kept that volume'),
  toastOf(leftoverEvents));
const failedToast = toastOf(await run('removeService', ['mysterium', 7, 'box-a'],
  removedWith({failed_volumes: ['mysterium-data'], replaced_volumes: []})));
check('control: a volume Docker would not delete still says Remove again',
  failedToast.includes('mysterium-data could not be deleted and stays. Try Remove again.'), failedToast);
// A volume an older worker's record names with nothing that proves it is the
// restore's: Remove again alone never deletes it, so the owner checks it.
const unverifiedToast = toastOf(await run('removeService', ['mysterium', 7, 'box-a'],
  removedWith({failed_volumes: ['mysterium-data'], replaced_volumes: [], unverified_volumes: ['mysterium-data']})));
check('an unverified volume is not sent back to Remove again alone',
  !unverifiedToast.includes('could not be deleted and stays. Try Remove again.'), unverifiedToast);
check('an unverified volume is named for the owner to check and delete',
  unverifiedToast.includes('cannot tell whether its volume mysterium-data holds the partial restore')
    && unverifiedToast.includes('service stays held'), unverifiedToast);
// Keeping the volume keeps the hold: the toast says so, not only "delete it if".
check('an unverified volume\'s toast says the hold ends only once the volume is gone',
  unverifiedToast.includes('stays held until that volume is gone')
    && !unverifiedToast.includes('delete it if it holds the partial restore'), unverifiedToast);
const unreadToast = toastOf(await run('removeService', ['mysterium', 7, 'box-a'],
  removedWith({failed_volumes: ['mysterium-data'], replaced_volumes: [], unverified_volumes: [], unread_volumes: ['mysterium-data']})));
check('an unreadable volume is sent back to Remove again, not to a delete by hand',
  unreadToast.includes('could not read its volume mysterium-data just now') && unreadToast.includes('Try Remove again.')
    && !unreadToast.includes('cannot tell whether') && !unreadToast.includes('could not be deleted and stays'), unreadToast);

// A custom service's Remove reads the box's answer too: a volume that stays is
// never a plain success, on the first DELETE or on the reviewed retry.
const customFirst = await run('removeCustomFromBox', ['my-app', 7, 'box-a'],
  () => ({status: 'removed', deleted_volumes: [], failed_volumes: ['my-app-data']}));
const customFirstToasts = customFirst.filter((e) => e.kind === 'toast');
check('a custom Remove whose volume stays is not a success',
  customFirstToasts.length === 1 && customFirstToasts[0].type === 'error'
    && customFirstToasts[0].text.includes('my-app-data could not be deleted and stays'), JSON.stringify(customFirstToasts));
// The Remove already deleted the container and its record, so the box row and
// its Remove button are gone, and a DELETE again finds nothing: the toast sends
// the owner to the box, never back to Remove.
check('a custom Remove whose volume stays is not sent back to Remove again',
  customFirstToasts.length === 1 && !customFirstToasts[0].text.includes('Remove again')
    && customFirstToasts[0].text.includes('Delete it on box-a by hand'), JSON.stringify(customFirstToasts));
const customRetry = await run('removeCustomFromBox', ['my-app', 7, 'box-a'],
  removedWith({failed_volumes: ['mysterium-data'], replaced_volumes: ['mysterium-data']}));
const customRetryToasts = customRetry.filter((e) => e.kind === 'toast');
check('a custom Remove\'s reviewed retry names the replaced volume, not a success',
  customRetryToasts.length === 1 && customRetryToasts[0].type === 'error'
    && customRetryToasts[0].text.includes('another client replaced its volume mysterium-data'), JSON.stringify(customRetryToasts));
const customClean = await run('removeCustomFromBox', ['my-app', 7, 'box-a'], box(null));
check('control: a custom Remove that deleted everything is a success',
  customClean.filter((e) => e.kind === 'toast').map((e) => e.type).join() === 'success', JSON.stringify(customClean));

if (bad) {
  console.error(`\n${bad} check(s) failed`);
  process.exit(1);
}
console.log('\nall checks passed');
