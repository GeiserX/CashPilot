// Run the REAL payouts.html renderers and check what each payout state produces.
//
// CashPilot-luj tier 1. The registry distinguishes four states, and the whole
// value of the page is that they stay distinguishable on screen:
//
//   external + an address  -> show it
//   external + nothing     -> "Not set", and it is ACTIONABLE (money may be
//                             going nowhere)
//   internal               -> there is NO address, BY DESIGN
//   minted                 -> the container made a wallet the user has never seen
//   unknown                -> OUR gap in the catalog, never the user's mistake
//
// Collapsing "internal" into "not set" is the specific regression this guards.
// One is nothing to do; the other is a service earning into an address the user
// never supplied. They must not render alike.
//
// pytest cannot see any of this: the renderers live inside a <script> block in a
// Jinja template, and asserting that the template *contains* a string would only
// prove a literal is present, not which state produces it. So the functions are
// extracted and run for real, and the OUTPUT is inspected.
//
// No browser needed: these renderers build strings and touch no DOM.
//   node scripts/payout_registry_check.mjs
// Exits non-zero on any mismatch.
import {readFileSync} from 'node:fs';

const html = readFileSync('app/templates/payouts.html', 'utf8');

function extract(name) {
  const start = html.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`payouts.html no longer defines ${name}() — this check is stale`);
  let i = html.indexOf('{', start), depth = 0;
  for (let j = i; j < html.length; j++) {
    if (html[j] === '{') depth++;
    else if (html[j] === '}' && --depth === 0) return html.slice(start, j + 1);
  }
  throw new Error(`unbalanced braces reading ${name}()`);
}

// Evaluate the real esc/payoutAddressCell/payoutRow together, since they call
// one another. A stub for esc() here would let escaping break while this stayed
// green — exactly the failure these harnesses exist to catch.
const src = [extract('esc'), extract('payoutAddressCell'), extract('balanceCell'), extract('payoutRow')].join('\n');
// payoutRow reads the module-level _balances map, so give it an empty one --
// the balance cell is exercised directly below.
const {payoutAddressCell, payoutRow, balanceCell} = new Function(
  `const _balances = {}; ${src}; return {payoutAddressCell, payoutRow, balanceCell};`
)();

let failures = 0;
function check(label, cond, detail) {
  if (cond) return;
  failures++;
  console.error(`FAIL: ${label}${detail ? `\n      ${detail}` : ''}`);
}

// ---------------------------------------------------------------------------
// The four states must be distinguishable from one another.
// ---------------------------------------------------------------------------
const external = payoutAddressCell({model: 'external', address: '0xabc123'});
const missing = payoutAddressCell({model: 'external', address: null});
const internal = payoutAddressCell({model: 'internal', address: null});
const minted = payoutAddressCell({model: 'minted', address: null});
const unknown = payoutAddressCell({model: 'unknown', address: null});

check('a resolved external address is shown', external.includes('0xabc123'), external);

check('an unset external address says "Not set"', /not set/i.test(missing), missing);

check(
  'internal does NOT render as "Not set" — nothing is missing',
  !/not set/i.test(internal),
  `internal rendered: ${internal}`
);
check('internal explains the balance is held', /held by the service/i.test(internal), internal);

check('minted does not claim an address', !/0x/.test(minted) && !/not set/i.test(minted), minted);
check('minted says the container generates one', /generates its own/i.test(minted), minted);

check('unknown is phrased as our gap', /not classified/i.test(unknown), unknown);
check('unknown is not an accusation', !/not set/i.test(unknown), unknown);

// All five states must be pairwise distinct strings, or the page is lying by
// omission somewhere.
const states = {external, missing, internal, minted, unknown};
for (const [a, av] of Object.entries(states)) {
  for (const [b, bv] of Object.entries(states)) {
    if (a < b) check(`"${a}" and "${b}" render differently`, av !== bv, `both: ${av}`);
  }
}

