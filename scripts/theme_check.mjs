// Run the real theme code against a stub DOM.
//
// Classic night is a third theme. Three things have to hold, and only running
// the code shows them:
//   1. the pre-paint script in every page template reads the same localStorage
//      key the theme code writes, so a saved Classic paints Classic first;
//   2. the sun/moon item never moves a Classic user to Light;
//   3. on a new browser the theme saved on the server wins.
//
//   node scripts/theme_check.mjs
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
  return rest.slice(0, end > 0 ? end : 3000);
};

let bad = 0;
const check = (label, cond, detail) => {
  console.log(`  ${cond ? 'ok  ' : 'FAIL'} ${label}${cond ? '' : `  <- ${detail}`}`);
  if (!cond) bad++;
};

function makeEnv(stored, serverPrefs) {
  const store = new Map(stored == null ? [] : [['cp-theme', stored]]);
  const localStorage = {getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v))};
  const attrs = {};
  const radios = ['dark', 'light', 'classic'].map(value => ({value, checked: false, addEventListener() {}}));
  const listeners = {};
  const toggle = {addEventListener: (ev, fn) => { listeners[ev] = fn; }};
  const posts = [];
  const document = {
    documentElement: {getAttribute: k => attrs[k] ?? null, setAttribute: (k, v) => { attrs[k] = v; }},
    getElementById: id => (id === 'theme-toggle' ? toggle : id === 'avatar-toggle' ? {} : null),
    querySelector: () => null,
    querySelectorAll: sel => (sel.includes('cp-theme') ? radios : []),
  };
  const api = (path, opts) => {
    if (opts && opts.method === 'POST') { posts.push(opts.body); return Promise.resolve({status: 'saved'}); }
    return Promise.resolve(serverPrefs);
  };
  return {store, attrs, radios, listeners, posts, localStorage, document, api};
}

const fns = ['currentTheme', 'applyTheme', 'chooseTheme', 'toggleTheme', 'initThemeToggle'].map(grab).join('\n');
const load = env => new Function('document', 'localStorage', 'api', 'toast',
  `const THEMES = ['dark', 'light', 'classic'];\n${fns}; return {toggleTheme, initThemeToggle, applyTheme};`,
)(env.document, env.localStorage, env.api, () => {});

// --- 1. the pre-paint script, from every template that has one --------------
for (const tpl of ['base.html', 'auth.html', 'onboarding.html']) {
  const html = readFileSync(`app/templates/${tpl}`, 'utf8');
  const m = html.match(/\(function\(\)\{var t=localStorage[^<]*?\}\)\(\);/);
  check(`${tpl}: has a pre-paint script`, !!m, 'not found');
  if (!m) continue;
  const env = makeEnv('classic');
  new Function('document', 'localStorage', m[0])(env.document, env.localStorage);
  check(`${tpl}: a saved Classic paints Classic`, env.attrs['data-theme'] === 'classic', env.attrs['data-theme']);
}
{
  const env = makeEnv(null);
  load(env).applyTheme('classic');
  check('choosing a theme writes the key the pre-paint reads', env.store.get('cp-theme') === 'classic', [...env.store]);
}

// --- 2. the sun/moon rule ------------------------------------------------------
{
  const run = load(makeEnv(null));
  check('Dark -> Light', run.toggleTheme('dark') === 'light', run.toggleTheme('dark'));
  check('Light -> Dark', run.toggleTheme('light') === 'dark', run.toggleTheme('light'));
  check('Classic never goes to Light', run.toggleTheme('classic') === 'classic', run.toggleTheme('classic'));
}
{
  const env = makeEnv('classic', {theme: 'classic'});
  env.attrs['data-theme'] = 'classic';
  load(env).initThemeToggle();
  env.listeners.click({stopPropagation() {}});
  check('a click while Classic leaves Classic on', env.attrs['data-theme'] === 'classic', env.attrs['data-theme']);
}
{
  const env = makeEnv('dark', {theme: 'dark'});
  env.attrs['data-theme'] = 'dark';
  load(env).initThemeToggle();
  env.listeners.click({stopPropagation() {}});
  check('a click on Dark goes to Light and saves it', env.attrs['data-theme'] === 'light' && env.posts.some(b => b.theme === 'light'), JSON.stringify(env.posts));
}

// --- 3. the server wins on a new browser ---------------------------------------
{
  const env = makeEnv(null, {theme: 'classic'});
  env.attrs['data-theme'] = 'dark'; // what the pre-paint gives an empty browser
  load(env).initThemeToggle();
  await new Promise(r => setTimeout(r, 0));
  check('server Classic replaces the browser default', env.attrs['data-theme'] === 'classic', env.attrs['data-theme']);
  check('and is mirrored for the next pre-paint', env.store.get('cp-theme') === 'classic', [...env.store]);
  check('the Settings radio follows', env.radios.find(r => r.value === 'classic').checked, 'unchecked');
}
{
  const env = makeEnv('light', {theme: null});
  env.attrs['data-theme'] = 'light';
  load(env).initThemeToggle();
  await new Promise(r => setTimeout(r, 0));
  check('no server choice keeps the browser one', env.attrs['data-theme'] === 'light', env.attrs['data-theme']);
}

if (bad) {
  console.error(`\n${bad} check(s) failed`);
  process.exit(1);
}
console.log('\ntheme behaviour ok');
