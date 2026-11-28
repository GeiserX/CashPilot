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
import './i18n_stub.mjs';
import {readFileSync} from 'node:fs';

const src = readFileSync('app/static/js/app.js','utf8');
const grab = name => {
  const i = src.indexOf(`function ${name}(`);
  const rest = src.slice(i);
  const end = rest.search(/\n  (?:async )?function [A-Za-z_]/);
  return rest.slice(0, end > 0 ? end : 2000);
};
// formatCurrency writes an unpriced coin through formatAmount, which needs isFiatCurrency.
const fns = ['effectiveDisplayCurrency', 'formatCurrency', 'isFiatCurrency', 'formatAmount'].map(grab).join('\n');

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

// Stale-rate reporting (CashPilot-dfw).
//
// exchange_rates.py keeps a separate staleness clock per source and publishes
// crypto_stale / fiat_stale on /api/exchange-rates. Nothing read either, so a
// token balance kept being converted at a price that could be hours or days old
// with nothing on screen changing. This is conditional logic about which source
// matters to which viewer, so it is RUN rather than read.
const staleFn = grab('staleRateNotice');
const staleCases = [
  ['fresh rates, USD viewer            ', {crypto_stale:false, fiat_stale:false}, 'USD', false, null],
  ['fresh rates, GBP viewer            ', {crypto_stale:false, fiat_stale:false}, 'GBP', false, null],
  ['crypto stale, USD viewer           ', {crypto_stale:true,  fiat_stale:false}, 'USD', true,  'crypto prices'],
  ['crypto stale, GBP viewer           ', {crypto_stale:true,  fiat_stale:false}, 'GBP', true,  'crypto prices'],
  // A USD viewer is not affected by a stale USD->X table, and warning them
  // would be the noise that teaches people to ignore warnings.
  ['fiat stale, USD viewer             ', {crypto_stale:false, fiat_stale:true},  'USD', false, null],
  ['fiat stale, GBP viewer             ', {crypto_stale:false, fiat_stale:true},  'GBP', true,  'GBP exchange rates'],
  ['both stale, GBP viewer             ', {crypto_stale:true,  fiat_stale:true},  'GBP', true,  'and'],
  // Absent is not stale: an older UI, or a payload that never carried the field.
  ['field absent entirely              ', {}, 'GBP', false, null],
];
for (const [label, rates, disp, expectNotice, mustMention] of staleCases) {
  const f = new Function('_displayCurrency','_exchangeRates',
    `${staleFn}; return staleRateNotice;`)(disp, {fiat:{USD:1,GBP:0.79}, crypto_usd:{MYST:0.087}, ...rates});
  const notice = f();
  let ok = Boolean(notice) === expectNotice;
  if (ok && mustMention) ok = notice.includes(mustMention);
  if (!ok) bad++;
  console.log(`${label} notice=${String(Boolean(notice)).padEnd(5)} expected=${String(expectNotice).padEnd(5)} ${ok?'ok':'MISMATCH'}   ${notice ? '"'+notice+'"' : ''}`);
}

// The catalog's estimates ('whole' digits) drop the cents only when the amount
// SHOWN has none. Deciding on the USD input showed a $1 bound as "€1" at 0.8
// EUR per USD, where it is €0.80.
const money = (n, currency, digits) => new Intl.NumberFormat(undefined, {
  style: 'currency', currency, minimumFractionDigits: digits, maximumFractionDigits: digits,
}).format(n);
const wholeCases = [
  ['$1 bound, EUR at 0.8                ', 1, 'EUR', {USD:1, EUR:0.8}, money(0.8, 'EUR', 2)],
  ['$5 bound, EUR at 0.86               ', 5, 'EUR', {USD:1, EUR:0.86}, money(4.3, 'EUR', 2)],
  ['$10 bound, EUR at 0.8               ', 10, 'EUR', {USD:1, EUR:0.8}, money(8, 'EUR', 0)],
  ['$5 bound, USD                       ', 5, 'USD', {USD:1}, money(5, 'USD', 0)],
  ['$2.5 bound, USD                     ', 2.5, 'USD', {USD:1}, money(2.5, 'USD', 2)],
  ['$5 bound, EUR with no rate yet      ', 5, 'EUR', {USD:1}, money(5, 'USD', 0)],
  // 1.005 as a double is 1.00499...: rounding by hand made it "€1", the
  // formatter's half-expand rounding makes it "€1.01".
  ['$0.5 bound, EUR at 2.01             ', 0.5, 'EUR', {USD:1, EUR:2.01}, money(1.005, 'EUR', 2)],
  ['$4.999 bound, USD                   ', 4.999, 'USD', {USD:1}, money(5, 'USD', 0)],
];
for (const [label, usd, disp, fiat, want] of wholeCases) {
  const fmt = new Function('_displayCurrency','_exchangeRates',
    `${fns}; return formatCurrency;`)(disp, {fiat, crypto_usd: {}});
  const got = fmt(usd, 'USD', 'whole');
  const ok = got === want;
  if (!ok) bad++;
  console.log(`${label} got=${got.padEnd(8)} expected=${want.padEnd(8)} ${ok?'ok':'MISMATCH'}`);
}

console.log(bad ? '\nRESULT: FAIL' : '\nRESULT: PASS');
process.exit(bad ? 1 : 0);
