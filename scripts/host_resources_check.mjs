// Run the real Disk/GPU column code against realistic worker payloads.
//
// These two columns answer questions no other column can:
//
//   * Storj is paid for what it STORES, so free space is earning capacity. A
//     node that quietly fills up stops growing and nothing said so.
//   * Salad, Nosana, io.net and Vast.ai only earn with a GPU. Today the table
//     cannot tell a GPU service that is earning from one that is running and
//     idle because the device was never passed through -- the Mysterium
//     /dev/net/tun failure mode: healthy-looking, earning nothing.
//
// Both are facts about the HOST, so they must work for a remote worker exactly
// as for the local one. That is the whole point, and it is why this drives the
// functions rather than grepping the file: the first draft iterated
// `svc.instances`, which is a COUNT, and `for...of` over a number throws --
// that would have taken down the entire table, not just one column.
//
//   node scripts/host_resources_check.mjs
//
// Exits non-zero on any mismatch.
import {readFileSync} from 'node:fs';

const src = readFileSync('app/static/js/app.js', 'utf8');

const START = '  let _hostResources = null;';
const END = '  async function loadServicesTable() {';
const from = src.indexOf(START);
const to = src.indexOf(END);
if (from < 0 || to < 0 || to <= from) {
  console.error('FAIL: the host-resource block moved; this harness is testing nothing.');
  process.exit(1);
}
const block = src.slice(from, to);

// escapeHtml is the real one's contract, reproduced: the block calls it.
const escapeHtml = s =>
  String(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c]);

const api = new Function(
  'escapeHtml',
  `${block}
   return {buildHostResourceMap, diskCell, gpuCell, sortableFreeBytes, sortableGpu, fmtBytes,
           hostForWorker, diskCellForHosts, gpuCellForHosts, SORT_UNKNOWN,
           setHosts: m => { _hostResources = m; }};`,
)(escapeHtml);

let bad = 0;
let checksRun = 0;
const check = (label, cond, detail) => {
  checksRun++;
  console.log(`  ${cond ? 'ok  ' : 'FAIL'} ${label}${cond ? '' : `  <- ${detail}`}`);
  if (!cond) bad++;
};

const GB = 1024 ** 3;
const worker = (id, name, {disk, gpu, online = true} = {}) => ({
  id, name, status: online ? 'online' : 'offline',
  system_info: {...(disk === undefined ? {} : {disk}), ...(gpu === undefined ? {} : {gpu})},
});
const svc = (...workerIds) => ({slug: 's', instance_details: workerIds.map(w => ({worker_id: w}))});

// ---------------------------------------------------------------- disk
const FLEET = [
  worker(1, 'watchtower', {disk: {free_bytes: 900 * GB, total_bytes: 1000 * GB}, gpu: {available: true, devices: ['DRM render node (3)']}}),
  worker(2, 'geiserct', {disk: {free_bytes: 24 * GB, total_bytes: 98 * GB}, gpu: {available: null, reason: 'no GPU is visible from inside this container'}}),
  worker(3, 'nodisk', {gpu: {available: false, devices: []}}),
];
api.setHosts(api.buildHostResourceMap(FLEET));

const one = api.diskCell(svc(1));
check('a host with free space reports it', /900 GB/.test(one), one);
check('and does not claim to be the service volume', /host filesystem/.test(one), one);

// The case that matters: a service spanning two hosts must surface the one
// that will run out first, not an average that hides it.
const spanning = api.diskCell(svc(1, 2));
check('a multi-host service shows the TIGHTEST host', /24 GB/.test(spanning), spanning);
check('and says it is the tightest of several', /tightest of 2 hosts/.test(spanning), spanning);
// 76% used is NOT "near full" -- the first version of this check asserted it
// was flagged and failed, because the code is right and the expectation was
// wrong. Thresholds are 80% (warning) and 90% (danger), so the fixtures now
// straddle them deliberately.
check('a host at 76% is not yet flagged', !/var\(--warning\)|var\(--danger\)/.test(spanning), spanning);
check('a roomy host is not flagged', !/var\(--danger\)/.test(one), one);

api.setHosts(api.buildHostResourceMap([
  ...FLEET,
  worker(4, 'tight', {disk: {free_bytes: 15 * GB, total_bytes: 100 * GB}}),   // 85%
  worker(5, 'critical', {disk: {free_bytes: 4 * GB, total_bytes: 100 * GB}}), // 96%
]));
const warned = api.diskCell(svc(4));
const danger = api.diskCell(svc(5));
check('a host at 85% is warned', /var\(--warning\)/.test(warned), warned);
check('a host at 96% escalates to danger', /var\(--danger\)/.test(danger), danger);
check('the used percentage is stated, not just free space', /85% used/.test(warned), warned);
api.setHosts(api.buildHostResourceMap(FLEET));

