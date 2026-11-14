// Run the real password step-up prompt against a stub DOM.
//
// The prompt is one shared modal. Two deploys that both need the password
// used to open it at once: the second took the first's buttons, and closing it
// after the second answer cancelled the first, so that deploy failed without
// ever being asked. Only running the prompt shows which answer reaches which
// caller, so this executes the real askStepUp and showStepUp.
//
//   node scripts/step_up_prompt_check.mjs
//
// Exits non-zero on any mismatch.
import {readFileSync} from 'node:fs';

const src = readFileSync('app/static/js/app.js', 'utf8');
const start = src.indexOf('let stepUpQueue');
const end = src.indexOf('function showStepUp(');
if (start < 0 || end < 0) {
  console.error('FAIL: the step-up queue or showStepUp is missing from app/static/js/app.js');
  process.exit(1);
}
// From the queue to the end of showStepUp (the next top-level comment block).
const tail = src.slice(end);
const stop = tail.search(/\n  \/\/ -{10}/);
const code = src.slice(start, end) + tail.slice(0, stop > 0 ? stop : 3000);

// A DOM small enough to be obviously correct. Class changes notify observers on
// a microtask, as a browser's MutationObserver does.
const observers = new Set();
const overlay = {
  classes: new Set(),
  classList: {
    add: c => { overlay.classes.add(c); notify(); },
    remove: c => { overlay.classes.delete(c); notify(); },
    contains: c => overlay.classes.has(c),
  },
};
const notify = () => { for (const o of [...observers]) queueMicrotask(() => observers.has(o) && o.cb()); };
class MutationObserver {
  constructor(cb) { this.cb = cb; }
  observe() { observers.add(this); }
  disconnect() { observers.delete(this); }
}
const els = {
  'stepup-modal': overlay,
  'stepup-password': {value: '', focus() {}},
  'stepup-message': {textContent: ''},
  'stepup-submit': {}, 'stepup-cancel': {}, 'stepup-close': {},
};
// The control the owner pressed to start the deploy; focus must come back to it.
const trigger = {isConnected: true, focused: 0, focus() { this.focused++; }};
const document = {getElementById: id => els[id] || null, activeElement: trigger};
const setTimeout = () => 0;
const {askStepUp} = new Function('document', 'MutationObserver', 'setTimeout', `${code}; return {askStepUp};`)(
  document, MutationObserver, setTimeout,
);

let bad = 0;
const check = (label, cond, detail) => {
  console.log(`  ${cond ? 'ok  ' : 'FAIL'} ${label}${cond ? '' : `  <- ${detail}`}`);
  if (!cond) bad++;
};
const tick = () => new Promise(r => setImmediate(r));
const type = text => { els['stepup-password'].value = text; };

// --- two prompts at once: each caller gets its own answer -------------------
const first = askStepUp('first deploy');
const second = askStepUp('second deploy');
await tick();
check('the first prompt shows first', els['stepup-message'].textContent === 'first deploy', els['stepup-message'].textContent);
type('pw-one');
els['stepup-submit'].onclick();
await tick();
check('the second prompt opens once the first is answered', overlay.classList.contains('open')
  && els['stepup-message'].textContent === 'second deploy', els['stepup-message'].textContent);
check('the field is empty for the second prompt', els['stepup-password'].value === '', els['stepup-password'].value);
type('pw-two');
els['stepup-submit'].onclick();
const answers = await Promise.all([first, second]);
check('the first caller gets the first password', answers[0] === 'pw-one', answers[0]);
check('the second caller gets the second password', answers[1] === 'pw-two', answers[1]);
check('the modal is closed after both', !overlay.classList.contains('open'), [...overlay.classes]);

// --- cancelling one prompt does not cancel the one behind it ----------------
const a = askStepUp('a');
const b = askStepUp('b');
await tick();
els['stepup-cancel'].onclick();
await tick();
type('pw-b');
els['stepup-submit'].onclick();
const [ra, rb] = await Promise.all([a, b]);
check('a cancelled prompt answers null', ra === null, ra);
check('the next prompt still gets its password', rb === 'pw-b', rb);

// --- closing the overlay from outside (Escape) cancels only the open prompt -
const c = askStepUp('c');
const d = askStepUp('d');
await tick();
overlay.classList.remove('open');
await tick();
check('the next prompt opens after an outside close', overlay.classList.contains('open')
  && els['stepup-message'].textContent === 'd', els['stepup-message'].textContent);
type('pw-d');
els['stepup-submit'].onclick();
const [rc, rd] = await Promise.all([c, d]);
check('the closed prompt answers null', rc === null, rc);
check('the one behind it gets its password', rd === 'pw-d', rd);

// --- focus returns to the control that opened the prompt, on every close ----
for (const [label, close] of [
  ['submit', () => { type('pw'); els['stepup-submit'].onclick(); }],
  ['cancel', () => els['stepup-cancel'].onclick()],
  ['an outside close', () => overlay.classList.remove('open')],
]) {
  trigger.focused = 0;
  const p = askStepUp(label);
  await tick();
  close();
  await p;
  check(`focus returns to the opener after ${label}`, trigger.focused === 1, trigger.focused);
}
trigger.isConnected = false;
trigger.focused = 0;
const gone = askStepUp('gone');
await tick();
els['stepup-cancel'].onclick();
await gone;
check('a removed opener is not focused', trigger.focused === 0, trigger.focused);

console.log(bad ? `\nRESULT: FAIL (${bad})` : '\nRESULT: PASS');
process.exit(bad ? 1 : 0);
