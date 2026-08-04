// Run the REAL sanitizeHint source in a REAL DOM against the REAL shipped hint.
//
// Needed because the interesting property cannot be seen from the source: an
// external review asked for rel="noopener noreferrer" on the 13 credential-hint
// anchors in services/*.yml, and that fix would have done NOTHING — the
// sanitiser strips every attribute it does not explicitly keep, so the rel is
// removed on its way to the DOM. It would have looked applied and had no
// effect. Case 2 below pins exactly that.
//
// Requires a headless Chrome on port 9222 (see scripts/ui_check.sh).
//   node scripts/hint_sanitizer_check.mjs
// Exits non-zero on any mismatch.
import {readFileSync} from 'node:fs';
const src = readFileSync('app/static/js/app.js', 'utf8');
const fn = src.slice(src.indexOf('function sanitizeHint('), src.indexOf('  function capFirst'));
const t = await (await fetch('http://127.0.0.1:9222/json/new?about:blank', {method:'PUT'})).json();
const ws = new WebSocket(t.webSocketDebuggerUrl);
let id = 0; const pend = new Map();
const send = (m,p={}) => new Promise(r => {pend.set(++id, r); ws.send(JSON.stringify({id, method:m, params:p}));});
await new Promise(r => ws.addEventListener('open', r));
ws.addEventListener('message', e => {const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) {pend.get(m.id)(m.result); pend.delete(m.id);}});
await send('Runtime.enable'); await send('Page.enable');
await send('Page.navigate', {url: 'about:blank'});
await new Promise(r => setTimeout(r, 800));
const ev = async e => JSON.parse((await send('Runtime.evaluate', {expression: e, returnByValue: true})).result.value);

// Run the REAL sanitizer source in a real DOM, on the real hint text.
const real = readFileSync('services/bandwidth/earnapp.yml', 'utf8')
  .match(/credential_hint: "(.*)"/)[1].replace(/\\"/g, '"');

const out = await ev(`(() => {
  ${fn}
  const cases = {};
  // 1. The real shipped hint, exactly as stored in YAML.
  const a = document.createElement('div');
  a.innerHTML = sanitizeHint(${JSON.stringify(real)});
  const link = a.querySelector('a');
  cases.shipped = {target: link && link.getAttribute('target'), rel: link && link.getAttribute('rel'), href: link && link.getAttribute('href')};

  // 2. A rel written IN THE YAML — proves the reviewer's fix would be stripped.
  const b = document.createElement('div');
  b.innerHTML = sanitizeHint("<a href='https://x.test' target='_blank' rel='WRITTEN-IN-YAML'>x</a>");
  cases.yamlRel = b.querySelector('a').getAttribute('rel');

  // 3. A link with no target must not gain a rel it does not need.
  const c = document.createElement('div');
  c.innerHTML = sanitizeHint("<a href='https://x.test'>x</a>");
  cases.noTarget = c.querySelector('a').getAttribute('rel');

  // 4. The sanitizer must still strip dangerous things.
  const d = document.createElement('div');
  d.innerHTML = sanitizeHint("<a href='javascript:alert(1)' target='_blank' onclick='x()'>x</a><script>bad()<\\/script>");
  const dl = d.querySelector('a');
  cases.dangerous = {href: dl && dl.getAttribute('href'), onclick: dl && dl.getAttribute('onclick'), scripts: d.querySelectorAll('script').length};
  return JSON.stringify(cases);
})()`);
console.log(JSON.stringify(out, null, 2));
const ok = out.shipped.rel === 'noopener noreferrer'
  && out.shipped.target === '_blank'
  && out.shipped.href === 'https://earnapp.com'
  && out.yamlRel === 'noopener noreferrer'     // overwritten, not the YAML value
  && out.noTarget === null                      // untouched
  && out.dangerous.href === null && !out.dangerous.onclick && out.dangerous.scripts === 0;
console.log(ok ? '\nRESULT: PASS' : '\nRESULT: FAIL');
process.exit(ok ? 0 : 1);
