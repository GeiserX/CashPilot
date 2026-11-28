// Run the REAL app/static/js/image_updates.js and check that a choice the
// owner has not saved yet survives every refresh.
//
// The section reloads its data every minute, after a save and after Check now.
// A reload that answered after the owner changed a select drew the controls
// again from the server's copy, so the change was lost without a word. The
// script now counts changes, and draws the controls again only when every
// change is saved. Only running it proves that, so this drives the script with
// a tiny DOM and API answers that arrive when the check says so.
//   node scripts/image_updates_check.mjs
// Exits non-zero on any mismatch.
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {t} from './i18n_stub.mjs';

const src = readFileSync('app/static/js/image_updates.js', 'utf8');

function makePage() {
  const listeners = {root: {}, doc: {}};
  const root = {
    innerHTML: '',
    renders: 0,
    addEventListener: (type, fn) => { listeners.root[type] = fn; },
    querySelectorAll: () => [],
  };
  // Count each time the controls are drawn.
  let html = '';
  Object.defineProperty(root, 'innerHTML', {
    get: () => html,
    set: (v) => { html = v; root.renders += 1; },
  });
  const pending = [];
  const calls = [];
  const api = (url, opts = {}) => new Promise((resolve) => {
    calls.push({url, method: opts.method || 'GET', body: opts.body});
    pending.push(resolve);
  });
  const data = {
    settings: {mode: 'auto', hour: 4, workers: {}, services: {}},
    settle_seconds: 120, workers: [], services: [], history: [], running: false,
  };
  const context = {
    document: {
      getElementById: (id) => (id === 'updates-body' ? root : null),
      addEventListener: (type, fn) => { listeners.doc[type] = fn; },
    },
    window: {CPI18N: globalThis.CPI18N},
    CP: {api, toast: () => {}},
    t,
    setInterval: (fn) => { context.tick = fn; },
    String, Number, Object, JSON, Promise, Array, Date,
  };
  vm.runInNewContext(src, context);
  return {
    root,
    calls,
    change: () => listeners.root.change(),
    click: (action) => listeners.doc.click({target: {closest: () => ({dataset: {updatesAction: action}})}}),
    tick: () => context.tick(),
    // Answer the oldest open request, then let the script run on.
    answer: async (body = data) => { pending.shift()(body); for (let i = 0; i < 5; i++) await Promise.resolve(); },
    open: () => pending.length,
  };
}

const failures = [];
let checksRun = 0;
const check = (name, ok, detail) => { checksRun++; if (!ok) failures.push(`${name}: ${detail}`); };

// 1. The first load draws the section.
let p = makePage();
await p.answer();
check('the first load draws the controls', p.root.renders === 1, `drawn ${p.root.renders} times`);

// 2. A change made while a refresh is on its way is kept.
p = makePage();
await p.answer();
p.tick();
p.change();
await p.answer();
check('a refresh that answers after a change keeps it', p.root.renders === 1, `drawn ${p.root.renders} times`);
p.tick();
check('the minute refresh waits while a change is not saved', p.open() === 0, `${p.open()} request(s) sent`);

// 3. A save clears the changes it sent, and only those.
p = makePage();
await p.answer();
p.change();
p.click('save');
check('Save sends a PUT', p.calls.at(-1).method === 'PUT', `sent ${p.calls.at(-1).method}`);
p.change();
await p.answer({});
await p.answer();
check('a change made during the save survives the reload after it', p.root.renders === 1, `drawn ${p.root.renders} times`);
p.click('save');
await p.answer({});
await p.answer();
check('once every change is saved, the reload draws the controls', p.root.renders === 2, `drawn ${p.root.renders} times`);

// 4. Check now keeps a change that is not saved.
p = makePage();
await p.answer();
p.change();
p.click('run');
check('Check now posts the run', p.calls.at(-1).url === '/api/image-updates/run', `sent ${p.calls.at(-1).url}`);
await p.answer({status: 'started'});
await p.answer();
check('Check now keeps a change that is not saved', p.root.renders === 1, `drawn ${p.root.renders} times`);

// 5. A positive control: with no change, Check now's reload draws again.
p = makePage();
await p.answer();
p.click('run');
await p.answer({status: 'started'});
await p.answer();
check('with no change, the reload after Check now draws the controls', p.root.renders === 2, `drawn ${p.root.renders} times`);

if (failures.length) {
  console.error(`image updates check FAILED (${failures.length} of ${checksRun}):\n  ${failures.join('\n  ')}`);
  process.exit(1);
}
console.log(`image updates check: ${checksRun} checks passed`);
