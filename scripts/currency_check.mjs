// Exercise formatCurrency and effectiveDisplayCurrency against controlled
// exchange-rate state, so the result does not depend on the locale of whoever
// runs it.
//
// Two defects this pins down, both found in a real browser and neither visible
// to a string test:
//
//   * formatCurrency stamped the display currency's symbol on an UNCONVERTED
//     USD figure when that currency had no rate, so $24.90 rendered as
//     "£24.90" — the same number wearing a different sign. Rates load
//     asynchronously, so this hit every figure on every page load until they
//     arrived, and hit permanently for a currency with no rate at all.
//
//   * The payout queue decided whether to print an approximate conversion by
//     comparing FORMATTED STRINGS ("$24.90" vs "24.90 USD"), which differ even
//     when no conversion happened, so it printed "24.90 USD (≈ $24.90)".
//
//   node scripts/currency_check.mjs
//
// Exits non-zero on any mismatch.
import {readFileSync} from 'node:fs';

const src = readFileSync('app/static/js/app.js','utf8');
const grab = name => {
  const i = src.indexOf(`function ${name}(`);
  const rest = src.slice(i);
  const end = rest.search(/\n  (?:async )?function [A-Za-z_]/);
  return rest.slice(0, end > 0 ? end : 2000);
};
const fns = grab('effectiveDisplayCurrency') + '\n' + grab('formatCurrency');

const cases = [
  ['USD payout, USD dashboard          ', 'USD', 'USD', {USD:1}, {}, false],
  ['USD payout, GBP dashboard + rate    ', 'USD', 'GBP', {USD:1, GBP:0.745}, {}, true],
  ['USD payout, GBP dashboard, NO rate  ', 'USD', 'GBP', {USD:1}, {}, false],
  ['MYST payout, no crypto rate         ', 'MYST', 'USD', {USD:1}, {}, false],
  ['MYST payout, crypto rate, USD dash  ', 'MYST', 'USD', {USD:1}, {MYST:0.087}, true],
];
let bad = 0;
for (const [label, native, disp, fiat, crypto, expectApprox] of cases) {
  const f = new Function('_displayCurrency','_exchangeRates',
    `${fns}; return {eff: effectiveDisplayCurrency, fmt: formatCurrency};`)(disp, {fiat, crypto_usd: crypto});
  const shows = f.eff(native) !== native;
  const ok = shows === expectApprox;
  if (!ok) bad++;
  console.log(`${label} approx=${String(shows).padEnd(5)} expected=${String(expectApprox).padEnd(5)} ${ok?'ok':'MISMATCH'}   (${f.fmt(24.90, native)})`);
}
console.log(bad ? '\nRESULT: FAIL' : '\nRESULT: PASS');
process.exit(bad ? 1 : 0);
