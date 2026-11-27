/* ============================================================
   CashPilot — the page's language (app/i18n)

   Loaded on every page, after /i18n/<locale>.js (which sets window.CP_I18N
   with the locale, its direction and every string, English where a
   translation is missing or stale) and before app.js.

   t(key, params) returns the string for key with its arguments filled in.
   Messages use the ICU MessageFormat subset app/i18n/__init__.py implements:
   {name}, {n, plural, one {# box} other {# boxes}} and {k, select, ...}.
   Plural categories come from Intl.PluralRules, so they follow CLDR. t()
   returns plain text; a caller putting it into innerHTML escapes the values
   it passes, never the message, which is ours.
   ============================================================ */

(() => {
  'use strict';

  const data = window.CP_I18N || { lang: 'en', dir: 'ltr', messages: {} };
  const lang = data.lang || 'en';
  const messages = data.messages || {};

  // The locale for Intl formatting: the browser's own tag when it is the same
  // language as the page (es-MX keeps its own number and date style on a
  // Spanish page), else the page's language.
  function formatLocale() {
    const primary = lang.split('-')[0].toLowerCase();
    const wanted = (navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language])
      .filter(Boolean);
    const same = wanted.find(tag => tag.split('-')[0].toLowerCase() === primary);
    return same || lang;
  }
  const locale = formatLocale();

  let plurals = null;
  try { plurals = new Intl.PluralRules(lang); } catch (e) { plurals = new Intl.PluralRules('en'); }

  // ---- The ICU subset parser: the same grammar as app/i18n/_Parser ----
  function parse(text) {
    let pos = 0;
    function word() {
      const m = /\s*([^\s,{}]+)\s*/y;
      m.lastIndex = pos;
      const found = m.exec(text);
      if (!found) throw new Error(`expected a name at ${pos} in ${text}`);
      pos = m.lastIndex;
      return found[1];
    }
    function message(depth) {
      const parts = [];
      let buf = '';
      while (pos < text.length) {
        const ch = text[pos];
        if (ch === "'" && pos + 1 < text.length && "'{}#".includes(text[pos + 1])) {
          if (text[pos + 1] === "'") { buf += "'"; pos += 2; continue; }
          let end = text.indexOf("'", pos + 1);
          if (end < 0) end = text.length;
          buf += text.slice(pos + 1, end);
          pos = end + 1;
          continue;
        }
        if (ch === '{') {
          if (buf) { parts.push(buf); buf = ''; }
          parts.push(argument());
          continue;
        }
        if (ch === '}') {
          if (depth === 0) throw new Error(`unmatched } at ${pos} in ${text}`);
          break;
        }
        if (ch === '#' && depth > 0) {
          if (buf) { parts.push(buf); buf = ''; }
          parts.push(['#']);
          pos += 1;
          continue;
        }
        buf += ch;
        pos += 1;
      }
      if (buf) parts.push(buf);
      return parts;
    }
    function argument() {
      pos += 1;
      const name = word();
      if (text[pos] === '}') { pos += 1; return ['arg', name]; }
      if (text[pos] !== ',') throw new Error(`expected , or } at ${pos} in ${text}`);
      pos += 1;
      const kind = word();
      if (kind !== 'plural' && kind !== 'select') throw new Error(`unsupported argument type ${kind} in ${text}`);
      if (text[pos] !== ',') throw new Error(`expected , after ${kind} in ${text}`);
      pos += 1;
      // No prototype: a select value such as "constructor" must find no option and fall to other.
      const options = Object.create(null);
      for (;;) {
        while (pos < text.length && /\s/.test(text[pos])) pos += 1;
        if (text[pos] === '}') { pos += 1; break; }
        const selector = word();
        if (text[pos] !== '{') throw new Error(`expected { after ${selector} in ${text}`);
        pos += 1;
        options[selector] = message(1);
        if (text[pos] !== '}') throw new Error(`unclosed option ${selector} in ${text}`);
        pos += 1;
      }
      if (!('other' in options)) throw new Error(`${kind} needs an other option in ${text}`);
      return [kind, name, options];
    }
    return message(0);
  }

  const parsed = new Map();
  function render(parts, params, number) {
    let out = '';
    for (const part of parts) {
      if (typeof part === 'string') { out += part; continue; }
      // The count as Python's str() writes it, so a message reads the same on both sides.
      if (part[0] === '#') { out += String(number); continue; }
      if (part[0] === 'arg') {
        out += Object.prototype.hasOwnProperty.call(params, part[1]) ? String(params[part[1]]) : `{${part[1]}}`;
        continue;
      }
      const [kind, name, options] = part;
      const value = params[name];
      let chosen;
      let inner = number;
      if (kind === 'plural') {
        const count = Number(value);
        const n = Number.isFinite(count) ? count : 0;
        chosen = options[`=${n}`] || options[plurals.select(n)];
        inner = n;
      } else {
        chosen = options[String(value)];
      }
      out += render(chosen || options.other, params, inner);
    }
    return out;
  }

  function format(text, params) {
    let tree = parsed.get(text);
    if (!tree) {
      tree = parse(text);
      parsed.set(text, tree);
    }
    return render(tree, params || {}, '');
  }

  function t(key, params) {
    const text = messages[key];
    if (text === undefined) return key;
    try {
      return format(text, params);
    } catch (e) {
      return text;
    }
  }

  // ---- The language picker (avatar menu, sign-in and first-run pages) ----
  const COOKIE = 'cp-lang';

  function remember(code) {
    const base = '; path=/; samesite=lax';
    document.cookie = code === 'auto'
      ? `${COOKIE}=${base}; max-age=0`
      : `${COOKIE}=${encodeURIComponent(code)}${base}; max-age=${365 * 24 * 3600}`;
  }

  async function save(code) {
    try {
      const res = await fetch('/api/preferences', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ language: code }),
      });
      if (!res.ok) throw new Error(`Error ${res.status}`);
      return true;
    } catch (err) {
      window.alert(t('lang.not_saved', { error: err.message }));
      return false;
    }
  }

  // Saves go one after another, so the account keeps the last choice even when
  // two changes overlap, and only the last one reloads the page.
  let saving = Promise.resolve(true);
  let latest = 0;
  async function choose(code) {
    remember(code);
    const turn = ++latest;
    // Signed in: the choice goes to the account, so every browser gets it.
    if (window._userRole) {
      saving = saving.then(() => save(code));
      const saved = await saving;
      if (!saved || turn !== latest) return;
    } else if (turn !== latest) {
      return;
    }
    window.location.reload();
  }

  function initPicker() {
    document.querySelectorAll('select[data-lang-choice]').forEach(select => {
      select.addEventListener('change', () => choose(select.value));
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initPicker);
  else initPicker();

  window.CPI18N = { t, format, parse, lang, dir: data.dir || 'ltr', locale, choose };
  window.t = t;
})();
