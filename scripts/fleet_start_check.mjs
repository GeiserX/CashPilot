import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import './i18n_stub.mjs';

const source = readFileSync('app/templates/fleet.html', 'utf8');
const from = source.indexOf("  document.getElementById('fleet-proxies').addEventListener('click'");
const to = source.indexOf('\n\n  load();', from);
assert(from >= 0 && to > from);

const firstId = 'a'.repeat(64);
const nextId = 'b'.repeat(64);
const firstTargets = {honeygain: firstId, earnfm: 'c'.repeat(64)};
const nextTargets = {...firstTargets, honeygain: nextId};
const firstProof = 'd'.repeat(64);
const nextProof = 'e'.repeat(64);
const startPath = '/api/proxies/3/copies/7/honeygain/start';
const single = id => Object.assign(new Error('The container changed'), {
  code: 'deploy_target_changed', refusal: {current_container: id},
});
const group = (targets, proof) => Object.assign(new Error('The shared tunnel needs approval'), {
  code: 'confirm_proxy_start_targets', refusal: {expected_containers: targets, group_approval: proof},
});
const started = {status: 'started'};

async function start(responses, decisions = []) {
  const posts = [];
  const prompts = [];
  const toasts = [];
  let click;
  vm.runInNewContext(source.slice(from, to), {
    t: globalThis.t,
    document: {getElementById: () => ({addEventListener: (_type, listener) => { click = listener; }})},
    CP: {
      api: async (path, opts) => {
        assert.equal(path, startPath, 'Every retry must start the selected copy');
        posts.push(JSON.parse(JSON.stringify(opts)));
        assert.ok(responses.length, 'Unexpected retry');
        const next = responses.shift();
        if (next instanceof Error) throw next;
        return next;
      },
      toast: (...args) => { toasts.push(args); },
    },
    confirm: message => { prompts.push(message); return decisions.shift() ?? true; },
    workerName: () => 'example worker',
    load: () => {},
  });
  await click({target: {closest: () => ({dataset: {copy: '3:7:honeygain', cmd: 'start'}})}});
  return {posts, prompts, toasts};
}

const stale = await start([single(firstId), group(firstTargets, firstProof), started]);
assert.equal(stale.posts.length, 3, 'Fleet must offer the group when the individual retry returns another 409');
assert.equal(stale.prompts.length, 2);
for (const [slug, id] of Object.entries(firstTargets)) {
  assert.ok(stale.prompts[1].includes(`${slug} (${id})`));
}
assert.deepEqual(stale.posts.map(post => post.body), [
  undefined,
  {expected_container: firstId},
  {expected_containers: firstTargets, group_approval: firstProof},
]);
assert.ok(stale.toasts.every(([, level]) => level !== 'error'));

const changed = await start([group(firstTargets, firstProof), single(nextId), group(nextTargets, nextProof), started]);
assert.equal(changed.prompts.length, 3);
assert.deepEqual(changed.posts.slice(1).map(post => post.body), [
  {expected_containers: firstTargets, group_approval: firstProof},
  {expected_container: nextId},
  {expected_containers: nextTargets, group_approval: nextProof},
]);
assert.ok(changed.toasts.every(([, level]) => level !== 'error'));

const cancelled = await start([single(firstId), group(firstTargets, firstProof)], [true, false]);
assert.equal(cancelled.posts.length, 2);
assert.equal(cancelled.prompts.length, 2);
assert.ok(cancelled.toasts.every(([, level]) => level !== 'error'));

console.log('Fleet handles individual and shared confirmations in either order and stops on cancel.');

const reordered = {earnfm: firstTargets.earnfm, honeygain: firstTargets.honeygain};
const repeatedGroup = await start(
  [group(firstTargets, firstProof), group(reordered, firstProof), group(reordered, firstProof)],
  [true, true, false],
);
assert.equal(repeatedGroup.posts.length, 2, 'Fleet must stop when the confirmed group is offered again');
assert.equal(repeatedGroup.prompts.length, 1);
assert.deepEqual(repeatedGroup.toasts, [['The shared tunnel needs approval', 'error']]);

const repeatedSingle = await start(
  [single(firstId), single(firstId), single(firstId)],
  [true, true, false],
);
assert.equal(repeatedSingle.posts.length, 2);
assert.equal(repeatedSingle.prompts.length, 1);
assert.deepEqual(repeatedSingle.toasts, [['The container changed', 'error']]);

const conflict = Object.assign(new Error('The previous move has not been settled.'), {
  code: 'proxy_recovery_conflict',
});
const pendingMove = await start([conflict]);
assert.equal(pendingMove.posts.length, 1);
assert.equal(pendingMove.prompts.length, 0);
assert.deepEqual(pendingMove.toasts, [['The previous move has not been settled.', 'error']]);

console.log('Fleet stops on repeated approvals and shows recovery conflicts without a prompt.');
