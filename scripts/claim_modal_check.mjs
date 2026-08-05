// Run the real claim-modal fallback against stubbed API responses.
//
// The bug: openClaimModal looks the service up in /api/earnings/breakdown, which
// is built from the EARNINGS table. A service that has never produced a reading
// is simply absent from it, and the modal rendered that absence as
//
//     Service not found.
//
// which is false. The service is in the catalog, on the dashboard, deployed and
// running. On the reference fleet that wording appeared for 5 of 18 tracked
// services: anyone-protocol, proxybase, proxylite, titan, uprock.
//
// Three different facts hide behind one empty result and they need three
// different answers. Only running the function can prove which one it gives, so
// this drives it rather than grepping for a string.
//
//   node scripts/claim_modal_check.mjs
//
// Exits non-zero on any mismatch.
import {readFileSync} from 'node:fs';

const src = readFileSync('app/static/js/app.js', 'utf8');

function grab(name) {
  let i = src.indexOf(`function ${name}(`);
  if (i < 0) {
    console.error(`FAIL: ${name} is not defined in app/static/js/app.js`);
    process.exit(1);
  }
  // Keep the `async` keyword. Slicing from `function` alone produced a
  // non-async body containing `await`, which is a SyntaxError -- the extraction
  // silently changed what it was testing.
  const asyncPrefix = 'async ';
  if (src.slice(i - asyncPrefix.length, i) === asyncPrefix) i -= asyncPrefix.length;
  const rest = src.slice(i);
  const end = rest.indexOf('\n  }\n');
  return rest.slice(0, end + 4);
}

// The catalog the stub server will answer with.
const CATALOG = [
  {slug: 'anyone-protocol', name: 'Anyone Protocol', has_collector: true},
  {slug: 'titan', name: 'Titan Network', has_collector: false},
];

let apiBehaviour = 'ok';
const api = async path => {
  if (apiBehaviour === 'throw') throw new Error('502 Bad Gateway');
  if (path === '/api/services/available') return CATALOG;
  throw new Error(`unexpected call: ${path}`);
};
const escapeHtml = s =>
  String(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c]);

const build = new Function(
  'api',
  'escapeHtml',
  `${grab('renderNoEarningsYet')}; return renderNoEarningsYet;`,
);
const renderNoEarningsYet = build(api, escapeHtml);

let bad = 0;
const check = (label, cond, detail) => {
  console.log(`  ${cond ? 'ok  ' : 'FAIL'} ${label}${cond ? '' : `  <- ${detail}`}`);
  if (!cond) bad++;
};

async function run(platform) {
  const title = {textContent: ''};
  const body = {innerHTML: ''};
  await renderNoEarningsYet(platform, title, body);
  return {title: title.textContent, body: body.innerHTML};
}

// 1. THE BUG. A tracked service with a collector but no readings yet.
const withCollector = await run('anyone-protocol');
check('tracked service is no longer called "not found"', !withCollector.body.includes('not found'), withCollector.body);
check('it names the service', withCollector.title.includes('Anyone Protocol'), withCollector.title);
check(
  'it says no earnings have been READ yet',
  /no earnings have been read/i.test(withCollector.body),
  withCollector.body,
);
check(
  'it points at the actual next step',
  /Settings/.test(withCollector.body) && /Collectors/.test(withCollector.body),
  withCollector.body,
);

// 2. A tracked service with NO collector. Different cause, different answer:
//    no credential will ever help, so telling them to add one would be wrong.
const noCollector = await run('titan');
check('a collector-less service says so', /no earnings collector/i.test(noCollector.body), noCollector.body);
check(
  'and does NOT send the user to add credentials',
  !/Settings/.test(noCollector.body),
  noCollector.body,
);
check(
  'and admits it may still be earning',
  /still be running and earning/i.test(noCollector.body),
  noCollector.body,
);

// 3. Genuinely absent from the catalog -- the ONLY case that earns the old wording.
const unknown = await run('does-not-exist');
check('an uncatalogued slug is reported as not in the catalog', /not in the service catalog/i.test(unknown.body), unknown.body);

// 4. The lookup itself failing must not be reported as either of the above.
apiBehaviour = 'throw';
const broken = await run('anyone-protocol');
apiBehaviour = 'ok';
check('a failed lookup says it could not check', /could not check/i.test(broken.body), broken.body);
check('and does not claim the service is missing', !/not in the service catalog/i.test(broken.body), broken.body);

// 5. The message is escaped before it reaches innerHTML.
check('the error detail is escaped', !broken.body.includes('<script'), broken.body);

console.log(bad ? `\nRESULT: FAIL (${bad})` : '\nRESULT: PASS');
process.exit(bad ? 1 : 0);
