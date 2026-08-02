// Drive the CashPilot UI in headless Chrome and report what a browser actually
// sees: inline handlers still present, Content-Security-Policy violations, and
// uncaught JS errors (CashPilot-guw).
//
// The CSP and app.js beads sat blocked for several sessions on "cannot verify
// without a browser". Static checks cannot see a CSP violation or a handler
// that silently stopped firing, and this is a live revenue UI, so shipping the
// change on a read-through was not acceptable. Chrome is already installed on
// any machine a developer uses; Node has a global WebSocket, so this needs no
// dependencies at all.
//
//   ./scripts/ui_check.sh http://127.0.0.1:8099/onboarding
//
// Exits non-zero on any CSP violation or uncaught error, so it can gate a
// change rather than merely describe one.
const [,, url] = process.argv;
const port = 9222;
const res = await fetch(`http://127.0.0.1:${port}/json/new?${encodeURIComponent(url)}`, {method: 'PUT'});
const target = await res.json();
const ws = new WebSocket(target.webSocketDebuggerUrl);
let id = 0;
const pending = new Map();
const violations = [];
const errors = [];
const send = (method, params = {}) => new Promise(r => { pending.set(++id, r); ws.send(JSON.stringify({id, method, params})); });

await new Promise(r => ws.addEventListener('open', r));
ws.addEventListener('message', ev => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m.result); pending.delete(m.id); }
  if (m.method === 'Log.entryAdded') {
    const e = m.params.entry;
    if (/Content Security Policy/i.test(e.text)) violations.push(e.text.slice(0, 160));
    else if (e.level === 'error') errors.push(e.text.slice(0, 160));
  }
  if (m.method === 'Runtime.exceptionThrown') {
    errors.push((m.params.exceptionDetails.exception?.description || 'exception').slice(0, 160));
  }
});
await send('Log.enable'); await send('Runtime.enable'); await send('Page.enable');
await send('Page.navigate', {url});
await new Promise(r => setTimeout(r, 2500));
const inline = await send('Runtime.evaluate', {
  expression: `JSON.stringify({
    onclick: document.querySelectorAll('[onclick]').length,
    dataAction: document.querySelectorAll('[data-action]').length,
    title: document.title
  })`, returnByValue: true});
const seen = JSON.parse(inline.result.value);
console.log(`page          : ${seen.title}`);
console.log(`inline onclick: ${seen.onclick}`);
console.log(`data-action   : ${seen.dataAction}`);
console.log(`csp_violations: ${violations.length}`, violations.slice(0, 5));
console.log(`js_errors     : ${errors.length}`, errors.slice(0, 5));
ws.close();

// A CSP violation or an uncaught error means the page is broken in a way no
// static check would have caught, which is the entire reason this exists.
if (violations.length || errors.length) process.exit(1);
