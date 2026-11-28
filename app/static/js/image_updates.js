/* ============================================================
   CashPilot — app image updates on the Fleet page (owner only)

   The fleet's choice (Off / Notify only / Update automatically), the hour of
   the daily check, an override per box and per app, and what the updates did.
   The server side is app/image_updates.py; docs/image-updates.md explains it.
   ============================================================ */

(() => {
  'use strict';

  const root = document.getElementById('updates-body');
  if (!root) return;
  const offer = document.getElementById('updates-offer');
  const MODES = ['off', 'notify', 'auto'];
  // The page's status colours: a fault in red, news muted.
  const BADGE = { updated: 'badge-running', rolled_back: 'badge-error', failed: 'badge-error', available: 'badge-available', skipped: 'badge-unknown' };
  const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  let state = null;
  // A choice not saved yet is never thrown away by a refresh: each change
  // counts, a save records the count it sent, and the controls are drawn
  // again only when every change is saved. Check now keeps them as well.
  let edits = 0;
  let savedEdits = 0;
  const unsaved = () => edits !== savedEdits;
  root.addEventListener('change', () => { edits += 1; });

  function options(value, inherit) {
    const choices = inherit ? [''].concat(MODES) : MODES;
    return choices.map((m) => `<option value="${m}"${m === (value || '') ? ' selected' : ''}>${esc(m ? t(`fleet.updates.mode.${m}`) : t('fleet.updates.mode.inherit'))}</option>`).join(''); // i18n-keys: fleet.updates.mode.off, fleet.updates.mode.notify, fleet.updates.mode.auto
  }

  function resultLabel(result) {
    return t(`fleet.updates.result.${result}`); // i18n-keys: fleet.updates.result.updated, fleet.updates.result.rolled_back, fleet.updates.result.failed, fleet.updates.result.available, fleet.updates.result.skipped
  }

  function shortDigest(d) {
    return d ? esc(String(d).replace(/^sha256:/, '').slice(0, 12)) : '—';
  }

  function when(sqlTime) {
    // SQLite's datetime('now') is UTC without a zone.
    const d = new Date(String(sqlTime || '').replace(' ', 'T') + 'Z');
    return Number.isNaN(d.getTime()) ? esc(sqlTime) : esc(d.toLocaleString(window.CPI18N ? window.CPI18N.locale : undefined));
  }

  function hourOptions(value) {
    let out = '';
    for (let h = 0; h < 24; h++) {
      const label = `${String(h).padStart(2, '0')}:00`;
      out += `<option value="${h}"${h === value ? ' selected' : ''}>${label}</option>`;
    }
    return out;
  }

  function boxNote(w) {
    if (w.desktop) return t('fleet.updates.box.desktop');
    if (!w.supported) return w.online ? t('fleet.updates.box.too_old') : t('fleet.updates.box.offline');
    return '';
  }

  function render() {
    const s = state.settings;
    if (offer) offer.hidden = !(s.offer && s.mode === 'off');
    const boxes = state.workers.map((w) => `
      <tr>
        <td>${esc(w.name)}</td>
        <td><select class="form-input form-input-sm" data-updates-worker="${esc(w.id)}" aria-label="${esc(t('fleet.updates.box.aria', { name: w.name }))}"${w.desktop ? ' disabled' : ''}>${options(s.workers[String(w.id)], true)}</select></td>
        <td class="muted">${esc(boxNote(w))}</td>
      </tr>`).join('');
    const apps = state.services.map((a) => `
      <tr>
        <td>${esc(a.name)}</td>
        <td><select class="form-input form-input-sm" data-updates-service="${esc(a.slug)}" aria-label="${esc(t('fleet.updates.app.aria', { name: a.name }))}">${options(s.services[a.slug], true)}</select></td>
      </tr>`).join('');
    const rows = state.history.map((r) => `
      <tr>
        <td>${when(r.created_at)}</td>
        <td>${esc(r.service)}</td>
        <td>${esc(r.worker)}</td>
        <td><code>${shortDigest(r.old_digest)}</code></td>
        <td><code>${shortDigest(r.new_digest)}</code></td>
        <td><span class="badge ${BADGE[r.result] || 'badge-unknown'}" data-result="${esc(r.result)}">${esc(resultLabel(r.result))}</span></td>
        <td class="muted">${esc(r.detail)}</td>
      </tr>`).join('');
    root.innerHTML = `
      <p class="muted" data-updates-load-error hidden></p>
      <div class="power-settings">
        <div><label class="form-label" for="updates-mode">${esc(t('fleet.updates.fleet_label'))}</label>
          <select class="form-input" id="updates-mode">${options(s.mode, false)}</select></div>
        <div><label class="form-label" for="updates-hour">${esc(t('fleet.updates.hour_label'))}</label>
          <select class="form-input form-input-code" id="updates-hour">${hourOptions(s.hour)}</select></div>
        <button class="btn btn-primary btn-sm" data-updates-action="save">${esc(t('fleet.save'))}</button>
        <button class="btn btn-secondary btn-sm" data-updates-action="run"${state.running ? ' disabled' : ''}>${esc(state.running ? t('fleet.updates.running') : t('fleet.updates.run'))}</button>
        <span class="muted">${esc(s.last_run ? t('fleet.updates.last_run', { date: s.last_run }) : t('fleet.updates.never_run'))}</span>
      </div>
      <p class="muted">${esc(t('fleet.updates.explain', { seconds: state.settle_seconds }))}</p>
      <details class="add-worker">
        <summary>${esc(t('fleet.updates.overrides'))}</summary>
        <div class="add-worker-body">
          <div class="table-scroll"><table class="fleet-table">
            <thead><tr><th>${esc(t('fleet.col.box'))}</th><th>${esc(t('fleet.updates.col.choice'))}</th><th></th></tr></thead>
            <tbody>${boxes || `<tr><td colspan="3" class="muted">${esc(t('fleet.updates.no_boxes'))}</td></tr>`}</tbody>
          </table></div>
          <div class="table-scroll"><table class="fleet-table">
            <thead><tr><th>${esc(t('fleet.updates.col.app'))}</th><th>${esc(t('fleet.updates.col.choice'))}</th></tr></thead>
            <tbody>${apps || `<tr><td colspan="2" class="muted">${esc(t('fleet.updates.no_apps'))}</td></tr>`}</tbody>
          </table></div>
          <p class="muted">${esc(t('fleet.updates.precedence'))}</p>
        </div>
      </details>
      <h3 class="block-title">${esc(t('fleet.updates.history'))}</h3>
      <div class="table-scroll"><table class="fleet-table updates-history">
        <thead><tr><th>${esc(t('fleet.updates.col.when'))}</th><th>${esc(t('fleet.updates.col.app'))}</th><th>${esc(t('fleet.col.box'))}</th>
          <th>${esc(t('fleet.updates.col.from'))}</th><th>${esc(t('fleet.updates.col.to'))}</th><th>${esc(t('fleet.updates.col.result'))}</th><th></th></tr></thead>
        <tbody>${rows || `<tr><td colspan="7" class="muted">${esc(t('fleet.updates.no_history'))}</td></tr>`}</tbody>
      </table></div>`;
  }

  // Each load is numbered, and only the newest one's answer counts: answers
  // can arrive out of order, and an older one would draw a choice the server
  // no longer holds, which the next Save would send back.
  let loads = 0;
  async function load() {
    const mine = ++loads;
    let next;
    try {
      next = await CP.api('/api/image-updates');
    } catch (err) {
      if (mine !== loads) return;
      const message = t('fleet.updates.load_failed', { error: err.message || '' });
      const line = root.querySelector('[data-updates-load-error]');
      if (state && line) {
        // The controls stay, with any change not saved yet; the error shows beside them.
        line.textContent = message;
        line.hidden = false;
      } else if (!state) {
        root.innerHTML = `<p class="muted">${esc(message)}</p>`;
      }
      return;
    }
    if (mine !== loads) return;
    state = next;
    const line = root.querySelector('[data-updates-load-error]');
    if (line) line.hidden = true;
    if (!unsaved()) render();
  }

  async function save(mode) {
    const pick = (sel) => {
      const out = {};
      root.querySelectorAll(sel).forEach((el) => {
        const key = el.dataset.updatesWorker || el.dataset.updatesService;
        out[key] = el.value || null;
      });
      return out;
    };
    const modeEl = document.getElementById('updates-mode');
    const body = {
      mode: mode || (modeEl ? modeEl.value : state.settings.mode),
      hour: parseInt((document.getElementById('updates-hour') || {}).value ?? state.settings.hour, 10),
      workers: pick('[data-updates-worker]'),
      services: pick('[data-updates-service]'),
    };
    const sent = edits;
    try {
      await CP.api('/api/image-updates', { method: 'PUT', body });
      savedEdits = sent;
      CP.toast(t('fleet.updates.saved'), 'success');
      await load();
    } catch (err) {
      CP.toast(t('fleet.updates.save_failed', { error: err.message || '' }), 'error');
    }
  }

  async function runNow() {
    try {
      await CP.api('/api/image-updates/run', { method: 'POST' });
      CP.toast(t('fleet.updates.started'), 'success');
      await load();
    } catch (err) {
      CP.toast(t('fleet.updates.run_failed', { error: err.message || '' }), 'error');
    }
  }

  document.addEventListener('click', (ev) => {
    const btn = ev.target.closest('[data-updates-action]');
    if (!btn) return;
    const action = btn.dataset.updatesAction;
    if (action === 'save') save();
    else if (action === 'run') runNow();
    else if (action === 'enable') save('auto');
  });

  load();
  setInterval(() => { if (!unsaved()) load(); }, 60000);
})();
