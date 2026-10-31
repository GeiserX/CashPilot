// A catalog row's Add opens the setup wizard on that one service, and the
// wizard starts at the setup step with it picked. Browser-free: the real
// functions are lifted out of app.js and run against a stub api and a stub DOM,
// as in currency_check.mjs. The Add link's href is fed back into initWizard as
// window.location.search, so the link and the wizard are tested together.
//
//   node scripts/setup_preselect_check.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync('app/static/js/app.js', 'utf8');
const escapeHtml = value => String(value).replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;');
const capFirst = s => s ? s[0].toUpperCase() + s.slice(1) : '';
const grab = name => {
  const offset = src.search(new RegExp(`  (?:async )?function ${name}\\(`));
  assert.ok(offset >= 0, `${name} is in app.js`);
  const rest = src.slice(offset);
  const next = rest.search(/\n  (?:async )?function /);
  return next >= 0 ? rest.slice(0, next) : rest;
};

// "a&b c+d" needs encoding: unencoded, the query string reads service=a.
const ODD = 'a&b c+d';
const services = [
  { slug: 'honeygain', name: 'Honeygain', category: 'bandwidth', docker: { image: 'honeygain/honeygain' } },
  { slug: 'storj', name: 'Storj', category: 'storage', docker: { image: 'storjlabs/storagenode' }, deployed: true },
  { slug: ODD, name: 'Odd', category: 'compute', docker: { image: 'odd/odd' } },
  { slug: 'grass', name: 'Grass', category: 'depin', platforms: ['desktop'], website: 'https://grass.io' },
];
const box = (id, slugs, status = 'online') => ({ id, name: `box${id}`, status, containers: slugs.map(slug => ({ slug })) });

// ---- The catalog row --------------------------------------------------------
const renderAs = (isOwner, onlineWorkers) => new Function(
  'escapeHtml', 'capFirst', '_isOwner', 'catalogOnlineWorkers',
  `${grab('runsOn')}\n${grab('renderCatalogCard')}\nreturn renderCatalogCard;`,
)(escapeHtml, capFirst, isOwner, onlineWorkers);
const row = (slug, { owner = true, workers = null } = {}) => renderAs(owner, workers)(services.find(s => s.slug === slug));
const addHref = html => (html.match(/<a href="(\/setup\?[^"]*)"/) || [])[1];

assert.match(row('honeygain'), /<a href="\/setup\?service=honeygain"[^>]*>Add<\/a>/);
assert.match(row('honeygain'), /data-action="openServiceDetail" data-a1="honeygain">Details</, 'Details still opens the modal');
assert.equal(addHref(row(ODD)), '/setup?service=a%26b%20c%2Bd', 'the slug is URL-encoded');
assert.match(row('storj'), /data-action="openServiceDetail"[^>]*>Manage</);
assert.match(row('storj'), /<a href="\/setup\?service=storj"[^>]*title="Run Storj on another box"[^>]*>Add<\/a>/, 'Add when the boxes are unknown');
assert.match(row('storj', { workers: [box(1, ['storj']), box(2, [])] }), /title="Run Storj on another box"/, 'Add when a box lacks it');
assert.doesNotMatch(row('storj', { workers: [box(1, ['storj']), box(2, ['storj'])] }), /\/setup/, 'no Add when every online box runs it');
assert.doesNotMatch(row('grass'), /\/setup/);
assert.match(row('grass'), />Visit</);
for (const slug of ['honeygain', 'storj', ODD]) {
  assert.doesNotMatch(row(slug, { owner: false }), /\/setup/, `a non-owner gets no Add on ${slug}`);
}
assert.match(row('honeygain', { owner: false }), />Details</, 'a non-owner still opens the modal');
assert.match(row('storj', { owner: false }), />Manage</);
console.log('Catalog rows: Add for the owner (encoded, dropped where the service runs everywhere), Details for everyone.');

// ---- The wizard -------------------------------------------------------------
const CATEGORIES = ['bandwidth', 'storage', 'compute', 'depin'];
function stubDom() {
  const cards = CATEGORIES.map(value => {
    const cls = new Set();
    const cb = { value, checked: false };
    return {
      cb, listeners: [],
      classList: { add: c => cls.add(c), remove: c => cls.delete(c), toggle: c => (cls.has(c) ? cls.delete(c) : cls.add(c), cls.has(c)), contains: c => cls.has(c) },
      querySelector: () => cb,
      addEventListener(type, fn) { this.listeners.push(fn); },
    };
  });
  return {
    cards,
    querySelectorAll(sel) {
      if (sel === '.category-card') return cards;
      if (sel === '.category-card.selected input') return cards.filter(c => c.classList.contains('selected')).map(c => c.cb);
      throw new Error(`unexpected selector ${sel}`);
    },
  };
}