// The actionable state must be visually louder than the by-design ones.
check(
  'only the actionable state uses the warning class',
  missing.includes('payout-missing')
    && !internal.includes('payout-missing')
    && !minted.includes('payout-missing')
    && !unknown.includes('payout-missing'),
  `missing=${missing}\n      internal=${internal}`
);

// ---------------------------------------------------------------------------
// Row-level: urgency belongs to DEPLOYED services only.
// ---------------------------------------------------------------------------
const deployedMissing = payoutRow({slug: 'storj', name: 'Storj', model: 'external', address: null, address_missing: true, deployed: true});
const undeployedMissing = payoutRow({slug: 'storj', name: 'Storj', model: 'external', address: null, address_missing: true, deployed: false});

check('a deployed service with no address is flagged', deployedMissing.includes('payout-row-actionable'), deployedMissing);
check(
  'an UNDEPLOYED service with no address is NOT flagged — it is information, not a problem',
  !undeployedMissing.includes('payout-row-actionable'),
  undeployedMissing
);

// ---------------------------------------------------------------------------
// Escaping. The address comes out of a deployed container's environment.
// ---------------------------------------------------------------------------
const hostile = payoutRow({
  slug: 's', name: '<img src=x onerror=alert(1)>', model: 'external',
  address: '"><script>alert(1)</script>', address_missing: false, deployed: true,
});
check('a hostile name is escaped', !hostile.includes('<img src=x'), hostile);
check('a hostile address is escaped', !hostile.includes('<script>'), hostile);
check('the escaped form is still present', hostile.includes('&lt;script&gt;'), hostile);

// ---------------------------------------------------------------------------
// Negative controls. A control that PASSES means the check above it is wrong.
// ---------------------------------------------------------------------------
check(
  'CONTROL: internal must not accidentally satisfy the "shows an address" test',
  !internal.includes('0xabc123'),
  internal
);
check(
  'CONTROL: an absent model falls through to unknown, never to external',
  !/not set/i.test(payoutAddressCell({})) && /not classified/i.test(payoutAddressCell({})),
  payoutAddressCell({})
);

// ---------------------------------------------------------------------------
// The on-chain column (dv6 tier 2). Same rule, one level down.
// ---------------------------------------------------------------------------
const bKnown = balanceCell({state: 'known', amount: '1.5', symbol: 'ETH'});
const bZero = balanceCell({state: 'known', amount: '0', symbol: 'ETH'});
const bUnreachable = balanceCell({state: 'unreachable', detail: 'timeout'});
const bUnsupported = balanceCell({state: 'unsupported'});
const bInvalid = balanceCell({state: 'invalid'});
const bNone = balanceCell(undefined);

check('a known balance is shown with its symbol', bKnown.includes('1.5') && bKnown.includes('ETH'), bKnown);
check('a real zero balance IS shown as 0', bZero.includes('0'), bZero);

check(
  'THE ONE THAT MATTERS: unreachable does not render as a number',
  !/\d/.test(bUnreachable.replace(/[^>]*>/g, '')) && /could not check/i.test(bUnreachable),
  bUnreachable
);
check(
  'unreachable and a zero balance look different',
  bUnreachable !== bZero && !bUnreachable.includes('payout-balance"'),
  `unreachable=${bUnreachable}\n      zero=${bZero}`
);
check(
  'a row that was never queried is an em dash, not "could not check"',
  bNone.includes('&mdash;') && !/could not check/i.test(bNone),
  bNone
);
check('unsupported is also an em dash, not an error', bUnsupported.includes('&mdash;'), bUnsupported);
check('an invalid address says so', /not valid/i.test(bInvalid), bInvalid);

check(
  'CONTROL: a hostile amount is escaped in the balance cell',
  !balanceCell({state: 'known', amount: '<script>x</script>', symbol: 'E'}).includes('<script>'),
  balanceCell({state: 'known', amount: '<script>x</script>', symbol: 'E'})
);

if (failures) {
  console.error(`\n${failures} payout-registry render check(s) failed`);
  process.exit(1);
}
console.log('payout registry render checks passed');
