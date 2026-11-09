// Run the real update card with a worker whose socket proxy policy is stale.
//
// The policy lives in the operator's compose file, which no image update
// changes, so the worker sends the release it needs and the commands that
// bring the compose file to it. Only running renderUpdateCard proves they reach
// the card, escaped, and that a worker cannot plant a javascript: link there.
//
//   node scripts/proxy_policy_card_check.mjs
//
// Exits non-zero on any mismatch.
import {readFileSync} from 'node:fs';

const src = readFileSync('app/static/js/app.js', 'utf8');
const grab = name => {
  const i = src.indexOf(`function ${name}(`);
  if (i < 0) {
    console.error(`FAIL: ${name} is not defined in app/static/js/app.js`);
    process.exit(1);
  }
  const rest = src.slice(i);
  const end = rest.search(/\n  (?:async )?function [A-Za-z_]/);
  return rest.slice(0, end > 0 ? end : 4000);
};

const container = {innerHTML: '', querySelector: () => null};
const document = {getElementById: id => (id === 'update-card-container' ? container : null)};
const fns = ['escapeHtml', 'proxyPolicyLink', 'renderUpdateCard'].map(grab).join('\n');
const render = new Function(
  'document',
  `let updateCardWorkerOnly = false; let updateCardWorkerId = 1; ${fns}; return renderUpdateCard;`,
)(document);

let bad = 0;
const check = (label, cond, detail) => {
  console.log(`  ${cond ? 'ok  ' : 'FAIL'} ${label}${cond ? '' : `  <- ${detail}`}`);
  if (!cond) bad++;
};

const base = {current_display: 'v2.1.9', compose_managed: true, known: true, latest: '2.1.9'};
const fix = {
  release: 'v2.1.9',
  command:
    'docker run --rm -i --network none drumsergio/cashpilot-worker:2.1.9 python -m app.socket_policy < docker-compose.yml > docker-compose.new.yml',
  url: 'https://github.com/GeiserX/CashPilot/blob/v2.1.9/docker-compose.worker.yml',
  recreate: 'docker compose up -d --force-recreate cashpilot-socket-proxy cashpilot-worker',
};

render({...base, proxy_policy_fix: null}, []);
check('a current policy shows no note', !container.innerHTML.includes('socket proxy'), container.innerHTML);

render({...base, proxy_policy_fix: fix}, []);
const html = container.innerHTML;
check('names the release', html.includes('this worker (v2.1.9) needs'), html);
check('gives the filter command, escaped', html.includes('docker-compose.yml &gt; docker-compose.new.yml'), html);
check('gives the recreate command', html.includes(fix.recreate), html);
check('links the release compose file', html.includes(`<a href="${fix.url}"`), html);

render({...base, proxy_policy_fix: {...fix, url: 'javascript:alert(1)', command: '<img src=x onerror=alert(1)>'}}, []);
const hostile = container.innerHTML;
check('a non-repository URL is not a link', !hostile.includes('href="javascript:'), hostile);
check('a planted tag is escaped', !hostile.includes('<img'), hostile);

console.log(bad ? `\nRESULT: FAIL (${bad})` : '\nRESULT: PASS');
process.exit(bad ? 1 : 0);
