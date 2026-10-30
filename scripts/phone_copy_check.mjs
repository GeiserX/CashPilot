// Run the real renderAttention and renderPlacement on a phone that reports one
// app stopped and one it cannot see. A phone app is never called a container,
// a stopped one says to open it on the phone, and an unknown one is never red
// "Down" or amber: the phone could not look, nothing died.
//
//   node scripts/phone_copy_check.mjs
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
const maybe = sig => (src.includes(`  ${sig}(`) ? grab(sig) : '');

const escapeHtml = s =>
  String(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c]);
const list = {innerHTML: ''};
const grid = {innerHTML: ''};
const document = {getElementById: id => (id === 'attention-list' ? list : id === 'placement-grid' ? grid : null)};

const run = new Function(
  'document', 'escapeHtml', 'api', 'fmtTimestamp',
  `let _attentionSeq = 0; let _canWrite = true; let _isOwner = false;
   const _attentionCount = {problems: 0, payouts: 0};
   function updateAttentionSummary() {}
   ${grab('function instanceState')}
   ${maybe('function copyState')}
   ${maybe('function copyWords')}
   ${grab('function renderPlacement')}
   ${grab('async function renderAttention')}
   return {renderAttention, renderPlacement, count: () => _attentionCount.problems};`,
)(document, escapeHtml, async () => [], () => ({text: ''}));

let bad = 0;
const check = (label, cond) => {
  console.log(`  ${cond ? 'ok  ' : 'FAIL'} ${label}`);
  if (!cond) bad++;
};

// What /api/services sends for a phone copy: status from the phone's
// three-valued `running`, is_android set, and the app slug as its name.
const phone = (status) => ({node: 'OPPO', worker_id: 5, status, is_android: true, has_docker: false, container_name: 'grass', instance: 1, hints: []});
const services = [
  {slug: 'grass', name: 'Grass', instance_details: [phone('stopped')]},
  {slug: 'wipter', name: 'Wipter', instance_details: [phone('unknown')]},
  {slug: 'nodle', name: 'Nodle', instance_details: [phone('running')]},
];
const workers = [{id: 5, name: 'OPPO', status: 'online'}];

await run.renderAttention(services, workers);
const rows = list.innerHTML.split('attn-row').slice(1);
const grass = rows.find(r => r.includes('Grass')) || '';
const wipter = rows.find(r => r.includes('Wipter')) || '';
check('no phone row says container', !/container/i.test(list.innerHTML));
check('a stopped app says it is not running on the phone', /not running on the phone/.test(grass) && /Open it on the phone/.test(grass));
check('a stopped app is not tagged Down', !/>Down</.test(grass));
check('an unknown app says the phone cannot tell', /phone cannot tell/.test(wipter));
check('an unknown app is never Down or red', !/>Down</.test(wipter) && !/attn-fail/.test(wipter));
check('a running app has no row', !rows.some(r => r.includes('Nodle')));
check('an unknown app is a grey row, not amber', /attn-unknown/.test(wipter) && !/attn-warn/.test(wipter));
check('only the stopped app counts as a problem', run.count() === 1);
check('no Start or Logs button for a phone app', !/startService|viewLogs/.test(list.innerHTML));

run.renderPlacement(services, workers);
const cell = name => (grid.innerHTML.split('<tr').find(r => r.includes(`>${name}<`)) || '');
check('placement: a stopped app reads as not running on the phone', /app not running on the phone/.test(cell('Grass')));
check('placement: an unknown app is neither red nor amber', /cell-unknown/.test(cell('Wipter')) && !/cell-fail|cell-warn/.test(cell('Wipter')));
check('placement: no phone cell says stopped or unknown bare', !/: stopped"|: unknown"/.test(grid.innerHTML));

// An offline phone's apps may still run; it has no containers.
await run.renderAttention([], [{id: 5, name: 'OPPO', status: 'offline', system_info: {os: 'Android'}}]);
check('an offline phone says its apps may still be running', /Its apps may still be running/.test(list.innerHTML) && !/container/i.test(list.innerHTML));
await run.renderAttention([], [{id: 7, name: 'nas', status: 'offline', system_info: {docker_available: true}}]);
check('an offline server still says containers', /Its containers may still be running/.test(list.innerHTML));

// A Docker copy keeps its container wording.
await run.renderAttention([{slug: 'honeygain', name: 'Honeygain', instance_details: [{node: 'nas', worker_id: 7, status: 'exited', has_docker: true, container_name: 'cashpilot-honeygain', instance: 1, hints: []}]}], [{id: 7, name: 'nas', status: 'online'}]);
check('a Docker copy still says container is exited', /container is exited/.test(list.innerHTML) && />Down</.test(list.innerHTML));

if (bad) {
  console.error(`${bad} check(s) failed`);
  process.exit(1);
}
console.log('Phone apps are never containers: stopped says open it on the phone, unknown stays neutral.');
