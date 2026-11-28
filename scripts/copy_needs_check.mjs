// Run the REAL fillNeeds() of fleet.html's copy form against a small DOM.
//
// The form lists one checkbox per risk the owner must acknowledge, and the
// server refuses the copy without every one. Two ways it went wrong:
//   - the page refreshes every 60 s and rebuilt the boxes unticked, so an
//     owner who ticked them and waited lost them, and the copy was refused;
//   - a failed lookup left an empty panel with Run enabled, so the copy went
//     out with no ticks and was refused with no word why.
//
//   node scripts/copy_needs_check.mjs
// Exits non-zero on any mismatch.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import './i18n_stub.mjs';

const html = readFileSync('app/templates/fleet.html', 'utf8');

function extract(name) {
  const start = html.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`fleet.html no longer defines ${name}() — this check is stale`);
  let i = html.indexOf('{', start), depth = 0;
  for (let j = i; j < html.length; j++) {
    if (html[j] === '{') depth++;
    else if (html[j] === '}' && --depth === 0) return html.slice(start, j + 1);
  }
  throw new Error(`unbalanced braces reading ${name}()`);
}

const esc = s => String(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

// The panel's checkboxes, read back from the HTML fillNeeds wrote.
const box = {
  innerHTML: '',
  querySelectorAll(sel) {
    assert.equal(sel, 'input[data-ack]:checked');
    return [...this.innerHTML.matchAll(/<input type="checkbox" data-ack="([a-z_]+)" checked>/g)].map(m => ({dataset: {ack: m[1]}}));
  },
};
const tick = key => { box.innerHTML = box.innerHTML.replace(`data-ack="${key}">`, `data-ack="${key}" checked>`); };
const run = {disabled: false};
const slug = {value: 'mysterium'};
const proxy = {value: '3'};
let retryHandler = null;
const document = {
  getElementById: id => ({
    'copy-needs': box,
    'copy-run': run,
    'copy-slug': slug,
    'copy-proxy': proxy,
    'copy-needs-retry': {addEventListener: (_, fn) => { retryHandler = fn; }},
  })[id],
};
let answer = {needs: ['net_admin', 'tun_device', 'no_inbound'], volumes: ['mysterium-data-p3']};
const CP = {api: async () => { if (answer instanceof Error) throw answer; return answer; }};

const fillNeeds = new Function(
  'document', 'CP', 'esc', 't',
  `let _needsAsked = 0;\nlet _needsFor = '';\n${extract('ackText')}\nreturn async ${extract('fillNeeds')};`,
)(document, CP, esc, globalThis.t);

await fillNeeds();
assert.equal(run.disabled, false, 'Run is on once the needs are known');
assert.equal(box.querySelectorAll('input[data-ack]:checked').length, 0, 'nothing is ticked for the owner');
assert.match(box.innerHTML, /data-ack="net_admin"/);

// The owner ticks two; the 60 s refresh asks again for the same service and proxy.
tick('net_admin');
tick('no_inbound');
await fillNeeds();
assert.deepEqual(
  box.querySelectorAll('input[data-ack]:checked').map(el => el.dataset.ack), ['net_admin', 'no_inbound'],
  'a refresh of the same service and proxy keeps the ticks',
);

// Another proxy: the ticks answered the old one's needs, so they go.
proxy.value = '4';
await fillNeeds();
assert.equal(box.querySelectorAll('input[data-ack]:checked').length, 0, 'another proxy clears the ticks');

// The lookup fails: the owner is told, Run stays off, and Try again asks again.
answer = new Error('worker offline');
await fillNeeds();
assert.equal(run.disabled, true, 'Run stays off while the needs are unknown');
assert.match(box.innerHTML, /could not read what this service needs behind this proxy \(worker offline\)/);
assert.equal(typeof retryHandler, 'function', 'the retry button asks again');
answer = {needs: ['net_admin'], volumes: []};
await retryHandler();
assert.equal(run.disabled, false, 'a retry that works turns Run back on');
assert.match(box.innerHTML, /data-ack="net_admin"/);

// A refusal keeps Run off.
answer = {refusal: 'Storj needs inbound connections on a published port.'};
await fillNeeds();
assert.equal(run.disabled, true, 'a refused service cannot be run');
console.log('Copy form: the ticks survive a refresh, a failed lookup is shown with a retry, and Run waits for the needs.');
