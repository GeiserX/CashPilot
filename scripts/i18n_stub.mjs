// Give a browser-free check the page's t(), in English.
//
// The checks in scripts/*.mjs pull functions out of app.js and the templates
// and run them alone. Since the strings moved into app/i18n/en.json, those
// functions call the global t() that app/static/js/i18n.js defines. Importing
// this file runs that real i18n.js against en.json and installs its t() on
// globalThis, so a pulled-out function finds it and renders the same English
// the page does. A check that runs code in its own vm context passes
// `t: globalThis.t` into that context.
//
//   import './i18n_stub.mjs';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const messages = JSON.parse(readFileSync(new URL('../app/i18n/en.json', import.meta.url), 'utf8'));
const src = readFileSync(new URL('../app/static/js/i18n.js', import.meta.url), 'utf8');
const window = {CP_I18N: {lang: 'en', dir: 'ltr', messages}};
vm.runInNewContext(src, {
  window,
  navigator: {language: 'en-US', languages: ['en-US']},
  document: {readyState: 'complete', querySelectorAll: () => [], cookie: ''},
  Intl, Map, Number, Object, String, Error,
});
globalThis.t = window.t;
globalThis.CPI18N = window.CPI18N;
if (typeof globalThis.window === 'object' && globalThis.window) {
  globalThis.window.t = window.t;
  globalThis.window.CPI18N = window.CPI18N;
}
export const t = window.t;
