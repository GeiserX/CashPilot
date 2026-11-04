// The import page (app/templates/import.html): read another tool's config
// files, show the server's dry run, save the ticked rows, deploy the drafts.
//
// The files are read in the browser and sent as text; the server parses them
// again on save, so a masked value never has to come back from here. Handlers
// are window globals, resolved by delegate.js from data-action.
(function () {
  'use strict';

  const MAX_FILES = 4;
  const MAX_TOTAL = 64 * 1024;
  let lastRequest = null; // {source, files} as last previewed
  let workers = [];

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));

  const FIELD_STATE = {
    imported: 'imported',
    missing: 'missing',
    placeholder: 'still the example value',
    retype: 'needs retyping (uses $ or quotes a shell would change)',
    invalid: 'not in the format this service needs',
  };
  const ROW_STATE = {
    ready: 'Ready',
    missing_fields: 'Needs a value',
    invalid: 'Check a value',
    unusable: 'Cannot bring over',
    not_deployable: 'Nothing to deploy',
  };

  function setStatus(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  async function readFiles() {
    const files = [];
    const picked = Array.from(document.getElementById('import-files').files || []);
    for (const file of picked) {
      files.push({ name: file.name, content: await file.text() });
    }
    const pasted = document.getElementById('import-paste').value;
    if (pasted.trim()) files.push({ name: 'pasted text', content: pasted });
    if (!files.length) throw new Error('Add a file or paste one.');
    if (files.length > MAX_FILES) throw new Error(`At most ${MAX_FILES} files at a time.`);
    const total = files.reduce((n, f) => n + new TextEncoder().encode(f.content).length, 0);
    if (total > MAX_TOTAL) throw new Error(`The files add up to more than ${MAX_TOTAL / 1024} KiB.`);
    return files;
  }

  function fieldCell(slug, field) {
    const state = FIELD_STATE[field.state] || field.state;
    let shown = '';
    if (field.state === 'imported') {
      shown = field.secret ? 'set' : `<code>${esc(field.value)}</code>`;
    } else if (field.state === 'invalid' && !field.secret && field.value !== undefined) {
      shown = `<code>${esc(field.value)}</code>`;
    }
    let input = '';
    if (field.state !== 'imported') {
      const type = field.secret ? 'password' : 'text';
      const pattern = field.pattern ? ` pattern="${esc(field.pattern)}"` : '';
      input = `<input class="form-input import-extra" type="${type}" autocomplete="off"${pattern}
        data-import-slug="${esc(slug)}" data-import-key="${esc(field.key)}"
        placeholder="${esc(field.label)}${field.required ? '' : ' (optional)'}">`;
    }
    return `<div class="import-field"><strong>${esc(field.label)}</strong>: ${shown} <span class="muted">${esc(state)}</span>${input}</div>`;
  }

  function renderPreview(preview) {
    const notices = (preview.notices || []).map((n) => `<p class="setup-line">${esc(n)}</p>`).join('');
    document.getElementById('import-notices').innerHTML =
      `<p class="setup-line">Read as <strong>${esc(preview.source_name)}</strong>.</p>${notices}`;

    const rows = preview.rows || [];
    const body = rows.map((row) => {
      const selectable = row.state !== 'unusable' && row.state !== 'not_deployable';
      const tick = selectable
        ? `<input type="checkbox" class="import-pick" data-import-slug="${esc(row.slug)}"${row.selected ? ' checked' : ''}>`
        : '';
      const extras = [];
      if (row.existing && row.existing.deployed) extras.push('already deployed by CashPilot');
      if (row.existing && row.existing.draft) extras.push('an earlier import is saved; saving replaces it');
      if (row.collector === 'will_set') extras.push('earnings tracking will use this login too');
      if (row.collector === 'already_set') extras.push('earnings login already set; left as it is');
      if (row.collector === 'partly_set') extras.push('part of the earnings login is already in Settings; left as it is, finish it there');
      return `<tr>
        <td>${tick}</td>
        <td><strong>${esc(row.name)}</strong><div class="muted">${esc(ROW_STATE[row.state] || row.state)}</div></td>
        <td>${(row.fields || []).map((f) => fieldCell(row.slug, f)).join('')}
          ${row.reason ? `<div class="muted">${esc(row.reason)}</div>` : ''}
          ${extras.length ? `<div class="muted">${esc(extras.join('; '))}</div>` : ''}</td>
      </tr>`;
    }).join('');
    document.getElementById('import-rows').innerHTML = rows.length
      ? `<table class="breakdown-table"><thead><tr><th></th><th>Service</th><th>Settings</th></tr></thead><tbody>${body}</tbody></table>`
      : '<p class="setup-line">These files set up no service CashPilot can bring over.</p>';

    const skipped = preview.not_imported || [];
    document.getElementById('import-skipped').innerHTML = skipped.length
      ? `<h4>Not imported</h4><ul>${skipped.map((s) => `<li><code>${esc(s.key)}</code>: ${esc(s.reason)}</li>`).join('')}</ul>`
      : '';
    document.getElementById('import-preview').hidden = false;
  }

  window.importPreview = async function importPreview() {
    setStatus('import-status', '');
    let files;
    try {
      files = await readFiles();
    } catch (err) {
      setStatus('import-status', err.message);
      return;
    }
    const source = document.getElementById('import-source').value;
    try {
      const preview = await CP.api('/api/import/preview', { method: 'POST', body: { source, files } });
      lastRequest = { source: preview.source, files };
      renderPreview(preview);
    } catch (err) {
      setStatus('import-status', err.message);
    }
  };

  window.importApply = async function importApply() {
    if (!lastRequest) return;
    const slugs = Array.from(document.querySelectorAll('.import-pick:checked')).map((el) => el.dataset.importSlug);
    if (!slugs.length) {
      setStatus('import-apply-status', 'Tick at least one service.');
      return;
    }
    const extra = {};
    for (const input of document.querySelectorAll('.import-extra')) {
      const slug = input.dataset.importSlug;
      if (!slugs.includes(slug) || !input.value.trim()) continue;
      if (!input.checkValidity()) {
        input.reportValidity();
        return;
      }
      (extra[slug] ||= {})[input.dataset.importKey] = input.value.trim();
    }
    try {
      const res = await CP.api('/api/import/apply', { method: 'POST', body: { ...lastRequest, slugs, extra } });
      setStatus('import-apply-status', `Saved ${res.saved.length} service(s).`);
      CP.toast(`Imported ${res.saved.length} service(s)`, 'success');
      await loadDrafts();
    } catch (err) {
      setStatus('import-apply-status', err.message);
    }
  };

  function chosenWorkers() {
    return Array.from(document.querySelectorAll('.import-worker:checked')).map((el) => el.dataset.wid);
  }

  async function deploySlug(slug) {
    const ids = chosenWorkers();
    if (!ids.length) {
      CP.toast('Tick at least one worker', 'warning');
      return false;
    }
    if (!await CP.confirmPreflight(slug, ids)) return false;
    let ok = 0;
    for (const wid of ids) {
      try {
        const res = await CP.api(`/api/import/drafts/${encodeURIComponent(slug)}/deploy?worker_id=${encodeURIComponent(wid)}`, { method: 'POST' });
        ok++;
        if (res && res.device_link && res.device_link.url) {
          CP.toast(`${slug}: ${res.device_link.steps} ${res.device_link.url}`, 'warning');
        }
      } catch (err) {
        CP.toast(`${slug} on worker ${wid}: ${err.message}`, 'error');
      }
    }
    if (ok) CP.toast(`${slug} deployed to ${ok} worker(s)`, 'success');
    return ok > 0;
  }

  window.importDeploy = (slug) => deploySlug(slug);

  window.importDeployAll = async function importDeployAll() {
    for (const el of document.querySelectorAll('[data-import-draft]')) {
      await deploySlug(el.dataset.importDraft);
    }
  };

  window.importForget = async function importForget(slug) {
    if (!window.confirm(`Forget the imported settings for ${slug}? Running containers are not touched.`)) return;
    try {
      await CP.api(`/api/import/drafts/${encodeURIComponent(slug)}`, { method: 'DELETE' });
      await loadDrafts();
    } catch (err) {
      CP.toast(err.message, 'error');
    }
  };

  async function loadDrafts() {
    const box = document.getElementById('import-drafts-body');
    let drafts = [];
    try {
      [drafts, workers] = await Promise.all([CP.api('/api/import/drafts'), CP.api('/api/workers').catch(() => [])]);
    } catch (err) {
      box.innerHTML = `<p class="setup-line">${esc(err.message)}</p>`;
      return;
    }
    if (!drafts.length) {
      box.innerHTML = '<p class="setup-line muted">Nothing imported yet.</p>';
      return;
    }
    const online = (workers || []).filter((w) => w.status === 'online');
    const picker = online.length
      ? online.map((w) => `<label class="checkbox-label"><input type="checkbox" class="import-worker" data-wid="${esc(w.id)}"> ${esc(w.name)}</label>`).join(' ')
      : '<span class="muted">No workers online.</span>';
    const list = drafts.map((d) => `<li data-import-draft="${esc(d.slug)}">
        <strong>${esc(d.name)}</strong> <span class="muted">from ${esc(d.source)}, ${esc(d.imported_at)} UTC; ${esc(d.keys.join(', '))}</span>
        <button class="btn btn-secondary btn-sm" data-action="importDeploy" data-a1="${esc(d.slug)}">Deploy</button>
        <button class="btn btn-secondary btn-sm" data-action="importForget" data-a1="${esc(d.slug)}">Forget</button>
      </li>`).join('');
    box.innerHTML = `<div class="form-group"><div class="form-label">Deploy to</div>${picker}</div>
      <ul class="import-drafts">${list}</ul>
      <div class="settings-actions"><button class="btn btn-primary" data-action="importDeployAll">Deploy all</button></div>`;
  }

  document.addEventListener('DOMContentLoaded', loadDrafts);
})();
