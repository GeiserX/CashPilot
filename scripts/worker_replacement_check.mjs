// Check what the dashboard sends after the owner confirms or cancels a replacement.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const app = readFileSync('app/static/js/app.js', 'utf8');
const fleet = readFileSync('app/templates/fleet.html', 'utf8');

function extract(source, name) {
  const start = source.indexOf(`  async function ${name}(`);
  assert.ok(start >= 0, name);
  return source.slice(start, source.indexOf('\n  }', start) + 4);
}

function dashboard(action, { accepts = true, fresh = false, mixed = false } = {}) {
  const posted = [];
  const prompts = [];
  const confirm = message => {
    prompts.push(message);
    return accepts;
  };
  const worker = { id: 1, name: 'box', status: 'online', containers: [{ slug: 'demo' }] };
  const api = async (path, opts) => {
    if (path === '/api/workers') return [worker];
    if (path.endsWith('/isolation')) return { earners_outside: ['demo'] };
    posted.push({ path, body: opts.body });
    return {};
  };
  const globals = {
    api,
    CP: { api },
    window: { confirm },
    confirm,
    document: { getElementById: () => ({ value: 'image:2', style: {}, dataset: {} }), querySelectorAll: () => [] },
    _routeChoice: () => undefined,
    _confirmPreflight: async () => true,
    _confirmDeviceRenames: async () => accepts,
    _deviceRenameLines: async () => ({ ids: [1], copyIds: [], copyLines: [] }),
    _runningWorkerIds: () => [1],
    _walletRequest: () => undefined,
    _imageChoice: () => undefined,
    _instancesFor: () => undefined,
    _selectedWorkerIds: selector => selector.endsWith(':not([data-routed])') && (fresh || mixed)
      ? [mixed ? 2 : 1] : [],
    _rescaledWorkerIds: () => fresh ? [] : [1],
    _identityRows: { 7: { label: 'id', service: 'Demo', worker: 'box' } },
    _identityChangeOpen: null,
    _detailWorkers: [worker],
    _movedBehindFence: new Set(),
    _fenceSwitch: {},
    wizardState: { deployed: [] },
    runsOn: () => true,
    _showDeviceLink: () => {},
    toast: () => {},
    loadFleet: () => {},
    loadServicesTable: () => {},
    openServiceDetail: () => {},
    closeModal: () => {},
    loadIdentities: () => {},
  };
  const source = ['moveBehindFence', 'enableFence'].includes(action) ? fleet : app;
  const run = new Function(
    ...Object.keys(globals),
    `${extract(app, '_deployToWorkers')}\n${extract(source, action)}\nreturn ${action};`,
  )(...Object.values(globals));
  return { run, posted, prompts };
}

const cases = [
  ['redeployOnWorker', ['demo', 1]],
  ['redeployWithImage', ['demo']],
  ['redeployWithValues', ['demo', 1]],
  ['redeployCustomService', ['demo']],
  ['renameDevices', ['demo']],
  ['deployServiceToWorkers', ['demo']],
  ['moveBehindFence', [1, 'demo', 'Demo']],
  ['enableFence', [1, 'box']],
  ['changeIdentity', [7]],
];

for (const [action, args] of cases) {
  test(`${action} sends explicit replacement approval`, async () => {
    const { run, posted } = dashboard(action);
    await run(...args);
    assert.equal(posted.length, 1);
    assert.equal(posted[0].path, action === 'changeIdentity' ? '/api/identities/7/change' : '/api/deploy/demo?worker_id=1');
    assert.equal(posted[0].body.replace_existing, true);
  });
  // The existing Redeploy with values button explicitly names the replacement.
  if (action !== 'redeployWithValues') {
    test(`${action} sends no deploy when the owner cancels`, async () => {
      const { run, posted } = dashboard(action, { accepts: false });
      await run(...args);
      assert.deepEqual(posted, []);
    });
  }
}

for (const action of ['deployServiceToWorkers', 'deployService']) {
  test(`${action} leaves approval out of a first deploy`, async () => {
    const { run, posted, prompts } = dashboard(action, { fresh: true });
    await run('demo');
    assert.equal(posted.length, 1);
    assert.equal(posted[0].body.replace_existing, undefined);
    assert.deepEqual(prompts, []);
  });
}

test('a mixed deploy approves replacement only on the box being scaled', async () => {
  const { run, posted } = dashboard('deployServiceToWorkers', { mixed: true });
  await run('demo');
  assert.deepEqual(posted.map(({ path, body }) => [path, body.replace_existing]), [
    ['/api/deploy/demo?worker_id=2', undefined],
    ['/api/deploy/demo?worker_id=1', true],
  ]);
});
