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

// The file at `path` (from the repo root) with its English put back, as
// tests/i18n_source.py's english_source does: a `{{ t('key') }}` or a
// `${t('key')}` slot becomes the bare message, a t() call in code becomes the
// string literal it replaced. A placeholder the call fills reads back as the
// expression that fills it (`${escapeHtml(n)}`, in backticks when the call is
// in code). For a check that asserts what a template or app.js says.
const JINJA = /\{\{\s*t\(\s*(['"])([^'"]+)\1/g;
const CALL = /(?<![\w$])(?:CPI18N\.|i18n\.)?t\(\s*(['"])([^'"]+)\1/g;

function callEnd(text, start) {
  let depth = 0;
  let quote = null;
  for (let i = start; i < text.length; i++) {
    const ch = text[i];
    if (quote) {
      if (ch === '\\') { i++; continue; }
      if (ch === quote) quote = null;
    } else if ("'\"`".includes(ch)) {
      quote = ch;
    } else if ('([{'.includes(ch)) {
      depth++;
    } else if (')]}'.includes(ch)) {
      depth--;
      if (depth === 0) return i + 1;
    }
  }
  return text.length;
}

function splitTop(text) {
  const parts = [];
  let depth = 0;
  let quote = null;
  let start = 0;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quote) {
      if (ch === '\\') { i++; continue; }
      if (ch === quote) quote = null;
    } else if ("'\"`".includes(ch)) {
      quote = ch;
    } else if ('([{'.includes(ch)) {
      depth++;
    } else if (')]}'.includes(ch)) {
      depth--;
    } else if (ch === ',' && depth === 0) {
      parts.push(text.slice(start, i));
      start = i + 1;
    }
  }
  parts.push(text.slice(start));
  return parts.map(p => p.trim()).filter(Boolean);
}

function params(args) {
  args = args.trim();
  if (!(args.startsWith('{') && args.endsWith('}'))) return {};
  const out = {};
  for (const part of splitTop(args.slice(1, -1))) {
    const at = part.indexOf(':');
    const name = (at < 0 ? part : part.slice(0, at)).trim().replace(/^['"]|['"]$/g, '');
    out[name] = at < 0 ? name : english(part.slice(at + 1).trim());
  }
  return out;
}

function fill(message, filled) {
  // Inside {name, plural, ...} the # that stands for the count gets the same treatment.
  for (const m of message.matchAll(/\{(\w+), plural,/g)) {
    if (!Object.prototype.hasOwnProperty.call(filled, m[1])) continue;
    const end = callEnd(message, m.index);
    const body = message.slice(m.index, end).replaceAll('#', `\${${filled[m[1]]}}`);
    return fill(message.slice(0, m.index), filled) + body + fill(message.slice(end), filled);
  }
  return message.replace(/\{(\w+)\}/g, (m, name) => (Object.prototype.hasOwnProperty.call(filled, name) ? `\${${filled[name]}}` : m));
}

export function english(text) {
  const out = [];
  let pos = 0;
  for (;;) {
    JINJA.lastIndex = pos;
    CALL.lastIndex = pos;
    const jinja = JINJA.exec(text);
    const call = CALL.exec(text);
    const found = [jinja, call].filter(Boolean).sort((a, b) => a.index - b.index)[0];
    if (!found) { out.push(text.slice(pos)); return out.join(''); }
    const key = found[2];
    out.push(text.slice(pos, found.index));
    const paren = text.indexOf('(', found.index);
    let end = callEnd(text, paren);
    let message = Object.prototype.hasOwnProperty.call(messages, key) ? messages[key] : key;
    if (found === jinja) {
      const close = text.indexOf('}}', end);
      out.push(message);
      pos = close >= 0 ? close + 2 : end;
      continue;
    }
    const argsAt = text.indexOf(found[1], paren + 1) + key.length + 2;
    const args = text.slice(argsAt, end - 1).trim().replace(/^,/, '').trim();
    const filled = params(args);
    message = fill(message, filled);
    if (out[out.length - 1].endsWith('${') && text[end] === '}') {
      out[out.length - 1] = out[out.length - 1].slice(0, -2);
      end += 1;
    } else if (Object.keys(filled).length) {
      message = `\`${message}\``;
    } else {
      message = `'${message}'` + (args ? ` /* ${args} */` : '');
    }
    out.push(message);
    pos = end;
  }
}

export function englishSource(path) {
  return english(readFileSync(new URL(`../${path}`, import.meta.url), 'utf8'));
}