const noDisk = api.diskCell(svc(3));
check('a worker that never reported disk is unknown, not 0', /&mdash;/.test(noDisk) && !/0 B/.test(noDisk), noDisk);
check('and says why', /did not report/.test(noDisk), noDisk);

// ---------------------------------------------------------------- gpu
const gpuYes = api.gpuCell(svc(1));
check('a visible GPU names the device', /DRM render node/.test(gpuYes), gpuYes);

// THE BUG THIS COLUMN EXISTS FOR. A containerised worker cannot see the host's
// GPU. Reporting that as "None" would state as fact that a machine has no GPU
// while it sits on three idle render nodes -- which is how the whole fleet read.
const gpuUnknown = api.gpuCell(svc(2));
check('a GPU that could not be checked is NOT reported as None', !/None/.test(gpuUnknown), gpuUnknown);
check('it renders as unknown', /&mdash;/.test(gpuUnknown), gpuUnknown);
// The worker's own words, verbatim from _gpu_info(). The first version of this
// looked for "not visible" while the reason says "no GPU is visible" -- the
// check was wrong, the string was right.
check('and carries the worker\'s own reason through',
  /no GPU is visible from inside this container/.test(gpuUnknown), gpuUnknown);

const gpuNone = api.gpuCell(svc(3));
check('a host that genuinely said no reads as None', /None/.test(gpuNone), gpuNone);

// Mixed: one host has a GPU, one could not tell. "Has one" is the true answer
// for the service, because it is earning on that host.
const mixed = api.gpuCell(svc(1, 2));
check('mixed hosts report the GPU that IS present', /DRM render node/.test(mixed), mixed);

// ---------------------------------------------------------------- unknown hosts
const unknownSvc = api.diskCell({slug: 'x', instance_details: []});
check('a service with no known host is unknown', /&mdash;/.test(unknownSvc), unknownSvc);

// Drive the BUILDER with the failure value, not setHosts(null) directly.
// Going straight to the private state skipped buildHostResourceMap entirely, so
// a mutation making it return {} for a failed lookup passed this harness --
// caught by a negative control that did not fire.
check('a failed worker fetch builds no map at all', api.buildHostResourceMap(null) === null, String(api.buildHostResourceMap(null)));
check('an empty fleet still builds a map', JSON.stringify(api.buildHostResourceMap([])) === '{}', String(api.buildHostResourceMap([])));

api.setHosts(api.buildHostResourceMap(null));
const noWorkers = api.diskCell(svc(1));
check('a failed worker lookup is not "no disk"', /could not read the worker list/.test(noWorkers), noWorkers);
check('the GPU column agrees', /could not read the worker list/.test(api.gpuCell(svc(1))), api.gpuCell(svc(1)));

// An EMPTY worker list is a different answer from a FAILED lookup.
api.setHosts(api.buildHostResourceMap([]));
check('an empty fleet does not claim the lookup failed',
  !/could not read the worker list/.test(api.diskCell(svc(1))), api.diskCell(svc(1)));

// ---------------------------------------------------------------- the count bug
api.setHosts(api.buildHostResourceMap(FLEET));
let threw = null;
try {
  // `instances` is a COUNT in the real payload. Reading it as a list throws.
  api.diskCell({slug: 's', instances: 3, instance_details: [{worker_id: 1}]});
} catch (e) {
  threw = e;
}
check('a payload carrying the instances COUNT does not throw', threw === null, String(threw));

// ---------------------------------------------------------------- sorting
const rows = [svc(1), svc(2), svc(3)];
check('free bytes sorts by the tightest host', api.sortableFreeBytes(svc(1, 2)) === 24 * GB, String(api.sortableFreeBytes(svc(1, 2))));
check('a host with no disk reading sorts as UNKNOWN', api.sortableFreeBytes(svc(3)) === api.SORT_UNKNOWN, String(api.sortableFreeBytes(svc(3))));
check('unknown is NOT zero', api.sortableFreeBytes(svc(3)) !== 0, 'unknown collapsed to 0 and would rank as a full disk');
check('a present GPU outranks a known-absent one', api.sortableGpu(svc(1)) > api.sortableGpu(svc(3)), '');
check('an unchecked GPU is unknown, not ranked below "none"', api.sortableGpu(svc(2)) === api.SORT_UNKNOWN, String(api.sortableGpu(svc(2))));

