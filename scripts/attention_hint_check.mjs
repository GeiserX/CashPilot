// Run the real renderAttention: a health hint on one box of a service shows as
// a "Needs fixing" row naming that box, and its text is escaped.
//
// The hint comes from a windowed health signal (Mysterium's sessions never
// connecting directly), and a string test cannot show it reaches the list.
//
//   node scripts/attention_hint_check.mjs
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

const run = new Function(
  'document', 'escapeHtml', 'api', 'fmtTimestamp',
  `let _attentionSeq = 0; let _canWrite = true; let _isOwner = false;
   const _attentionCount = {problems: 0, payouts: 0};
   function updateAttentionSummary() {}
   ${grab('function instanceState')}
   ${grab('function copyState')}
   ${grab('function copyWords')}
   ${grab('async function renderAttention')}
   return {renderAttention, count: () => _attentionCount.problems};`,
)(document, escapeHtml, async () => [], () => ({text: ''}));

let bad = 0;
const check = (label, cond) => {
  console.log(`  ${cond ? 'ok  ' : 'FAIL'} ${label}`);
  if (!cond) bad++;
};

const svc = hints => ({
  slug: 'mysterium', name: 'MystNodes',
  instance_details: [
    {node: 'nas', worker_id: 7, status: 'running', instance: 1, hints},
    {node: 'pi', worker_id: 8, status: 'running', instance: 1, hints: []},
  ],
});
const workers = [{id: 7, name: 'nas', status: 'online'}, {id: 8, name: 'pi', status: 'online'}];

await run.renderAttention([svc(['Forward UDP 56000:56100 to <192.168.10.100>.'])], workers);
check('the hint is one Needs fixing row', (list.innerHTML.match(/Needs fixing/g) || []).length === 1 && run.count() === 1);
check('it names the box it is about', /attn-where">nas</.test(list.innerHTML));
check('its text is escaped', list.innerHTML.includes('&lt;192.168.10.100&gt;') && !list.innerHTML.includes('<192.168'));

await run.renderAttention([svc([])], workers);
check('no hint, no row', !list.innerHTML.includes('Needs fixing') && run.count() === 0);

if (bad) {
  console.error(`${bad} check(s) failed`);
  process.exit(1);
}
console.log('A health hint shows as one escaped Needs fixing row on its own box, and goes when the hint does.');