async function openWizard(search, { prefs = ['bandwidth'], prefsFail = false, catalogFail = false } = {}) {
  const document = stubDom();
  const toasts = [];
  const api = async path => {
    if (path === '/api/preferences') {
      if (prefsFail) throw new Error('Error 500');
      return { selected_categories: JSON.stringify(prefs) };
    }
    if (path === '/api/services/available') {
      if (catalogFail) throw new Error('Error 502');
      return services;
    }
    throw new Error(`unexpected api ${path}`);
  };
  const loaded = [];
  const wiz = new Function(
    'api', 'toast', 'document', 'window', 'updateWizardUI', 'loadWizardServices', 'loadWizardSetupForms',
    `let wizardState;\n${grab('initWizard')}\n${grab('wizardPreselect')}\n${grab('wizardPreferencesBody')}
     return { initWizard, state: () => wizardState, body: () => wizardPreferencesBody(wizardState) };`,
  )(api, (msg, type) => toasts.push({ msg, type }), document, { location: { search } },
    () => {}, () => loaded.push('services'), () => loaded.push('forms'));
  await wiz.initWizard();
  const checked = document.cards.filter(c => c.cb.checked).map(c => c.cb.value);
  return { ...wiz, toasts, loaded, checked, document };
}
const searchOf = href => href.slice(href.indexOf('?'));

{
  const w = await openWizard(searchOf(addHref(row('storj'))));
  assert.equal(w.state().step, 3, 'starts at the setup step');
  assert.deepEqual(w.state().selectedServices, ['storj']);
  assert.deepEqual(w.state().categories, ['bandwidth', 'storage']);
  assert.deepEqual(w.checked, ['bandwidth', 'storage'], 'step 1 shows both categories ticked');
  assert.deepEqual(w.loaded, ['services', 'forms']);
  assert.deepEqual(w.toasts, []);
  assert.equal(w.body().selected_categories, JSON.stringify(['bandwidth']), 'finishing does not save the added category');
  // Untick it and tick it again on step 1: now it is the user's pick.
  const storage = w.document.cards.find(c => c.cb.value === 'storage');
  storage.listeners.forEach(fn => fn()); storage.listeners.forEach(fn => fn());
  assert.equal(w.body().selected_categories, JSON.stringify(['bandwidth', 'storage']), 'a category the user ticks is saved');
}
{
  const w = await openWizard(searchOf(addHref(row(ODD))));
  assert.equal(w.state().step, 3, 'an encoded slug reaches the wizard');
  assert.deepEqual(w.state().selectedServices, [ODD]);
}
{
  const w = await openWizard('?service=storj', { prefs: ['storage'] });
  assert.deepEqual(w.state().categories, ['storage'], 'no duplicate category');
  assert.equal(w.body().selected_categories, JSON.stringify(['storage']), 'a saved category stays saved');
}
{
  const w = await openWizard('?service=storj', { prefsFail: true });
  assert.equal(w.state().step, 3);
  assert.equal('selected_categories' in w.body(), false, 'unread preferences are not overwritten with an empty list');
}
{
  const w = await openWizard('?service=nope');
  assert.equal(w.state().step, 1, 'an unknown slug preselects nothing');
  assert.deepEqual(w.toasts, [{ msg: 'No service called "nope" in the catalog', type: 'warning' }]);
}
{
  const w = await openWizard('?service=storj', { catalogFail: true });
  assert.equal(w.state().step, 1);
  assert.equal(w.toasts.length, 1);
  assert.doesNotMatch(w.toasts[0].msg, /No service called/, 'a failed fetch is not reported as an unknown service');
  assert.match(w.toasts[0].msg, /Could not load the catalog/);
}
{
  const w = await openWizard('');
  assert.equal(w.state().step, 1, 'plain /setup starts at step 1');
  assert.equal(w.body().selected_categories, JSON.stringify(['bandwidth']));
}
console.log('/setup?service=<slug> starts the wizard at the setup step with that service picked, and saves only the user\'s categories.');
