// Exercise the shared field builder used by the wizard and service detail.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync('app/static/js/app.js', 'utf8');
const start = src.indexOf('  function envInputFields(');
const end = src.indexOf('\n  function workerCheckboxList(', start);
const escapeHtml = value => String(value).replaceAll('&', '&amp;').replaceAll('"', '&quot;');
const render = new Function('escapeHtml', `${src.slice(start, end)}\nreturn envInputFields;`)(escapeHtml);
const envs = [{ key: 'RP_API_KEY', label: 'API Key', secret: true, required: true, pattern: '[a-f0-9-]+' }];
for (const withId of [true, false]) {
  const html = render({ slug: 'repocket' }, envs, { withId });
  assert.match(html, /type="password"/);
  assert.match(html, /autocomplete="new-password"/);
  assert.match(html, /pattern="\[a-f0-9-\]\+"/);
  assert.match(html, /value=""/);
  assert.match(html, /data-key="RP_API_KEY"/);
}
console.log('Repocket fields request a new secret and expose the catalog constraint in both forms.');
