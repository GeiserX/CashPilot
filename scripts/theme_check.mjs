// Run the real theme code against a stub DOM.
//
// Classic night is a third theme. What has to hold, and only running the code
// shows it:
//   1. every page's pre-paint script reads the localStorage key the theme code
//      writes, so a saved Classic paints Classic first;
//   2. on a signed-in page the theme the server wrote into <html data-theme>
//      wins over whatever the browser kept, and is mirrored into that key;
//   3. the avatar menu's Dark / Light / Classic buttons switch the page, mark
//      the chosen one, and save it to the account;
//   4. nothing reads the theme back after the page loads, so a late reply can
//      never undo a click made while it was in flight.
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

function makeEnv(stored) {
  const store = new Map(stored == null ? [] : [['cp-theme', stored]]);
  const localStorage = {getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v))};
  const attrs = {};
  const buttons = ['dark', 'light', 'classic'].map(choice => {
    const b = {dataset: {themeChoice: choice}, attrs: {}, listeners: {}};
    b.setAttribute = (k, v) => { b.attrs[k] = v; };
    b.addEventListener = (ev, fn) => { b.listeners[ev] = fn; };
    return b;
  });
  const posts = [];
  const gets = [];
  const document = {
    documentElement: {getAttribute: k => attrs[k] ?? null, setAttribute: (k, v) => { attrs[k] = v; }},
    getElementById: () => null,
    querySelector: () => null,
    querySelectorAll: sel => (sel === '[data-theme-choice]' ? buttons : []),
  };
  const api = (path, opts) => {
    if (opts && opts.method === 'POST') posts.push(opts.body);
    else { gets.push(path); return Promise.resolve({theme: 'dark'}); } // the value from before the click
    return Promise.resolve({status: 'saved'});
  };
  return {store, attrs, buttons, posts, gets, localStorage, document, api};
}

const fns = ['currentTheme', 'applyTheme', 'chooseTheme', 'initThemePicker'].map(grab).join('\n');
const load = env => new Function('document', 'localStorage', 'api', 'toast',
  `const THEMES = ['dark', 'light', 'classic'];\n${fns}; return {initThemePicker, applyTheme};`,
)(env.document, env.localStorage, env.api, () => {});

const prePaint = tpl => {
  const html = readFileSync(`app/templates/${tpl}`, 'utf8');
  const m = html.match(/\(function\(\)\{var [^<]*?localStorage[^<]*?\}\)\(\);/);
  check(`${tpl}: has a pre-paint script`, !!m, 'not found');
  return m && (env => new Function('document', 'localStorage', m[0])(env.document, env.localStorage));
};

// --- 1. the pre-paint script, from every template that has one --------------
for (const tpl of ['base.html', 'auth.html', 'onboarding.html']) {
  const run = prePaint(tpl);
  if (!run) continue;
  const env = makeEnv('classic');
  run(env);
  check(`${tpl}: a saved Classic paints Classic`, env.attrs['data-theme'] === 'classic', env.attrs['data-theme']);
}
{
  const env = makeEnv(null);
  load(env).applyTheme('classic');
  check('choosing a theme writes the key the pre-paint reads', env.store.get('cp-theme') === 'classic', [...env.store]);
}

// --- 2. the server's theme wins on a signed-in page -------------------------
{
  // Another user left Classic in this browser; this user's account says dark.
  const run = prePaint('base.html');
  const env = makeEnv('classic');
  env.attrs['data-theme'] = 'dark'; // what the server rendered
  run(env);
  check('the server theme beats the browser leftover', env.attrs['data-theme'] === 'dark', env.attrs['data-theme']);
  check('and is mirrored for the sign-in pages', env.store.get('cp-theme') === 'dark', [...env.store]);
}
{
  const run = prePaint('base.html');
  const env = makeEnv(null);
  env.attrs['data-theme'] = 'classic';
  run(env);
  check('a server Classic paints Classic on an empty browser', env.attrs['data-theme'] === 'classic' && env.store.get('cp-theme') === 'classic', [...env.store]);
}

// --- 3. the avatar menu picker ----------------------------------------------
for (const [from, to] of [['dark', 'classic'], ['classic', 'light'], ['light', 'dark'], ['classic', 'dark']]) {
  const env = makeEnv(from);
  env.attrs['data-theme'] = from;
  load(env).initThemePicker();
  const pressed = () => env.buttons.filter(b => b.attrs['aria-pressed'] === 'true').map(b => b.dataset.themeChoice);
  check(`${from}: its button starts pressed`, pressed().join() === from, pressed());
  env.buttons.find(b => b.dataset.themeChoice === to).listeners.click();
  check(`${from} -> ${to}: page, key, pressed button and saved value follow`,
    env.attrs['data-theme'] === to && env.store.get('cp-theme') === to && pressed().join() === to
      && env.posts.length === 1 && env.posts[0].theme === to,
    JSON.stringify({theme: env.attrs['data-theme'], pressed: pressed(), posts: env.posts}));
}

// --- 4. no late read can undo a click ---------------------------------------
{
  const env = makeEnv('dark');
  env.attrs['data-theme'] = 'dark';
  load(env).initThemePicker();
  env.buttons.find(b => b.dataset.themeChoice === 'classic').listeners.click();
  await new Promise(r => setTimeout(r, 0));
  check('the picker never reads the theme back from the server', env.gets.length === 0, JSON.stringify(env.gets));
  check('so a click during page load stays', env.attrs['data-theme'] === 'classic', env.attrs['data-theme']);
}

if (bad) {
  console.error(`\n${bad} check(s) failed`);
  process.exit(1);
}
console.log('\ntheme behaviour ok');
