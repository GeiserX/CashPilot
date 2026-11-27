// Run the browser's message formatter (app/static/js/i18n.js) on the shared
// cases in tests/fixtures/i18n_format_cases.json. tests/test_i18n.py runs the
// server's formatter (app/i18n) on the same file, so the two cannot drift: a
// message reads the same whether the page or the API filled it in.
//
//   node scripts/i18n_format_check.mjs
//
// Exits non-zero on any mismatch, and when the case file is empty.
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const cases = JSON.parse(readFileSync('tests/fixtures/i18n_format_cases.json', 'utf8'));
const src = readFileSync('app/static/js/i18n.js', 'utf8');

function load(lang, messages = {}) {
  const window = {CP_I18N: {lang, dir: lang === 'ar' ? 'rtl' : 'ltr', messages}};
  const context = {
    window,
    navigator: {language: 'en-US', languages: ['en-US']},
    document: {readyState: 'complete', querySelectorAll: () => [], cookie: ''},
    Intl, Map, Number, Object, String, Error,
  };
  vm.runInNewContext(src, context);
  return window;
}

let bad = 0;
if (!cases.length) {
  console.error('FAIL: no cases');
  process.exit(1);
}
for (const c of cases) {
  const w = load(c.locale, {k: c.message});
  const got = w.t('k', c.params);
  const ok = got === c.expected;
  if (!ok) bad++;
  console.log(`  ${ok ? 'ok  ' : 'FAIL'} [${c.locale}] ${c.message.slice(0, 60)}${ok ? '' : `\n       got ${JSON.stringify(got)}, want ${JSON.stringify(c.expected)}`}`);
}

// A key with no string shows the key, never a blank.
const w = load('en', {});
if (w.t('missing.key') !== 'missing.key') { bad++; console.log('  FAIL missing key'); }
// A broken message shows its raw text rather than throwing into the page.
const broken = load('en', {k: '{n, plural, one {x}}'});
if (broken.t('k', {n: 1}) !== '{n, plural, one {x}}') { bad++; console.log('  FAIL broken message'); }

// Two language changes in a row, the first save slow: the saves run one after
// another, the account ends on the second choice, and only that one reloads.
{
  const posts = [];
  const answers = [];
  let reloads = 0;
  let onChange = null;
  const select = {value: '', addEventListener: (event, fn) => { onChange = fn; }};
  const window = {CP_I18N: {lang: 'en', dir: 'ltr', messages: {}}, _userRole: 'owner',
    location: {reload: () => { reloads++; }}, alert: () => {}};
  vm.runInNewContext(src, {
    window,
    navigator: {language: 'en-US', languages: ['en-US']},
    document: {readyState: 'complete', cookie: '', querySelectorAll: sel => (sel === 'select[data-lang-choice]' ? [select] : [])},
    fetch: (url, opts) => new Promise(resolve => {
      posts.push(JSON.parse(opts.body).language);
      answers.push(() => resolve({ok: true}));
    }),
    Intl, Map, Number, Object, String, Error, Promise, JSON,
  });
  const tick = () => new Promise(r => setTimeout(r, 0));
  select.value = 'es'; onChange();
  select.value = 'de'; onChange();
  await tick();
  const inOrder = posts.length === 1;  // the second save waits for the first
  answers[0](); await tick(); await tick();
  answers[1] && answers[1](); await tick(); await tick();
  const race = inOrder && posts.join() === 'es,de' && reloads === 1;
  if (!race) { bad++; console.log(`  FAIL overlapping saves: posts ${posts.join()}, reloads ${reloads}, in order ${inOrder}`); }
  else console.log('  ok   overlapping language saves keep the last choice');
}

console.log(bad ? `\n${bad} failure(s)` : `\nall ${cases.length + 3} cases pass`);
process.exit(bad ? 1 : 0);
