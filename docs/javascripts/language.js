// The language switcher, made to keep the reader on the same page.
//
// Each locale is its own build at <site>/<lang>/ with the same pages, so the same
// page in another language is the same path under another root. The roots come from
// the switcher's own links (extra.alternate in zensical.toml).
//
// On the first visit to an English page, the reader goes to the best match for the
// browser's languages, once. A language picked in the switcher is remembered and wins
// from then on. A page opened in another language is never moved.
(function () {
  var KEY = "cashpilot-docs-language";
  var ALIAS = { tl: "fil" }; // Tagalog browsers read Filipino

  function store(value) {
    try {
      if (value === undefined) return localStorage.getItem(KEY);
      localStorage.setItem(KEY, value);
    } catch (e) {
      return null; // storage blocked: the switcher still works, nothing is remembered
    }
  }

  function roots() {
    var out = [];
    document.querySelectorAll("a.md-select__link[hreflang]").forEach(function (a) {
      out.push({ lang: a.getAttribute("hreflang"), path: new URL(a.href).pathname, link: a });
    });
    // Longest root first: /CashPilot/es/ must win over /CashPilot/.
    return out.sort(function (a, b) { return b.path.length - a.path.length; });
  }

  // Language first, then region: es-MX reads es, pt-PT reads pt-BR, zh-TW reads zh-Hans.
  function best(langs, codes) {
    for (var i = 0; i < langs.length; i++) {
      var want = langs[i].toLowerCase();
      var base = want.split("-")[0];
      base = ALIAS[base] || base;
      var exact = codes.filter(function (c) { return c.toLowerCase() === want; })[0];
      if (exact) return exact;
      var same = codes.filter(function (c) { return c.toLowerCase().split("-")[0] === base; })[0];
      if (same) return same;
    }
    return null;
  }

  function update() {
    var all = roots();
    if (!all.length) return;
    var here = location.pathname;
    var current = all.filter(function (r) { return here.indexOf(r.path) === 0; })[0];
    if (!current) return; // a local preview at another path: leave the links as built
    var rest = here.slice(current.path.length) + location.search + location.hash;
    all.forEach(function (r) {
      r.link.href = r.path + rest;
      r.link.onclick = function () { store(r.lang); };
    });

    if (current.lang !== "en") return;
    var wanted = store();
    if (!wanted) {
      var codes = all.map(function (r) { return r.lang; });
      wanted = best(navigator.languages || [navigator.language || "en"], codes) || "en";
      store(wanted);
    }
    var target = all.filter(function (r) { return r.lang === wanted; })[0];
    if (target && target.lang !== "en") location.replace(target.path + rest);
  }

  // With navigation.instant the page changes without a reload; document$ fires each time.
  if (window.document$ && window.document$.subscribe) {
    window.document$.subscribe(update);
  } else {
    document.addEventListener("DOMContentLoaded", update);
  }
})();
