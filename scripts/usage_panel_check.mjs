// Run the real resource-use graph helpers from app/static/js/app.js.
//
// What it guards: an hour with no reading reaches Chart.js as null, which draws
// a gap, never as 0, which would draw a drop to idle. And a missing figure in
// the captions renders as a dash, never as 0.
//
//   node scripts/usage_panel_check.mjs
//
// Exits non-zero on any mismatch.
import {readFileSync} from 'node:fs';

const src = readFileSync('app/static/js/app.js', 'utf8');

function grab(name) {
  const i = src.indexOf(`  function ${name}(`);
  if (i < 0) {
    console.error(`FAIL: ${name} is not defined in app/static/js/app.js; this harness is testing nothing.`);
    process.exit(1);
  }
  const rest = src.slice(i);
  const end = rest.indexOf('\n  }\n');
  return rest.slice(0, end + 4);
}

const constLine = src.match(/\n  const USAGE_DASH = [^\n]+\n/);
if (!constLine) {
  console.error('FAIL: USAGE_DASH is not defined in app/static/js/app.js');
  process.exit(1);
}
const names = ['fmtBytes', 'usageRate', 'usageCpu', 'usageMem', 'usageLast', 'usagePeak', 'usageModel'];
const body = constLine[0] + names.map(grab).join('\n') +
  '\nreturn {usageRate, usageCpu, usageMem, usageLast, usagePeak, usageModel};';
const fn = new Function(body)();

let bad = 0;
const check = (label, cond, detail) => {
  console.log(`  ${cond ? 'ok  ' : 'FAIL'} ${label}${cond ? '' : `  <- ${JSON.stringify(detail)}`}`);
  if (!cond) bad++;
};

const MB = 1024 ** 2;
const m = fn.usageModel({
  hours: [0, 3600, 7200, 10800],
  series: {
    cpu_percent: [null, 12.5, undefined, 0],
    memory_mb: [null, 512, null, 600],
    rx_rate: [null, 2 * MB, null, null],
    tx_rate: [null, MB, null, null],
    rx_bytes: [null, 7200 * MB, null, null],
    tx_bytes: [null, 3600 * MB, null, null],
    traffic_partial: [false, true, false, true],
  },
});
check('one value per hour', m.cpu.length === 4 && m.rx.length === 4, m);
check('an hour with no reading stays null (a gap)', m.cpu[0] === null && m.cpu[2] === null && m.rx[3] === null, m.cpu);
check('a measured zero stays zero', m.cpu[3] === 0, m.cpu);
check('partial flags carry through', m.partial[1] === true && m.partial[0] === false, m.partial);
check('a short series is padded with gaps, not zeros', fn.usageModel({hours: [0, 1], series: {cpu_percent: [5]}}).cpu[1] === null, '');
check('latest skips trailing gaps', fn.usageLast([1, 2, null]) === 2, '');
check('peak ignores gaps', fn.usagePeak([null, 3, 1]) === 3, '');
check('no reading renders a dash', fn.usageRate(null) === '—' && fn.usageCpu(null) === '—' && fn.usageMem(null) === '—', '');
check('rate renders per second', fn.usageRate(2 * MB) === '2.0 MB/s', fn.usageRate(2 * MB));
check('memory over 1 GB renders in GB', fn.usageMem(2048) === '2.00 GB', fn.usageMem(2048));
check('empty payload gives empty series', fn.usageModel({}).cpu.length === 0, '');

if (bad) {
  console.error(`${bad} check(s) failed`);
  process.exit(1);
}
console.log('all usage graph checks passed');