// Unknown must sink in BOTH directions. A numeric sentinel cannot do that:
// -Infinity sorts last descending but FIRST ascending, which would put every
// unreadable host at the top of "least free space".
const cmp = (a, b, asc) => {
  const va = api.sortableFreeBytes(a), vb = api.sortableFreeBytes(b);
  const aU = va === api.SORT_UNKNOWN, bU = vb === api.SORT_UNKNOWN;
  if (aU || bU) return aU && bU ? 0 : (aU ? 1 : -1);
  return asc ? va - vb : vb - va;
};
for (const asc of [true, false]) {
  const sorted = [...rows].sort((a, b) => cmp(a, b, asc));
  const lastIsUnknown = api.sortableFreeBytes(sorted[sorted.length - 1]) === api.SORT_UNKNOWN;
  check(`unknown sorts LAST when ascending=${asc}`, lastIsUnknown, JSON.stringify(sorted.map(api.sortableFreeBytes).map(String)));
}

// ------------------------------------------------- the real fleet, verbatim
// Copied from the live database rather than invented, so this asserts what
// production actually sends. Every Docker worker reports disk; NONE reports a
// GPU, because the workers are containerised and the devices were never passed
// through -- while the hosts have three render nodes each.
const REAL = [
  {id: 1, name: 'watchtower', status: 'online', system_info: {
    disk: {free_bytes: 1073 * GB, total_bytes: 1798 * GB},
    gpu: {available: null, devices: [], reason: 'no GPU is visible from inside this container; the host may still have one that was not passed through'}}},
  {id: 2, name: 'geiserback', status: 'online', system_info: {
    disk: {free_bytes: 545 * GB, total_bytes: 899 * GB},
    gpu: {available: null, devices: [], reason: 'no GPU is visible from inside this container; the host may still have one that was not passed through'}}},
  {id: 3, name: 'geiserct', status: 'online', system_info: {
    disk: {free_bytes: 23 * GB, total_bytes: 98 * GB},
    gpu: {available: null, devices: [], reason: 'no GPU is visible from inside this container; the host may still have one that was not passed through'}}},
  // The phone reports neither, and never will -- it is not a Docker host.
  {id: 4, name: 'OPPO CPH1951', status: 'online', system_info: {device_type: 'android'}},
];
api.setHosts(api.buildHostResourceMap(REAL));

const ct = api.diskCell(svc(3));
check('the real tightest host is surfaced', /23 GB/.test(ct), ct);
check('and flagged, since 76% is under the 80% threshold it is NOT', !/var\(--danger\)/.test(ct), ct);
const fleetWide = api.diskCell(svc(1, 2, 3));
check('a service across the whole real fleet reports the tightest', /23 GB/.test(fleetWide), fleetWide);

// Not one of them reports a GPU. All three must read UNKNOWN, never "None" --
// the hosts have three render nodes each.
for (const id of [1, 2, 3]) {
  const cell = api.gpuCell(svc(id));
  check(`real worker ${id} reads GPU as unknown, not None`, !/None/.test(cell) && /&mdash;/.test(cell), cell);
}

// The Android client collects neither. Telling its owner to upgrade would send
// them after something that was never going to report.
const phoneDisk = api.diskCell(svc(4));
const phoneGpu = api.gpuCell(svc(4));
check('the phone is not told it predates the feature', !/predate/.test(phoneDisk), phoneDisk);
check('it is told the Android client does not report disk', /Android client does not report host disk/.test(phoneDisk), phoneDisk);
check('and the same for GPU', /Android client does not report GPU/.test(phoneGpu), phoneGpu);
check('the phone is never reported as having no GPU', !/None/.test(phoneGpu), phoneGpu);

api.setHosts(api.buildHostResourceMap(FLEET));

// ---------------------------------------------------------------- formatting
check('bytes format readably', api.fmtBytes(24 * GB) === '24 GB', api.fmtBytes(24 * GB));
check('a null size is null, not "0 B"', api.fmtBytes(null) === null, String(api.fmtBytes(null)));
check('a negative size is rejected', api.fmtBytes(-5) === null, String(api.fmtBytes(-5)));
check('zero bytes is a real reading and formats', api.fmtBytes(0) === '0 B', String(api.fmtBytes(0)));

// ---------------------------------------------------------------- escaping
api.setHosts(api.buildHostResourceMap([
  worker(9, '<img src=x onerror=alert(1)>', {gpu: {available: true, devices: ['<script>bad()</script>']}}),
]));
const nasty = api.gpuCell(svc(9));
check('a hostile device name is escaped', !nasty.includes('<script>'), nasty);
check('a hostile worker name is escaped in the tooltip', !nasty.includes('<img'), nasty);

console.log(bad ? `\nRESULT: FAIL (${bad} of ${checksRun})` : `\nRESULT: PASS (${checksRun} assertions)`);
process.exit(bad ? 1 : 0);
