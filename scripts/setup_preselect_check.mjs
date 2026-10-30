// A catalog row's Add opens the setup wizard on that one service, and the
// wizard starts at the setup step with it picked. Browser-free: the functions
// are lifted out of app.js and run against stand-ins, as in currency_check.mjs.
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

const services = [
  { slug: 'honeygain', name: 'Honeygain', category: 'bandwidth', docker: { image: 'honeygain/honeygain' } },
  { slug: 'storj', name: 'Storj', category: 'storage', docker: { image: 'storjlabs/storagenode' }, deployed: true },
  { slug: 'grass', name: 'Grass', category: 'depin', platforms: ['desktop'], website: 'https://grass.io' },
];

// The wizard: step 3, the service picked, its category added to the saved ones.
const preselect = new Function(`${grab('wizardPreselect')}\nreturn wizardPreselect;`)();
assert.deepEqual(preselect('storj', services, ['bandwidth']),
  { step: 3, categories: ['bandwidth', 'storage'], selectedServices: ['storj'] });
assert.deepEqual(preselect('storj', services, ['storage']).categories, ['storage'], 'no duplicate category');
assert.deepEqual(preselect('honeygain', services, []).categories, ['bandwidth']);
assert.equal(preselect('nope', services, []), null, 'an unknown slug preselects nothing');
console.log('/setup?service=<slug> starts the wizard at the setup step with that service picked.');

// The catalog: every Docker service links to the wizard on itself. A running
// one keeps Manage and offers Add for another box; a desktop-only one has no
// deploy, so it keeps its Visit link.
const render = new Function('escapeHtml', 'capFirst', `${grab('renderCatalogCard')}\nreturn renderCatalogCard;`)(escapeHtml, capFirst);
const row = slug => render(services.find(s => s.slug === slug));
assert.match(row('honeygain'), /<a href="\/setup\?service=honeygain"[^>]*>Add<\/a>/);
assert.match(row('storj'), /data-action="openServiceDetail"[^>]*>Manage</);
assert.match(row('storj'), /<a href="\/setup\?service=storj"[^>]*title="Run Storj on another box"[^>]*>Add<\/a>/);
assert.doesNotMatch(row('grass'), /\/setup/);
assert.match(row('grass'), />Visit</);
console.log('Catalog rows add through the wizard; running ones keep Manage; desktop-only ones keep Visit.');
