// Drive a REAL first-boot install in a browser: land on whatever the root URL
// gives a new user, fill the form, press Create Account, then ask the SERVER
// whether the account exists.
//
//   1. start a fresh instance on an empty CASHPILOT_DATA_DIR
//   2. take the setup token from its startup log
//   3. node scripts/first_boot_check.mjs http://127.0.0.1:PORT <token>
//
// Exists because this path was broken in v1.10.1 and no test noticed: every
// other test creates its owner by calling database.create_user directly, so
// the actual install flow was never once exercised.
// Can a brand-new user actually install CashPilot?
//
// Nothing in the suite answered this. Every test creates its owner by calling
// database.create_user directly, so the real first-boot path — land on
// /onboarding, fill the form, click Create Account — had never once been
// exercised. It 403s, because that page never asked for the setup token the
// backend requires.
const [, , base, token] = process.argv;
const t = await (await fetch('http://127.0.0.1:9222/json/new?about:blank', {method: 'PUT'})).json();
const ws = new WebSocket(t.webSocketDebuggerUrl);
let id = 0; const pend = new Map(); const errors = [], violations = [];
const send = (m, p = {}) => new Promise(r => {pend.set(++id, r); ws.send(JSON.stringify({id, method: m, params: p}));});
await new Promise(r => ws.addEventListener('open', r));
ws.addEventListener('message', e => {
  const m = JSON.parse(e.data);
  if (m.id && pend.has(m.id)) {pend.get(m.id)(m.result); pend.delete(m.id);}
  if (m.method === 'Log.entryAdded') {
    const x = m.params.entry;
    if (/Content Security Policy/i.test(x.text)) violations.push(x.text.slice(0, 140));
    else if (x.level === 'error') errors.push(x.text.slice(0, 140));
  }
  if (m.method === 'Runtime.exceptionThrown') errors.push((m.params.exceptionDetails.exception?.description || 'x').slice(0, 140));
});
await send('Log.enable'); await send('Runtime.enable'); await send('Page.enable');

// A real new user opens the root URL and follows whatever it gives them.
await send('Page.navigate', {url: base + '/'});
await new Promise(r => setTimeout(r, 2500));
const ev = async e => JSON.parse((await send('Runtime.evaluate', {expression: e, returnByValue: true, awaitPromise: true})).result.value);

const landed = await ev(`JSON.stringify({url: location.pathname, hasTokenField: !!document.getElementById('setup_token')})`);
console.log('landed on           :', JSON.stringify(landed));

// Walk the wizard the way a person does, then submit with the real token.
const result = await ev(`(async () => {
  if (typeof goToStep === 'function') goToStep(2);
  await new Promise(r => setTimeout(r, 400));
  const set = (id, v) => { const el = document.getElementById(id); if (el) { el.value = v; } };
  set('username', 'sergio');
  set('password', 'A-real-passphrase-123');
  set('password_confirm', 'A-real-passphrase-123');
  set('setup_token', ${JSON.stringify(token)});
  document.getElementById('register-form').dispatchEvent(new Event('submit', {cancelable: true, bubbles: true}));
  await new Promise(r => setTimeout(r, 2500));
  const err = document.getElementById('reg-error');
  return JSON.stringify({
    errorShown: err && err.classList.contains('visible') ? err.textContent.trim() : null,
    step3Visible: !!document.querySelector('#step-3.active, [id="step-3"].active'),
  });
})()`);
console.log('after Create Account:', JSON.stringify(result));

// The real proof: does the account now exist? Ask the server, not the page.
const after = await fetch(base + '/login', {redirect: 'manual'});
const stillOnboarding = after.status === 303 && (after.headers.get('location') || '').includes('onboarding');
console.log('server says users ex.:', !stillOnboarding);
console.log('csp violations      :', violations.length ? violations : 'none');
console.log('js errors           :', errors.length ? errors : 'none');

const ok = landed.hasTokenField && !result.errorShown && !stillOnboarding && !violations.length && !errors.length;
console.log(ok ? '\nRESULT: PASS — a new user can install' : '\nRESULT: FAIL');
process.exit(ok ? 0 : 1);
