// Run the real Settings failure path against a stub DOM.
//
// CashPilot-cn3: /api/env-info and /api/collectors/meta each carry their own
// .catch, so the only call in loadSettings' Promise.all that can reject is
// /api/config — and its rejection aborts the whole thing before either render
// function runs. Both panels then keep the template's "Loading..." string, and
// the catch body was empty, so nothing ever corrected it. An expired session or
// a restarting server looked like a page that simply never finished loading.
//
// A string test can prove the catch is no longer empty. It cannot prove that
// BOTH containers get written, or that what lands in them says anything useful.
// So this executes the real functions.
//
//   node scripts/settings_failure_check.mjs
//
// Exits non-zero on any mismatch.
import {readFileSync} from 'node:fs';

const src = readFileSync('app/static/js/app.js', 'utf8');
const grab = name => {
  const i = src.indexOf(`function ${name}(`);
  if (i < 0) {
    console.error(`FAIL: ${name} is not defined in app/static/js/app.js`);
    process.exit(1);
  }
  const rest = src.slice(i);
  const end = rest.search(/\n  (?:async )?function [A-Za-z_]/);
  return rest.slice(0, end > 0 ? end : 2000);
};

// A DOM small enough to be obviously correct: two containers holding exactly
// what the template ships.
const made = {};
const document = {
  getElementById(id) {
    if (!['env-vars-container', 'collectors-container'].includes(id)) return null;
    if (!made[id]) made[id] = {innerHTML: 'Loading...'};
    return made[id];
  },
};

const fns = grab('escapeHtml') + '\n' + grab('settingsLoadFailureMessage') + '\n' + grab('settingsPanelsFailed');
const run = new Function('document', `${fns}; return {settingsLoadFailureMessage, settingsPanelsFailed};`)(document);

let bad = 0;
const check = (label, cond, detail) => {
  console.log(`  ${cond ? 'ok  ' : 'FAIL'} ${label}${cond ? '' : `  <- ${detail}`}`);
  if (!cond) bad++;
};

// --- the message itself -----------------------------------------------------
const msg = run.settingsLoadFailureMessage(new Error('401 Unauthorized'));
check('names a cause', /session|expired/i.test(msg), msg);
check('names an action', /reload|sign in/i.test(msg), msg);
check('carries the underlying detail', msg.includes('401 Unauthorized'), msg);

const bare = run.settingsLoadFailureMessage(undefined);
check('survives an error with no message', bare.length > 0 && !bare.includes('undefined'), bare);

// --- what actually lands in the panels --------------------------------------
run.settingsPanelsFailed(new Error('boom'));
for (const id of ['env-vars-container', 'collectors-container']) {
  const html = made[id].innerHTML;
  check(`${id} no longer says Loading`, !html.includes('Loading...'), html);
  check(`${id} explains itself`, /session|expired/i.test(html), html);
}

// --- the message is escaped before it reaches innerHTML ---------------------
// The detail comes from a server response, so it is untrusted.
made['env-vars-container'] = {innerHTML: 'Loading...'};
made['collectors-container'] = {innerHTML: 'Loading...'};
run.settingsPanelsFailed(new Error('<img src=x onerror=alert(1)>'));
check(
  'the error detail is escaped, not injected',
  !made['env-vars-container'].innerHTML.includes('<img'),
  made['env-vars-container'].innerHTML,
);

console.log(bad ? `\nRESULT: FAIL (${bad})` : '\nRESULT: PASS');
process.exit(bad ? 1 : 0);
