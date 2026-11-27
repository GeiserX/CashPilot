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

console.log(bad ? `\n${bad} failure(s)` : `\nall ${cases.length + 2} cases pass`);
process.exit(bad ? 1 : 0);
