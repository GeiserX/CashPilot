/* ============================================================
   CashPilot — Frontend Application (Vanilla JS)
   ============================================================ */

const CP = (() => {
  'use strict';

  const _isOwner = window._userRole === 'owner';
  const _canWrite = _isOwner || window._userRole === 'writer';

  // -----------------------------------------------------------
  // API helper
  // -----------------------------------------------------------
  async function api(path, opts = {}) {
    const defaults = {
      headers: { 'Content-Type': 'application/json' },
    };
    const config = { ...defaults, ...opts };
    if (opts.body && typeof opts.body === 'object') {
      config.body = JSON.stringify(opts.body);
    }
    try {
      const res = await fetch(path, config);
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        // An action that can take a wallet or node identity asks for the
        // owner's password again (app/step_up.py). Asked once, then the same
        // request is sent again with it; a refusal after that is shown as is.
        const asked = data && data.detail;
        if (asked && asked.error === 'step_up_required' && !opts.steppedUp
            && opts.body && typeof opts.body === 'object') {
          const password = await askStepUp(asked.message);
          if (password) {
            return api(path, { ...opts, steppedUp: true, body: { ...opts.body, step_up_password: password } });
          }
        }
        // A device id this deploy uses already runs on another box: two boxes
        // on one id look like one device to the provider. Asked once; OK sends
        // the same deploy again, saying the owner saw it.
        if (asked && asked.error === 'identity_in_use' && !opts.sharedOk
            && opts.body && typeof opts.body === 'object'
            && window.confirm(`${asked.message}\n\n${t('app.api.deploy_anyway')}`)) {
          return api(path, { ...opts, sharedOk: true, body: { ...opts.body, allow_shared_identity: true } });
        }
        if (asked && asked.error === 'confirm_deploy_targets' && opts.body
            && !opts.body.expected_containers && window.confirm(asked.message)) {
          return api(path, { ...opts, body: { ...opts.body, expected_containers: asked.expected_containers } });
        }
        // detail can be a structured refusal ({error, message, ...}); surface
        // its message instead of the useless "[object Object]".
        let detail = data && data.detail;
        const refusal = detail && typeof detail === 'object' ? detail : {};
        if (detail && typeof detail === 'object') detail = detail.message || JSON.stringify(detail);
        // The refusal's code and fields go with it, for a caller that offers a way out.
        throw Object.assign(new Error(detail || t('app.api.error_status', { status: res.status })), { code: refusal.error, refusal });
      }
      return data;
    } catch (err) {
      if (err.name === 'TypeError') {
        throw new Error(t('app.api.network_error'));
      }
      throw err;
    }
  }

  // One prompt at a time: the modal is shared, so a second prompt opened over a
  // first would take its buttons and its close would cancel the first.
  let stepUpQueue = Promise.resolve();

  // The password prompt of a step-up. Resolves to the typed password, or null
  // when the owner cancels or closes it (Escape and the overlay close every modal).
  // A prompt asked while another is open waits for that one to finish.
  function askStepUp(message) {
    const turn = stepUpQueue.then(() => showStepUp(message));
    stepUpQueue = turn.catch(() => null);
    return turn;
  }

  function showStepUp(message) {
    const overlay = document.getElementById('stepup-modal');
    const input = document.getElementById('stepup-password');
    if (!overlay || !input) return Promise.resolve(null);
    const text = document.getElementById('stepup-message');
    if (text) text.textContent = message || t('app.stepup.default');
    input.value = '';
    // Focus goes back where it was when the prompt closes, however it closes,
    // so a keyboard or screen-reader user keeps their place in the page.
    const before = document.activeElement;
    return new Promise((resolve) => {
      let done = false;
      const finish = (value) => {
        if (done) return;
        done = true;
        watcher.disconnect();
        input.value = '';
        overlay.classList.remove('open');
        if (before && before.isConnected && typeof before.focus === 'function') before.focus();
        resolve(value);
      };
      const watcher = new MutationObserver(() => { if (!overlay.classList.contains('open')) finish(null); });
      watcher.observe(overlay, { attributes: true, attributeFilter: ['class'] });
      document.getElementById('stepup-submit').onclick = () => finish(input.value || null);
      document.getElementById('stepup-cancel').onclick = () => finish(null);
      document.getElementById('stepup-close').onclick = () => finish(null);
      // preventDefault: focus goes back to the button that opened the prompt,
      // and the same Enter would press it again and open a second prompt.
      input.onkeydown = (e) => { if (e.key === 'Enter') { e.preventDefault(); finish(input.value || null); } };
      overlay.classList.add('open');
      setTimeout(() => input.focus(), 50);
    });
  }

  // -----------------------------------------------------------
  // Toast notifications
  // -----------------------------------------------------------
  function toast(message, type = 'info') {
    let container = document.querySelector('.toast-container');
    if (!container) {
      container = document.createElement('div');
      container.className = 'toast-container';
      document.body.appendChild(container);
    }

    const icons = {
      success: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>',
      error: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
      warning: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
      info: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
    };

    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.innerHTML = `${icons[type] || icons.info}<span>${escapeHtml(message)}</span>`;
    container.appendChild(el);

    requestAnimationFrame(() => el.classList.add('show'));

    setTimeout(() => {
      el.classList.remove('show');
      setTimeout(() => el.remove(), 250);
    }, 4000);
  }

  // Escaped text with a break hint after each separator in names, ids, URLs
  // and image references ("motorola-one_fusion+ (1414f972)",
  // "ghcr.io/org/image@sha256:..."), so a long one wraps at a natural point
  // before the CSS has to break inside a word.
  function brk(str) {
    // "://" is one unit, so a URL never breaks between its two slashes.
    return escapeHtml(str).replace(/:\/\/|[-_.\/:@]/g, '$&<wbr>').replace(/\(/g, '<wbr>(');
  }

  function escapeHtml(str) {
    // Escape quotes too (the textContent/innerHTML trick doesn't), so values
    // interpolated into attributes like placeholder="..." can't break out.
    return String(str ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');
  }

  function sanitizeHint(html) {
    const el = document.createElement('div');
    el.innerHTML = html;
    const allowedSchemes = ['http:', 'https:', 'mailto:'];
    el.querySelectorAll('*').forEach(node => {
      if (!['A', 'B', 'CODE'].includes(node.tagName)) {
        node.replaceWith(document.createTextNode(node.textContent));
        return;
      }
      for (const attr of [...node.attributes]) {
        if (node.tagName === 'A' && attr.name === 'href') {
          const scheme = (attr.value || '').trim().toLowerCase();
          if (!allowedSchemes.some(s => scheme.startsWith(s))) node.removeAttribute('href');
          continue;
        }
        if (node.tagName === 'A' && attr.name === 'target') continue;
        node.removeAttribute(attr.name);
      }
      // Anything opening a new tab gets rel="noopener noreferrer", set HERE
      // rather than in the YAML.
      //
      // The loop above strips every attribute it does not explicitly keep, so a
      // rel written into a service's credential_hint would be removed on its
      // way to the DOM — the fix would look applied, pass review, and do
      // nothing. Setting it after sanitising covers all 13 existing hints and
      // every future one, and cannot be forgotten by whoever writes the next.
      //
      // Modern browsers imply noopener for target=_blank, so this is defence in
      // depth rather than a live hole; noreferrer is the part still worth
      // having, since these links point at a provider's dashboard and the
      // referrer would name the user's CashPilot host.
      if (node.tagName === 'A' && node.getAttribute('target')) {
        node.setAttribute('rel', 'noopener noreferrer');
      }
    });
    return el.innerHTML;
  }

  function capFirst(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : ''; }

  // A container status as a label. The states Docker names are translated; any
  // other status shows as it came, capitalised.
  function statusLabelOf(s) {
    switch (s) {
      case 'running': return t('app.status.running');
      case 'exited': return t('app.status.exited');
      case 'stopped': return t('app.status.stopped');
      case 'paused': return t('app.status.paused');
      case 'restarting': return t('app.status.restarting');
      case 'created': return t('app.status.created');
      case 'dead': return t('app.status.dead');
      case 'removing': return t('app.status.removing');
      case 'unknown': return t('app.status.unknown');
      default: return capFirst(s);
    }
  }

  // A catalog category as a label: "Depin" in the badges, "DePIN" in the
  // catalog table (dePin true). Unknown categories show as they came, capitalised.
  function categoryLabel(c, dePin = false) {
    switch (c) {
      case 'bandwidth': return t('app.category.bandwidth');
      case 'depin': return dePin ? t('app.category.depin_table') : t('app.category.depin');
      case 'storage': return t('app.category.storage');
      case 'compute': return t('app.category.compute');
      case 'mining': return t('app.category.mining');
      default: return capFirst(c);
    }
  }

  function fmtNetBytes(b) {
    if (!b || b < 1024) return (b || 0) + ' B';
    if (b < 1048576) return (b / 1024).toFixed(1) + ' KB';
    if (b < 1073741824) return (b / 1048576).toFixed(1) + ' MB';
    return (b / 1073741824).toFixed(2) + ' GB';
  }

  // -----------------------------------------------------------
  // Modal
  // -----------------------------------------------------------
  function openModal(id) {
    const overlay = document.getElementById(id);
    if (overlay) overlay.classList.add('open');
  }

  function closeModal(id) {
    const overlay = document.getElementById(id);
    if (overlay) overlay.classList.remove('open');
  }

  function closeAllModals() {
    document.querySelectorAll('.modal-overlay.open').forEach(m => m.classList.remove('open'));
  }

  // Close modals on overlay click or Escape
  document.addEventListener('click', (e) => {
    if (e.target.classList.contains('modal-overlay')) closeAllModals();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeAllModals();
  });

  // -----------------------------------------------------------
  // Keyboard navigation
  //
  // "/" focuses the page's search box, "r" refreshes the dashboard. Ignored while
  // typing.
  // -----------------------------------------------------------
  function initSidebar() {
    const typing = (el) => el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
    document.addEventListener('keydown', (e) => {
      if (e.metaKey || e.ctrlKey || e.altKey || typing(e.target)) return;
      if (document.querySelector('.modal-overlay.open')) return;
      if (e.key === '/') {
        const search = document.querySelector('#catalog-search, #payout-filter');
        if (search) { e.preventDefault(); search.focus(); }
        return;
      }
      if (e.key === 'r' && document.body.dataset.page === 'dashboard') {
        e.preventDefault();
        refreshServices();
      }
    });
  }

  // -----------------------------------------------------------
  // Dashboard
  // -----------------------------------------------------------
  let earningsChart = null;
  let refreshTimer = null;

  let _exchangeRates = { fiat: { USD: 1 }, crypto_usd: {} };
  let _displayCurrency = 'USD';

  // Sort state — persisted across re-renders
  let _sortCol = 'name';
  let _sortAsc = true;

  function detectDefaultCurrency() {
    const locale = navigator.language || 'en-US';
    const map = {
      'en-US': 'USD', 'en-GB': 'GBP', 'en-AU': 'AUD', 'en-CA': 'CAD',
      'de': 'EUR', 'fr': 'EUR', 'es': 'EUR', 'it': 'EUR', 'pt': 'EUR',
      'nl': 'EUR', 'el': 'EUR', 'fi': 'EUR', 'et': 'EUR', 'lv': 'EUR',
      'lt': 'EUR', 'sk': 'EUR', 'sl': 'EUR', 'mt': 'EUR', 'ie': 'EUR',
      'ja': 'JPY', 'ko': 'KRW', 'zh': 'CNY', 'hi': 'INR',
      'pt-BR': 'BRL', 'ru': 'RUB', 'tr': 'TRY', 'pl': 'PLN',
      'cs': 'CZK', 'sv': 'SEK', 'nb': 'NOK', 'nn': 'NOK', 'da': 'DKK',
      'hu': 'HUF', 'ro': 'RON', 'bg': 'BGN', 'hr': 'EUR',
      'th': 'THB', 'id': 'IDR', 'ms': 'MYR', 'vi': 'VND',
      'ar': 'SAR', 'he': 'ILS', 'uk': 'UAH',
    };
    return map[locale] || map[locale.split('-')[0]] || 'USD';
  }

  // Which sources are currently stale, and what that means for what is shown.
  //
  // exchange_rates.py keeps a separate clock per source, each advanced only on
  // that source's own HTTP 200, and publishes crypto_stale / fiat_stale. No
  // caller ever asked. So if CoinGecko stopped responding after one successful
  // fetch, every token balance kept rendering at a price that could be hours or
  // days old, and nothing on screen changed (CashPilot-dfw).
  function staleRateNotice() {
    const cryptoStale = _exchangeRates.crypto_stale === true;
    // Fiat only matters when a conversion actually uses it — a viewer reading in
    // USD is not affected by a stale USD->X table, and warning them would be the
    // kind of noise that teaches people to ignore warnings.
    const fiatStale = _exchangeRates.fiat_stale === true && _displayCurrency !== 'USD';
    if (!cryptoStale && !fiatStale) return '';
    if (cryptoStale && fiatStale) return t('app.rates.stale_both', { currency: _displayCurrency });
    return cryptoStale ? t('app.rates.stale_crypto') : t('app.rates.stale_fiat', { currency: _displayCurrency });
  }

  function renderStaleRateNotice() {
    const note = document.getElementById('rates-stale-note');
    if (!note) return;
    const message = staleRateNotice();
    note.textContent = message;
    note.style.display = message ? '' : 'none';
  }

  async function loadExchangeRates() {
    try {
      _exchangeRates = await api('/api/exchange-rates');
    } catch (err) {
      console.warn('Could not refresh exchange rates, keeping previous values:', err);
    }
    renderStaleRateNotice();
  }

  async function loadTopbarEarnings() {
    try {
      await loadExchangeRates();
      const data = await api('/api/earnings/summary');
      setTextContent('topbar-total', formatCurrency(data.total || 0));
    } catch (err) {
      // Keep whatever was already shown rather than fabricating $0.
      console.warn('Could not refresh topbar earnings, keeping previous value:', err);
    }
  }

  async function loadDashboard() {
    await loadExchangeRates();
    await Promise.all([
      loadDashboardStats(),
      loadServicesTable(),
      loadEarningsChart('7'),
      loadPayoutQueue(),
      loadMoneyWaiting(),
      loadUsagePanel(),
    ]);

    // Auto-refresh every hour
    if (refreshTimer) clearInterval(refreshTimer);
    refreshTimer = setInterval(() => {
      loadDashboardStats();
      loadServicesTable();
      loadPayoutQueue();
      loadMoneyWaiting();
      loadUsagePanel();
    }, 3600000);
  }

  // Resource use per server (/api/usage): hourly lines for one server's total,
  // or for one of its containers. A missing reading is null and draws a gap,
  // never a drop to 0: a host-network container has no traffic counters, and
  // a worker that was offline sent nothing.
  const USAGE_DASH = '—';
  // Where a worker that lost Docker finds the cause and the lasting fix (main.DOCKER_LOST_DOC).
  const DOCKER_LOST_DOC = 'https://geiserx.github.io/CashPilot/faq/#worker-lost-docker';
  const usageState = { days: '7', worker: null, container: '', step: 3600 };
  const usageCharts = {};

  function usageRate(v) {
    if (v === null || v === undefined) return USAGE_DASH;
    return `${fmtBytes(v) || USAGE_DASH}/s`;
  }

  function usageCpu(v) {
    return v === null || v === undefined ? USAGE_DASH : `${Number(v).toFixed(1)}%`;
  }

  function usageMem(mb) {
    if (mb === null || mb === undefined) return USAGE_DASH;
    return mb >= 1024 ? `${(mb / 1024).toFixed(2)} GB` : `${Math.round(mb)} MB`;
  }

  function usageLastIndex(values) {
    for (let i = values.length - 1; i >= 0; i -= 1) {
      if (values[i] !== null && values[i] !== undefined) return i;
    }
    return -1;
  }

  function usageLast(values) {
    const i = usageLastIndex(values);
    return i < 0 ? null : values[i];
  }

  function usagePeak(values) {
    let peak = null;
    for (const v of values) if (v !== null && v !== undefined && (peak === null || v > peak)) peak = v;
    return peak;
  }

  // The chart's data from the API payload. Pure, so scripts/usage_panel_check.mjs
  // can pin that a null reading stays null (a gap) all the way to Chart.js.
  function usageModel(data) {
    const s = (data && data.series) || {};
    const hours = (data && data.hours) || [];
    const pick = (k) => hours.map((_, i) => {
      const v = (s[k] || [])[i];
      return v === null || v === undefined ? null : Number(v);
    });
    return {
      hours,
      cpu: pick('cpu_percent'),
      mem: pick('memory_mb'),
      rx: pick('rx_rate'),
      tx: pick('tx_rate'),
      rxBytes: pick('rx_bytes'),
      txBytes: pick('tx_bytes'),
      partial: hours.map((_, i) => !!(s.traffic_partial || [])[i]),
      cpuPartial: hours.map((_, i) => !!(s.cpu_partial || [])[i]),
      memPartial: hours.map((_, i) => !!(s.memory_partial || [])[i]),
    };
  }

  function usageHourTitle(epoch, step) {
    const d = new Date(epoch * 1000);
    const start = d.toLocaleString(undefined, { weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    if (!step || step <= 3600) return start;
    const end = new Date((epoch + step) * 1000).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    return t('app.usage.hour_range', { start, end });
  }

  // A weekday at each local midnight on 7 days, a date each week on 30. The
  // charts are small, so a tick label must stay a few characters wide.
  function usageTick(epoch, days) {
    const d = new Date(epoch * 1000);
    const prev = new Date((epoch - (Number(days) > 7 ? 6 * 3600 : 3600)) * 1000);
    if (d.getDate() === prev.getDate()) return '';
    if (Number(days) > 7) {
      const dayIndex = Math.floor((epoch - d.getTimezoneOffset() * 60) / 86400);
      if (dayIndex % 7 !== 0) return '';
      // The month only on the first tick in it: "Oct 1", "8", "15".
      return d.getDate() <= 7 ? d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : String(d.getDate());
    }
    return d.toLocaleDateString(undefined, { weekday: 'short' });
  }

  // A vertical hairline at the hovered hour, across the plot.
  const usageCrosshair = {
    id: 'usageCrosshair',
    afterDatasetsDraw(chart) {
      const active = chart.tooltip && chart.tooltip.getActiveElements();
      if (!active || !active.length) return;
      const x = active[0].element.x;
      const { top, bottom } = chart.chartArea;
      const c = chart.ctx;
      c.save();
      c.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue('--text-muted').trim();
      c.lineWidth = 1;
      c.beginPath();
      c.moveTo(x, top);
      c.lineTo(x, bottom);
      c.stroke();
      c.restore();
    },
  };

  function usageChart(id, datasets, yFormat, tooltipLabel) {
    const canvas = document.getElementById(id);
    if (!canvas || typeof Chart === 'undefined') return null;
    const cs = getComputedStyle(document.documentElement);
    const tok = (n) => cs.getPropertyValue(n).trim();
    const fontMono = tok('--font-mono');
    // A point with no neighbour on either side would be invisible with no
    // marker, so only those get a dot.
    const isolated = (ctx) => {
      const d = ctx.dataset.data;
      const i = ctx.dataIndex;
      const has = (j) => d[j] !== null && d[j] !== undefined;
      return has(i) && !has(i - 1) && !has(i + 1) ? 2 : 0;
    };
    return new Chart(canvas, {
      type: 'line',
      data: {
        labels: [],
        datasets: datasets.map(ds => ({
          label: ds.label,
          data: [],
          borderColor: tok(ds.color),
          backgroundColor: tok(ds.color),
          borderWidth: 2,
          pointRadius: isolated,
          pointHoverRadius: 4,
          pointHoverBorderColor: tok('--bg-card'),
          pointHoverBorderWidth: 2,
          spanGaps: false,
          tension: 0,
        })),
      },
      plugins: [usageCrosshair],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: tok('--bg-secondary'),
            titleColor: tok('--text-primary'),
            bodyColor: tok('--text-secondary'),
            borderColor: tok('--border-color'),
            borderWidth: 1,
            padding: 10,
            callbacks: {
              title: (items) => (items.length ? usageHourTitle(Number(items[0].label), usageState.step) : ''),
              label: tooltipLabel,
            },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            border: { color: tok('--border-color') },
            ticks: {
              color: tok('--text-muted'),
              font: { size: 12, family: fontMono },
              autoSkip: false,
              maxRotation: 0,
              align: 'inner',
              callback: function (value) { return usageTick(Number(this.getLabelForValue(value)), usageState.days); },
            },
          },
          y: {
            beginAtZero: true,
            grid: { color: tok('--border-color') },
            border: { display: false },
            ticks: { color: tok('--text-muted'), maxTicksLimit: 4, font: { size: 12, family: fontMono }, callback: yFormat },
          },
        },
      },
    });
  }

  function usageSetChart(key, labels, columns) {
    const chart = usageCharts[key];
    if (!chart) return;
    chart.data.labels = labels;
    columns.forEach((values, i) => { chart.data.datasets[i].data = values; });
    chart.update();
  }

  function usageFillPickers(data) {
    const serverSel = document.getElementById('usage-server');
    const containerSel = document.getElementById('usage-container');
    if (!serverSel || !containerSel) return null;
    const servers = data.servers || [];
    serverSel.innerHTML = servers.map(sv => `<option value="${escapeHtml(String(sv.worker_id))}">${escapeHtml(sv.name)}${sv.status === 'online' ? '' : escapeHtml(t('app.offline_suffix'))}</option>`).join('');
    serverSel.value = data.worker_id === null || data.worker_id === undefined ? '' : String(data.worker_id);
    const server = servers.find(sv => sv.worker_id === data.worker_id) || { containers: [], name: '' };
    containerSel.innerHTML = `<option value="">${escapeHtml(t('app.usage.all_containers'))}</option>` + server.containers.map(c =>
      `<option value="${escapeHtml(c.name)}">${escapeHtml(c.name === `cashpilot-${c.slug}` ? c.service : `${c.service} \u00b7 ${c.name}`)}</option>`).join('');
    containerSel.value = data.container || '';
    if (!serverSel.dataset.bound) {
      serverSel.dataset.bound = '1';
      serverSel.addEventListener('change', () => { usageState.worker = serverSel.value; usageState.container = ''; loadUsagePanel(); });
      containerSel.addEventListener('change', () => { usageState.container = containerSel.value; loadUsagePanel(); });
    }
    return server;
  }

  function usageFoot(data, server) {
    if (data.container) {
      const c = server.containers.find(x => x.name === data.container);
      return c && c.no_counters
        ? t('app.usage.host_network_one')
        : '';
    }
    const host = server.containers.filter(c => c.no_counters).map(c => c.service);
    const parts = [t('app.usage.sum_note')];
    if (host.length) {
      parts.push(t('app.usage.host_network_some', { names: [...new Set(host)].join(', ') }));
    }
    return parts.join(' ');
  }

  function renderUsage(data) {
    const charts = document.getElementById('usage-charts');
    const empty = document.getElementById('usage-empty');
    const foot = document.getElementById('usage-foot');
    const server = usageFillPickers(data);
    const hasData = server && server.containers.length > 0;
    if (charts) charts.hidden = !hasData;
    if (empty) {
      empty.hidden = !!hasData;
      empty.innerHTML = hasData ? '' : `<div class="block-empty">${t('app.usage.empty')}</div>`;
    }
    if (!hasData) { if (foot) foot.textContent = ''; return; }
    if (foot) foot.textContent = usageFoot(data, server);

    const m = usageModel(data);
    if (!usageCharts.cpu) {
      // A container whose stats read failed is missing from the sum: a floor.
      const geq = (flags, i) => (usageCharts.net._cpModel[flags][i] ? '\u2265 ' : '');
      usageCharts.cpu = usageChart('usage-cpu', [{ label: t('app.usage.cpu'), color: '--series-1' }], (v) => `${v}%`,
        (ctx) => `${t('app.usage.cpu')} ${geq('cpuPartial', ctx.dataIndex)}${usageCpu(ctx.parsed.y)}`);
      usageCharts.mem = usageChart('usage-mem', [{ label: t('app.usage.memory'), color: '--series-1' }], (v) => usageMem(v),
        (ctx) => `${t('app.usage.memory')} ${geq('memPartial', ctx.dataIndex)}${usageMem(ctx.parsed.y)}`);
      usageCharts.net = usageChart('usage-net', [{ label: t('app.usage.down'), color: '--series-1' }, { label: t('app.usage.up'), color: '--series-2' }],
        (v) => usageRate(v), (ctx) => {
          const cur = usageCharts.net._cpModel;
          const i = ctx.dataIndex;
          const bytes = ctx.datasetIndex === 0 ? cur.rxBytes[i] : cur.txBytes[i];
          const floor = cur.partial[i] ? '\u2265 ' : '';
          const moved = bytes === null ? '' : `, ${fmtBytes(bytes)}`;
          return `${ctx.dataset.label} ${floor}${usageRate(ctx.parsed.y)}${moved}`;
        });
    }
    if (usageCharts.net) usageCharts.net._cpModel = m;
    usageLastData = data;
    const labels = m.hours.map(String);
    usageSetChart('cpu', labels, [m.cpu]);
    usageSetChart('mem', labels, [m.mem]);
    usageSetChart('net', labels, [m.rx, m.tx]);

    const who = data.container || server.name;
    const describe = (id, title, values, fmt) => {
      const el = document.getElementById(id);
      if (el) el.setAttribute('aria-label', t('app.usage.describe', { title, who, days: data.days, now: fmt(usageLast(values)), peak: fmt(usagePeak(values)) }));
    };
    describe('usage-cpu', t('app.usage.cpu'), m.cpu, usageCpu);
    describe('usage-mem', t('app.usage.memory'), m.mem, usageMem);
    const net = document.getElementById('usage-net');
    if (net) {
      net.setAttribute('aria-label', t('app.usage.describe_net', { who, days: data.days, down: usageRate(usageLast(m.rx)), downPeak: usageRate(usagePeak(m.rx)), up: usageRate(usageLast(m.tx)), upPeak: usageRate(usagePeak(m.tx)) }));
    }
    const now = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };
    // The value and its "at least" mark come from the same point.
    const latest = (values, flags, fmt) => {
      const i = usageLastIndex(values);
      return i < 0 ? fmt(null) : `${flags[i] ? '\u2265 ' : ''}${fmt(values[i])}`;
    };
    now('usage-cpu-now', latest(m.cpu, m.cpuPartial, usageCpu));
    now('usage-mem-now', latest(m.mem, m.memPartial, usageMem));
    now('usage-rx-now', latest(m.rx, m.partial, usageRate));
    now('usage-tx-now', latest(m.tx, m.partial, usageRate));
  }

  // Each load gets a number; a response that arrives after a newer request
  // started is dropped, so a slow old answer cannot overwrite a newer one.
  let usageLoadSeq = 0;
  let usageLastData = null;

  // The charts read their colours from the theme once, when built, so a theme
  // switch rebuilds them from the last payload.
  new MutationObserver(() => {
    if (!usageCharts.cpu) return;
    for (const key of Object.keys(usageCharts)) {
      if (usageCharts[key]) usageCharts[key].destroy();
      delete usageCharts[key];
    }
    if (usageLastData) renderUsage(usageLastData);
  }).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

  function setUsageDays(days) {
    usageState.days = String(days);
    document.querySelectorAll('.usage-period-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.days === usageState.days);
    });
    loadUsagePanel();
  }

  async function loadUsagePanel() {
    const section = document.getElementById('usage-charts');
    if (!section) return;
    const seq = ++usageLoadSeq;
    const meta = document.getElementById('usage-meta');
    try {
      await _waitForChart();
      const q = new URLSearchParams({ days: usageState.days });
      if (usageState.worker) q.set('worker_id', usageState.worker);
      if (usageState.container) q.set('container', usageState.container);
      const data = await api(`/api/usage?${q}`);
      if (seq !== usageLoadSeq) return;
      usageState.worker = data.worker_id === null || data.worker_id === undefined ? null : String(data.worker_id);
      usageState.container = data.container || '';
      usageState.step = data.step || 3600;
      renderUsage(data);
      if (meta) meta.textContent = '';
    } catch (err) {
      if (seq !== usageLoadSeq) return;
      console.warn('Could not load resource use, keeping the previous graphs:', err);
      if (meta) meta.textContent = t('app.usage.refresh_failed');
      const empty = document.getElementById('usage-empty');
      if (empty && !usageCharts.cpu) {
        empty.hidden = false;
        empty.innerHTML = `<div class="block-empty block-error"><span>${err && err.message ? t('app.usage.load_failed_detail', { error: escapeHtml(err.message) }) : t('app.usage.load_failed')}</span></div>`;
      }
    }
  }

  // Payouts awaiting an answer.
  //
  // The backend has detected these for a while and had nowhere to ask: a
  // balance drop was recorded as a PROBABLE payout, and without an answer it
  // never counts toward lifetime earnings. So a real payout quietly looked like
  // a loss, which is the opposite of what the feature is for.
  async function loadPayoutQueue() {
    const card = document.getElementById('payout-queue-card');
    const list = document.getElementById('payout-queue-list');
    if (!card || !list) return;

    let pending;
    try {
      pending = (await api('/api/earnings/payouts')).probable || [];
    } catch (err) {
      // Unknown is not "nothing pending". Leave whatever is on screen rather
      // than hiding a question the user still owes an answer to.
      console.warn('Could not load pending payouts:', err);
      _attentionCount.payoutsUnknown = true;
      updateAttentionSummary(null, null);
      return;
    }

    _attentionCount.payoutsUnknown = false;
    _attentionCount.payouts = pending.length;
    updateAttentionSummary(null, null);
    if (!pending.length) {
      card.style.display = 'none';
      list.innerHTML = '';
      return;
    }

    card.style.display = '';
    list.innerHTML = pending.map(p => {
      // The NATIVE amount leads, because it is what the provider actually paid
      // and it is what the user will see on the provider's own page when they
      // go to check. Everywhere else on the dashboard the display currency is
      // the right answer; here it is a converted approximation of a specific
      // real transaction, so it is shown second and marked as approximate.
      // A browser check caught this: a 24.90 USD payout rendered as "£18.55",
      // which is not a figure the user can match against anything.
      const nativeCurrency = p.currency || 'USD';
      const native = `${formatAmount(p.amount, nativeCurrency)} ${nativeCurrency}`;
      // Compare CURRENCY CODES, not the formatted strings. formatCurrency
      // returns "$24.90" via Intl while `native` is "24.90 USD", so a string
      // comparison finds them different for a USD payout on a USD dashboard
      // and renders "24.90 USD (≈ $24.90)" — the duplication this is meant to
      // suppress. The codes are the thing that actually decides whether a
      // conversion happened.
      const approx = effectiveDisplayCurrency(nativeCurrency) !== nativeCurrency
        ? ` <span class="muted">(≈ ${escapeHtml(formatCurrency(p.amount, nativeCurrency))})</span>`
        : '';
      return `
        <div class="payout-queue-item attn-row attn-ask" data-payout-id="${escapeHtml(String(p.id))}">
          <span class="attn-tag">${t('app.payq.tag')}</span>
          <span class="attn-what payout-queue-platform">${escapeHtml(p.platform || '')}</span>
          <span class="attn-why payout-queue-detail">${p.detected_at ? t('app.payq.dropped_on', { amount: escapeHtml(native), approx, day: escapeHtml(String(p.detected_at).slice(0, 10)) }) : t('app.payq.dropped', { amount: escapeHtml(native), approx })}</span>
          <span class="attn-actions payout-queue-actions">
            ${_canWrite ? `
            <button class="btn btn-primary btn-sm" data-action="confirmPayout" data-a1="${escapeHtml(String(p.id))}" data-a2="${escapeHtml(p.platform || '')}">${t('app.payq.yes')}</button>
            <button class="btn btn-ghost btn-sm" data-action="rejectPayout" data-a1="${escapeHtml(String(p.id))}" data-a2="${escapeHtml(p.platform || '')}">${t('app.payq.no')}</button>
            ` : `<span class="muted">${t('app.payq.writer_needed')}</span>`}
          </span>
        </div>
      `;
    }).join('');
  }

  // Money waiting (/api/obligations, docs/reminders.md): deadlines before a
  // provider writes off earnings, and balances ready to cash out. Catalog text
  // only goes through escapeHtml. Credential expiry is not repeated here: Needs
  // attention already shows it with its Renew button, and the push covers the
  // rest. A failed check reads "Could not check", never an all-clear.
  const OBLIGATION_TAGS = { claim: t('app.obl.tag.claim'), withdraw: t('app.obl.tag.withdraw'), 'keep-active': t('app.obl.tag.keep_active') };

  function obligationDate(iso) {
    // A due date is a calendar day, so it is drawn as that day, not shifted
    // by the viewer's offset from UTC.
    const d = new Date(`${iso}T00:00:00Z`);
    return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
  }

  function obligationWhen(item) {
    if (!item.due) return '';
    const by = item.censored ? t('app.obl.by_or_earlier', { date: obligationDate(item.due) }) : t('app.obl.by', { date: obligationDate(item.due) });
    const n = item.days_left;
    if (n < 0) return t('app.obl.days_ago', { by, n: -n });
    if (n === 0) return t('app.obl.today', { by });
    return t('app.obl.days_left', { by, n });
  }

  function obligationRow(item) {
    const cash = item.kind === 'cash-out';
    let tag = OBLIGATION_TAGS[item.action] || t('app.obl.tag.act');
    if (cash) tag = t('app.obl.tag.cash_out');
    if (item.stage === 'overdue') tag = t('app.obl.tag.overdue');
    if (item.stage === 'recheck') tag = t('app.obl.tag.arrived');
    const level = item.stage === 'overdue' ? 'fail'
      : (item.days_left != null && item.days_left <= 7) || item.stage === 'recheck' ? 'warn' : 'ask';
    const slug = escapeHtml(item.slug);
    const rule = escapeHtml(item.rule);
    let what = escapeHtml(item.title);
    if (cash && item.balance != null) {
      const cur = item.currency || 'USD';
      const approx = effectiveDisplayCurrency(cur) !== cur
        ? ` (≈ ${escapeHtml(formatCurrency(item.balance, cur))})` : '';
      what += `: ${escapeHtml(`${formatAmount(item.balance, cur)} ${cur}`)}${approx}`;
    }
    const when = obligationWhen(item);
    const parts = [`<span class="mw-title">${what}</span>`];
    if (when) parts.push(`<span class="mw-when">${escapeHtml(when)}</span>`);
    if (item.stage === 'recheck') parts.push(`<span class="mw-loss">${t('app.obl.recheck')}</span>`);
    else if (item.stage === 'overdue') parts.push(`<span class="mw-loss">${t('app.obl.overdue')}</span>`);
    parts.push(`<span class="mw-loss">${escapeHtml(item.loss)}</span>`);
    if (item.how) parts.push(`<details class="mw-how"><summary>${t('app.obl.how')}</summary>${escapeHtml(item.how)}</details>`);

    const actions = [];
    if (item.url) {
      actions.push(`<a class="btn btn-primary btn-sm" href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">${t('app.obl.open', { name: escapeHtml(item.name) })}</a>`);
    }
    if (_canWrite) {
      if (item.can_done) {
        const label = item.stage === 'recheck' ? t('app.obl.arrived') : (cash || item.action === 'withdraw') ? t('app.obl.requested') : t('app.obl.done');
        actions.push(`<button class="btn btn-ghost btn-sm" data-action="obligationDone" data-a1="${slug}" data-a2="${rule}" data-a3="${escapeHtml(item.occurrence)}">${label}</button>`);
      }
      if (item.can_snooze) {
        actions.push(`<button class="btn btn-ghost btn-sm" data-action="obligationSnooze" data-a1="${slug}" data-a2="${rule}" data-a3="1">${t('app.obl.snooze_day')}</button>`);
      }
      const more = [];
      if (item.can_snooze) more.push(`<button class="btn btn-ghost btn-sm" data-action="obligationSnooze" data-a1="${slug}" data-a2="${rule}" data-a3="7">${t('app.obl.snooze_week')}</button>`);
      more.push(`<button class="btn btn-ghost btn-sm" data-action="obligationMute" data-a1="${slug}" data-a2="${rule}">${t('app.obl.not_for_me')}</button>`);
      more.push(`<button class="btn btn-ghost btn-sm" data-action="obligationMute" data-a1="${slug}" data-a2="*">${t('app.obl.mute_all', { name: escapeHtml(item.name) })}</button>`);
      if (item.source) more.push(`<a class="btn btn-ghost btn-sm" href="${escapeHtml(item.source)}" target="_blank" rel="noopener noreferrer">${t('app.obl.source_checked', { date: escapeHtml(item.checked) })}</a>`);
      actions.push(`<details class="mw-more"><summary class="btn btn-ghost btn-sm">${t('app.obl.more')}</summary><div class="mw-menu">${more.join('')}</div></details>`);
    } else if (item.source) {
      actions.push(`<a class="btn btn-ghost btn-sm" href="${escapeHtml(item.source)}" target="_blank" rel="noopener noreferrer">${t('app.obl.source')}</a>`);
    }
    return `
      <div class="attn-row attn-${level} mw-row" data-obligation="${slug}:${rule}">
        <span class="attn-tag">${escapeHtml(tag)}</span>
        <span class="attn-what">${escapeHtml(item.name)}</span>
        <span class="attn-why mw-why">${parts.join('')}</span>
        <span class="attn-actions">${actions.join('')}</span>
      </div>`;
  }

  async function loadMoneyWaiting() {
    const section = document.getElementById('money-waiting');
    const list = document.getElementById('money-waiting-list');
    const foot = document.getElementById('money-waiting-muted');
    const count = document.getElementById('money-waiting-count');
    if (!section || !list) return;
    let data;
    try {
      data = await api('/api/obligations');
    } catch (err) {
      console.warn('Could not check the reminders:', err);
      section.hidden = false;
      if (count) count.textContent = '';
      list.innerHTML = `<div class="attn-row attn-unknown"><span class="attn-tag">${t('app.obl.unknown_tag')}</span><span class="attn-what">${t('app.obl.money_waiting')}</span><span class="attn-why">${t('app.obl.check_failed')}</span><span class="attn-actions"></span></div>`;
      if (foot) foot.hidden = true;
      return;
    }
    const items = (data.items || []).filter(i => i.kind !== 'credential');
    const muted = data.muted || [];
    list.innerHTML = items.map(obligationRow).join('');
    if (count) count.textContent = items.length ? String(items.length) : '';
    if (foot) {
      foot.hidden = !muted.length;
      foot.innerHTML = muted.length ? t('app.obl.muted_list', { list: muted.map(m => `${escapeHtml(m.name)}, ${escapeHtml(m.title)}${_canWrite
        ? ` <button class="btn btn-link btn-sm" data-action="obligationUnmute" data-a1="${escapeHtml(m.slug)}" data-a2="${escapeHtml(m.rule)}">${t('app.obl.unmute')}</button>` : ''}`).join(' · ') }) : '';
    }
    // Hidden while there is nothing to do, like the payout card: an empty
    // panel every day teaches people to skip the one day it matters.
    section.hidden = !items.length && !muted.length;
  }

  async function obligationPost(slug, rule, body, done) {
    try {
      await api(`/api/obligations/${encodeURIComponent(slug)}/${encodeURIComponent(rule)}`, { method: 'POST', body });
      toast(done, 'success');
    } catch (err) {
      toast(err.message, 'error');
    }
    await loadMoneyWaiting();
  }

  function obligationDone(slug, rule, occurrence) {
    return obligationPost(slug, rule, { action: 'done', occurrence }, t('app.obl.marked_done'));
  }

  function obligationSnooze(slug, rule, days) {
    const n = Number(days);
    return obligationPost(slug, rule, { action: 'snooze', days: n }, n === 1 ? t('app.obl.snoozed_day') : t('app.obl.snoozed_week'));
  }

  function obligationMute(slug, rule) {
    return obligationPost(slug, rule, { action: 'mute' }, t('app.obl.muted'));
  }

  function obligationUnmute(slug, rule) {
    return obligationPost(slug, rule, { action: 'unmute' }, t('app.obl.unmuted'));
  }

  // How far off is the next payout for this one service.
  //
  // Three separate questions that used to be one number which went DOWN when
  // the user got paid: what is sitting there now, what has this service earned
  // in total, and when can it be cashed out. The backend already answers all
  // three and states its own uncertainty precisely — "not enough history yet"
  // and "this is not earning" are different problems with different fixes — so
  // this renders that sentence rather than inventing a cheerier one.
  async function loadPayoutProgress() {
    const card = document.getElementById('payout-progress-card');
    const body = document.getElementById('payout-progress-body');
    if (!card || !body) return;
    const slug = card.dataset.slug;
    if (!slug) return;

    let data;
    try {
      data = await api(`/api/services/${encodeURIComponent(slug)}/payout-progress`);
    } catch (err) {
      // Leave the card hidden rather than showing a fabricated zero.
      console.warn('Could not load payout progress:', err);
      return;
    }

    const projection = data.projection || {};
    const balance = Number(data.current_balance || 0);

    // The endpoint reports what is LEFT, not the target, so the target is
    // derived. A service with no documented minimum omits `remaining`
    // entirely — checked against payouts.project() rather than assumed — and
    // that absence is what suppresses the bar. "No documented minimum" is not
    // "0% of the way there", and a bar stuck at zero would say the wrong thing
    // far more loudly than no bar at all.
    let bar = '';
    const remaining = projection.remaining;
    if (typeof remaining === 'number') {
      const threshold = balance + remaining;
      const pct = threshold > 0 ? Math.max(0, Math.min(100, (balance / threshold) * 100)) : 100;
      bar = `
        <div class="payout-progress-track" role="img"
             aria-label="${escapeHtml(t('app.progress.bar_aria', { pct: pct.toFixed(0), min: formatAmount(threshold, data.balance_currency || card.dataset.currency) }))}">
          <div class="payout-progress-fill" style="width:${pct.toFixed(1)}%;"></div>
        </div>`;
    }

    // Everything in this card shares ONE unit, and it is the unit the balance is
    // actually recorded in — deliberately not the dashboard's display currency.
    // A browser check caught why: the balance rendered as "£3.73" directly above
    // "to the 20 minimum", so the two halves of a single comparison were in
    // different units and the progress bar agreed with neither.
    //
    // It used to be the CASHOUT currency from the catalog, which is right only
    // while the collector reports that same unit. Storj records USD and declares
    // its minimum in STORJ, so a $3.50 balance rendered as "3.50 STORJ" and
    // counted down to a threshold in tokens. The endpoint now converts the
    // minimum into the balance's unit and states what that unit is.
    const unit = data.balance_currency || card.dataset.currency || '';
    const money = value => (unit ? `${formatAmount(value, unit)} ${unit}` : formatCurrency(value));

    const paid = data.confirmed_payout_count || 0;

    // Nothing read and nothing ever paid out: there is no progress to show.
    //
    // The card used to appear anyway, asserting a definite 0.00 lifetime and a
    // 0%-of-minimum bar for a service CashPilot had never once looked at. It
    // already got "Balance now" right (`balance_known`), which made the two
    // fabricated figures beside it read as corroborated.
    //
    // Confirmed payouts alone are worth showing, so this hides the card only
    // when BOTH are absent. Same defect filed three times: CashPilot-3oa
    // (the API), -s2b (the lifetime figure), -jkd (the card and bar).
    // The record form stays reachable even with nothing collected: a cash-out
    // made before CashPilot was installed is exactly the one to enter.
    // null, not [], when the list could not be read: an empty list would invite
    // the user to record again a cash-out that is already there.
    const confirmed = await api(`/api/earnings/payouts?platform=${encodeURIComponent(slug)}`)
      .then(r => r.confirmed || [])
      .catch(err => { console.warn('Could not load cash-outs', err); return null; });
    card.style.display = '';
    const payoutRows = (confirmed || []).map(p => `
        <li class="payout-row">
          <span class="num">${escapeHtml(String(p.detected_at || '').slice(0, 10))} · ${escapeHtml(formatAmount(p.amount, p.currency))} ${escapeHtml(p.currency || '')}${p.method ? ` · ${escapeHtml(p.method)}` : ''}</span>
          ${_canWrite ? `<button type="button" class="btn btn-ghost btn-sm" data-remove-payout="${escapeHtml(String(p.id))}" title="${t('app.cashout.remove_tip')}">${t('app.cashout.remove')}</button>` : ''}
        </li>`).join('');
    const payoutList = confirmed === null
      ? `<p class="form-hint text-warn">${t('app.cashout.load_failed')}</p>`
      : (payoutRows ? `<ul class="payout-list">${payoutRows}</ul>` : '');
    const recordForm = (_canWrite ? `
      <details class="payout-record">
        <summary>${t('app.cashout.record')}</summary>
        <form id="record-payout-form" class="payout-record-form">
          <input class="form-input form-input-price" name="amount" type="number" step="any" min="0" required placeholder="${unit ? escapeHtml(t('app.cashout.amount_unit', { unit })) : t('app.cashout.amount')}">
          <input class="form-input" name="method" type="text" maxlength="40" placeholder="${t('app.cashout.method')}">
          <input class="form-input" name="date" type="date">
          <button type="submit" class="btn btn-primary btn-sm">${t('app.save')}</button>
        </form>
        <p class="form-hint">${t('app.cashout.hint')}</p>
      </details>` : '') + payoutList;
    if (!data.balance_known && !paid) {
      body.innerHTML = recordForm;
      wirePayoutForm(card, slug);
      return;
    }
    body.innerHTML = `
      <div class="detail-grid">
        <div class="detail-item">
          <div class="detail-label">${t('app.progress.balance_now')}</div>
          <div class="detail-value">${data.balance_known ? escapeHtml(money(balance)) : `<span class="muted">${t('app.progress.not_collected')}</span>`}</div>
        </div>
        <div class="detail-item">
          <div class="detail-label">${t('app.progress.earned_total')}</div>
          <div class="detail-value">${data.balance_known || paid ? escapeHtml(money(data.lifetime_earned || 0)) : `<span class="muted">${t('app.progress.not_collected')}</span>`}</div>
          ${paid ? `<div class="detail-sub">${t('app.progress.includes_paid', { n: paid })}</div>` : ''}
        </div>
      </div>
      ${bar}
      <p class="sd-note">${escapeHtml(projection.summary || '')}</p>
      ${recordForm}
    `;
    wirePayoutForm(card, slug);
  }

  function wirePayoutForm(card, slug) {
    const form = card.querySelector('#record-payout-form');
    if (form) {
      form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const fd = new FormData(form);
        try {
          const out = await api('/api/earnings/payouts', {
            method: 'POST',
            body: { platform: slug, amount: Number(fd.get('amount')), method: String(fd.get('method') || ''), date: String(fd.get('date') || '') || null },
          });
          toast(out.priced === false ? t('app.cashout.recorded_unpriced') : t('app.cashout.recorded'), 'success');
          await Promise.all([loadPayoutProgress(), loadDashboardStats()]);
        } catch (err) {
          toast(err.message || t('app.cashout.record_failed'), 'error');
        }
      });
    }
    card.querySelectorAll('[data-remove-payout]').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!window.confirm(t('app.cashout.remove_confirm'))) return;
        try {
          await api(`/api/earnings/payouts/${encodeURIComponent(btn.dataset.removePayout)}`, { method: 'DELETE' });
          await Promise.all([loadPayoutProgress(), loadDashboardStats()]);
        } catch (err) {
          toast(err.message || t('app.cashout.remove_failed'), 'error');
        }
      });
    });
  }

  // What running this service actually does with the machine and connection.
  //
  // Two questions the deploy step never asked: whether strangers route traffic
  // through the user's IP under their name, and whether the container can be
  // kept off the home LAN. Both are answered by the backend already, and both
  // are things a person deserves to know BEFORE they click deploy rather than
  // after an ISP letter.
  //
  // "Nobody has documented this" is rendered as loudly as a known risk,
  // because unknown is not safe — that distinction is the whole design of
  // app/lan_isolation.py and dropping it here would undo it.
  //
  // Fills every risk card on the page: the detail modal has one, and the setup
  // wizard has one per selected service.
  async function loadDeployRisk() {
    await Promise.all(Array.from(document.querySelectorAll('.deploy-risk-card[data-slug]'), fillDeployRisk));
  }

  async function fillDeployRisk(card) {
    const body = card.querySelector('.deploy-risk-body');
    const slug = card.dataset.slug;
    if (!body || !slug) return;

    let risk;
    try {
      risk = await api(`/api/services/${encodeURIComponent(slug)}/deploy-risk`);
    } catch (err) {
      console.warn('Could not load deploy risk:', err);
      return;
    }

    const attribution = risk.attribution;
    const isolation = risk.isolation || {};
    const mining = risk.mining;
    if (!attribution && !isolation.summary && !mining) { card.style.display = 'none'; return; }

    let html = '';
    if (attribution) {
      // documented === false means nobody checked, which is a different claim
      // from "no risk" and is styled to say so rather than to reassure.
      const tone = attribution.documented ? 'deploy-risk-known' : 'deploy-risk-unknown';
      html += `
        <div class="deploy-risk-block ${tone}">
          <div class="deploy-risk-headline">${escapeHtml(attribution.headline || '')}</div>
          <div class="deploy-risk-body-text">${escapeHtml(attribution.body || '')}</div>
          ${attribution.lateral_note ? `<div class="deploy-risk-body-text">${escapeHtml(attribution.lateral_note)}</div>` : ''}
          ${attribution.source ? `<div class="deploy-risk-source">${t('app.risk.source', { source: escapeHtml(attribution.source) })}</div>` : ''}
        </div>`;
    }
    if (isolation.summary) {
      html += `
        <div class="deploy-risk-block deploy-risk-info">
          <div class="deploy-risk-headline">${t('app.risk.lan')}</div>
          <div class="deploy-risk-body-text">${escapeHtml(isolation.summary)}</div>
        </div>`;
    }
    if (mining) {
      html += `
        <div class="deploy-risk-block deploy-risk-info">
          <div class="deploy-risk-headline">${t('app.risk.miner_fee', { pct: escapeHtml(String(mining.dev_fee_percent)) })}</div>
          ${mining.pool_fee_note ? `<div class="deploy-risk-body-text">${escapeHtml(mining.pool_fee_note)}</div>` : ''}
          <div class="deploy-risk-body-text">${mining.payout_model === 'internal'
            ? t('app.risk.pool_internal')
            : t('app.risk.pool_external')}</div>
          <div class="deploy-risk-source"><a href="${escapeHtml(mining.dev_fee_source)}" target="_blank" rel="noopener noreferrer">${t('app.risk.fee_source')}</a></div>
        </div>`;
    }
    card.style.display = '';
    body.innerHTML = html;
  }

  async function confirmPayout(payoutId, platform) {
    try {
      await api(`/api/earnings/payouts/${encodeURIComponent(payoutId)}/confirm`, { method: 'POST' });
      toast(platform ? t('app.payq.confirmed', { platform }) : t('app.payq.confirmed_generic'), 'success');
      // The totals move as a direct result, so refresh them alongside the queue
      // rather than leaving the user to wonder whether it took effect.
      await Promise.all([loadPayoutQueue(), loadDashboardStats(), loadCollectorAlerts()]);
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function rejectPayout(payoutId, platform) {
    // Rejection DELETES the row, and there is no undo, so it asks first.
    if (!window.confirm(t('app.payq.reject_confirm', { platform: platform || '' }))) return;
    try {
      await api(`/api/earnings/payouts/${encodeURIComponent(payoutId)}/reject`, { method: 'POST' });
      toast(t('app.payq.rejected'), 'success');
      await Promise.all([loadPayoutQueue(), loadCollectorAlerts()]);
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function loadDashboardStats() {
    try {
      const data = await api('/api/earnings/summary');
      const totalBonus = data.total_bonus || 0;
      const displayTotal = totalBonus > 0 ? (data.total_adjusted || 0) : (data.total || 0);
      // "Nothing has been read yet" and "we read it and it was zero" are
      // different facts, and only one of them is a measurement. Rendering both
      // as $0.00 told a brand-new user their balance was zero before anything
      // had ever looked, and said exactly the same thing on an install whose
      // collection had silently stopped.
      const money = value => (data.has_readings === false ? '\u2014' : formatCurrency(value));
      setTextContent('total-earnings', money(displayTotal));
      setTextContent('today-earnings', money(data.today || 0));
      setTextContent('month-earnings', money(data.month || 0));
      // `|| 0` would render "could not be counted" as "nothing is running".
      // The endpoint sends null when the count could not be taken
      // (CashPilot-45k).
      setTextContent('active-services', data.active_services == null ? '\u2014' : data.active_services);

      const nothingYet = document.getElementById('no-readings-note');
      if (nothingYet) nothingYet.style.display = data.has_readings === false ? '' : 'none';

      // Show promo offset footnote under total
      const bonusNote = document.getElementById('total-bonus-note');
      if (bonusNote) {
        if (totalBonus > 0) {
          bonusNote.textContent = t('app.stats.promo', { amount: `\u2212${formatCurrency(totalBonus)}` });
          bonusNote.style.display = '';
        } else {
          bonusNote.style.display = 'none';
        }
      }

      const allTime = document.getElementById('all-time-note');
      if (allTime) {
        const unpriced = data.unpriced_payouts || 0;
        const unpricedNote = unpriced > 0 ? t('app.stats.unpriced', { n: unpriced }) : '';
        if (data.paid_out === null) {
          allTime.textContent = t('app.stats.all_time_unread');
          allTime.style.display = '';
        } else if ((data.paid_out || 0) > 0 || unpriced > 0) {
          allTime.textContent = t('app.stats.all_time', { earned: formatCurrency(data.earned_all_time || 0), paid: formatCurrency(data.paid_out), unpriced: unpricedNote });
          allTime.style.display = '';
        } else {
          allTime.style.display = 'none';
        }
      }

      // Update topbar
      setTextContent('topbar-total', money(displayTotal));

      // Change indicators
      if (data.today_change !== undefined) {
        setChangeIndicator('today-change', data.today_change);
      }
      if (data.month_change !== undefined) {
        setChangeIndicator('month-change', data.month_change);
      }
    } catch (err) {
      // Keep whatever was already displayed — a transient fetch failure
      // must not look like the dashboard's earnings dropped to zero.
      toast(err.message || t('app.stats.refresh_failed'), 'error');
    }
  }

  // The cashout terms to judge a row's payout by. The breakdown's block is the
  // only one carrying min_amount_comparable and eligible, both worked out
  // against the balance's own unit; the deployed list carries the catalog's raw
  // block, which has neither. Reading the deployed one is what left every
  // Payout cell at "--" and made the Payout sort a no-op.
  function cashoutFor(svc, bk) {
    return (bk && bk.cashout) || svc.cashout || {};
  }

  function sortServices(services, breakdownMap) {
    const statusOrder = { running: 0, external: 1, restarting: 2, paused: 3, stopped: 4, exited: 5, error: 6 };
    services.sort((a, b) => {
      let va, vb;
      switch (_sortCol) {
        case 'name':
          va = (a.name || '').toLowerCase();
          vb = (b.name || '').toLowerCase();
          return _sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
        case 'status': {
          const sa = (a.container_status || 'stopped').toLowerCase();
          const sb = (b.container_status || 'stopped').toLowerCase();
          va = statusOrder[sa] ?? 99;
          vb = statusOrder[sb] ?? 99;
          break;
        }
        case 'health':
          va = a.health_score ?? -1;
          vb = b.health_score ?? -1;
          break;
        case 'balance': {
          const ba = breakdownMap[a.slug];
          const bb = breakdownMap[b.slug];
          va = (ba && ba.signup_bonus) ? (ba.balance_adjusted ?? ba.balance) : ((ba && ba.balance) || a.balance || 0);
          vb = (bb && bb.signup_bonus) ? (bb.balance_adjusted ?? bb.balance) : ((bb && bb.balance) || b.balance || 0);
          break;
        }
        case 'change': {
          const ba = breakdownMap[a.slug];
          const bb = breakdownMap[b.slug];
          va = ba ? ba.delta : 0;
          vb = bb ? bb.delta : 0;
          break;
        }
        case 'cpu':
          va = parseFloat(a.cpu) || 0;
          vb = parseFloat(b.cpu) || 0;
          break;
        case 'memory':
          va = parseFloat(a.memory) || 0;
          vb = parseFloat(b.memory) || 0;
          break;
        // Both sort UNKNOWN last in either direction rather than as zero.
        // `parseFloat(x) || 0` — the idiom used above — would rank a host whose
        // free space could not be read as the fullest disk on the fleet, which
        // is the same "absent read as a definite value" this codebase keeps
        // having to undo.
        case 'disk':
          va = sortableFreeBytes(a);
          vb = sortableFreeBytes(b);
          break;
        case 'gpu':
          va = sortableGpu(a);
          vb = sortableGpu(b);
          break;
        case 'payout': {
          const coA = cashoutFor(a, breakdownMap[a.slug]);
          const coB = cashoutFor(b, breakdownMap[b.slug]);
          const balA = (breakdownMap[a.slug] && breakdownMap[a.slug].balance) || a.balance || 0;
          const balB = (breakdownMap[b.slug] && breakdownMap[b.slug].balance) || b.balance || 0;
          // Sorting by "closest to payout" needs the same like-for-like ratio;
          // otherwise a USD balance over a token minimum sorts nonsensically.
          va = coA.min_amount_comparable > 0 ? (balA / coA.min_amount_comparable) : -1;
          vb = coB.min_amount_comparable > 0 ? (balB / coB.min_amount_comparable) : -1;
          break;
        }
        default:
          va = 0; vb = 0;
      }
      if (_sortCol !== 'name') {
        // Unknown sinks in BOTH directions. A sentinel number cannot do this:
        // -Infinity sorts last descending but FIRST ascending, which would put
        // every host whose free space could not be read at the top of "least
        // free space" -- stating a failed reading as the worst case.
        const aU = va === SORT_UNKNOWN;
        const bU = vb === SORT_UNKNOWN;
        if (aU || bU) return aU && bU ? 0 : (aU ? 1 : -1);
        return _sortAsc ? va - vb : vb - va;
      }
      return 0;
    });
  }

  // worker_id -> {disk, gpu} for the Disk and GPU columns, or null when the
  // worker list could not be read at all.
  let _hostResources = null;

  // Sort keys. Unknown must not collapse into a number that sorts like a real
  // reading, so both return this sentinel, which the comparator keeps at the
  // bottom regardless of direction.
  const SORT_UNKNOWN = Symbol('unknown');

  function sortableFreeBytes(svc) {
    const hosts = hostsFor(svc);
    if (!hosts) return SORT_UNKNOWN;
    const free = hosts
      .filter(h => h.disk && typeof h.disk.free_bytes === 'number')
      .map(h => h.disk.free_bytes);
    return free.length ? Math.min(...free) : SORT_UNKNOWN;
  }

  // Ranked has-one > known-none > unknown, matching what the cell says.
  function sortableGpu(svc) {
    const hosts = hostsFor(svc);
    if (!hosts) return SORT_UNKNOWN;
    if (hosts.some(h => h.gpu && h.gpu.available === true)) return 2;
    if (hosts.every(h => h.gpu && h.gpu.available === false)) return 1;
    return SORT_UNKNOWN;
  }

  function buildHostResourceMap(workers) {
    if (!Array.isArray(workers)) return null;
    const map = {};
    for (const w of workers) {
      const info = w.system_info || {};
      map[String(w.id)] = {
        name: w.name || 'worker',
        online: w.status === 'online',
        // The Android client does not collect either of these. Telling its
        // owner their worker "may predate the feature" would send them to
        // upgrade something that was never going to report it -- verified
        // against the live fleet, where the phone reports neither.
        android: info.device_type === 'android' || String(info.os || '').trim().toLowerCase() === 'android',
        disk: info.disk || null,
        gpu: info.gpu || null,
      };
    }
    return map;
  }

  function fmtBytes(n) {
    if (typeof n !== 'number' || !isFinite(n) || n < 0) return null;
    const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
    let i = 0;
    let v = n;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    return `${v >= 10 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`;
  }

  // The hosts a service actually runs on. A service can span several workers,
  // and the columns must describe THOSE hosts rather than the fleet.
  function hostsFor(svc) {
    if (!_hostResources) return null;
    // `instance_details`, NOT `instances` — the latter is a COUNT, and
    // `for...of` over a number throws, which would have taken the whole table
    // down rather than degrading one column. Checked against app/main.py:1229
    // instead of assumed from the name.
    const ids = new Set();
    for (const inst of (Array.isArray(svc.instance_details) ? svc.instance_details : [])) {
      if (inst && inst.worker_id != null) ids.add(String(inst.worker_id));
    }
    if (svc.worker_id != null) ids.add(String(svc.worker_id));
    const hosts = [...ids].map(id => _hostResources[id]).filter(Boolean);
    return hosts.length ? hosts : null;
  }

  const UNKNOWN_CELL = (why) => `<span class="muted" title="${escapeHtml(why)}">&mdash;</span>`;

  // Free space on the host filesystem, NOT the service's own volume.
  //
  // Storj is paid for what it stores, so free space is earning capacity — a
  // node that quietly fills up stops growing. The column is labelled "Host
  // disk" because those are two different numbers and showing one under the
  // other's name would be worse than showing neither.
  function diskCell(svc) {
    return diskCellForHosts(hostsFor(svc));
  }

  // One instance's own host, so a sub-row is exact rather than an aggregate.
  function hostForWorker(workerId) {
    if (!_hostResources || workerId == null) return null;
    const h = _hostResources[String(workerId)];
    return h ? [h] : null;
  }

  function diskCellForHosts(hosts) {
    if (!_hostResources) return UNKNOWN_CELL(t('app.host.no_list'));
    if (!hosts) return UNKNOWN_CELL(t('app.host.unknown_host'));
    const known = hosts.filter(h => h.disk && typeof h.disk.free_bytes === 'number' && h.disk.total_bytes > 0);
    if (!known.length) {
      if (hosts.every(h => h.android)) {
        return UNKNOWN_CELL(t('app.host.android_disk'));
      }
      const offline = hosts.every(h => !h.online);
      return UNKNOWN_CELL(offline
        ? t('app.host.disk_offline')
        : t('app.host.disk_unreported'));
    }
    // The tightest host is the one that decides whether the service can keep
    // growing, so a fleet-wide average would hide exactly the case that matters.
    const tightest = known.reduce((a, b) => (a.disk.free_bytes <= b.disk.free_bytes ? a : b));
    const free = tightest.disk.free_bytes;
    const total = tightest.disk.total_bytes;
    const usedPct = Math.round(((total - free) / total) * 100);
    const unreported = hosts.length - known.length;
    const detail = [
      t('app.host.disk_line', { name: tightest.name, free: fmtBytes(free), total: fmtBytes(total), pct: usedPct }),
      t('app.host.disk_note'),
      known.length > 1 ? t('app.host.disk_tightest', { n: known.length }) : '',
      unreported > 0 ? t('app.host.unreported', { n: unreported }) : '',
    ].filter(Boolean).join(' ');
    const warn = usedPct >= 90 ? ' style="color:var(--error);"' : usedPct >= 80 ? ' style="color:var(--warning);"' : '';
    return `<span${warn} title="${escapeHtml(detail)}">${fmtBytes(free)}</span>`;
  }

  // Three-valued on purpose. `available: false` is a real "this host has no
  // GPU"; `null` is "could not tell" — which is what a containerised worker
  // reports when the device was never passed through. Rendering the second as
  // the first would state as fact that a machine has no GPU when it has three
  // idle render nodes, which is precisely how the fleet looked.
  function gpuCell(svc) {
    return gpuCellForHosts(hostsFor(svc));
  }

  function gpuCellForHosts(hosts) {
    if (!_hostResources) return UNKNOWN_CELL(t('app.host.no_list'));
    if (!hosts) return UNKNOWN_CELL(t('app.host.unknown_host'));
    const withGpu = hosts.filter(h => h.gpu && h.gpu.available === true);
    if (withGpu.length) {
      // A worker that read sysfs names the vendors (app/gpu.py); an older one sends devices only.
      const GPU_VENDORS = { nvidia: 'NVIDIA', amd: 'AMD', intel: 'Intel' };
      const vendorNames = new Set(withGpu.flatMap(h => Object.keys(h.gpu.vendors || {}))
        .map(v => GPU_VENDORS[v]).filter(Boolean));
      if (vendorNames.size) {
        const names = [...vendorNames];
        const detail = withGpu.map(h => `${h.name}: ${(h.gpu.devices || [t('app.gpu.present')]).join(', ')}`).join(' | ');
        return `<span title="${escapeHtml(detail)}">${escapeHtml(names.join(', '))}</span>`;
      }
      const devices = withGpu.flatMap(h => h.gpu.devices || []);
      const label = devices.length ? devices[0] : t('app.gpu.yes');
      const detail = withGpu.map(h => `${h.name}: ${(h.gpu.devices || [t('app.gpu.present')]).join(', ')}`).join(' | ');
      const more = devices.length > 1 ? ` +${devices.length - 1}` : '';
      return `<span title="${escapeHtml(detail)}">${escapeHtml(String(label))}${more}</span>`;
    }
    // No host says yes. Only call it "None" when every host actually SAID no.
    if (hosts.every(h => h.gpu && h.gpu.available === false)) {
      return `<span class="muted" title="${t('app.gpu.none_tip', { n: hosts.length })}">${t('app.gpu.none')}</span>`;
    }
    if (hosts.every(h => h.android)) {
      return UNKNOWN_CELL(t('app.gpu.android'));
    }
    const reason = hosts.map(h => h.gpu && h.gpu.reason).find(Boolean);
    return UNKNOWN_CELL(reason
      ? t('app.gpu.unknown_reason', { reason })
      : t('app.gpu.unreported'));
  }

  // A refresh that started later wins: an older one whose requests answer
  // last must not overwrite the newer attention list.
  let _attentionSeq = 0;

  async function loadServicesTable() {
    const container = document.getElementById('services-table-container');
    if (!container) return;

    // Show spinner while loading (only on first load, not refresh)
    if (!container.querySelector('.breakdown-table')) {
      container.innerHTML = `<div class="loading-line"><div class="spinner"></div> ${t('app.services.loading')}</div>`;
    }

    try {
      // Workers are fetched for the Disk and GPU columns. Both are facts about
      // the HOST a service runs on, not about the container, so they can only
      // come from the worker that reported them — which is what makes them work
      // for a remote host exactly as they do for the local one.
      //
      // .catch(() => null) rather than `[]`: an empty list would mean "no
      // workers", and the columns would render a confident em-dash for every
      // row. null means the lookup itself failed, which is a different answer
      // and gets a different tooltip.
      // Taken before the requests, so an older refresh that answers last
      // cannot claim the newest number.
      const seq = ++_attentionSeq;
      const [services, breakdown, workers] = await Promise.all([
        api('/api/services/deployed'),
        api('/api/earnings/breakdown').catch(() => []),
        api('/api/workers').catch(() => null),
      ]);
      _hostResources = buildHostResourceMap(workers);
      // The GPU column only earns its width when some box has a GPU: on a
      // fleet without one every row read "None" or a dash. The cells are still
      // rendered, so the row keeps the header's shape; the container class
      // hides the column (style.css, .no-gpu).
      // A failed worker list keeps the column, so its cells can say why.
      container.classList.toggle('no-gpu', workers !== null && !Object.values(_hostResources || {}).some(h => h.gpu && h.gpu.available === true));
      renderPlacement(services || [], workers);
      renderAttention(services || [], workers, seq);

      if (!services || services.length === 0) {
        // An empty list means one of two very different things, and saying the
        // wrong one is worse than saying nothing.
        //
        // /api/services/deployed is built only from ONLINE workers, so three
        // minutes after a host stops heartbeating — a reboot, a network blip, a
        // worker container restart — the table emptied and the dashboard stated
        // as fact that the user had no services and should start over. The
        // containers were still running and still earning.
        let unreachable = 0;
        try {
          const workers = await api('/api/workers');
          unreachable = (workers || []).filter(w => w.status !== 'online').length;
        } catch (err) {
          // Cannot tell which case this is; say so rather than guess.
          unreachable = -1;
        }
        container.innerHTML = unreachable === 0
          ? `
          <div class="empty-state empty-state-first">
            <div class="empty-state-title">${t('app.services.empty_title')}</div>
            <div class="empty-state-text">${t('app.services.empty_text')}</div>
            <a href="/setup" class="btn btn-primary">${t('app.services.add')}</a>
          </div>`
          : `
          <div class="empty-state">
            <div class="empty-state-title">${unreachable > 0 ? t('app.services.unreachable_n', { n: escapeHtml(String(unreachable)) }) : t('app.services.unreachable_all')}</div>
            <div class="empty-state-text">${t('app.services.unreachable_text', { n: unreachable === 1 ? 1 : 2 })}</div>
            <a href="/fleet" class="btn btn-ghost">${t('app.services.check_fleet')}</a>
          </div>`;
        return;
      }

      // Merge breakdown data into services by slug
      const breakdownMap = {};
      (breakdown || []).forEach(b => { breakdownMap[b.platform] = b; });

      // Preserve expanded rows across re-renders
      const expandedSlugs = new Set();
      container.querySelectorAll('.breakdown-row.expanded').forEach(r => {
        const slug = r.dataset.slug;
        if (slug) expandedSlugs.add(slug);
      });

      // Sort services
      sortServices(services, breakdownMap);

      const rows = services.map(svc => renderServiceRow(svc, breakdownMap[svc.slug])).join('');
      const sortIcon = (col) => {
        if (_sortCol !== col) return '<span class="sort-indicator"></span>';
        return _sortAsc
          ? '<span class="sort-indicator active">&#9650;</span>'
          : '<span class="sort-indicator active">&#9660;</span>';
      };
      const sortTh = (col, label, cls) => `<th class="sortable ${cls}" data-sort="${col}">${label}${sortIcon(col)}</th>`;

      container.innerHTML = `
        <table class="breakdown-table">
          <thead>
            <tr>
              ${sortTh('name', t('app.col.service'), 'c-name')}
              ${sortTh('status', t('app.col.status'), 'c-status')}
              ${sortTh('health', t('app.col.health'), 'c-health c-num')}
              ${sortTh('balance', t('app.col.balance'), 'c-bal c-num')}
              ${sortTh('change', t('app.col.change'), 'c-chg c-num')}
              ${sortTh('cpu', t('app.usage.cpu'), 'c-cpu c-num')}
              ${sortTh('memory', t('app.usage.memory'), 'c-mem c-num')}
              ${sortTh('disk', t('app.col.disk'), 'c-disk c-num')}
              ${sortTh('gpu', t('app.col.gpu'), 'c-gpu')}
              ${sortTh('payout', t('app.col.payout'), 'c-pay')}
              <th class="c-act">${t('app.col.actions')}</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>`;

      // Bind sort click handlers
      container.querySelectorAll('th.sortable').forEach(th => {
        th.addEventListener('click', () => {
          const col = th.dataset.sort;
          if (_sortCol === col) {
            _sortAsc = !_sortAsc;
          } else {
            _sortCol = col;
            _sortAsc = col === 'name' || col === 'status'; // text cols default A-Z, numeric cols default highest-first
          }
          loadServicesTable();
        });
      });

      // Restore expanded state
      expandedSlugs.forEach(slug => {
        const mainRow = container.querySelector(`.breakdown-row[data-slug="${slug}"]`);
        if (mainRow) {
          mainRow.classList.add('expanded');
          container.querySelectorAll(`.instance-row[data-parent="${slug}"]`).forEach(r => { r.style.display = ''; });
        }
      });
    } catch (err) {
      // Keep the existing table on a refresh failure. Only replace the
      // perpetual "Loading..." spinner with a clear error + retry affordance
      // when there was nothing on screen yet.
      if (!container.querySelector('.breakdown-table')) {
        container.innerHTML = `
          <div class="block-empty block-error">
            <span>${err && err.message ? t('app.services.load_failed_detail', { error: escapeHtml(err.message) }) : t('app.services.load_failed')}</span>
            <button class="btn btn-ghost btn-sm" data-action="loadServicesTable">${t('app.retry')}</button>
          </div>`;
      }
    }
  }

  // -----------------------------------------------------------
  // Operator view: placement grid and the attention list
  //
  // Both read the payloads loadServicesTable already fetched, so they never
  // disagree with the table under them.
  // -----------------------------------------------------------
  function instanceState(status) {
    const s = String(status || 'unknown').toLowerCase();
    if (s === 'running') return 'ok';
    if (s === 'exited' || s === 'stopped' || s === 'dead') return 'fail';
    return 'warn';
  }

  // A phone copy is an Android app, never a container. The phone says
  // "unknown" when it lacks the access to look (Detection.kt in
  // CashPilot-android), and that is a blind spot on the phone, not an app
  // that died, so it gets its own neutral state instead of red or amber.
  function copyState(inst) {
    if (inst && inst.is_android && String(inst.status || 'unknown').toLowerCase() === 'unknown') return 'unknown';
    return instanceState(inst && inst.status);
  }

  function copyWords(inst) {
    if (!inst || !inst.is_android) return inst && inst.status || t('app.place.status_unknown');
    const st = copyState(inst);
    if (st === 'ok') return t('app.place.phone_running');
    if (st === 'unknown') return t('app.place.phone_unknown');
    return t('app.place.phone_stopped');
  }

  function renderPlacement(services, workers) {
    const holder = document.getElementById('placement-grid');
    if (!holder) return;
    if (workers === null) {
      holder.innerHTML = `<p class="block-empty">${t('app.place.no_workers')}</p>`;
      return;
    }
    const boxes = (workers || []).slice().sort((a, b) => String(a.name).localeCompare(String(b.name)));
    if (!services.length || !boxes.length) {
      holder.innerHTML = `<p class="block-empty">${t('app.place.empty')}</p>`;
      return;
    }
    const rank = { fail: 0, warn: 1, unknown: 2, ok: 3 };
    const rows = services.map((svc) => {
      const details = svc.instance_details || [];
      const external = svc.container_status === 'external';
      const byBox = {};
      for (const inst of details) {
        const key = inst.worker_id != null ? String(inst.worker_id) : String(inst.node);
        (byBox[key] = byBox[key] || []).push(inst);
      }
      const states = details.map(copyState);
      const worst = states.reduce((w, st) => (rank[st] < rank[w] ? st : w), 'ok');
      const up = states.filter(st => st === 'ok').length;
      return { svc, byBox, external, worst: external ? 'ext' : worst, up, total: details.length };
    });
    rows.sort((a, b) => {
      const ra = a.external ? 4 : rank[a.worst];
      const rb = b.external ? 4 : rank[b.worst];
      return ra - rb || String(a.svc.name).localeCompare(String(b.svc.name));
    });

    // Cut long device names here, not with text-overflow: WebKit drops the
    // ellipsis on vertical text. The full name stays in the header title.
    const shortBox = (n) => { const s = String(n); return s.length > 14 ? `${s.slice(0, 13).trimEnd()}\u2026` : s; };
    const head = boxes.map((w) => {
      const online = w.status === 'online';
      return `<th class="pg-box${online ? '' : ' pg-box-off'}" scope="col" title="${escapeHtml(w.name)}: ${online ? t('app.place.online') : t('app.place.not_reporting')}"><span class="pg-box-name">${escapeHtml(shortBox(w.name))}</span></th>`;
    }).join('');

    const body = rows.map((r) => {
      const name = `<th scope="row" class="pg-svc">${escapeHtml(r.svc.name)}</th>`;
      if (r.external) {
        return `<tr class="pg-row pg-ext">${name}<td class="pg-ext-note" colspan="${boxes.length}">${t('app.place.external')}</td><td class="pg-count">${t('app.place.ext')}</td></tr>`;
      }
      const cells = boxes.map((w) => {
        const insts = r.byBox[String(w.id)] || r.byBox[String(w.name)] || [];
        if (!insts.length) return `<td><span class="cell cell-none" aria-label="${t('app.place.not_placed')}"></span></td>`;
        const st = insts.map(copyState).reduce((x, y) => (rank[y] < rank[x] ? y : x), 'ok');
        const words = insts.map(copyWords).join(', ');
        const n = insts.length > 1 ? `<span class="cell-n">${insts.length}</span>` : '';
        return `<td><span class="cell cell-${st}" title="${escapeHtml(t('app.place.cell_tip', { service: r.svc.name, box: w.name, words }))}" aria-label="${escapeHtml(words)}">${n}</span></td>`;
      }).join('');
      const countCls = r.up < r.total ? ` pg-count-${r.worst}` : '';
      return `<tr class="pg-row">${name}${cells}<td class="pg-count${countCls}">${r.up}/${r.total}</td></tr>`;
    }).join('');

    holder.innerHTML = `
      <div class="table-scroll">
        <table class="placement-table">
          <thead><tr><th scope="col" class="pg-svc">${t('app.col.service')}</th>${head}<th scope="col" class="pg-count">${t('app.place.up')}</th></tr></thead>
          <tbody>${body}</tbody>
        </table>
      </div>`;
  }

  async function renderAttention(services, workers, seq, knownAlerts, draw) {
    const list = document.getElementById('attention-list');
    if (!list) return;
    // The alerts this draw read and the number of that read, null when it could not read them.
    let alertsUsed = null;
    let alertsRead = null;
    const items = [];
    if (workers === null) {
      items.push({ level: 'warn', tag: t('app.attn.tag.unknown'), what: t('app.attn.boxes'), why: t('app.attn.no_workers') });
    }
    const boxName = {};
    for (const w of (workers || [])) boxName[String(w.id)] = w.name;

    for (const w of (workers || [])) {
      if (w.status !== 'online') {
        const info = w.system_info || {};
        const phone = info.device_type === 'android' || String(info.os || '').trim().toLowerCase() === 'android';
        items.push({ level: 'fail', tag: t('app.attn.tag.offline'), what: w.name, why: phone ? t('app.attn.offline_phone', { when: fmtTimestamp(w.last_heartbeat).text }) : t('app.attn.offline_box', { when: fmtTimestamp(w.last_heartbeat).text }), actions: `<a class="btn btn-ghost btn-sm" href="/fleet">${t('app.attn.open_fleet')}</a>` });
      }
    }
    for (const svc of services) {
      if (svc.account_disabled) {
        // One cause for every box and for the missing balance: the provider
        // turned the account off. A card per crash-looping box with a Start
        // button, and a "Fix credentials" one, pointed at fixes that cannot work.
        items.push(accountDisabledItem(svc));
        continue;
      }
      for (const inst of (svc.instance_details || [])) {
        const st = copyState(inst);
        if (st === 'ok') continue;
        const where = inst.node === 'local' ? t('app.attn.local') : (boxName[String(inst.worker_id)] || inst.node);
        if (inst.is_android) {
          // An app on a phone: CashPilot cannot start it, only the phone can.
          items.push(st === 'unknown'
            ? { level: 'unknown', tag: t('app.attn.tag.unknown'), what: svc.name, where, why: t('app.attn.phone_unknown') }
            : { level: 'fail', tag: t('app.attn.tag.not_running'), what: svc.name, where, why: t('app.attn.phone_stopped') });
          continue;
        }
        // The copy number rides along, or Start and Logs act on copy one.
        const wid = inst.worker_id != null
          ? ` data-a2="${escapeHtml(String(inst.worker_id))}"${inst.instance > 1 ? ` data-a3="${escapeHtml(String(inst.instance))}"` : ''}`
          : '';
        const controllable = _canWrite && !inst.unmanaged && !svc.unmanaged && inst.can_command && !inst.is_android;
        if (inst.held) {
          // The worker's fence guard keeps it stopped (a fence-gated node): Start
          // is refused for the same reason, so the card says why and offers what works.
          items.push({
            level: 'fail',
            tag: t('app.attn.tag.held'),
            what: svc.name,
            where,
            why: t('app.attn.held', { reason: escapeHtml(inst.held) }),
            actions: _isOwner && !inst.unmanaged && inst.worker_id != null
              ? `<button class="btn btn-ghost btn-sm" data-action="viewLogs" data-a1="${escapeHtml(svc.slug)}"${wid}>${t('app.logs')}</button>
               <button class="btn btn-primary btn-sm" data-action="redeployOnWorker" data-a1="${escapeHtml(svc.slug)}" data-a2="${escapeHtml(String(inst.worker_id))}">${t('app.redeploy')}</button>`
              : '',
          });
          continue;
        }
        items.push({
          level: st,
          tag: st === 'fail' ? t('app.attn.tag.down') : t('app.attn.tag.degraded'),
          what: svc.name,
          where,
          why: inst.container_name
            ? t('app.attn.container_is_named_html', { status: escapeHtml(inst.status || t('app.place.status_unknown')), name: escapeHtml(inst.container_name) })
            : t('app.attn.container_is', { status: escapeHtml(inst.status || t('app.place.status_unknown')) }),
          actions: controllable
            ? `<button class="btn btn-ghost btn-sm" data-action="viewLogs" data-a1="${escapeHtml(svc.slug)}"${wid}>${t('app.logs')}</button>
               <button class="btn btn-primary btn-sm" data-action="startService" data-a1="${escapeHtml(svc.slug)}"${wid}>${t('app.start')}</button>`
            : '',
        });
      }
      for (const inst of (svc.instance_details || [])) {
        const where = inst.node === 'local' ? t('app.attn.local') : (boxName[String(inst.worker_id)] || inst.node);
        for (const hint of (inst.hints || [])) {
          items.push({ level: 'fail', tag: t('app.attn.tag.needs_fixing'), what: svc.name, where, why: escapeHtml(hint) });
        }
      }
      if (svc.unstable === true) {
        items.push({ level: 'warn', tag: t('app.attn.tag.unstable'), what: svc.name, why: t('app.attn.crashes', { n: svc.crashes_7d || 0 }) });
      }
      if (svc.collector_disconnected) {
        items.push({
          level: 'warn', tag: t('app.attn.tag.no_reading'), what: svc.name,
          why: t('app.attn.no_reading'),
          actions: _isOwner ? `<button class="btn btn-ghost btn-sm" data-action="openCredentialModal" data-a1="${escapeHtml(svc.slug)}">${t('app.attn.fix_credentials')}</button>` : '',
        });
      }
      if (svc.image_outdated === true) {
        const outdatedWhy = svc.custom
          ? t('app.attn.outdated_custom')
          : t('app.attn.outdated');
        items.push({ level: 'warn', tag: t('app.attn.tag.outdated'), what: svc.name, why: outdatedWhy, actions: `<button class="btn btn-ghost btn-sm" data-action="openServiceDetail" data-a1="${escapeHtml(svc.slug)}">${t('app.open')}</button>` });
      }
      // A container made before a catalog fix (app/drift.py). One row per box:
      // a redeploy there rebuilds every copy on it.
      const driftByBox = new Map();
      for (const inst of (svc.instance_details || [])) {
        if (!(inst.drift || []).length || driftByBox.has(String(inst.worker_id))) continue;
        driftByBox.set(String(inst.worker_id), inst);
      }
      for (const inst of driftByBox.values()) {
        const where = inst.node === 'local' ? t('app.attn.local') : (boxName[String(inst.worker_id)] || inst.node);
        const what = inst.drift.map(d => escapeHtml(d)).join('; ');
        const fix = inst.drift_has_record
          ? t('app.attn.drift_fix')
          : t('app.attn.drift_no_record');
        // A fence-gated node still on the host's network (app/drift.py move_advice):
        // the one action for this worker's isolation mode first, then what to fix
        // before it, then the reasons.
        const move = inst.drift_move;
        const why = move
          ? `${escapeHtml(move.action)}${move.warning ? ` ${escapeHtml(move.warning)}` : ''}${inst.drift_has_record ? '' : ` ${fix}`}${inst.drift.map(d => `<br>· ${escapeHtml(d)}`).join('')}`
          : t('app.attn.drift', { what, fix });
        let actions = '';
        if (_isOwner && !inst.unmanaged) {
          actions = inst.drift_has_record && inst.worker_id != null && !(move && move.redeploy === false)
            ? `<button class="btn btn-primary btn-sm" data-action="redeployOnWorker" data-a1="${escapeHtml(svc.slug)}" data-a2="${escapeHtml(String(inst.worker_id))}">${t('app.redeploy')}</button>`
            : `<button class="btn btn-ghost btn-sm" data-action="openServiceDetail" data-a1="${escapeHtml(svc.slug)}">${t('app.open')}</button>`;
          if (inst.worker_id != null) {
            actions += `<button class="btn btn-ghost btn-sm" data-action="ignoreDrift" data-a1="${escapeHtml(svc.slug)}" data-a2="${escapeHtml(String(inst.worker_id))}">${t('app.attn.ignore')}</button>`;
          }
        }
        items.push({ level: 'fail', tag: t('app.attn.tag.needs_fixing'), what: svc.name, where, why, actions });
      }
    }

    // Deployments CashPilot records that no box runs (the server's "missing"
    // check, past its grace period). Forget drops only CashPilot's record, so it
    // is the way out when the container was removed on purpose.
    // A function, so the write below can swap in newer alerts the bell read.
    const alertsAt = items.length;
    function pushAlertRows(alerts) {
      for (const a of (alerts || [])) {
        // A proxied copy or its tunnel gone or down: the per-service rows
        // never list proxied copies, so without this the list says nothing is wrong.
        if (a.kind === 'proxied') {
          items.push({ level: 'fail', tag: t('app.attn.tag.proxied_down'), what: a.platform, why: escapeHtml(a.error), actions: `<a class="btn btn-ghost btn-sm" href="/fleet">${t('app.attn.open_fleet')}</a>` });
          continue;
        }
        // A box that reports in but cannot reach Docker: it looks online and manages nothing.
        // The message is cut at 200 characters, so the doc link is a button of its own.
        if (a.kind === 'docker') {
          items.push({ level: 'fail', tag: t('app.attn.tag.docker_lost'), what: a.platform, why: escapeHtml(a.error), actions: `<a class="btn btn-ghost btn-sm" href="/fleet">${t('app.attn.open_fleet')}</a> <a class="btn btn-ghost btn-sm" href="${DOCKER_LOST_DOC}" target="_blank" rel="noopener">${t('app.how_to_fix')}</a>` });
          continue;
        }
        // A running copy that carries almost no traffic: its own row says it runs, so only this says it idles.
        if (a.kind === 'stall') {
          items.push({ level: 'warn', tag: t('app.attn.tag.stall'), what: a.platform, why: escapeHtml(a.error) });
          continue;
        }
        if (a.kind !== 'missing') continue;
        const svc = services.find(s => s.slug === a.platform);
        let actions = '';
        if (_canWrite) {
          const targets = a.everywhere ? [{ worker_id: null, name: '' }] : (a.boxes || []);
          actions = targets.map(target => `<button class="btn btn-ghost btn-sm" data-action="forgetDeployment" data-a1="${escapeHtml(a.platform)}"${target.worker_id != null ? ` data-a2="${escapeHtml(String(target.worker_id))}"` : ''}>${target.name ? t('app.attn.forget_on', { name: escapeHtml(target.name) }) : t('app.attn.forget')}</button>`).join(' ');
        }
        items.push({ level: 'fail', tag: a.everywhere === false ? t('app.attn.tag.gone_from_box') : a.everywhere ? t('app.attn.tag.runs_nowhere') : t('app.attn.tag.missing'), what: a.name || (svc && svc.name) || a.platform, why: escapeHtml(a.error), actions });
      }
    }
    try {
      // The bell poll passes the alerts it just read, so its redraw cannot fail on a second fetch.
      const read = knownAlerts ? _attentionLatestRead : ++_attentionReads;
      const bell = knownAlerts ? { alerts: knownAlerts } : await api('/api/collector-alerts');
      alertsUsed = attentionAlertsKey(bell.alerts);
      alertsRead = read;
      pushAlertRows(bell.alerts);
    } catch (err) {
      console.warn('Could not load the missing-deployment alerts:', err);
      items.push({ level: 'warn', tag: t('app.attn.tag.unknown'), what: t('app.attn.deployments'), why: t('app.attn.no_missing_check') });
    }
    const alertsEnd = items.length;

    if (_isOwner) {
      let health = [];
      try {
        health = await api('/api/credentials/health');
      } catch (err) {
        console.warn('Could not load credential health:', err);
        items.push({ level: 'warn', tag: t('app.attn.tag.unknown'), what: t('app.attn.credentials'), why: t('app.attn.no_cred_check') });
      }
      for (const row of (Array.isArray(health) ? health : [])) {
        if (row.status !== 'expiring_soon' && row.status !== 'likely_expired') continue;
        if (items.some(i => i.tag === t('app.attn.tag.no_reading') && String(i.what).toLowerCase() === String(row.service).toLowerCase())) continue;
        // The credential is fine; the provider disabled the account.
        if (services.some(s => s.account_disabled && s.slug === row.service)) continue;
        items.push({
          level: 'warn', tag: row.status === 'likely_expired' ? t('app.attn.tag.expired') : t('app.attn.tag.expiring'),
          what: row.name || row.service,
          why: row.status === 'likely_expired' ? t('app.attn.cred_expired') : t('app.attn.cred_expiring'),
          actions: `<button class="btn btn-ghost btn-sm" data-action="openCredentialModal" data-a1="${escapeHtml(row.service)}">${t('app.attn.renew')}</button>`,
        });
      }
    }

    if (draw !== undefined && draw !== _attentionDrawSeq) return;
    if (seq !== undefined) {
      if (seq !== _attentionSeq) return;
      _attentionDrawSeq++;
    }
    // The bell read newer alerts while this draw waited (or this draw could not
    // read them): write those with this draw's services, so the list never goes
    // back to older alerts, not even until a second draw answers.
    if (_attentionLatestAlerts && _attentionLatestRead > (alertsRead || 0)) {
      const rest = items.splice(alertsAt).slice(alertsEnd - alertsAt);
      pushAlertRows(_attentionLatestAlerts);
      items.push(...rest);
      alertsUsed = attentionAlertsKey(_attentionLatestAlerts);
      alertsRead = _attentionLatestRead;
    }
    _attentionDrawnKey = alertsUsed;
    _attentionDrawnRead = alertsRead || 0;
    const order = { fail: 0, warn: 1, unknown: 2 };
    items.sort((a, b) => order[a.level] - order[b.level]);
    list.innerHTML = items.map(i => `
      <div class="attn-row attn-${i.level}">
        <span class="attn-tag">${escapeHtml(i.tag)}</span>
        <span class="attn-what">${escapeHtml(i.what)}${i.where ? ` <span class="attn-where">${escapeHtml(i.where)}</span>` : ''}</span>
        <span class="attn-why">${i.why}</span>
        <span class="attn-actions">${i.actions || ''}</span>
      </div>`).join('');
    // A phone that cannot see an app is shown, in grey, but it is not a
    // problem to count: nothing is known to be wrong.
    _attentionCount.problems = items.filter(i => i.level !== 'unknown').length;
    updateAttentionSummary(services, workers);
  }

  // The copies "Stop on all servers" would act on: CashPilot's own containers
  // that are not already stopped.
  function stoppableCopies(svc) {
    return (svc.instance_details || []).filter(inst => inst.can_command && !inst.unmanaged && !inst.is_android
      && inst.worker_id != null && !['exited', 'stopped', 'dead'].includes(String(inst.status || '').toLowerCase()));
  }

  function accountDisabledItem(svc) {
    const name = escapeHtml(svc.name);
    let actions = '';
    if (_canWrite && !svc.unmanaged && stoppableCopies(svc).length) {
      actions += `<button class="btn btn-ghost btn-sm" data-action="stopEverywhere" data-a1="${escapeHtml(svc.slug)}">${t('app.attn.stop_everywhere')}</button>`;
    }
    if (/^https:\/\//.test(String(svc.support_url || ''))) {
      actions += ` <a class="btn btn-ghost btn-sm" href="${escapeHtml(svc.support_url)}" target="_blank" rel="noopener noreferrer">${t('app.attn.contact', { name })}</a>`;
    }
    // The Services table keeps showing the last balance read, so say that
    // figure here too: "no balance can be read" next to "$7.62" read as a
    // contradiction.
    const known = svc.balance_known !== false && svc.balance != null;
    return {
      level: 'fail', tag: t('app.attn.tag.account_disabled'), what: t('app.attn.disabled_by', { name: svc.name }),
      why: known
        ? t('app.attn.disabled_why_balance', { name, amount: escapeHtml(formatCurrency(svc.balance, svc.currency || 'USD')) })
        : t('app.attn.disabled_why', { name }),
      actions,
    };
  }

  const _attentionCount = { problems: 0, payouts: 0, payoutsUnknown: false, services: null, workers: null };

  function updateAttentionSummary(services, workers) {
    if (services) { _attentionCount.services = services; _attentionCount.workers = workers; }
    services = _attentionCount.services;
    workers = _attentionCount.workers;
    const total = _attentionCount.problems + _attentionCount.payouts;
    const count = document.getElementById('attention-count');
    if (count) count.textContent = total ? String(total) : '';
    const clear = document.getElementById('attention-clear');
    const section = document.getElementById('attention');
    if (section) section.classList.toggle('attention-quiet', total === 0);
    if (!clear) return;
    if (total) { clear.hidden = true; return; }
    const online = (workers || []).filter(w => w.status === 'online').length;
    clear.textContent = _attentionCount.payoutsUnknown
      ? t('app.attn.no_payout_check')
      : services
      ? t('app.attn.clear_boxes', { online, total: (workers || []).length })
      : t('app.attn.clear');
    clear.hidden = false;
  }

  // The attention list and the bell read the same alerts, but the list is
  // drawn only when the services refresh. When the alerts it shows (missing,
  // proxied, docker) differ from the ones the list was drawn with, draw it
  // again, or it can say nothing needs you while the bell reports a failure.
  // The latest bell poll and the drawn list are tracked apart: a poll that
  // lands while a services response is on its way is drawn once that response
  // commits (renderAttention), not lost because it was the first poll.
  // Every alert read, the bell's and the services draw's, is numbered when it
  // is sent, so the newer of two reads wins whichever answers first.
  let _attentionReads = 0;
  let _attentionLatestAlerts = null;
  let _attentionLatestRead = 0;
  let _attentionDrawnKey = null;
  let _attentionDrawnRead = 0;
  // Bell redraws have their own generation, so a redraw never discards a
  // services response still in flight (renderAttention): the newest services
  // response commits, and only it or a newer redraw ends a redraw.
  let _attentionDrawSeq = 0;
  function attentionAlertsKey(alerts) {
    return JSON.stringify((alerts || [])
      .filter(a => a.kind === 'missing' || a.kind === 'stall' || a.kind === 'proxied' || a.kind === 'docker')
      .map(a => [a.kind, a.platform, a.error]));
  }
  function refreshAttentionOnAlertChange(alerts, read = ++_attentionReads) {
    // A poll sent before the alerts the list or the bell already has: older news.
    if (read < _attentionLatestRead || read < _attentionDrawnRead) return null;
    _attentionLatestAlerts = (alerts || []).slice();
    _attentionLatestRead = read;
    if (attentionAlertsKey(alerts) === _attentionDrawnKey) {
      // The list already shows these: a redraw still in flight has older alerts.
      _attentionDrawSeq++;
      return null;
    }
    if (!_attentionCount.services || !document.getElementById('attention-list')) return null;
    // Its own generation: two redraws can be in flight at once, and only the
    // newest may write. A services response in flight still commits.
    return renderAttention(_attentionCount.services, _attentionCount.workers, undefined, alerts.slice(), ++_attentionDrawSeq);
  }

  // Action-button icons, extracted so the single-instance row and the per-node sub-row
  // share one copy each (cyc componentization). Byte-identical to the inline SVGs replaced.
  const ICON_RESTART = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/></svg>';
  const ICON_STOP = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>';
  const ICON_LOGS = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>';

  // -------------------------------------------------------------------------
  // Shared fragment builders (CashPilot-cyc)
  //
  // These markup blocks were written out three and two times respectively, and
  // had already drifted: one env-input copy omitted the label's `for` and the
  // hint, and the two worker lists differed only in a class name. Duplicated
  // markup does not stay identical — it stays ALMOST identical, which is worse,
  // because a fix applied to one copy silently misses the others.
  // -------------------------------------------------------------------------

  function envInputFields(svc, envs, { withId = true, withHint = true } = {}) {
    return (envs || []).map((env) => {
      // Never a text box: the seed goes to the node, not into CashPilot.
      if (env.seed_file) return walletSeedField(svc, env);
      const inputType = env.secret ? 'password' : 'text';
      const id = withId ? `env-${svc.slug}-${env.key}` : '';
      const label = withId
        ? `<label class="form-label" for="${id}">${escapeHtml(env.label)}</label>`
        : `<label class="form-label">${escapeHtml(env.label)}</label>`;
      const hint = withHint && env.description
        ? `<div class="form-hint">${escapeHtml(env.description)}</div>`
        : '';
      // A default containing {hostname} is a TEMPLATE, not a value. Prefilling
      // it put the literal text in the box, and the browser posted it straight
      // back as a user override — which outranks the default the server would
      // have substituted. Showing it as the placeholder keeps the hint visible
      // while leaving the field genuinely empty, so the server fills it in per
      // worker and each host registers under its own name.
      const defaultIsTemplate = String(env.default || '').includes('{hostname}');
      const minerDefault = svc.mining && env.default && !env.secret && !isIdentityField(env);
      const showPlaceholder = defaultIsTemplate || minerDefault;
      return `
      <div class="form-group">
        ${label}${identityPickButton(svc, env)}
        <input class="form-input" type="${inputType}"${withId ? ` id="${id}"` : ''}
               data-slug="${svc.slug}" data-key="${env.key}"
               placeholder="${escapeHtml(showPlaceholder ? String(env.default) : (env.description || ''))}"
               value="${escapeHtml(showPlaceholder ? '' : (env.default || ''))}"
               ${env.secret ? 'autocomplete="new-password"' : ''}
               ${env.pattern ? `pattern="${escapeHtml(env.pattern)}"` : ''}
               ${env.required && !minerDefault ? 'required' : ''}>
        ${hint}${isIdentityField(env) && _isOwner ? `<div class="identity-pick" data-pick-slug="${escapeHtml(svc.slug)}" data-pick-key="${escapeHtml(env.key)}"></div>` : ''}
      </div>`;
    }).join('');
  }

  // A field whose value names the device to the provider (catalog per_device or
  // identifier). CashPilot keeps these after a removal, in Settings > Device ids.
  function isIdentityField(env) {
    return !!env && !env.secret && (env.per_device === true || env.identifier === true);
  }

  // Owner only: the ids are read through owner-only routes, so nobody else gets the button.
  function identityPickButton(svc, env) {
    if (!_isOwner || !isIdentityField(env)) return '';
    return ` <button type="button" class="btn btn-link btn-sm" data-action="pickPreviousIdentity"
      data-a1="${escapeHtml(svc.slug)}" data-a2="${escapeHtml(env.key)}">${t('app.dep.pick_identity')}</button>`;
  }

  // The class is a parameter rather than unified, deliberately: the setup wizard
  // and the detail view can both be in the DOM at once, and their deploy
  // handlers select by class. One shared class would make each pick up the
  // other's checkboxes.
  // One rule for "this box runs it", shared by the wizard's node list and the
  // catalog's Add link, so the two cannot disagree.
  function runsOn(worker, slug) {
    return workerCopies(worker, slug).length > 0;
  }

  // The copies of a service on one box: its containers, and a service routed
  // through a proxy from its deploy, which runs only as a proxied copy and so
  // is reported apart (app/route_gate.py). That copy carries its route.
  function workerCopies(worker, slug) {
    const copies = (worker.containers || []).filter((c) => c.slug === slug);
    const proxied = (worker.system_info || {}).proxied;
    for (const e of Array.isArray(proxied) ? proxied : []) {
      if (e && e.routed === true && e.slug === slug) {
        copies.push({
          slug, status: e.status || 'unknown', instance: 1,
          route: { proxy_id: e.proxy_id, exit_ip: e.exit_ip, exit_country: e.exit_country },
        });
      }
    }
    return copies;
  }

  // "via proxy 203.0.113.9 (DE)" for a routed copy; empty for a direct one.
  function routeBadge(container) {
    const r = container && container.route;
    if (!r) return '';
    const where = [r.exit_ip, r.exit_country ? `(${r.exit_country})` : ''].filter(Boolean).join(' ');
    return `<span class="badge badge-routed" title="${t('app.route.badge_title')}">${where ? t('app.route.via_proxy_at', { where: escapeHtml(where) }) : t('app.route.via_proxy')}</span>`;
  }

  // The deploy form's Route box: the box's own IP, or one of the owner's
  // proxies. Filled once the proxy list arrives (owner only). A service the
  // catalog cannot route says why instead. Where it is recorded as routed
  // (svc.routes, what a deploy with no route keeps), the first choice keeps
  // that route and Direct is its own choice, which leaves the route with the
  // owner's password.
  function routeChoiceSection(svc) {
    const slug = escapeHtml(svc.slug);
    if (svc.route_refusal) {
      return `<div class="form-hint route-hint">${t('app.route.refused', { reason: escapeHtml(svc.route_refusal) })}</div>`;
    }
    const routed = Object.values(svc.routes || {}).some(Boolean);
    const choices = routed
      ? `<option value="">${t('app.route.keep')}</option>
          <option value="0">${t('app.route.direct')}</option>`
      : `<option value="">${t('app.route.direct')}</option>`;
    // What lowers its isolation behind a proxy: one checkbox each, shown once a
    // proxy is chosen. The server refuses the route without every one of them.
    const needs = svc.route_needs || [];
    const acks = needs.length ? `
        <div class="route-acks" data-slug="${slug}" style="display:none;">
          <div class="form-hint">${t('app.route.ack_title')}</div>
          ${needs.map((key) => `<label class="form-hint" style="display:block;"><input type="checkbox" data-route-ack="${escapeHtml(key)}"> ${escapeHtml(routeAckText(key))}</label>`).join('')}
        </div>` : '';
    return `
      <div class="form-group route-choice">
        <label class="form-label" for="route-select-${slug}">${t('app.route.label')}</label>
        <select class="form-input" id="route-select-${slug}" data-slug="${slug}">
          ${choices}
        </select>
        <div class="form-hint">${t('app.route.hint')}</div>
        ${svc.route_udp ? `<div class="form-hint">${t('app.route.udp_hint')}</div>` : ''}
        ${acks}
      </div>`;
  }

  function routeAckText(key) {
    return {
      net_admin: t('app.route.ack.net_admin'),
      net_raw: t('app.route.ack.net_raw'),
      tun_device: t('app.route.ack.tun_device'),
      no_inbound: t('app.route.ack.no_inbound'),
    }[key] || key;
  }

  // The acknowledgements ticked in ``slug``'s Route box, sent with a route to a proxy.
  function _routeAcks(root, slug) {
    const select = _routeSelect(root, slug);
    const box = select && select.closest('.route-choice');
    return box ? [...box.querySelectorAll('input[data-route-ack]:checked')].map((el) => el.dataset.routeAck) : [];
  }

  // The Route box of ``slug`` inside ``root``, the form that owns it. The setup
  // wizard and the service page both render one for the same service, and the
  // wizard's stays in the DOM when it is hidden, so a document-wide lookup by
  // id can return the other form's box.
  function _routeSelect(root, slug) {
    return (root && root.querySelector(`select[id="route-select-${slug}"]`)) || null;
  }

  async function loadRouteChoices(slug, root) {
    const select = _routeSelect(root, slug);
    if (!select || !_isOwner) return;
    select.addEventListener('change', () => _routeSwitchBoxes(select));
    try {
      const data = await api('/api/proxies');
      for (const p of (data && data.proxies) || []) {
        const opt = document.createElement('option');
        opt.value = String(p.id);
        const exit = [p.last_exit_ip, p.last_country ? `(${p.last_country})` : ''].filter(Boolean).join(' ');
        const pname = p.name || t('app.route.proxy_n', { id: p.id });
        opt.textContent = exit ? t('app.route.through_exit', { name: pname, exit }) : t('app.route.through', { name: pname });
        select.appendChild(opt);
      }
    } catch (err) {
      select.title = t('app.route.load_failed', { error: err.message });
    }
  }

  // A box where the service already runs routed is ticked and locked, as any
  // deployed box: a plain redeploy keeps its route. Choosing Direct unlocks it,
  // unticked, so it can leave the route by ticking it; anything else locks it
  // again. Another proxy keeps it locked: the server refuses moving a route to
  // another proxy (main._check_route), so the owner removes it first.
  function _routeSwitchBoxes(select) {
    const scope = (select.closest && select.closest('.route-choice') || {}).parentElement || document;
    const switching = select.value === '0';
    const acks = select.closest && select.closest('.route-choice') && select.closest('.route-choice').querySelector('.route-acks');
    if (acks) acks.style.display = parseInt(select.value, 10) > 0 ? '' : 'none';
    for (const cb of scope.querySelectorAll(`input[data-routed="1"][data-slug="${select.dataset.slug}"]`)) {
      cb.disabled = !switching;
      cb.checked = !switching;
    }
  }

  // The proxy id to send as "route", 0 for Direct chosen to leave a route, or
  // undefined: the server then keeps the route a box already has, and a new
  // deploy runs from the box's own IP.
  function _routeChoice(root, slug) {
    const select = _routeSelect(root, slug);
    if (select && select.value === '0') return 0;
    const id = select ? parseInt(select.value, 10) : NaN;
    return Number.isInteger(id) && id > 0 ? id : undefined;
  }

  // A joined Desktop that takes commands reports a URL too, so it is a deploy target.
  // One without a URL only reports what runs on it.
  function onlineDeployWorkers(workers) {
    return (workers || []).filter(w => w.status === 'online' && w.url);
  }

  function isDesktopWorker(w) {
    return ((w && w.system_info) || {}).device_type === 'desktop';
  }

  function workerCheckboxList(svc, onlineWorkers, checkboxClass) {
    let rows = '';
    let allDeployed = true;
    // The Instances box appears only where the service detail said how many
    // copies one worker may run (the setup wizard's list has no such answer).
    const maxInstances = svc.max_instances;
    // A single box is the only choice, so it starts ticked: Deploy works on the first click.
    const onlyChoice = onlineWorkers.length === 1;
    for (const w of onlineWorkers) {
      const copies = workerCopies(w, svc.slug).length;
      const deployed = copies > 0;
      const proxiedOnly = (w.system_info || {}).proxied_only === true;
      // It can still leave its route here (_routeSwitchBoxes), so the form stays.
      const routed = deployed && Boolean((svc.routes || {})[w.id]);
      if (!deployed || routed) allDeployed = false;
      let instancesBox = '';
      if (maxInstances) {
        const capable = ((w.system_info || {}).features || []).includes('instances');
        const locked = maxInstances <= 1 || !capable;
        const why = maxInstances <= 1 ? ''
          : (isDesktopWorker(w) ? ` title="${t('app.dep.desktop_one_copy')}"`
            : (capable ? '' : ` title="${t('app.dep.update_for_copies')}"`));
        instancesBox = `
        <span class="instances-box"${why}>${t('app.dep.instances')}
          <input class="form-input instances-input" type="number" min="1" max="${maxInstances}" step="1"
                 data-slug="${escapeHtml(svc.slug)}" data-wid="${w.id}" data-current="${copies}" value="${copies || 1}"${locked ? ' disabled' : ''}>
        </span>`;
      }
      rows += `
      <label class="worker-pick">
        <input type="checkbox" class="${checkboxClass}" data-slug="${svc.slug}" data-wid="${w.id}"${routed ? ' data-routed="1"' : ''} ${deployed ? 'disabled checked' : (onlyChoice ? 'checked' : '')}>
        <span class="worker-pick-name${deployed ? ' is-deployed' : ''}">${escapeHtml(w.name)}</span>
        ${isDesktopWorker(w) ? `<span class="badge" title="${t('app.dep.desktop_title')}">Desktop</span>` : ''}
        ${proxiedOnly ? `<span class="badge" title="${t('app.dep.proxy_only_title')}">${t('app.dep.proxy_only')}</span>` : ''}
        ${deployed
          ? `<span class="badge badge-deployed">${t('app.dep.deployed')}</span>`
          : `<span class="badge badge-available">${t('app.dep.available')}</span>`}
        ${instancesBox}
      </label>`;
    }
    return { rows, allDeployed };
  }

  // What the Instances boxes mean for this provider, under the node list.
  function instancesHint(svc) {
    if (!svc.max_instances) return '';
    const name = escapeHtml(svc.name);
    if (svc.max_instances <= 1) {
      return svc.max_instances_reason
        ? `<div class="form-hint instances-hint">${t('app.dep.instances_capped', { reason: escapeHtml(svc.max_instances_reason) })}</div>`
        : '';
    }
    const perIp = (svc.requirements || {}).devices_per_ip;
    if (perIp === 0) {
      return `<div class="form-hint instances-hint">${t('app.dep.instances_per_ip_html', { name })}</div>`;
    }
    return `<div class="form-hint instances-hint">${t('app.dep.instances_unknown', { name })}</div>`;
  }

  // Workers whose Instances box was changed. A deployed worker cannot be
  // ticked again, so a changed count is how it joins a deploy.
  function _rescaledWorkerIds(slug) {
    return Array.from(document.querySelectorAll(`.instances-input[data-slug="${slug}"]:not(:disabled)`))
      .filter((input) => Number(input.dataset.current) > 0 && Number(input.value) !== Number(input.dataset.current))
      .map((input) => parseInt(input.dataset.wid))
      .filter((id) => !Number.isNaN(id));
  }

  function _instancesFor(slug, wid) {
    const input = document.querySelector(`.instances-input[data-slug="${slug}"][data-wid="${wid}"]`);
    if (!input || input.disabled) return undefined;
    const n = parseInt(input.value);
    return Number.isNaN(n) ? undefined : n;
  }

  function renderServiceRow(svc, bk) {
    const isExternal = svc.container_status === 'external';
    const statusClass = isExternal ? 'external' : (svc.container_status || 'stopped').toLowerCase();
    const statusLabel = isExternal ? t('app.status.external') : statusLabelOf(statusClass);
    const instances = svc.instances || 0;
    const details = svc.instance_details || [];
    const isMulti = details.length > 1;

    // Service name — linked to the provider dashboard, or the website when the catalog has none.
    // Every row here is deployed or marked external, so its user nearly always has an account;
    // one who deployed first (MystNodes) still finds Sign Up in the service's detail dialog.
    const name = escapeHtml(svc.name);
    const dashUrl = (svc.cashout && svc.cashout.dashboard_url) || svc.website || '';
    const nameLink = dashUrl;
    const nameTitle = t('app.row.open_dashboard');
    const nameHtml = nameLink
      ? `<a href="${escapeHtml(nameLink)}" target="_blank" rel="noopener" title="${nameTitle}" class="svc-name">${name}</a>`
      : `<span class="svc-name">${name}</span>`;

    // Subtitle: image for Docker, empty for external
    const subtitle = svc.image
      ? brk(svc.image)
      : (isExternal ? t('app.row.app_browser') : '');

    // Health badge — external services always show a muted dash
    let healthBadge = '<span class="muted">&mdash;</span>';
    if (!isExternal && svc.health_score !== null && svc.health_score !== undefined) {
      const score = svc.health_score;
      const crashes = svc.crashes_7d || 0;
      const restarts = svc.restarts_7d || 0;
      const unstable = svc.unstable === true;
      // Unstable (repeated crashes in the 7-day window) takes the worst tone + an explicit
      // label so a crash-looping service is legible at a glance, not just via a low number.
      const hClass = (unstable || score < 50) ? 'badge-stopped' : score >= 80 ? 'badge-running' : 'badge-error';
      const title = (svc.uptime_pct !== null && svc.uptime_pct !== undefined)
        ? t('app.row.health_title_uptime', { score, uptime: svc.uptime_pct, restarts, crashes })
        : t('app.row.health_title', { score, restarts, crashes });
      const label = unstable ? t('app.row.unstable', { crashes }) : String(score);
      healthBadge = `<span class="badge ${hClass}" title="${title}">${label}</span>`;
    }

    // Balance + delta from breakdown
    // `|| 0` would defeat the whole fix: it coerces a null balance — which now
    // explicitly means "never read" — straight back into a confident zero.
    const balanceKnown = (bk ? bk.balance != null : null) ?? svc.balance_known ?? (svc.balance != null);
    const balance = (bk && bk.balance != null ? bk.balance : svc.balance) ?? 0;
    const signupBonus = (bk && bk.signup_bonus) || 0;
    const balanceAdj = signupBonus > 0 ? ((bk && bk.balance_adjusted) ?? Math.max(0, balance - signupBonus)) : balance;
    const currency = (bk && bk.currency) || svc.currency || 'USD';
    const delta = bk ? bk.delta : 0;
    const deltaSign = delta > 0 ? '+' : '';
    // Money deltas are deliberately uncoloured: colour on this page means state
    // (ok / warn / fail) only, so a rise or dip carries just its sign.
    const deltaStr = delta !== 0 ? `${deltaSign}${formatCurrency(delta, currency)}` : '<span class="muted">&mdash;</span>';
    const displayBalance = signupBonus > 0 ? balanceAdj : balance;
    const nativeLabel = formatNative(displayBalance, currency);
    const bonusLabel = signupBonus > 0
      ? `<div class="cell-sub">${t('app.row.promo', { amount: `\u2212${formatCurrency(signupBonus, currency)}` })}</div>`
      : '';
    // Image drift: the running container no longer matches the catalog image
    // (provider migrated or re-pinned). Prompt a re-deploy — otherwise a retired
    // image keeps looking healthy while it silently stops earning.
    const outdatedBadge = svc.image_outdated === true
      ? (svc.custom
        ? ` <span class="badge badge-stopped" title="${t('app.row.outdated_custom_title')}">${t('app.row.update_available')}</span>`
        : ` <span class="badge badge-stopped" title="${t('app.row.outdated_title')}">${t('app.row.update_available')}</span>`)
      : '';
    // A service the user added from an image reference: not reviewed, no collector.
    const customLabel = svc.custom
      ? ` <span class="badge badge-category" title="${CUSTOM_SERVICE_TITLE}">${t('app.row.custom')}</span>`
      : '';

    // Earnings-collector state. "disconnected" = collector ran and failed
    // (e.g. wrong credentials). "needs setup" = the service is deployed and
    // earning, but its (separate) earnings-tracking credentials aren't set yet.
    let disconnectedLabel = '';
    if (svc.account_disabled) {
      disconnectedLabel = `<div title="${t('app.row.disabled_title', { name: escapeHtml(svc.name) })}" class="cell-sub cell-sub-warn">${t('app.row.account_disabled')}</div>`;
    } else if (svc.collector_disconnected) {
      disconnectedLabel = `<div title="${t('app.row.no_reading_title')}" class="cell-sub cell-sub-warn">${t('app.row.no_reading')}${_isOwner ? ` <button class="btn btn-link" data-action="openCredentialModal" data-stop="1" data-a1="${escapeHtml(svc.slug)}">${t('app.row.fix')}</button>` : ''}</div>`;
    } else if (svc.collector_notice) {
      disconnectedLabel = `<div title="${escapeHtml(svc.collector_notice)}" class="cell-sub">${t('app.row.see_note')}</div>`;
    } else if (svc.collector_needs_setup) {
      disconnectedLabel = `<div title="${t('app.row.not_tracked_title')}" class="cell-sub">${t('app.row.not_tracked')}${_isOwner ? ` <button class="btn btn-link" data-action="openCredentialModal" data-stop="1" data-a1="${escapeHtml(svc.slug)}">${t('app.row.set_up')}</button>` : ''}</div>`;
    }
    let balanceHtml;
    if (!balanceKnown) {
      // Never read. An em dash, not a number — the user must be able to tell
      // "nothing has looked at this" from "this earned nothing".
      const why = svc.custom
        ? t('app.row.custom_no_balance')
        : t('app.row.never_read');
      balanceHtml = `<span class="muted" title="${why}">&mdash;</span>${disconnectedLabel}`;
    } else if (nativeLabel && formatCurrency(displayBalance, currency).includes(currency)) {
      // No price for this unit, so the "converted" figure already IS the
      // native one. Printing it twice read as two different numbers.
      balanceHtml = `${formatCurrency(displayBalance, currency)}<div class="cell-sub">${t('app.row.no_price')}</div>${bonusLabel}${disconnectedLabel}`;
    } else if (nativeLabel) {
      balanceHtml = `${formatCurrency(displayBalance, currency)}<div class="cell-sub">${nativeLabel}</div>${bonusLabel}${disconnectedLabel}`;
    } else {
      balanceHtml = `${formatCurrency(displayBalance, currency)}${bonusLabel}${disconnectedLabel}`;
    }

    // CPU/Memory — skip for external; show avg for multi-instance
    let cpuStr, memStr;
    if (isExternal) {
      cpuStr = '<span class="muted">&mdash;</span>';
      memStr = '<span class="muted">&mdash;</span>';
    } else if (svc.cpu == null || svc.memory == null) {
      // Nothing could be measured: every instance's Docker stats call failed.
      // `|| '0'` used to render that as a confident 0%, which reads as idle for
      // a container that may be working hard (CashPilot-zdi).
      const why = t('app.row.no_stats');
      cpuStr = `<span title="${why}">—</span>`;
      memStr = `<span title="${why}">—</span>`;
    } else if (isMulti && instances > 0) {
      // Averaged over the instances that WERE measured. Dividing by the full
      // instance count when some failed would drag the average toward zero for
      // the same reason.
      const measured = Math.max(1, instances - (svc.stats_unknown || 0));
      const avgCpu = (parseFloat(svc.cpu) / measured).toFixed(2);
      const avgMem = (parseFloat(svc.memory) / measured).toFixed(1);
      const avgTitle = (svc.stats_unknown || 0) > 0
        ? t('app.row.avg_title_unmeasured', { n: measured, m: svc.stats_unknown })
        : t('app.row.avg_title', { n: measured });
      cpuStr = `<span title="${avgTitle}">~${avgCpu}%</span>`;
      memStr = `<span title="${avgTitle}">~${avgMem} MB</span>`;
    } else {
      cpuStr = `${svc.cpu}%`;
      memStr = svc.memory;
    }

    // Payout progress
    const co = cashoutFor(svc, bk);
    // The minimum in the SAME unit as the balance beside it. co.min_amount is
    // whatever the provider declared — STORJ for a Storj balance recorded in USD
    // — so comparing against it directly rated a $3.50 balance as 87% of the way
    // to "4", and the tooltip printed 4 STORJ as "$4.00". null means the two
    // units cannot be reconciled right now, and no bar is better than a wrong one.
    // `?? 0` here would defeat the endpoint's own three-valued answer: null
    // means the threshold could not be brought into the balance's unit, and
    // coercing it to zero rates EVERY positive balance as eligible — the exact
    // "unknown read as a definite yes" this whole change exists to remove.
    const minAmount = co.min_amount_comparable;
    const comparable = typeof minAmount === 'number';
    // Eligibility is the endpoint's to decide; it is the only side that knows
    // whether a rate was available. Recomputing it here is what let the two
    // disagree.
    const eligible = co.eligible === true;
    const pctToMin = comparable && minAmount > 0 ? Math.min(100, (balance / minAmount) * 100) : 0;
    const progressBar = comparable && minAmount > 0 ? `
      <div class="payout-progress" title="${formatCurrency(balance, currency)} / ${formatCurrency(minAmount, currency)}">
        <div class="payout-progress-bar ${eligible ? 'eligible' : ''}" style="width:${pctToMin.toFixed(0)}%"></div>
      </div>
      <span class="payout-label">${pctToMin.toFixed(0)}%</span>
    ` : '<span class="muted">&mdash;</span>';

    // Payout (claim) button — always visible in main row
    const claimTitle = co.dashboard_url
      ? (eligible ? t('app.row.cash_out') : t('app.row.payout_details'))
      : t('app.row.no_payout_info');
    const claimDisabled = !co.dashboard_url;
    const claimBtn = `<button class="btn btn-icon ${eligible ? 'btn-success' : ''}" data-action="openClaimModal" data-a1="${escapeHtml(svc.slug)}" title="${claimTitle}"${claimDisabled ? ' disabled' : ''}>
           <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/></svg>
         </button>`;

    // A row whose instances are not all up says so. The server reports the
    // BEST status per service, so "Running 2x" used to hide a dead copy.
    const downCount = details.filter(d => instanceState(d.status) !== 'ok').length;
    const partialDown = !isExternal && isMulti && downCount > 0 && downCount < details.length;

    // Instance badge (shown next to status)
    const instanceLabel = !isExternal && instances > 0
      ? ` <span class="badge badge-instances" title="${t('app.row.instances', { n: instances })}">${instances}x</span>`
      : '';

    // Say why the buttons are dead rather than leaving the user to click one.
    const unmanagedLabel = svc.unmanaged
      ? ` <span class="badge badge-category" title="${t('app.row.unmanaged_title')}">${t('app.row.unmanaged')}</span>`
      : '';

    // Settings gear (owner-only) — opens credential + bonus modal
    const settingsBtn = _isOwner && !svc.custom
      ? `<button class="btn btn-icon" data-action="openCredentialModal" data-stop="1" data-a1="${escapeHtml(svc.slug)}" title="${t('app.row.settings')}">
           <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg>
         </button>` : '';

    // For multi-instance: expand chevron, no container action buttons in main row
    // For single instance: show action buttons directly
    let actionBtns;
    if (isMulti) {
      const chevron = `<button class="btn btn-icon expand-toggle" data-action="toggleInstances" data-stop="1" data-a1="${escapeHtml(svc.slug)}" title="${t('app.row.expand')}">
        <svg class="expand-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
      </button>`;
      actionBtns = `<div class="action-btns">${claimBtn}${settingsBtn}${chevron}</div>`;
    } else if (isExternal) {
      actionBtns = `<div class="action-btns">${claimBtn}${settingsBtn}</div>`;
    } else {
      // Single instance — build container buttons targeting the right node
      const inst = details[0] || {};
      const wParam = inst.worker_id != null ? ` data-a2="${inst.worker_id}"` : '';
      const noDocker = !inst.can_command || inst.is_android;
      // Started outside CashPilot — matched by IMAGE, not by a CashPilot label,
      // so every container command targets a name that does not exist and
      // answers "404 Container not found" for a row this same screen calls
      // Running. Offering the button at all is the bug; the disabled title says
      // why rather than leaving it looking broken.
      const unmanaged = inst.unmanaged || svc.unmanaged;
      const disabledAttr = unmanaged
        ? ` disabled title="${t('app.row.outside_title')}"`
        : (noDocker ? (inst.desktop_report_only ? ` disabled title="${t('app.row.report_only_title')}"` : t('app.row.no_docker_attr_html')) : '');
      actionBtns = `<div class="action-btns">
          ${claimBtn}
          ${settingsBtn}
          ${_canWrite ? `
          <button class="btn btn-icon" data-action="restartService" data-a1="${escapeHtml(svc.slug)}"${wParam}${disabledAttr} title="${t('app.row.restart')}">
            ${ICON_RESTART}
          </button>
          <button class="btn btn-icon" data-action="stopService" data-a1="${escapeHtml(svc.slug)}"${wParam}${disabledAttr} title="${t('app.row.stop')}">
            ${ICON_STOP}
          </button>
          <button class="btn btn-icon" data-action="viewLogs" data-a1="${escapeHtml(svc.slug)}"${wParam}${disabledAttr} title="${t('app.logs')}">
            ${ICON_LOGS}
          </button>` : ''}
        </div>`;
    }

    // Main row
    let html = `
    <tr class="breakdown-row${isMulti ? ' expandable' : ''}" data-slug="${escapeHtml(svc.slug)}"${isMulti ? ` data-action="toggleInstances" data-a1="${escapeHtml(svc.slug)}" data-a2="event"` : ''}>
      <td class="c-name">${nameHtml}<div class="cell-sub cell-mono c-name-image">${subtitle}</div></td>
      <td class="c-status">${partialDown
        ? `<span class="badge badge-stopped" title="${t('app.row.down_title', { down: downCount, total: details.length })}"><span class="status-dot stopped"></span> ${t('app.row.n_up', { up: details.length - downCount, total: details.length })}</span>`
        : `<span class="badge badge-${statusClass}"><span class="status-dot ${statusClass}"></span> ${statusLabel}</span>${instanceLabel}`}${unmanagedLabel}${customLabel}${outdatedBadge}${!isMulti && details[0] ? ` ${routeBadge(details[0])}` : ''}</td>
      <td class="c-health c-num" data-label="${t('app.label.health')}">${healthBadge}</td>
      <td class="c-bal c-num">${balanceHtml}</td>
      <td class="c-chg c-num"><span class="delta">${deltaStr}</span></td>
      <td class="c-cpu c-num" data-label="${t('app.label.cpu')}">${cpuStr}</td>
      <td class="c-mem c-num" data-label="${t('app.label.memory')}">${memStr}</td>
      <td class="c-disk c-num" data-label="${t('app.label.host_disk')}">${diskCell(svc)}</td>
      <td class="c-gpu" data-label="${t('app.label.gpu')}">${gpuCell(svc)}</td>
      <td class="c-pay">${progressBar}</td>
      <td class="c-act">${actionBtns}</td>
    </tr>`;

    // Sub-rows for multi-instance (hidden by default)
    if (isMulti) {
      for (const inst of details) {
        const iStatus = (inst.status || 'unknown').toLowerCase();
        const iStatusLabel = statusLabelOf(iStatus);
        const copyLabel = (inst.instance || 1) > 1 || details.some(d => d !== inst && d.worker_id === inst.worker_id)
          ? ` #${inst.instance || 1}` : '';
        const nodeLabel = (inst.node === 'local' ? t('app.row.local') : escapeHtml(inst.node)) + copyLabel;
        const wParam = inst.worker_id != null
          ? ` data-a2="${inst.worker_id}"${(inst.instance || 1) > 1 ? ` data-a3="${inst.instance}"` : ''}`
          : '';
        const iNoDocker = !inst.can_command || inst.is_android;
        // The mixed case this whole change is built around. The ROW keeps its
        // buttons because a managed instance can still be controlled — but the
        // external instance in that same row cannot, and its sub-row was still
        // offering Restart/Stop/Logs that answer 404. The per-instance flag has
        // to be READ here; marking it in the payload and ignoring it at the one
        // place a mixed service is drawn left the bug exactly where it was.
        // (CodeRabbit, PR #212.)
        const iUnmanaged = inst.unmanaged || svc.unmanaged;
        const disabledAttr = iUnmanaged
          ? ` disabled title="${t('app.row.outside_title')}"`
          : (iNoDocker ? (inst.desktop_report_only ? ` disabled title="${t('app.row.report_only_title')}"` : t('app.row.no_docker_attr_html')) : '');
        const subLabel = inst.is_android ? '' : escapeHtml(inst.container_name);
        // `|| '0'` would render an unmeasurable container as a confident 0%.
        // The endpoint sends null when the Docker stats call failed, and an em
        // dash is the only honest rendering of that (CashPilot-zdi).
        const cpuCell = inst.is_android
          ? `↑ ${fmtNetBytes(inst.net_tx_24h)}`
          : (inst.cpu == null ? `<span title="${t('app.row.no_container_stats')}">—</span>` : `${inst.cpu}%`);
        const memCell = inst.is_android
          ? `↓ ${fmtNetBytes(inst.net_rx_24h)}`
          : (inst.memory == null ? `<span title="${t('app.row.no_container_stats')}">—</span>` : inst.memory);
        html += `
        <tr class="instance-row" data-parent="${escapeHtml(svc.slug)}" style="display:none;">
          <td class="c-name">
            <span class="instance-node-label">${nodeLabel}</span>
            ${subLabel ? `<span class="instance-ctr">${subLabel}</span>` : ''}
          </td>
          <td class="c-status"><span class="badge badge-${iStatus}"><span class="status-dot ${iStatus}"></span> ${iStatusLabel}</span> ${routeBadge(inst)}</td>
          <td class="c-health c-empty"></td>
          <td class="c-bal c-empty"></td>
          <td class="c-chg c-empty"></td>
          <td class="c-cpu c-num" data-label="${inst.is_android ? t('app.label.upload_24h') : t('app.label.cpu')}">${cpuCell}</td>
          <td class="c-mem c-num" data-label="${inst.is_android ? t('app.label.download_24h') : t('app.label.memory')}">${memCell}</td>
          <td class="c-disk c-num" data-label="${t('app.label.host_disk')}">${diskCellForHosts(hostForWorker(inst.worker_id))}</td>
          <td class="c-gpu" data-label="${t('app.label.gpu')}">${gpuCellForHosts(hostForWorker(inst.worker_id))}</td>
          <td class="c-pay c-empty"></td>
          <td class="c-act">
            <div class="action-btns">
              ${_canWrite ? `
              <button class="btn btn-icon" data-action="restartService" data-a1="${escapeHtml(svc.slug)}"${wParam}${disabledAttr} title="${t('app.row.restart_on', { node: nodeLabel })}">
                ${ICON_RESTART}
              </button>
              <button class="btn btn-icon" data-action="stopService" data-a1="${escapeHtml(svc.slug)}"${wParam}${disabledAttr} title="${t('app.row.stop_on', { node: nodeLabel })}">
                ${ICON_STOP}
              </button>
              <button class="btn btn-icon" data-action="viewLogs" data-a1="${escapeHtml(svc.slug)}"${wParam}${disabledAttr} title="${t('app.logs_on', { node: nodeLabel })}">
                ${ICON_LOGS}
              </button>` : ''}
            </div>
          </td>
        </tr>`;
      }
    }

    return html;
  }

  function toggleInstances(slug, event) {
    if (event) {
      // Don't toggle when clicking links or buttons inside the row
      const target = event.target.closest('a, button, .action-btns');
      if (target) return;
    }
    const rows = document.querySelectorAll(`.instance-row[data-parent="${slug}"]`);
    const mainRow = document.querySelector(`.breakdown-row[data-slug="${slug}"]`);
    const isOpen = rows.length > 0 && rows[0].style.display !== 'none';
    rows.forEach(r => { r.style.display = isOpen ? 'none' : ''; });
    if (mainRow) mainRow.classList.toggle('expanded', !isOpen);
  }

  function refreshServices() {
    loadServicesTable();
    toast(t('app.services.refreshed'), 'info');
  }

  async function _waitForChart() {
    if (typeof Chart !== 'undefined') return;
    return new Promise(resolve => {
      const id = setInterval(() => { if (typeof Chart !== 'undefined') { clearInterval(id); resolve(); } }, 100);
      setTimeout(() => { clearInterval(id); resolve(); }, 5000);
    });
  }

  async function loadEarningsChart(days) {
    const ctx = document.getElementById('earnings-chart');
    if (!ctx) return;
    await _waitForChart();
    if (typeof Chart === 'undefined') return;

    // Highlight active tab
    document.querySelectorAll('.chart-period-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.days === days);
    });

    let labels = [];
    let values = [];

    try {
      const data = await api(`/api/earnings/daily?days=${days}`);
      labels = data.map(d => d.date);
      values = data.map(d => d.amount);
    } catch (err) {
      // A failed fetch is NOT a month of zero earnings.
      //
      // This used to fabricate one bar per day at exactly 0.00, drawn with the
      // same axis and tooltips as real money. The user read "I earned nothing
      // every day for the last month" when the truth was that the browser could
      // not reach the server. Of every place in this app that could turn
      // unknown into a number, this was the loudest: a full-width chart of
      // confident zeros.
      //
      // Leave whatever is on screen alone if a chart already exists — stale
      // real data beats invented data — and say so plainly when there is not.
      console.warn('Could not load earnings for the chart:', err);
      if (!earningsChart && ctx) {
        const holder = ctx.parentElement;
        if (holder) {
          holder.innerHTML =
            '<div class="empty-state">'
            + `<div class="empty-state-text">${t('app.chart.load_failed')}</div>`
            + '<button class="btn btn-ghost btn-sm" data-action="loadEarningsChart" data-a1="'
            + escapeHtml(String(days)) + `">${t('app.retry')}</button>`
            + '</div>';
        }
      }
      return;
    }

    if (earningsChart) {
      earningsChart.data.labels = labels;
      earningsChart.data.datasets[0].data = values;
      earningsChart.update();
      return;
    }

    const cs = getComputedStyle(document.documentElement);
    const textMuted = cs.getPropertyValue('--text-muted').trim();
    const fontMono = cs.getPropertyValue('--font-mono').trim();
    const textPrimary = cs.getPropertyValue('--text-primary').trim();
    const textSecondary = cs.getPropertyValue('--text-secondary').trim();
    const bgSecondary = cs.getPropertyValue('--bg-secondary').trim();
    const borderColor = cs.getPropertyValue('--border-color').trim();
    const accent = cs.getPropertyValue('--chart-bar').trim() || cs.getPropertyValue('--accent').trim();

    // Tick labels are measured once; measuring with the fallback font and
    // drawing with the webfont clipped the y axis.
    if (document.fonts && document.fonts.ready) {
      try { await document.fonts.ready; } catch (err) { /* draw with whatever loaded */ }
    }
    if (earningsChart) return;
    earningsChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          label: t('app.chart.daily'),
          data: values,
          backgroundColor: accent,
          borderWidth: 0,
          borderRadius: 0,
          maxBarThickness: 28,
          hoverBackgroundColor: textPrimary,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: bgSecondary,
            titleColor: textPrimary,
            bodyColor: textSecondary,
            borderColor: borderColor,
            borderWidth: 1,
            padding: 10,
            callbacks: {
              label: (ctx) => formatCurrency(ctx.parsed.y),
            },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            border: { color: borderColor },
            ticks: { color: textMuted, font: { size: 12, family: fontMono }, maxRotation: 0, autoSkipPadding: 12 },
          },
          y: {
            beginAtZero: true,
            grid: { color: borderColor },
            border: { display: false },
            ticks: {
              color: textMuted,
              maxTicksLimit: 4,
              font: { size: 12, family: fontMono },
              callback: (v) => formatCurrency(v),
            },
          },
        },
      },
    });
  }

  // -----------------------------------------------------------
  // Earnings Breakdown
  // -----------------------------------------------------------
  // loadEarningsBreakdown merged into loadServicesTable above

  // -----------------------------------------------------------
  // Credential Update Modal (inline from dashboard / notifications)
  // -----------------------------------------------------------
  let _collectorMetaCache = null;

  async function openCredentialModal(slug) {
    openModal('cred-modal');
    const title = document.getElementById('cred-modal-title');
    const body = document.getElementById('cred-modal-body');
    if (title) title.textContent = t('app.cred.title');
    if (body) body.innerHTML = '<div class="spinner spinner-block"></div>';

    try {
      if (!_collectorMetaCache) {
        _collectorMetaCache = await api('/api/collectors/meta');
      }
      const config = await api('/api/config');
      const col = _collectorMetaCache.find(c => c.slug === slug);
      if (!col || !col.fields.length) {
        if (body) body.innerHTML = `<p class="muted">${t('app.cred.none_needed')}</p>`;
        return;
      }
      if (title) title.textContent = t('app.cred.title_for', { name: col.name });

      const secrets = config._secrets || {};
      // EVERY field, not just the required ones.
      //
      // Filtering to required hid exactly the credentials this UI recommends.
      // Bytelixir's session cookie expires in about two hours; its remember_web
      // and xsrf_token cookies last a year and are what stop collection dying
      // the same afternoon — and both are optional, so the credential-health
      // panel said "a longer-lived credential exists for this service" while
      // the modal it links to offered nowhere to put it.
      //
      // Storj is worse: its only field is optional, so the modal rendered no
      // inputs at all.
      const fieldsHtml = col.fields.map(f => {
        const inputType = f.secret ? 'password' : 'text';
        const optionalSuffix = f.required ? '' : ` <span class="optional">${t('app.cred.optional')}</span>`;
        // Secret inputs are write-only: empty, with a placeholder that reflects
        // whether a value is already stored (per _secrets). Non-secret fields keep
        // their plain placeholder.
        const placeholder = f.secret
          ? (secrets[f.key] ? t('app.cred.set_keep') : escapeHtml(f.label))
          : escapeHtml(f.label);
        return `
        <div class="form-group">
          <label class="form-label">${escapeHtml(f.label)}${optionalSuffix}</label>
          <input class="form-input form-input-wide cred-modal-input" type="${inputType}"
                 data-config="${escapeHtml(f.key)}"
                 value=""
                 placeholder="${placeholder}"
                 ${f.secret ? 'autocomplete="new-password"' : ''}>
        </div>`;
      }).join('');
      const hint = col.hint || '';

      // Signup bonus offset field — show current value from config
      const bonusKey = `${slug}_signup_bonus`;
      const currentBonus = config[bonusKey] || '';
      const payCurrency = col.currency || 'USD';
      const currencyLabel = payCurrency === 'USD' ? '$' : payCurrency;
      const bonusHtml = `
        <div class="modal-section">
          <label class="form-label">${t('app.cred.bonus', { currency: escapeHtml(currencyLabel) })}</label>
          <div class="inline-field">
            <input class="form-input form-input-num cred-modal-input" type="number" step="0.01" min="0"
                   data-config="${escapeHtml(bonusKey)}"
                   value="${escapeHtml(currentBonus)}"
                   placeholder="0.00">
            <span class="form-hint">${t('app.cred.bonus_hint')}</span>
          </div>
        </div>`;

      body.innerHTML = `
        ${hint ? `<p class="modal-hint">${sanitizeHint(hint)}</p>` : ''}
        ${fieldsHtml}
        ${bonusHtml}
        <div class="modal-actions">
          <button class="btn btn-primary" data-action="saveCredentialModal" data-a1="${escapeHtml(slug)}">${t('app.save')}</button>
          <button class="btn btn-ghost" data-action="closeModal" data-a1="cred-modal">${t('app.cancel')}</button>
          <button class="btn btn-danger push-right" data-action="clearServiceCredentials" data-a1="${escapeHtml(slug)}" data-a2="${escapeHtml(col.name)}">${t('app.cred.clear')}</button>
        </div>`;
    } catch (err) {
      if (body) body.innerHTML = `<p class="text-fail">${t('app.load_failed', { error: escapeHtml(err.message) })}</p>`;
    }
  }

  async function saveCredentialModal(slug) {
    const inputs = document.querySelectorAll('.cred-modal-input');
    const data = {};
    inputs.forEach(input => {
      const key = input.dataset.config;
      const val = input.value.trim();
      if (val) data[key] = val;
    });
    if (!Object.keys(data).length) {
      toast(t('app.cred.enter_one'), 'warning');
      return;
    }
    try {
      await api('/api/config', { method: 'POST', body: { data } });
      closeModal('cred-modal');

      // Say whether the credentials WORK, not just that they were stored.
      //
      // app/credential_test.py exists to end the "paste a token, wait up to an
      // hour, learn from the notification bell" loop, and it produces the
      // actionable sentence ("... most likely expired — copy a fresh one and try
      // again"). Nothing called it. What a user with a mistyped password got
      // instead was the next hourly run's alert, rendered verbatim: "Client
      // error '401 Unauthorized' for url 'https://.../api/v1/users/tokens' For
      // more information check: https://developer.mozilla.org/...".
      //
      // The endpoint deliberately returns no field that could carry a secret,
      // so its message is safe to show as-is.
      if (slug) {
        toast(t('app.cred.saved_checking'), 'success');
        try {
          const verdict = await api(`/api/services/${encodeURIComponent(slug)}/test-credentials`, { method: 'POST' });
          toast(verdict.message || (verdict.ok ? t('app.cred.work') : t('app.cred.unverified')),
                verdict.ok ? 'success' : 'error');
        } catch (err) {
          // The CHECK failed, which is not the same as the credentials failing.
          // Saying "rejected" here would send someone to re-copy a token that
          // was fine.
          toast(t('app.cred.check_failed', { error: err.message }), 'warning');
        }
      } else {
        toast(t('app.cred.saved_collecting'), 'success');
      }

      // Trigger a collection so it picks up new creds immediately
      api('/api/collect', { method: 'POST' }).catch(() => {});
      // Silently refresh the dashboard after collection has time to finish
      setTimeout(() => loadServicesTable(), 8000);
    } catch (err) {
      toast(t('app.save_failed', { error: err.message }), 'error');
    }
  }

  // -----------------------------------------------------------
  // Change Password Modal
  // -----------------------------------------------------------
  function openChangePasswordModal() {
    // Reset fields and any prior error each time the modal opens.
    ['chpw-current', 'chpw-new', 'chpw-confirm'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });
    const err = document.getElementById('chpw-error');
    if (err) { err.textContent = ''; err.style.display = 'none'; }
    // Close the avatar dropdown if it was the launch point.
    const dropdown = document.getElementById('avatar-dropdown');
    if (dropdown) dropdown.classList.remove('open');
    openModal('password-modal');
    const current = document.getElementById('chpw-current');
    if (current) setTimeout(() => current.focus(), 50);
  }

  function _setPwdError(msg) {
    const err = document.getElementById('chpw-error');
    if (err) {
      err.textContent = msg;
      err.style.display = msg ? '' : 'none';
    }
  }

  async function submitPasswordChange() {
    const currentEl = document.getElementById('chpw-current');
    const newEl = document.getElementById('chpw-new');
    const confirmEl = document.getElementById('chpw-confirm');
    if (!currentEl || !newEl || !confirmEl) return;

    const current_password = currentEl.value;
    const new_password = newEl.value;
    const confirm = confirmEl.value;

    // Client-side validation mirrors the backend rules for instant feedback.
    if (!current_password) {
      _setPwdError(t('app.pwd.enter_current'));
      currentEl.focus();
      return;
    }
    if (new_password.length < 10) {
      _setPwdError(t('app.pwd.too_short'));
      newEl.focus();
      return;
    }
    if (new_password !== confirm) {
      _setPwdError(t('app.pwd.mismatch'));
      confirmEl.focus();
      return;
    }
    if (new_password === current_password) {
      _setPwdError(t('app.pwd.same'));
      newEl.focus();
      return;
    }

    _setPwdError('');
    const btn = document.getElementById('pwd-submit');
    if (btn) { btn.disabled = true; btn.dataset.label = btn.textContent; btn.textContent = t('app.pwd.saving'); }

    try {
      await api('/api/users/me/password', {
        method: 'POST',
        body: { current_password, new_password },
      });
      // Cookie is re-minted server-side, so the session stays valid.
      toast(t('app.pwd.changed'), 'success');
      closeModal('password-modal');
    } catch (err) {
      _setPwdError(err.message);
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = btn.dataset.label || t('app.pwd.submit'); }
    }
  }

  // -----------------------------------------------------------
  // Claim Modal
  // -----------------------------------------------------------
  // Why this service has no earnings row, said accurately. Three different
  // facts hide behind one empty result and they need three different answers.
  async function renderNoEarningsYet(platform, title, body) {
    let service = null;
    try {
      const available = await api('/api/services/available');
      service = (available || []).find(s => s.slug === platform) || null;
    } catch (err) {
      // Could not check. Say that, rather than guessing at either answer.
      if (title) title.textContent = t('app.claim.title');
      if (body) {
        body.innerHTML = `<p>${t('app.claim.check_failed', { error: escapeHtml(err.message || t('app.claim.request_failed')) })}</p>`;
      }
      return;
    }

    const name = service ? (service.name || platform) : platform;
    if (title) title.textContent = t('app.claim.title_for', { name });
    if (!body) return;

    if (!service) {
      // The only case that genuinely deserves the old wording.
      body.innerHTML = `<p>${t('app.claim.not_in_catalog', { name: escapeHtml(name) })}</p>`;
      return;
    }

    // Deployed and running, but nothing has been read yet. Name the likely
    // cause, because "no data" without a reason reads as a broken page.
    const reason = service.has_collector
      ? t('app.claim.none_read')
      : t('app.claim.no_collector');
    body.innerHTML = `<p>${escapeHtml(reason)}</p>`;
  }

  async function openClaimModal(platform) {
    openModal('claim-modal');
    const title = document.getElementById('claim-modal-title');
    const body = document.getElementById('claim-modal-body');

    if (title) title.textContent = t('app.claim.checking');
    if (body) body.innerHTML = '<div class="spinner spinner-block"></div>';

    try {
      const data = await api('/api/earnings/breakdown');
      const svc = data.find(s => s.platform === platform);
      if (!svc) {
        // /api/earnings/breakdown is built from the EARNINGS table, so a service
        // that has never produced a reading is simply absent from it. Reporting
        // that absence as "Service not found" told the user the software had
        // lost track of a service they were looking straight at -- it is in the
        // catalog, on the dashboard, deployed and running. On this fleet that
        // was 5 of 18 tracked services (CashPilot: claim-modal bead).
        await renderNoEarningsYet(platform, title, body);
        return;
      }

      const co = svc.cashout || {};
      // Three-valued, exactly as the endpoint reports it. `eligible` false and
      // `eligible` null are different answers — "you are below the minimum" and
      // "we cannot tell" — and rendering the second as the first tells the user
      // something we do not know.
      const eligible = co.eligible;
      const eligibilityUnknown = eligible == null;
      // Same reconciliation as the service row: compare and render in the unit
      // the balance is in, never the catalog's declared cashout unit.
      const minAmount = co.min_amount_comparable;
      const comparable = typeof minAmount === 'number';
      const currency = svc.currency || 'USD';

      if (title) title.textContent = t('app.claim.payout_for', { name: svc.name });

      // One state line in the Console's colour-only-for-state language: a
      // square and a word, then the reason. No hero icon.
      const stateClass = eligibilityUnknown ? 'claim-unknown' : eligible ? 'claim-ok' : 'claim-warn';
      const statusText = eligibilityUnknown
        ? `<span class="claim-state ${stateClass}">${t('app.claim.cannot_tell')}</span>
           <p class="claim-why">
             ${t('app.claim.cannot_compare', { min: escapeHtml(String(co.min_amount_currency || t('app.claim.another_currency'))), currency: escapeHtml(String(currency)) })}
           </p>`
        : eligible
        ? `<span class="claim-state ${stateClass}">${t('app.claim.eligible')}</span>`
        : `<span class="claim-state ${stateClass}">${t('app.claim.below')}</span>`;

      const pctToMin = comparable && minAmount > 0 ? Math.min(100, (svc.balance / minAmount) * 100) : 0;
      const remaining = comparable ? Math.max(0, minAmount - svc.balance) : 0;

      const progressSection = comparable && minAmount > 0 ? `
        <div class="claim-progress">
          <div class="claim-figures">
            <span>${t('app.claim.balance_html', { amount: formatCurrency(svc.balance, currency) })}</span>
            <span>${t('app.claim.minimum_html', { amount: formatCurrency(minAmount, currency) })}</span>
          </div>
          <div class="payout-progress payout-progress-lg">
            <div class="payout-progress-bar ${eligible ? 'eligible' : ''}" style="width:${pctToMin.toFixed(0)}%"></div>
          </div>
          ${!eligible ? `<p class="claim-why">${t('app.claim.remaining', { amount: formatCurrency(remaining, currency) })}</p>` : ''}
        </div>` : '';

      const notesSection = co.notes
        ? `<p class="claim-notes">${t('app.claim.notes_html', { notes: escapeHtml(co.notes) })}</p>`
        : '';

      const methodLabel = {
        redirect: t('app.claim.method.redirect'),
        api: t('app.claim.method.api'),
        manual: t('app.claim.method.manual'),
        auto: t('app.claim.method.auto'),
      };
      const extIcon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>';

      let actionSection = '';
      if (co.method === 'auto') {
        // Auto-settle services — always show the dashboard link (e.g. rewards page)
        actionSection = `<div class="claim-action">
             <p class="claim-why">${methodLabel.auto}</p>
             ${co.dashboard_url ? `<a href="${escapeHtml(co.dashboard_url)}" target="_blank" rel="noopener" class="btn btn-primary">${extIcon} ${t('app.claim.open_rewards')}</a>` : ''}
           </div>`;
      } else if (eligible && co.dashboard_url) {
        actionSection = `<div class="claim-action">
             <p class="claim-why">${methodLabel[co.method] || methodLabel.redirect}</p>
             <a href="${escapeHtml(co.dashboard_url)}" target="_blank" rel="noopener" class="btn btn-primary">${extIcon} ${t('app.claim.open_dashboard')}</a>
           </div>`;
      } else if (eligibilityUnknown) {
        actionSection = co.dashboard_url
          ? `<div class="claim-action"><a href="${escapeHtml(co.dashboard_url)}" target="_blank" rel="noopener" class="btn btn-ghost">${extIcon} ${t('app.claim.open_dashboard')}</a></div>`
          : '';
      } else if (!eligible) {
        actionSection = `<p class="claim-why">${t('app.claim.keep_running')}</p>`;
      }

      if (body) body.innerHTML = `
        <div class="claim-head">${statusText}</div>
        ${progressSection}
        ${notesSection}
        ${actionSection}
      `;
    } catch (err) {
      if (body) body.innerHTML = `<p class="text-fail">${t('app.error', { error: escapeHtml(err.message) })}</p>`;
    }
  }

  // -----------------------------------------------------------
  // Service actions
  // -----------------------------------------------------------
  async function restartService(slug, workerId, instance) {
    const q = workerId != null ? `?worker_id=${workerId}${_instanceQuery(instance)}` : '';
    try {
      const out = await api(`/api/services/${slug}/restart${q}`, { method: 'POST' });
      toast(t('app.svc.restarting', { slug }), 'success');
      // A routed copy the worker started, but could not make that last through a power cut.
      if (out && out.warning) toast(out.warning, 'warning');
      loadServicesTable();
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function stopService(slug, workerId, instance) {
    const q = workerId != null ? `?worker_id=${workerId}${_instanceQuery(instance)}` : '';
    try {
      const out = await api(`/api/services/${slug}/stop${q}`, { method: 'POST' });
      toast(t('app.svc.stopped', { slug }), 'success');
      // A routed copy the worker stopped, but could not make that last through a power cut.
      if (out && out.warning) toast(out.warning, 'warning');
      loadServicesTable();
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  // Only ever on the user's click: CashPilot never stops a disabled account's
  // containers by itself (the user may be appealing and want them left alone).
  async function stopEverywhere(slug) {
    let svc;
    try {
      svc = (await api('/api/services/deployed')).find(s => s.slug === slug);
    } catch (err) {
      toast(err.message, 'error');
      return;
    }
    const copies = svc ? stoppableCopies(svc) : [];
    if (!copies.length) { toast(t('app.svc.not_running', { slug }), 'success'); return; }
    if (!confirm(t('app.svc.stop_all_confirm', { name: svc.name, n: copies.length }))) return;
    const failed = [];
    const warnings = [];
    for (const inst of copies) {
      try {
        const out = await api(`/api/services/${encodeURIComponent(slug)}/stop?worker_id=${encodeURIComponent(inst.worker_id)}${_instanceQuery(inst.instance)}`, { method: 'POST' });
        // A routed copy the worker stopped, but could not make that last through a power cut.
        if (out && out.warning) warnings.push(`${inst.node}: ${out.warning}`);
      } catch (err) {
        failed.push(`${inst.node}: ${err.message}`);
      }
    }
    if (failed.length) toast(t('app.svc.stop_failed', { slug, where: failed.join('; ') }), 'error');
    else toast(t('app.svc.stopped_n', { slug, n: copies.length }), 'success');
    if (warnings.length) toast(warnings.join('; '), 'warning');
    loadServicesTable();
  }

  async function startService(slug, workerId, instance) {
    const q = workerId != null ? `?worker_id=${workerId}${_instanceQuery(instance)}` : '';
    try {
      const out = await api(`/api/services/${slug}/start${q}`, { method: 'POST' });
      toast(t('app.svc.starting', { slug }), 'success');
      // A routed copy the worker started, but could not make that last through a power cut.
      if (out && out.warning) toast(out.warning, 'warning');
      loadServicesTable();
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function forgetDeployment(slug, workerId) {
    if (!confirm(workerId != null ? t('app.svc.forget_box_confirm', { slug }) : t('app.svc.forget_confirm', { slug }))) return;
    const q = workerId != null ? `?worker_id=${encodeURIComponent(workerId)}` : '';
    try {
      await api(`/api/deployments/${encodeURIComponent(slug)}${q}`, { method: 'DELETE' });
      toast(t('app.svc.forgotten', { slug }), 'success');
      loadServicesTable();
      loadCollectorAlerts();
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  // The critical volumes a box's refusal named, each with the time Docker made
  // it (its critical_set reads "name@time,..."), shown to the owner before the
  // password. Their yes returns that set as a query parameter, which the
  // approval binds: the box deletes those or nothing, never a volume mounted or
  // made again since. Null when the owner cancels.
  function confirmCriticalVolumes(slug, place, refusal) {
    const reviewed = String(refusal?.critical_set || '');
    const made = new Map(reviewed.split(',').filter(Boolean).map((entry) => {
      const at = entry.lastIndexOf('@');
      return at < 0 ? [entry, ''] : [entry.slice(0, at), entry.slice(at + 1)];
    }));
    const when = (at) => (at === '' ? t('app.vol.gone') : at === '?' || at == null ? t('app.vol.no_time') : t('app.vol.made', { at }));
    const lines = (Array.isArray(refusal?.blocked) ? refusal.blocked : []).map((b) =>
      t('app.vol.line', { volume: b.volume, when: when(made.get(b.volume)), holds: b.holds }));
    if (!confirm(t('app.vol.confirm', { slug, place, lines: lines.join('\n') }))) return null;
    return `critical_set=${encodeURIComponent(reviewed)}`;
  }

  // CashPilot Desktop deletes data that cannot be made again only on that
  // computer, and refuses that delete from here whatever the password. So the
  // owner is told at once, and not asked to review the volumes or for the password.
  // A partial restore has its own words: a Remove that keeps the data is
  // refused while it stays, so "keep the data" would lead back here.
  function _desktopKeepsCriticalData(slug, workerId, boxName, partialRestore = false) {
    const worker = (_detailWorkers || []).find((w) => String(w.id) === String(workerId));
    if (!isDesktopWorker(worker)) return false;
    toast(partialRestore
      ? t('app.vol.desktop_partial', { box: boxName, slug })
      : t('app.vol.desktop_critical', { box: boxName, slug }), 'error');
    return true;
  }

  // What a Remove's answer says about the volumes it was asked to delete:
  // success only when none stayed. byHandOn names the box when a Remove again
  // cannot reach a volume that stays: a custom service's Remove already
  // deleted its container and its record, so its row and button are gone and
  // a DELETE again finds nothing (no restore keeps a custom service held).
  function _removeToast(done, result, byHandOn) {
    // A volume the box could not delete stays, and stays marked half-written.
    // One another client replaced since the owner's review (or since the
    // restore made it) is that client's: the box keeps it, and Remove again
    // would not delete it either. A leftover row's first Remove can report
    // one with no review at all, so the text names no confirmation.
    const list = (v) => (Array.isArray(v) ? v : []);
    const replaced = list(result?.replaced_volumes);
    // Named by a restore record from an older worker with nothing that
    // proves it is the restore's: the box keeps it and the service stays
    // held until the owner deletes it.
    const unverified = list(result?.unverified_volumes);
    // Named on that record but unreadable just now: not known to be there,
    // so the owner is not sent to delete it by hand; Remove again reads it.
    const unread = list(result?.unread_volumes);
    const kept = list(result?.failed_volumes).filter((v) => !replaced.includes(v) && !unverified.includes(v) && !unread.includes(v));
    const notes = [];
    if (kept.length) {
      notes.push(byHandOn
        ? t('app.vol.kept_by_hand', { volumes: kept.join(', '), box: byHandOn })
        : t('app.vol.kept', { volumes: kept.join(', ') }));
    }
    if (replaced.length) notes.push(t('app.vol.replaced', { volumes: replaced.join(', ') }));
    if (unverified.length) notes.push(t('app.vol.unverified', { volumes: unverified.join(', ') }));
    if (unread.length) notes.push(t('app.vol.unread', { volumes: unread.join(', ') }));
    if (notes.length) toast(t('app.vol.done_but', { done, notes: notes.join(t('app.vol.and')) }), 'error');
    else toast(done, 'success');
  }

  // Remove a service. From a box's row (workerId, boxName) it goes to that box
  // only; from the service page it goes to the one online box, and never
  // takes the data with it. A row a restore that did not finish left
  // (leftover) removes only while that partial restore is still there.
  // Deleting the data asks for the owner's password only when it holds a
  // node identity or wallet: the box's own catalog decides that (it answers
  // critical_volume), then the critical delete goes, the server answers
  // step_up_required and api() asks, as for a restore.
  async function removeService(slug, workerId, boxName, leftover) {
    const pinned = workerId != null && workerId !== '';
    const fromBox = boxName || t('app.svc.worker_n', { id: workerId });
    if (!confirm(pinned ? t('app.svc.remove_from_confirm', { slug, box: fromBox }) : t('app.svc.remove_confirm', { slug }))) return;
    const box = (id) => `?worker_id=${encodeURIComponent(id)}`;
    // Its data goes only when the owner says so, never by default: the same
    // owner-only, audited delete a custom service's Remove offers. It is the
    // way to free the box for a restore of a backup. Only from a box's own
    // row: the service page names no box, and the server would pick the one
    // online box, which may not be the one the owner means.
    const params = pinned ? [`worker_id=${encodeURIComponent(workerId)}`] : [];
    const withData = pinned && _isOwner && confirm(t('app.svc.remove_data_confirm', { slug, box: fromBox }));
    if (withData) params.push('delete_volumes=true');
    // That row was drawn for a partial restore: a restore that finished since,
    // in another tab, is not what was meant, with its data or without, by the
    // owner or a writer. The worker then removes nothing.
    if (leftover === 'leftover') params.push('only_if_restore_unfinished=true');
    const path = (list) => `/api/services/${slug}${list.length ? `?${list.join('&')}` : ''}`;
    try {
      let result;
      try {
        result = await api(path(params), { method: 'DELETE' });
      } catch (err) {
        // The box kept everything: its data holds a node identity or wallet.
        // The owner's yes above was to that; the critical delete asks for the
        // password, as for a restore. It names the critical volumes this
        // refusal reported, and the approval binds them: the box deletes
        // those or nothing, never one mounted since.
        if (withData && err.code === 'critical_volume') {
          if (_desktopKeepsCriticalData(slug, workerId, fromBox, leftover === 'leftover')) return;
          const reviewed = confirmCriticalVolumes(slug, fromBox, err.refusal);
          if (!reviewed) return;
          return removed(await api(path([...params, 'allow_delete_critical=true', reviewed]), { method: 'DELETE', body: {} }));
        }
        // A restore that did not finish left a half-written data volume, and
        // the worker keeps it marked until it goes. The way out is the same
        // owner-only, audited critical delete a custom service's Remove uses.
        if (err.code !== 'restore_unfinished') throw err;
        if (!_isOwner) throw new Error(t('app.svc.owner_only_delete', { error: err.message }));
        // The delete goes to the box that refused and to no other, even if
        // the online boxes changed while the owner read the question.
        const refused = pinned ? workerId : err.refusal.worker_id;
        if (refused == null) throw err;
        const name = err.refusal.worker_name || boxName || t('app.svc.worker_n', { id: refused });
        if (!confirm(t('app.svc.partial_confirm', { slug, name }))) return;
        // Only while that partial restore is still there: one restored since,
        // in another tab, is not what the owner agreed to delete. The box first
        // names the volumes it finds critical (the partial restore's always),
        // the owner reviews exactly those, and the approval binds them.
        const retry = `/api/services/${slug}${box(refused)}&delete_volumes=true&only_if_restore_unfinished=true`;
        try {
          result = await api(retry, { method: 'DELETE' });
        } catch (again) {
          if (again.code !== 'critical_volume') throw again;
          if (_desktopKeepsCriticalData(slug, refused, name, true)) return;
          const reviewed = confirmCriticalVolumes(slug, name, again.refusal);
          if (!reviewed) return;
          result = await api(`${retry}&allow_delete_critical=true&${reviewed}`, { method: 'DELETE', body: {} });
        }
      }
      removed(result);
    } catch (err) {
      toast(err.message, 'error');
    }

    function removed(result) {
      _removeToast(pinned ? t('app.svc.removed_from', { slug, box: fromBox }) : t('app.svc.removed', { slug }), result);
      loadServicesTable();
      if (pinned) openServiceDetail(slug);
    }
  }

  // -----------------------------------------------------------
  // Log viewer
  // -----------------------------------------------------------
  let logPollTimer = null;

  // Docker starts every line with an RFC 3339 time in nanoseconds, which is
  // often longer than the message. It is shown in local time, without the
  // date when every line is from today; the full value is in its tooltip.
  const LOG_TIME = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?(Z|[+-]\d{2}:\d{2}) ?/;

  function logEntries(text, now) {
    const pad = n => String(n).padStart(2, '0');
    const day = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    const entries = String(text ?? '').replace(/\r?\n$/, '').split(/\r?\n/).map(raw => {
      const m = LOG_TIME.exec(raw);
      // Date reads at most milliseconds.
      const at = m ? new Date(`${m[1]}${(m[2] || '').slice(0, 4)}${m[3]}`) : null;
      if (!at || Number.isNaN(at.getTime())) return { stamp: '', day: '', time: '', message: raw };
      const time = `${pad(at.getHours())}:${pad(at.getMinutes())}:${pad(at.getSeconds())}`;
      return { stamp: m[0].trim(), day: day(at), time, message: raw.slice(m[0].length) };
    });
    const today = day(now || new Date());
    const stamped = entries.filter(e => e.stamp);
    const dated = stamped.some(e => e.day !== today);
    for (const e of entries) e.shown = e.stamp ? (dated ? `${e.day} ${e.time}` : e.time) : '';
    return { entries, width: stamped.length ? (dated ? 19 : 8) : 0 };
  }

  // The text each viewer shows, so a poll that brings nothing new keeps the
  // reader's selection and scroll position.
  const shownLogs = new WeakMap();

  function renderLogs(viewer, text) {
    if (!viewer) return;
    const value = String(text ?? '');
    // The day is part of the key: past midnight, today's times need their date.
    const shown = `${new Date().toDateString()}\n${value}`;
    if (shownLogs.get(viewer) === shown) return;
    const first = !shownLogs.has(viewer);
    const atEnd = viewer.scrollHeight - viewer.scrollTop - viewer.clientHeight < 24;
    shownLogs.set(viewer, shown);
    const { entries, width } = logEntries(value);
    const list = document.createElement('div');
    list.className = 'log-lines';
    list.style.setProperty('--log-ts', `${width}ch`);
    for (const e of entries) {
      const row = document.createElement('div');
      row.className = 'log-line';
      if (e.shown) {
        const ts = document.createElement('span');
        ts.className = 'log-ts';
        ts.title = e.stamp;
        ts.textContent = e.shown;
        row.append(ts);
      }
      row.append(document.createTextNode(e.message));
      list.append(row);
    }
    viewer.replaceChildren(list);
    // Follow new lines only while the reader is at the end.
    if (first || atEnd) viewer.scrollTop = viewer.scrollHeight;
  }

  function logNote(viewer, text) {
    if (!viewer) return;
    shownLogs.delete(viewer);
    viewer.textContent = text;
  }

  const LOG_WRAP_KEY = 'cashpilot-log-wrap';
  // Read once from storage, then kept here: a browser that refuses to read or
  // write storage still shows logs and still honours the toggle.
  let logWrap = null;

  function logWrapOn() {
    if (logWrap === null) {
      try { logWrap = localStorage.getItem(LOG_WRAP_KEY) === '1'; } catch { logWrap = false; }
    }
    return logWrap;
  }

  function applyLogWrap() {
    const wrap = logWrapOn();
    const viewer = document.getElementById('log-content');
    const button = document.getElementById('log-wrap-toggle');
    if (viewer) viewer.classList.toggle('log-wrap', wrap);
    if (button) button.setAttribute('aria-pressed', String(wrap));
  }

  function toggleLogWrap() {
    const viewer = document.getElementById('log-content');
    const atEnd = viewer && viewer.scrollHeight - viewer.scrollTop - viewer.clientHeight < 24;
    logWrap = !logWrapOn();
    try { localStorage.setItem(LOG_WRAP_KEY, logWrap ? '1' : '0'); } catch { /* kept in memory */ }
    applyLogWrap();
    // Wrapping changes every line's height: a reader at the end stays there.
    if (atEnd) viewer.scrollTop = viewer.scrollHeight;
  }

  async function viewLogs(slug, workerId, instance) {
    openModal('logs-modal');
    const title = document.getElementById('logs-modal-title');
    const viewer = document.getElementById('log-content');
    const copy = parseInt(instance) > 1 ? `, copy ${parseInt(instance)}` : '';
    const label = workerId != null ? `${slug} (worker #${workerId}${copy})` : slug;
    if (title) title.textContent = `Logs: ${label}`;
    applyLogWrap();
    logNote(viewer, 'Loading logs...');

    if (logPollTimer) clearInterval(logPollTimer);
    const q = workerId != null ? `lines=200&worker_id=${workerId}${_instanceQuery(instance)}` : 'lines=200';

    async function fetchLogs() {
      try {
        const data = await api(`/api/services/${slug}/logs?${q}`);
        renderLogs(viewer, data.logs || '(no logs)');
      } catch (err) {
        logNote(viewer, `Error loading logs: ${err.message}`);
      }
    }

    await fetchLogs();
    logPollTimer = setInterval(fetchLogs, 5000);
  }

  function stopLogPolling() {
    if (logPollTimer) {
      clearInterval(logPollTimer);
      logPollTimer = null;
    }
  }

  // -----------------------------------------------------------
  // Setup Wizard
  // -----------------------------------------------------------
  let wizardState = {
    step: 1,
    categories: [],
    selectedServices: [],
    deployed: [],
    deployAttempted: false,
  };

  async function initWizard() {
    wizardState = {
      step: 1, categories: [], selectedServices: [], deployed: [], deployAttempted: false,
      // false when the saved categories could not be read: then finishing
      // does not save an empty list over them.
      prefsLoaded: false,
      // The category a catalog Add put in, not the user. Left out when saving.
      addedCategory: null,
    };

    // Pre-populate from saved preferences
    try {
      const prefs = await api('/api/preferences');
      wizardState.prefsLoaded = true;
      if (prefs.selected_categories) {
        const saved = JSON.parse(prefs.selected_categories);
        if (Array.isArray(saved) && saved.length > 0) {
          wizardState.categories = saved;
          // Check matching category cards
          document.querySelectorAll('.category-card').forEach(card => {
            const cb = card.querySelector('input[type="checkbox"]');
            if (cb && saved.includes(cb.value)) {
              card.classList.add('selected');
              cb.checked = true;
            }
          });
        }
      }
    } catch (err) {
      // Preferences not available — no pre-population
    }

    // /setup?service=<slug>, from a catalog row: start on the setup step with
    // that service picked. Back still walks through categories and services.
    const wanted = new URLSearchParams(window.location.search).get('service');
    if (wanted) {
      let services = null;
      try { services = await api('/api/services/available'); } catch (err) { /* handled below */ }
      const pre = services && wizardPreselect(wanted, services, wizardState.categories);
      if (!services) {
        toast(t('app.wiz.no_catalog'), 'error');
      } else if (pre) {
        Object.assign(wizardState, pre);
        document.querySelectorAll('.category-card').forEach(card => {
          const cb = card.querySelector('input[type="checkbox"]');
          if (cb && pre.categories.includes(cb.value)) {
            card.classList.add('selected');
            cb.checked = true;
          }
        });
        updateWizardUI();
        loadWizardServices();
        loadWizardSetupForms();
      } else {
        toast(t('app.wiz.no_such_service', { slug: wanted }), 'warning');
      }
    }

    updateWizardUI();

    // Category card toggles
    document.querySelectorAll('.category-card').forEach(card => {
      card.addEventListener('click', () => {
        card.classList.toggle('selected');
        const cb = card.querySelector('input[type="checkbox"]');
        if (cb) cb.checked = card.classList.contains('selected');
        wizardState.categories = Array.from(document.querySelectorAll('.category-card.selected input'))
          .map(input => input.value);
        if (cb && cb.value === wizardState.addedCategory) wizardState.addedCategory = null;
      });
    });
  }

  // What the wizard starts with when it opens on one service: the service
  // selected, step 3, and its category selected too (step 2 lists services by
  // category). addedCategory names it when the user had not saved it, so
  // finishing leaves it out. null when the slug is not in the catalog.
  function wizardPreselect(slug, services, savedCategories) {
    const svc = (services || []).find(s => s.slug === slug);
    if (!svc) return null;
    const categories = [...(savedCategories || [])];
    let addedCategory = null;
    if (svc.category && !categories.includes(svc.category)) {
      categories.push(svc.category);
      addedCategory = svc.category;
    }
    return { step: 3, categories, selectedServices: [svc.slug], addedCategory };
  }

  // What finishing the wizard saves. The category a catalog Add put in is not
  // the user's pick, so it is left out. And when the saved list could not be
  // read, an empty list is not saved over it: that would wipe it unseen.
  function wizardPreferencesBody(state) {
    const body = {
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
      setup_completed: 1,
    };
    const categories = state.categories.filter(c => c !== state.addedCategory);
    if (state.prefsLoaded || categories.length) body.selected_categories = JSON.stringify(categories);
    return body;
  }

  function wizardNext() {
    if (wizardState.step === 1 && wizardState.categories.length === 0) {
      toast(t('app.wiz.pick_category'), 'warning');
      return;
    }
    if (wizardState.step === 2 && wizardState.selectedServices.length === 0) {
      toast(t('app.wiz.pick_service'), 'warning');
      return;
    }
    if (wizardState.step < 4) {
      wizardState.step++;
      updateWizardUI();
      if (wizardState.step === 2) loadWizardServices();
      if (wizardState.step === 3) loadWizardSetupForms();
      if (wizardState.step === 4) {
        renderWizardOutcome();
        // Persist category/service selections
        api('/api/preferences', { method: 'POST', body: wizardPreferencesBody(wizardState) }).catch(() => {});
      }
    }
  }

  function renderWizardOutcome() {
    // Say what actually happened.
    //
    // The final screen was unconditional markup: "You're all set! Your services
    // are being deployed." It said that whether five services deployed, or none
    // did, or every deploy 403'd — wizardState.deployed was written twice and
    // read nowhere. A user whose deploys all failed was congratulated and sent
    // to an empty dashboard with no idea anything had gone wrong.
    const title = document.getElementById('wizard-done-title');
    const text = document.getElementById('wizard-done-text');
    if (!title || !text) return;
    const done = wizardState.deployed || [];
    const wanted = wizardState.selectedServices || [];
    if (done.length === 0) {
      // Three different nothings, and only one is a failure. Skipping step 3
      // reaches here with services selected and no deploy attempted, which is
      // not the same as every deploy failing — telling someone their deploys
      // failed when none were tried sends them hunting a problem that is not
      // there.
      if (!wizardState.deployAttempted) {
        title.textContent = t('app.wiz.saved_title');
        text.textContent = wanted.length
          ? t('app.wiz.saved_choices')
          : t('app.wiz.saved_none');
        return;
      }
      title.textContent = t('app.wiz.nothing_title');
      text.textContent = t('app.wiz.nothing_text');
      return;
    }
    const missed = wanted.filter(s => !done.includes(s));
    title.textContent = missed.length ? t('app.wiz.partly_title') : t('app.wiz.done_title');
    const names = done.map(escapeHtml).join(', ');
    text.textContent = missed.length
      ? t('app.wiz.partly_text', { names, n: missed.length })
      : t('app.wiz.done_text', { names });
  }

  function wizardPrev() {
    if (wizardState.step > 1) {
      wizardState.step--;
      updateWizardUI();
    }
  }

  function updateWizardUI() {
    // Update step indicators
    document.querySelectorAll('.wizard-step').forEach((el, i) => {
      const num = i + 1;
      el.classList.remove('active', 'completed');
      if (num === wizardState.step) el.classList.add('active');
      else if (num < wizardState.step) el.classList.add('completed');
    });

    // Update connectors
    document.querySelectorAll('.wizard-step-connector').forEach((el, i) => {
      el.classList.toggle('completed', i + 1 < wizardState.step);
    });

    // Show active panel
    document.querySelectorAll('.wizard-panel').forEach((el, i) => {
      el.classList.toggle('active', i + 1 === wizardState.step);
    });

    // Button visibility
    const prevBtn = document.getElementById('wizard-prev');
    const nextBtn = document.getElementById('wizard-next');
    if (prevBtn) prevBtn.style.display = wizardState.step > 1 ? '' : 'none';
    if (nextBtn) {
      if (wizardState.step === 4) {
        nextBtn.style.display = 'none';
      } else if (wizardState.step === 3) {
        nextBtn.textContent = t('app.wiz.skip');
        nextBtn.style.display = '';
      } else {
        nextBtn.textContent = t('app.wiz.next');
        nextBtn.style.display = '';
      }
    }
  }

  // Cached worker container data for wizard
  let _wizardWorkerSlugs = {};  // slug -> node count
  let _wizardWorkers = [];      // full workers array from /api/workers

  async function loadWizardServices() {
    const container = document.getElementById('wizard-services');
    if (!container) return;

    try {
      // Fetch services and worker data in parallel
      const [services, workers] = await Promise.all([
        api('/api/services/available'),
        api('/api/workers').catch(() => []),
      ]);

      // Cache full workers list and count how many nodes run each slug
      _wizardWorkers = workers;
      _wizardWorkerSlugs = {};
      for (const w of workers) {
        const slugs = new Set((w.containers || []).map(c => c.slug).filter(Boolean));
        for (const s of slugs) {
          _wizardWorkerSlugs[s] = (_wizardWorkerSlugs[s] || 0) + 1;
        }
      }

      const filtered = services.filter(s =>
        wizardState.categories.includes(s.category)
      );
      if (filtered.length === 0) {
        container.innerHTML = `<p class="empty-state-text">${t('app.wiz.no_services')}</p>`;
        return;
      }
      container.innerHTML = filtered.map(renderWizardServiceCard).join('');
    } catch (err) {
      container.innerHTML = `<p class="empty-state-text">${t('app.wiz.load_failed')}</p>`;
    }
  }

  function renderWizardServiceCard(svc) {
    const isSelected = wizardState.selectedServices.includes(svc.slug);
    const isDeployed = svc.deployed;
    const isManual = svc.manual_only;
    const totalNodes = svc.node_count || 0;

    const classes = ['service-card'];
    if (isSelected) classes.push('selected');
    if (isDeployed) classes.push('deployed');
    if (isManual) classes.push('manual-only');

    let deployedBadge = '';
    if (totalNodes > 0) {
      const label = t('app.wiz.deployed_nodes', { n: totalNodes });
      deployedBadge = `<span class="deployed-badge"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg> ${label}</span>`;
    }

    // Platform notice for manual-only services
    let manualNotice = '';
    if (isManual && svc.category === 'mining') {
      // A pool tracked by payout address: there is no app to install.
      manualNotice = `<div class="manual-notice">${t('app.wiz.pool_notice')}</div>`;
    } else if (isManual) {
      const platforms = (svc.platforms || []).map(p => p.charAt(0).toUpperCase() + p.slice(1)).join('/');
      manualNotice = `<div class="manual-notice">${t('app.wiz.platform_only', { platforms: platforms || 'Desktop' })}</div>`;
    }

    return `
    <div class="${classes.join(' ')}" data-slug="${svc.slug}" data-action="toggleWizardService" data-a1="${svc.slug}">
      <div class="service-card-header">
        <div class="service-icon">${(svc.name || '?')[0]}</div>
        <div>
          <div class="service-name">${escapeHtml(svc.name)}</div>
          <span class="badge badge-category">${escapeHtml(categoryLabel(svc.category))}</span>
        </div>
      </div>
      <div class="service-desc">${escapeHtml(svc.short_description || '')}</div>
      ${manualNotice}
      <div class="service-meta">
        ${svc.requirements && svc.requirements.residential_ip ? `<span class="badge badge-residential">${t('app.wiz.residential')}</span>` : ''}
        ${deployedBadge}
      </div>
    </div>`;
  }

  function toggleWizardService(slug) {
    // Resolves its own element. It used to take one as a second argument, fed
    // by `data-a2="this"` — a leftover from the inline-handler migration, where
    // `this` really was the element. delegate.js reads arguments out of
    // `dataset`, and dataset values are ALWAYS strings, so the handler received
    // the literal string "this" and threw on `.classList`.
    //
    // The throw was the harmless half. The selection is mutated BEFORE the
    // line that throws, so a click updated wizardState and then died before
    // highlighting anything: no visual feedback, and a second click silently
    // deselected a service the user could not see was selected. They then
    // pressed Next and were told to select something.
    const card = document.querySelector(`#wizard-services .service-card[data-slug="${CSS.escape(slug)}"]`)
      || document.querySelector(`.service-card[data-slug="${CSS.escape(slug)}"]`);
    const idx = wizardState.selectedServices.indexOf(slug);
    if (idx >= 0) {
      wizardState.selectedServices.splice(idx, 1);
      card?.classList.remove('selected');
    } else {
      wizardState.selectedServices.push(slug);
      card?.classList.add('selected');
    }
  }

  async function loadWizardSetupForms() {
    const container = document.getElementById('wizard-setup-forms');
    if (!container) return;

    container.innerHTML = '<div class="spinner spinner-block"></div>';

    try {
      const [services, workers] = await Promise.all([
        api('/api/services/available'),
        _wizardWorkers.length ? Promise.resolve(_wizardWorkers) : api('/api/workers').catch(() => []),
      ]);
      _wizardWorkers = workers;
      const selected = services.filter(s => wizardState.selectedServices.includes(s.slug));
      container.innerHTML = selected.map(svc => renderServiceSetupForm(svc, workers)).join('');
      loadDeployRisk();
      for (const svc of selected) loadRouteChoices(svc.slug, container);
    } catch (err) {
      container.innerHTML = `<p class="empty-state-text">${t('app.wiz.details_failed')}</p>`;
    }
  }

  // Earnings tracking takes a SECOND set of credentials.
  //
  // The container credentials only configure the container; the dashboard shows
  // no balance until the same values are entered again under Settings →
  // Collectors. The service-detail view said so; the setup wizard — the one
  // screen a new user actually sees — did not, so the expected end state of
  // onboarding was a dashboard reading zero (CashPilot-p6s).
  //
  // One function rather than two copies: a notice that exists twice drifts, and
  // the wizard's version is the one that matters most.
  // A provider with no account to sign up for (referral.account: false, e.g. a
  // relay that needs only a wallet): its link opens the provider's site, so the
  // button says Visit. "Sign Up" there sent people looking for an account form.
  function hasAccount(svc) {
    return !(svc.referral && svc.referral.account === false);
  }

  // The Sign Up buttons open the maintainer's referral link, and the person
  // clicking should know that before the click, not from a README section they
  // never open. Shown only where the catalog records a referral code: a bare
  // signup_url (no programme, or none found yet) is not a referral link.
  // The new user's bonus goes first when the catalog records one: it is the
  // reason to use this link at all, and it used to sit only on the detail page.
  // Some signups never read the code from the link (Dawn's extension asks for
  // it, Gradient's form ignores the URL): referral.code_entry is then the code
  // to type, shown with a Copy button so a user who signs up here still
  // credits the referral.
  function referralNote(svc) {
    const ref = svc.referral || {};
    if (!ref.code || !ref.signup_url) return '';
    const referee = ref.bonus && ref.bonus.referee;
    const typed = ref.code_entry
      ? `<p class="referral-code">${t('app.ref.type_code_html', { name: escapeHtml(svc.name), code: escapeHtml(ref.code_entry) })} ${codeEntryCopy(svc, t('app.ref.copy'))}</p>`
      : '';
    const note = referee
      ? t('app.ref.note_bonus_html', { bonus: escapeHtml(referee) })
      : t('app.ref.note');
    return `${typed}<p class="referral-note">${note}</p>`;
  }

  // The Copy button for a code typed by hand (referral.code_entry), or '' when the
  // link carries the code. Its accessible name says what it copies.
  function codeEntryCopy(svc, label) {
    const ref = svc.referral || {};
    if (!ref.code || !ref.signup_url || !ref.code_entry) return '';
    const code = escapeHtml(ref.code_entry);
    const name = escapeHtml(t('app.ref.copy_label', { name: svc.name, code: ref.code_entry }));
    return `<button class="btn btn-ghost btn-sm" data-action="copyText" data-a1="${code}" aria-label="${name}" title="${name}">${label}</button>`;
  }

  function collectorCredentialsNotice(slug) {
    return `
        <div class="inline-note">
          ${t('app.wiz.collector_notice_html', { attrs: `href="#" data-action="openCredentialModal" data-prevent="1" data-a1="${escapeHtml(slug)}"` })}
        </div>`;
  }

  function renderServiceSetupForm(svc, workers) {
    const isDeployed = svc.deployed || false;
    const accountRequired = hasAccount(svc);
    const dashboardUrl = (svc.cashout && svc.cashout.dashboard_url) || svc.website || '';
    const signupUrl = svc.referral && svc.referral.signup_url
      ? svc.referral.signup_url
      : svc.website || '#';
    // Sign Up stays on a deployed service: a deploy does not prove an account
    // (a MystNodes node runs before anyone signs up), and the referral only
    // counts through this link. The dashboard sits beside it.
    const dashboardLink = isDeployed && dashboardUrl
      ? `<a href="${escapeHtml(dashboardUrl)}" target="_blank" rel="noopener" class="btn btn-ghost btn-sm">${t('app.wiz.dashboard')}</a>`
      : '';

    // A mining pool with no image is tracked by its payout address: CashPilot
    // runs nothing, and the address goes in Settings, where the collector reads it.
    if (svc.manual_only && svc.category === 'mining') {
      return `
      <div class="card setup-card" id="setup-${svc.slug}">
        <div class="card-header">
          <h3 class="section-title">${escapeHtml(svc.name)}</h3>
          <span class="badge badge-category">${escapeHtml(categoryLabel(svc.category))}</span>
        </div>
        <div class="setup-body">
          <p class="setup-line">
            ${t('app.wiz.pool_html')}
          </p>
          <a href="/settings#collector-${escapeHtml(svc.slug)}" class="btn btn-primary btn-sm">${t('app.wiz.add_payout_address')}</a>
          <a href="${escapeHtml(signupUrl)}" target="_blank" rel="noopener" class="btn btn-ghost btn-sm">
            ${t('app.wiz.start_mining', { name: escapeHtml(svc.name) })}
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
          </a>
          ${dashboardLink}
          <a href="https://geiserx.github.io/CashPilot/guides/${svc.slug}/" target="_blank" rel="noopener" class="btn btn-ghost btn-sm">
            ${t('app.wiz.setup_guide')}
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 3h6a4 4 0 014 4v14a3 3 0 00-3-3H2z"/><path d="M22 3h-6a4 4 0 00-4 4v14a3 3 0 013-3h7z"/></svg>
          </a>
          ${referralNote(svc)}
        </div>
      </div>`;
    }

    // Manual-only services: show signup link + earnings tracking notice + any env fields
    if (svc.manual_only) {
      const platforms = (svc.platforms || []).map(p => p.charAt(0).toUpperCase() + p.slice(1)).join(', ');
      const manualEnvFields = envInputFields(svc, svc.docker && svc.docker.env);
      const manualBtnLabel = accountRequired ? t('app.wiz.sign_up_for', { name: escapeHtml(svc.name) }) : t('app.wiz.visit_name', { name: escapeHtml(svc.name) });
      return `
      <div class="card setup-card" id="setup-${svc.slug}">
        <div class="card-header">
          <h3 class="section-title">${escapeHtml(svc.name)}</h3>
          <span class="badge badge-category">${escapeHtml(categoryLabel(svc.category))}</span>
        </div>
        <div class="setup-body">
          <p class="setup-line text-warn">
            ${t('app.wiz.no_image_html', { platforms: platforms || 'Desktop' })}
          </p>
          <p class="setup-line">
            ${t('app.wiz.install_app')}
          </p>
          <a href="${escapeHtml(signupUrl)}" target="_blank" rel="noopener" class="btn btn-primary btn-sm">
            ${manualBtnLabel}
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
          </a>
          ${dashboardLink}
          <a href="https://geiserx.github.io/CashPilot/guides/${svc.slug}/" target="_blank" rel="noopener" class="btn btn-ghost btn-sm">
            ${t('app.wiz.setup_guide')}
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 3h6a4 4 0 014 4v14a3 3 0 00-3-3H2z"/><path d="M22 3h-6a4 4 0 00-4 4v14a3 3 0 013-3h7z"/></svg>
          </a>
          ${referralNote(svc)}
          ${manualEnvFields ? `<div class="setup-fields">${manualEnvFields}</div>` : ''}
        </div>
      </div>`;
    }

    const envFields = envInputFields(svc, svc.docker && svc.docker.env);

    return `
    <div class="card setup-card" id="setup-${svc.slug}">
      <div class="card-header">
        <h3 class="section-title">${escapeHtml(svc.name)}</h3>
        <span class="badge badge-category">${escapeHtml(categoryLabel(svc.category))}</span>
      </div>

      <div class="setup-body">
        <p class="setup-line setup-links">
          <span>${t('app.wiz.new_to', { name: escapeHtml(svc.name) })}</span>
          <a href="${escapeHtml(signupUrl)}" target="_blank" rel="noopener" class="btn btn-primary btn-sm">
            ${accountRequired ? t('app.wiz.sign_up') : t('app.wiz.visit')}
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
          </a>
          ${dashboardLink}
          <a href="https://geiserx.github.io/CashPilot/guides/${svc.slug}/" target="_blank" rel="noopener" class="btn btn-ghost btn-sm">
            ${t('app.wiz.setup_guide')}
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 3h6a4 4 0 014 4v14a3 3 0 00-3-3H2z"/><path d="M22 3h-6a4 4 0 00-4 4v14a3 3 0 013-3h7z"/></svg>
          </a>
        </p>
        ${referralNote(svc)}
        ${accountRequired ? `<p class="setup-line muted">${t('app.wiz.have_account')}</p>` : ''}
      </div>

      <!-- IP attribution and LAN isolation, before the Deploy button. Filled
           by loadDeployRisk once the forms are in the DOM. -->
      <div class="deploy-risk-card setup-risk" data-slug="${escapeHtml(svc.slug)}" style="display:none;">
        <div class="deploy-risk-body"></div>
      </div>

      ${envFields}

      ${svc.has_collector ? collectorCredentialsNotice(svc.slug) : ''}

      ${(() => {
        const onlineWorkers = onlineDeployWorkers(workers);
        const { rows: workerRows, allDeployed } = workerCheckboxList(svc, onlineWorkers, 'setup-deploy-worker-cb');

        if (onlineWorkers.length === 0) {
          return `<p class="setup-line muted">${t('app.wiz.no_workers')}</p>`;
        }

        if (allDeployed) {
          return `<p class="setup-line"><span class="status-dot running"></span> ${t('app.wiz.deployed_everywhere')}</p>`;
        }

        return `
        <div class="setup-workers">
          <div class="form-label">${t('app.wiz.deploy_to')}</div>
          <div id="setup-worker-list-${svc.slug}">${workerRows}</div>
          ${svc.custom ? '' : routeChoiceSection(svc)}
        </div>
        <div class="setup-deploy">
          <button class="btn btn-primary" data-action="deployService" data-a1="${svc.slug}"${_isOwner ? '' : ` disabled title="${t('app.owner_required')}"`}>
            ${t('app.wiz.deploy_name', { name: escapeHtml(svc.name) })}
          </button>
          <span class="deploy-status" id="deploy-status-${svc.slug}"></span>
        </div>`;
      })()}
    </div>`;
  }

  // Deploy `slug` to the given worker node ids: collect the env inputs, validate the
  // required fields, POST per worker, and surface each per-worker failure. Shared by both
  // deploy entry points (the setup wizard and the catalog/detail view) so validation and
  // error reporting are identical — the detail view previously skipped validation and
  // swallowed server errors silently.
  // Ask preflight about every target node, and put anything it objects to in
  // front of the user before the deploy rather than after.
  //
  // Returns true to proceed. A preflight that cannot be reached returns TRUE:
  // the check is advice, and failing to fetch advice is not grounds for
  // blocking a deploy the user asked for. Silence here means "no opinion", not
  // "no risk", which is why nothing is displayed in that case either.
  async function _confirmPreflight(slug, workerIds) {
    let assessments;
    try {
      // Every worker in THIS deploy is passed along, so each assessment can see
      // the others. Asking per worker in isolation meant two machines behind one
      // connection warned about nothing — neither had the service yet, so
      // neither counted against the other (CashPilot-3tr).
      const planned = workerIds.join(',');
      // The copies asked of each worker: without it, a worker that already runs
      // the service is replaced, which is no second device.
      assessments = await Promise.all(
        workerIds.map(id => {
          const n = _instancesFor(slug, id);
          const copies = n === undefined ? '' : `&instances=${encodeURIComponent(n)}`;
          return api(
            `/api/services/${slug}/preflight?worker_id=${encodeURIComponent(id)}&planned=${encodeURIComponent(planned)}${copies}`
          );
        })
      );
    } catch (err) {
      console.warn('Preflight unavailable, proceeding:', err);
      return true;
    }

    // Show the hosting terms when the selected box reports a hosting exit.
    // Keep routine advice out of the confirmation.
    const serious = [];
    assessments.forEach((a, i) => {
      (a && a.findings ? a.findings : [])
        .filter(f => f.verdict === 'will_earn_nothing' || f.kind === 'hosting_note' || a.blocking)
        .forEach(f => serious.push({worker: workerIds[i], message: f.message}));
    });
    if (!serious.length) return true;

    const lines = serious.map(s => `• ${s.message}`).join('\n\n');
    return window.confirm(
      t('app.dep.preflight_confirm', { slug, lines })
    );
  }

  // The device names a deploy of `slug` with `env` would rename, one line per
  // name ("box: label old -> new"), named by box, and the ids of those boxes.
  // A box whose deploy with `env` would lack a required value cannot be renamed
  // this way: it goes to `skipped`, with what it lacks. A box whose original is
  // renamed but whose proxied copies kept the old name (their rebuild failed or
  // was skipped) goes to `copyLines`/`copyIds`: only those copies are rebuilt.
  // Throws when the check fails.
  async function _deviceRenameLines(slug, workerIds, env) {
    const answers = await Promise.all(workerIds.map(id =>
      api(`/api/deploy/${encodeURIComponent(slug)}/device-names?worker_id=${encodeURIComponent(id)}`, { method: 'POST', body: { env } })
    ));
    const lines = [], skipped = [], skippedIds = [], ids = [], copyLines = [], copyIds = [];
    answers.forEach((a, i) => {
      const box = (a && a.worker) || t('app.dep.node_n', { id: workerIds[i] });
      const renames = (a && a.renames) || [];
      const copies = (a && a.copies) || [];
      if (!renames.length && copies.length) {
        copyIds.push(workerIds[i]);
        copies.forEach(c => copyLines.push(t('app.dep.copy_old_name', { box, copy: c })));
        return;
      }
      if (!renames.length) return;
      const missing = (a && a.missing) || [];
      if (missing.length) {
        skipped.push(t('app.dep.rename_missing', { box, missing: missing.join(', ') }));
        skippedIds.push(workerIds[i]);
        return;
      }
      ids.push(workerIds[i]);
      renames.forEach(r => lines.push(`• ${box}: ${r.label} ${r.old} -> ${r.new}`));
    });
    return { lines, skipped, skippedIds, ids, copyLines, copyIds };
  }

  // A box that still runs under the old shared device name ("cashpilot-cashpilot")
  // keeps it unless the user agrees to the new one: a new name is a new device to
  // the provider. Ask once for every node in this deploy, showing each name
  // old -> new. Returns true to rename. A check that cannot be reached returns
  // false, which keeps every name as it is.
  async function _confirmDeviceRenames(slug, workerIds, env) {
    let lines, skipped;
    try {
      ({ lines, skipped } = await _deviceRenameLines(slug, workerIds, env));
    } catch (err) {
      console.warn('Device-name check unavailable, keeping names:', err);
      return false;
    }
    if (!lines.length) return false;
    return window.confirm(skipped.length
      ? t('app.dep.rename_confirm_skipped', { slug, lines: lines.join('\n'), skipped: skipped.join('\n') })
      : t('app.dep.rename_confirm', { slug, lines: lines.join('\n') }));
  }

  // -----------------------------------------------------------
  // Wallet seed kept in the node's own file (catalog seed_file,
  // app/wallet_seed.py). The phrase never reaches CashPilot's database: the
  // worker that runs the node makes or takes it, and this page shows a new
  // one once. Nothing here stores it; the modal forgets it when it closes.
  // -----------------------------------------------------------
  let _walletFieldSeq = 0;

  function walletSeedField(svc, env) {
    const n = ++_walletFieldSeq;
    const name = `wallet-${svc.slug}-${n}`;
    return `
      <div class="form-group wallet-seed" data-wallet-slug="${escapeHtml(svc.slug)}">
        <div class="form-label">${escapeHtml(env.label || t('app.wallet.label'))}</div>
        <label class="wallet-choice"><input type="radio" name="${name}" value="generate" checked
          data-action="walletChoice" data-a1="event"> ${t('app.wallet.create')}</label>
        <label class="wallet-choice"><input type="radio" name="${name}" value="import"
          data-action="walletChoice" data-a1="event"> ${t('app.wallet.import')}</label>
        <textarea class="form-input wallet-phrase" rows="2" autocomplete="off" autocapitalize="off"
          spellcheck="false" placeholder="${t('app.wallet.phrase_placeholder')}" hidden></textarea>
        <div class="form-hint">${t('app.wallet.hint')}</div>
      </div>`;
  }

  function walletChoice(event) {
    const input = event && event.target;
    const box = input && input.closest('.wallet-seed');
    const phrase = box && box.querySelector('.wallet-phrase');
    if (!phrase) return;
    phrase.hidden = input.value !== 'import';
    if (phrase.hidden) phrase.value = '';
  }

  // The wallet box of this service's visible deploy form, or null.
  function _walletBox(slug) {
    const boxes = [...document.querySelectorAll(`.wallet-seed[data-wallet-slug="${CSS.escape(slug)}"]`)];
    return boxes.find(b => b.offsetParent !== null) || boxes[0] || null;
  }

  // {mode, phrase} for the deploy body, undefined for a service without the
  // box, or null when the form is not ready (it says why).
  function _walletRequest(slug, workerIds) {
    const box = _walletBox(slug);
    if (!box) return undefined;
    const picked = box.querySelector('input[type="radio"]:checked');
    const mode = picked ? picked.value : 'generate';
    if (mode !== 'import') return { mode: 'generate' };
    const area = box.querySelector('.wallet-phrase');
    const phrase = (area && area.value || '').trim().toLowerCase().split(/\s+/).filter(Boolean).join(' ');
    if (!phrase) {
      if (area) area.style.borderColor = 'var(--error)';
      toast(t('app.wallet.paste'), 'warning');
      return null;
    }
    if (workerIds.length > 1) {
      toast(t('app.wallet.one_node'), 'warning');
      return null;
    }
    if (area) area.style.borderColor = '';
    return { mode: 'import', phrase };
  }

  // Three distinct word positions (1-based), in order.
  function _quizPositions(count) {
    const picks = new Set();
    const pool = new Uint32Array(16);
    while (picks.size < Math.min(3, count)) {
      crypto.getRandomValues(pool);
      for (const v of pool) {
        if (picks.size >= Math.min(3, count)) break;
        picks.add((v % count) + 1);
      }
    }
    return [...picks].sort((a, b) => a - b);
  }

  // Shows a phrase in the wallet modal. reveal: no quiz, just Close. Resolves
  // when it closes, to true when the owner proved they wrote it down.
  function showWalletPhrase(phrase, { title, intro, address, reveal = false } = {}) {
    const overlay = document.getElementById('wallet-modal');
    const body = document.getElementById('wallet-modal-body');
    if (!overlay || !body) return Promise.resolve(false);
    let words = String(phrase || '').split(' ');
    document.getElementById('wallet-modal-title').textContent = title || t('app.wallet.new_title');
    return new Promise((resolve) => {
      let done = false;
      let proved = false;
      const finish = () => {
        if (done) return;
        done = true;
        watcher.disconnect();
        // Forget it: nothing of the phrase stays in the page.
        body.innerHTML = '';
        words = [];
        overlay.classList.remove('open');
        if (!reveal && !proved) {
          toast(t('app.wallet.closed_early'), 'warning');
        }
        resolve(proved);
      };
      const watcher = new MutationObserver(() => { if (!overlay.classList.contains('open')) finish(); });
      const showWords = () => {
        body.innerHTML = `
          <p>${escapeHtml(intro || '')}</p>
          <ol class="seed-words">${words.map(w => `<li><span class="seed-word">${escapeHtml(w)}</span></li>`).join('')}</ol>
          ${address ? `<p class="form-hint">${t('app.wallet.address_html', { address: escapeHtml(address) })}</p>` : ''}
          <p class="inline-note inline-note-warn">${t('app.wallet.warning')}</p>
          <div class="modal-actions modal-actions-end">
            ${reveal
              ? `<button class="btn btn-primary" id="wallet-close-btn">${t('app.close')}</button>`
              : `<button class="btn btn-primary" id="wallet-next-btn">${t('app.wallet.wrote_down')}</button>`}
          </div>`;
        const next = document.getElementById('wallet-next-btn');
        if (next) next.onclick = showQuiz;
        const close = document.getElementById('wallet-close-btn');
        if (close) close.onclick = finish;
      };
      const showQuiz = () => {
        const asked = _quizPositions(words.length);
        body.innerHTML = `
          <p>${t('app.wallet.quiz_intro')}</p>
          ${asked.map(n => `
            <div class="form-group">
              <label class="form-label" for="wallet-quiz-${n}">${t('app.wallet.word_n', { n })}</label>
              <input class="form-input wallet-quiz" id="wallet-quiz-${n}" data-pos="${n}" autocomplete="off" autocapitalize="off" spellcheck="false">
            </div>`).join('')}
          <div id="wallet-quiz-error" class="form-error" style="display:none;"></div>
          <div class="modal-actions modal-actions-end">
            <button class="btn btn-ghost" id="wallet-back-btn">${t('app.wallet.show_again')}</button>
            <button class="btn btn-primary" id="wallet-check-btn">${t('app.wallet.check')}</button>
          </div>`;
        document.getElementById('wallet-back-btn').onclick = showWords;
        document.getElementById('wallet-check-btn').onclick = () => {
          const wrong = [...body.querySelectorAll('.wallet-quiz')]
            .filter(i => i.value.trim().toLowerCase() !== words[Number(i.dataset.pos) - 1]);
          if (wrong.length) {
            const err = document.getElementById('wallet-quiz-error');
            err.textContent = t('app.wallet.mismatch', { n: wrong.length, list: wrong.map(i => i.dataset.pos).join(', ') });
            err.style.display = '';
            return;
          }
          proved = true;
          toast(t('app.wallet.confirmed'), 'success');
          finish();
        };
        const first = body.querySelector('.wallet-quiz');
        if (first) setTimeout(() => first.focus(), 50);
      };
      showWords();
      watcher.observe(overlay, { attributes: true, attributeFilter: ['class'] });
      overlay.classList.add('open');
    });
  }

  async function revealWalletSeed(slug, workerId, workerName) {
    try {
      const res = await api(`/api/services/${encodeURIComponent(slug)}/wallet-seed/reveal?worker_id=${encodeURIComponent(workerId)}`,
        { method: 'POST', body: {} });
      await showWalletPhrase(res.phrase, {
        title: t('app.wallet.reveal_title'),
        intro: t('app.wallet.reveal_intro', { slug, box: workerName }),
        reveal: true,
      });
    } catch (err) {
      toast(t('app.wallet.reveal_failed', { error: err.message }), 'error');
    }
  }

  async function _deployToWorkers(slug, workerIds, { rescaleOnly = false, routeRoot = null, replaceWorkers = [] } = {}) {
    const statusEl = document.getElementById(`deploy-status-${slug}`);
    // Read once, before anything waits: a Route box changed while the first
    // box deploys must not send another route (or none) to the next one.
    const route = _routeChoice(routeRoot, slug);
    const routeAcks = _routeAcks(routeRoot, slug);
    if (workerIds.length === 0) {
      toast(t('app.dep.pick_worker'), 'warning');
      if (statusEl) statusEl.textContent = t('app.dep.pick_node');
      return;
    }

    // Collect env vars (only env inputs carry data-key, not the worker checkboxes).
    const envInputs = document.querySelectorAll(`input[data-slug="${slug}"][data-key]`);
    const env = {};
    let missingRequired = false;
    let invalidInput = null;
    envInputs.forEach(input => {
      if (input.pattern && input.value.trim()) {
        input.value = input.value.trim();
        if (!input.checkValidity()) invalidInput ||= input;
      }
      env[input.dataset.key] = input.value;
      if (input.required && !input.value.trim() && !rescaleOnly) {
        input.style.borderColor = 'var(--error)';
        missingRequired = true;
      } else {
        input.style.borderColor = '';
      }
    });

    if (invalidInput) {
      invalidInput.reportValidity();
      if (statusEl) statusEl.textContent = t('app.dep.invalid_field');
      return;
    }

    if (missingRequired) {
      toast(t('app.dep.fill_required'), 'warning');
      if (statusEl) statusEl.textContent = '';
      return;
    }

    const wallet = rescaleOnly ? undefined : _walletRequest(slug, workerIds);
    if (wallet === null) {
      if (statusEl) statusEl.textContent = '';
      return;
    }

    // Preflight, at the deploy step — which is where the backend's own comments
    // say it belongs, "not buried in an FAQ". It has been computed since 1.10.x
    // and asked by nothing.
    //
    // WARNS, never blocks: the assessment itself reports blocking=false and
    // says "you can deploy it anyway", and the machine running this knows
    // things CashPilot does not. But the findings include cases like a second
    // instance behind one IP, where some providers forfeit the account balance
    // — a real loss, and worth one question before it happens rather than an
    // explanation afterwards.
    if (!await _confirmPreflight(slug, workerIds)) {
      if (statusEl) statusEl.textContent = '';
      return;
    }

    const renameDevices = await _confirmDeviceRenames(slug, workerIds, env);

    if (statusEl) {
      statusEl.innerHTML = `<span class="spinner spinner-inline"></span> ${t('app.dep.deploying')}`;
    }

    let ok = 0, fail = 0;
    const links = new Map();
    const newWallets = [];
    for (const wid of workerIds) {
      try {
        const body = { env };
        if (replaceWorkers.includes(wid)) body.replace_existing = true;
        if (wallet) body.wallet_seed = wallet;
        if (renameDevices) body.rename_devices = true;
        const image = _imageChoice(slug);
        if (image !== undefined) body.image = image;
        const instances = _instancesFor(slug, wid);
        if (instances !== undefined) body.instances = instances;
        if (route !== undefined) body.route = route;
        if (route > 0) body.route_acknowledged = routeAcks;
        const res = await api(`/api/deploy/${slug}?worker_id=${wid}`, { method: 'POST', body });
        ok++;
        if (res && res.wallet && res.wallet.phrase) newWallets.push({ wid, wallet: res.wallet });
        if (res && res.device_link && res.device_link.id) links.set(res.device_link.id, res.device_link);
        // A redeploy rebuilds from the RECORDED spec where it diverges from
        // the catalog. The API has always reported what it kept; nothing
        // rendered it, so the operator saw a plain success while e.g. their
        // typed-in catalog values were quietly superseded (CashPilot-23yb).
        const kept = res && res.kept_from_previous_deployment;
        if (Array.isArray(kept) && kept.length) {
          toast(t('app.dep.redeploy_notes', { slug, notes: kept.join('; ') }), 'warning');
        }
      } catch (err) {
        fail++;
        toast(t('app.dep.worker_failed', { id: wid, error: err.message }), 'error');
      }
    }

    if (statusEl) {
      statusEl.textContent = fail === 0 ? t('app.dep.deployed_to', { n: ok }) : t('app.dep.ok_failed', { ok, fail });
      statusEl.style.color = fail === 0 ? 'var(--success)' : 'var(--error)';
    }
    _showDeviceLink(slug, statusEl, [...links.values()]);
    // Last, one at a time: each new wallet's phrase is on screen once.
    if (wallet) {
      const area = _walletBox(slug) && _walletBox(slug).querySelector('.wallet-phrase');
      if (area) area.value = '';
    }
    for (const { wid, wallet: made } of newWallets.splice(0)) {
      const label = document.querySelector(`[data-wid="${CSS.escape(String(wid))}"]`)?.closest('label');
      const where = (label && label.textContent.trim().split('\n')[0].trim()) || t('app.dep.worker_id', { id: wid });
      await showWalletPhrase(made.phrase, {
        intro: t('app.wallet.created_intro', { slug, box: where }),
        address: made.address,
      });
    }
    if (ok > 0) {
      toast(t('app.dep.deployed_toast', { slug, n: ok }), 'success');
      if (!wizardState.deployed.includes(slug)) {
        wizardState.deployed.push(slug);
      }
    }
    return ok;
  }

  // Some providers pay a device only once the user adds its id to their
  // account (EarnApp, ProxyRack); a node left unlinked earns for nobody, and
  // nothing else on screen says so. The deploy API returns the step from the
  // catalog's `device_link` block, so it is shown right where the deploy succeeded.
  function _showDeviceLink(slug, statusEl, links) {
    const id = `device-link-${slug}`;
    document.getElementById(id)?.remove();
    const row = statusEl && statusEl.parentElement;
    if (!row || !links.length) return;
    // Added through the provider's API with the saved collector credentials:
    // nothing left to do, so say so instead of asking for a manual step.
    const todo = links.filter(l => !l.registered);
    const done = links.filter(l => l.registered);
    const item = (l, linkBtn) => `
      <div class="device-link-item">
        <code class="device-link-id">${escapeHtml(l.id)}</code>
        <button class="btn btn-ghost btn-sm" data-action="copyText" data-a1="${escapeHtml(l.id)}">${t('app.ref.copy')}</button>
        ${linkBtn && l.url ? `<a href="${escapeHtml(l.url)}" target="_blank" rel="noopener" class="btn btn-primary btn-sm">${t('app.link.open')}</a>` : ''}
      </div>`;
    row.insertAdjacentHTML('afterend', `
      <div class="device-link${todo.length ? '' : ' device-link-done'}" id="${id}">
        ${todo.length ? `
        <div class="device-link-title">${t('app.link.title')}</div>
        <p class="device-link-text">${escapeHtml(todo[0].steps)}</p>
        ${todo.some(l => l.retrying) ? `<p class="device-link-text">${t('app.link.retrying')}</p>` : ''}
        ${todo.map(l => item(l, true)).join('')}` : ''}
        ${done.length ? `
        <div class="device-link-title">${t('app.link.added')}</div>
        <p class="device-link-text">${t('app.link.added_text')}</p>
        ${done.map(l => item(l, false)).join('')}` : ''}
      </div>`);
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      toast(t('app.copied'), 'success');
    } catch (err) {
      // No clipboard outside a secure context (plain http on a LAN address).
      window.prompt(t('app.copy_this'), text);
    }
  }

  // Parse the checked worker ids from a checkbox selector (dropping any unparseable id).
  function _selectedWorkerIds(selector) {
    return Array.from(document.querySelectorAll(selector))
      .map(cb => parseInt(cb.dataset.wid))
      .filter(id => !Number.isNaN(id));
  }

  async function deployService(slug) {
    // Record that a deploy was ATTEMPTED, separately from whether it worked.
    // Step 3 offers "Skip to Summary", so a user can select services and reach
    // the final screen having deployed nothing — and an empty `deployed` list
    // then looks identical to every deploy having failed.
    wizardState.deployAttempted = true;
    const picked = `.setup-deploy-worker-cb[data-slug="${slug}"]:checked:not(:disabled)`;
    const fresh = _selectedWorkerIds(`${picked}:not([data-routed])`);
    // A routed box ticked to change its route reuses its recorded credentials.
    const switching = _selectedWorkerIds(`${picked}[data-routed]`);
    await _deployToWorkers(slug, [...fresh, ...switching], {
      rescaleOnly: fresh.length === 0 && switching.length > 0,
      routeRoot: document.getElementById('wizard-setup-forms'),
    });
  }

  // -----------------------------------------------------------
  // Catalog
  // -----------------------------------------------------------
  let catalogServices = [];
  // The deploy targets, so Add stays hidden when a service runs on all of them.
  // null when the targets are unknown: then Add stays visible.
  let catalogOnlineWorkers = null;

  async function loadCatalog() {
    const [services, workers] = await Promise.all([
      api('/api/services/available').catch(() => []),
      _isOwner ? api('/api/workers').catch(() => null) : Promise.resolve(null),
    ]);
    catalogServices = services;
    catalogOnlineWorkers = Array.isArray(workers) ? onlineDeployWorkers(workers) : null;
    filterCatalog();
    loadCustomServices();
  }

  function filterCatalog() {
    const activeTab = document.querySelector('.filter-tab.active');
    const category = activeTab ? activeTab.dataset.category : 'all';
    const query = (document.getElementById('catalog-search')?.value || '').toLowerCase();

    let filtered = catalogServices;
    if (category !== 'all') {
      filtered = filtered.filter(s => s.category === category);
    }
    if (query) {
      filtered = filtered.filter(s =>
        (s.name || '').toLowerCase().includes(query) ||
        (s.short_description || '').toLowerCase().includes(query)
      );
    }

    const container = document.getElementById('catalog-grid');
    if (!container) return;

    if (filtered.length === 0) {
      container.innerHTML = `<div class="empty-state"><div class="empty-state-text">${t('app.cat.no_match')}</div></div>`;
      return;
    }

    // What you run, then what you could add. Within each, the catalog's
    // priority first (1 first, the services that pay the project best), then
    // the rest by category and name. Priority first matches the API, the
    // wizard, the README and Desktop. The tail sorts by category like Desktop,
    // but compares names without case, so "io.net" sorts among the i's.
    const rank = x => (Number.isInteger(x.priority) ? x.priority : Infinity);
    const byPriority = (x, y) => (rank(x) - rank(y))
      || String(x.category).localeCompare(String(y.category))
      || String(x.name).toLowerCase().localeCompare(String(y.name).toLowerCase());
    const running = filtered.filter(x => x.deployed).sort(byPriority);
    const rest = filtered.filter(x => !x.deployed).sort(byPriority);
    const group = (label, rows) => rows.length
      ? `<tbody class="cat-group"><tr class="cat-group-row"><th colspan="7" scope="colgroup">${label} <span class="count">${rows.length}</span></th></tr>${rows.map(renderCatalogCard).join('')}</tbody>`
      : '';
    container.innerHTML = `
      <table class="catalog-table">
        <thead><tr>
          <th scope="col">${t('app.cat.col.service')}</th><th scope="col" class="cat-col-kind">${t('app.cat.col.kind')}</th><th scope="col" class="cat-col-plat">${t('app.cat.col.runs_on')}</th>
          <th scope="col" class="num">${t('app.cat.col.estimate')}</th><th scope="col" class="cat-col-grade">${t('app.cat.col.grade')}</th><th scope="col" class="cat-col-needs">${t('app.cat.col.needs')}</th><th scope="col"><span class="sr-only">${t('app.cat.col.action')}</span></th>
        </tr></thead>
        ${group(t('app.cat.running'), running)}${group(t('app.cat.not_running'), rest)}
      </table>`;
  }

  function renderCatalogCard(svc) {
    const earning = svc.earnings
      ? t('app.cat.estimate', { low: svc.earnings.monthly_low, high: svc.earnings.monthly_high, per: escapeHtml(svc.earnings.per || t('app.cat.month')) })
      : t('app.cat.varies');
    const isDeployed = svc.deployed || false;
    const broken = svc.status === 'broken';

    const hasDocker = svc.docker && svc.docker.image;
    let actionBtn;
    // Add opens the setup wizard on this one service, and only the owner can
    // deploy, so only the owner gets it. Details opens the modal (description,
    // payouts, deploy risk, custom image, instances), as Deploy used to.
    const addLink = (title) => _isOwner
      ? `<a href="/setup?service=${encodeURIComponent(svc.slug)}" class="btn btn-ghost btn-sm" title="${escapeHtml(title)}">${t('app.cat.add')}</a>`
      : '';
    const detailsBtn = `<button class="btn btn-link btn-sm" data-action="openServiceDetail" data-a1="${svc.slug}">${t('app.cat.details')}</button>`;
    if (isDeployed) {
      // The wizard can only add boxes that do not run it yet. On every online
      // target already, Add would only open a form with nothing to deploy.
      const everywhere = catalogOnlineWorkers && catalogOnlineWorkers.length > 0
        && catalogOnlineWorkers.every(w => runsOn(w, svc.slug));
      actionBtn = [
        `<button class="btn btn-secondary btn-sm" data-action="openServiceDetail" data-a1="${svc.slug}">${t('app.cat.manage')}</button>`,
        hasDocker && !everywhere ? addLink(t('app.cat.run_another', { name: svc.name })) : '',
      ].filter(Boolean).join(' ');
    } else if (hasDocker) {
      actionBtn = [addLink(t('app.cat.add_name', { name: svc.name })), detailsBtn].filter(Boolean).join(' ');
    } else {
      const url = (svc.referral && svc.referral.signup_url) || svc.website || '#';
      // Visit opens the signup page. Where the signup never reads the code from
      // the link (Dawn's extension), the code sits right beside it, or a user
      // who signs up from this row credits nobody.
      const code = svc.referral && svc.referral.code_entry;
      actionBtn = [
        `<a href="${escapeHtml(url)}" target="_blank" rel="noopener" class="btn btn-ghost btn-sm">${t('app.wiz.visit')}</a>`,
        // On its own line: the action cell does not wrap, and both buttons on one
        // line push a phone-width table past the screen edge.
        code ? `<span class="cat-act-code">${codeEntryCopy(svc, t('app.cat.code', { code: escapeHtml(code) }))}</span>` : '',
      ].filter(Boolean).join(' ');
    }

    // Platform list — add Docker if service has a Docker image
    const allPlatforms = [...(svc.platforms || [])];
    if (hasDocker && !allPlatforms.includes('docker')) allPlatforms.unshift('docker');
    const platforms = allPlatforms.map(p => escapeHtml(p)).join(', ');

    const needs = [];
    if (svc.requirements && svc.requirements.residential_ip) needs.push(t('app.cat.needs_residential'));
    if (svc.requirements && svc.requirements.gpu) needs.push('GPU');
    const state = broken
      ? `<span class="state state-fail">${t('app.cat.broken')}</span>`
      : '';

    return `
    <tr class="service-card cat-row${isDeployed ? ' service-card-deployed' : ''}" data-slug="${svc.slug}">
      <td class="cat-svc">
        <span class="service-name">${escapeHtml(svc.name)}</span>${state}
        <span class="service-desc">${escapeHtml(svc.short_description || '')}</span>
      </td>
      <td class="cat-kind">${escapeHtml(categoryLabel(svc.category, true))}</td>
      <td class="cat-plat">${platforms || `<span class="muted">${t('app.cat.none_listed')}</span>`}</td>
      <td class="num cat-est">${escapeHtml(earning)}</td>
      <td class="cat-grade">${(svc.rating_result && svc.rating_result.rated)
        ? `<a class="grade-link" href="https://geiserx.github.io/CashPilot/ratings/#${encodeURIComponent(svc.slug || '')}" target="_blank" rel="noopener" aria-label="${escapeHtml(t('app.cat.grade_label', { name: svc.name, grade: svc.rating_result.grade }))}">${gradeBadge(svc.rating_result)}</a>`
        : gradeBadge(svc.rating_result)}</td>
      <td class="cat-needs">${needs.length ? escapeHtml(needs.join(', ')) : `<span class="muted">${t('app.cat.nothing_special')}</span>`}</td>
      <td class="cat-act">${actionBtn}</td>
    </tr>`;
  }

  // The provider's grade, computed server-side from the published criteria
  // (app/ratings.py). The badge's tooltip is the worst con.
  function gradeBadge(r) {
    if (!r || !r.rated) return `<span class="muted">${t('app.rating.not_rated')}</span>`;
    const top = [r.thin_evidence ? t('app.rating.thin', { n: r.unknown_count }) : '',
      (r.top_cons && r.top_cons[0]) ? r.top_cons[0].text : ''].filter(Boolean).join(' ');
    const g = escapeHtml(r.grade);
    return `<span class="grade-badge grade-${g.toLowerCase()}" title="${escapeHtml(top)}">${g}</span>`;
  }

  function ratingBlock(svc) {
    const r = svc.rating_result;
    const how = `https://geiserx.github.io/CashPilot/ratings/#${encodeURIComponent(svc.slug || '')}`;
    if (!r || !r.rated) {
      return `<div class="sd-block sd-rating"><h4 class="sd-h">${t('app.rating.title')}</h4>
        <p class="muted">${t('app.rating.not_yet')} <a href="https://geiserx.github.io/CashPilot/ratings/" target="_blank" rel="noopener">${t('app.rating.how')}</a></p></div>`;
    }
    const cited = (item) => `<li>${escapeHtml(item.text)}
        <span class="sd-rating-src">${t('app.rating.cited_html', { url: escapeHtml(item.source), date: escapeHtml(item.checked_on) })}</span></li>`;
    const caps = (r.caps || []).map(c => `<li>${escapeHtml(c.reason)}</li>`).join('');
    const cons = (r.top_cons || []).map(cited).join('');
    const pros = (r.pros || []).map(cited).join('');
    return `
    <div class="sd-block sd-rating">
      <h4 class="sd-h">${t('app.rating.title')}</h4>
      <div class="sd-rating-head">${gradeBadge(r)}
        <span class="sd-rating-score">${escapeHtml(r.summary || '')}</span>
        <a href="${how}" target="_blank" rel="noopener">${t('app.rating.how')}</a></div>
      ${caps ? `<ul class="sd-rating-caps">${caps}</ul>` : ''}
      ${cons ? `<div class="detail-label">${t('app.rating.top_cons')}</div><ul class="sd-rating-list">${cons}</ul>` : ''}
      ${pros ? `<details class="sd-rating-pros"><summary>${t('app.rating.pros', { n: (r.pros || []).length })}</summary><ul class="sd-rating-list">${pros}</ul></details>` : ''}
    </div>`;
  }

  function initCatalogFilters() {
    document.querySelectorAll('.filter-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        document.querySelectorAll('.filter-tab').forEach(tab => tab.classList.remove('active'));
        tab.classList.add('active');
        filterCatalog();
      });
    });

    const searchInput = document.getElementById('catalog-search');
    if (searchInput) {
      searchInput.addEventListener('input', debounce(filterCatalog, 200));
    }
  }

  // -----------------------------------------------------------
  // Service Detail Modal
  // -----------------------------------------------------------
  // Cached workers for detail modal
  let _detailWorkers = [];

  async function openServiceDetail(slug) {
    openModal('service-detail-modal');
    const body = document.getElementById('service-detail-body');
    const title = document.getElementById('service-detail-title');
    if (body) body.innerHTML = '<div class="spinner spinner-block"></div>';
    if (title) title.textContent = 'Loading...';

    try {
      const [svc, workers] = await Promise.all([
        api(`/api/services/${slug}`),
        api('/api/workers').catch(() => []),
      ]);
      _detailWorkers = workers;
      if (title) title.textContent = svc.name;
      if (body) body.innerHTML = renderServiceDetail(svc, workers);
      // After the markup is in the DOM, not before: the container it fills is
      // created by the line above. Not awaited, so a slow earnings query never
      // holds up the rest of the modal.
      loadPayoutProgress();
      loadDeployRisk();
      loadRouteChoices(svc.slug, body);
      loadDeviceRenames(slug);
    } catch (err) {
      if (body) body.innerHTML = `<p class="empty-state-text">${t('app.detail.load_failed', { error: escapeHtml(err.message) })}</p>`;
    }
  }

  // The Image box under Advanced. Blank means the catalog image. It is filled
  // with the image the deployments already use when they all agree, and only
  // sent when the operator changes it: a box left alone keeps each worker's
  // recorded choice. Running instances are redeployed with it from here,
  // because the node list cannot select a node that already runs the service.
  function imageChoiceSection(svc, workers) {
    const catalogImage = (svc.docker && svc.docker.image) || '';
    const chosen = Object.values(svc.custom_images || {});
    const common = chosen.length && chosen.every(i => i === chosen[0]) ? chosen[0] : '';
    const running = (workers || []).filter(w => w.status === 'online' && runsOn(w, svc.slug));
    const name = escapeHtml(svc.name);
    return `
      <details class="image-choice"${chosen.length ? ' open' : ''}>
        <summary>${t('app.image.advanced')}</summary>
        <div class="form-group">
          <label class="form-label" for="image-input-${escapeHtml(svc.slug)}">${t('app.image.label')}</label>
          <input class="form-input" type="text" id="image-input-${escapeHtml(svc.slug)}" data-initial="${escapeHtml(common)}"
                 placeholder="${escapeHtml(catalogImage)}" value="${escapeHtml(common)}" spellcheck="false" autocomplete="off">
          <div class="form-hint">${catalogImage
            ? t('app.image.hint_catalog_html', { image: escapeHtml(catalogImage), name })
            : t('app.image.hint', { name })}</div>
          ${chosen.length > 1 && !common ? `<div class="form-hint">${t('app.image.mixed')}</div>` : ''}
        </div>
        ${running.length && _isOwner ? `<button class="btn btn-secondary btn-sm" data-action="redeployWithImage" data-a1="${escapeHtml(svc.slug)}">${t('app.image.redeploy_running')}</button>
          <span id="image-status-${escapeHtml(svc.slug)}" class="form-hint"></span>` : ''}
      </details>`;
  }

  // The image to send with a deploy: undefined when the box is absent or left
  // as it was (the server then keeps each worker's recorded choice), "" to go
  // back to the catalog image, otherwise the typed reference.
  function _imageChoice(slug) {
    const input = document.getElementById(`image-input-${slug}`);
    if (!input) return undefined;
    const value = input.value.trim();
    return value === (input.dataset.initial || '') ? undefined : value;
  }

  // One click from the "Needs fixing" row: no env and no image, so the server
  // rebuilds from this worker's recorded settings and the current catalog.
  // For a container changed on purpose. The server ties the mute to the
  // catalog as it is now, so a later catalog fix to this service shows again.
  async function ignoreDrift(slug, workerId) {
    if (!window.confirm(t('app.drift.ignore_confirm', { slug }))) return;
    try {
      await api(`/api/services/${slug}/drift/ignore?worker_id=${workerId}`, { method: 'POST' });
      toast(t('app.drift.ignored', { slug }), 'success');
      loadServicesTable();
    } catch (err) {
      toast(t('app.drift.ignore_failed', { error: err.message }), 'error');
    }
  }

  // The boxes that run `slug` now, from the workers the detail modal loaded,
  // a box that runs it only through its route included.
  function _runningWorkerIds(slug) {
    return (_detailWorkers || [])
      .filter(w => w.status === 'online' && runsOn(w, slug))
      .map(w => w.id);
  }

  // Boxes that already run a service cannot be ticked in the deploy form, and a
  // service with one device per IP has no Instances box, so this is how a
  // running deployment still on the old shared device name gets its own: the
  // service page says which boxes, and one button renames them after a confirm.
  async function loadDeviceRenames(slug) {
    const el = document.getElementById(`device-rename-${slug}`);
    if (!el) return;
    const ids = _runningWorkerIds(slug);
    if (!ids.length) return;
    let check;
    try {
      check = await _deviceRenameLines(slug, ids, {});
    } catch (err) {
      console.warn('Could not check device names:', err);
      return;
    }
    const { lines, skipped, skippedIds, copyLines } = check;
    if (!lines.length && !skipped.length && !copyLines.length) return;
    // A box the one-click redeploy cannot rename gets a note, not the button,
    // and its own redeploy that sends the values typed in the deploy form: the
    // form cannot tick a box that already runs the service.
    // Only proxied copies left: their box's device name or id changed (a
    // rename, or Change in Settings > Device ids), not the old shared name.
    const onlyCopies = !lines.length && !skipped.length;
    el.innerHTML = onlyCopies
      ? `${t('app.rename.copies_note', { slug: escapeHtml(slug) })}
        <button class="btn btn-secondary btn-sm" data-action="renameDevices" data-a1="${escapeHtml(slug)}">${t('app.rename.rebuild_copies')}</button>`
      : `${t('app.rename.shared_note', { n: lines.length + skipped.length + copyLines.length, slug: escapeHtml(slug) })}
      ${lines.length || copyLines.length ? `<button class="btn btn-secondary btn-sm" data-action="renameDevices" data-a1="${escapeHtml(slug)}">${t('app.rename.give_own')}</button>` : ''}
      ${skipped.map((line, i) => `<br>${escapeHtml(line)}
        <button class="btn btn-secondary btn-sm" data-action="redeployWithValues" data-a1="${escapeHtml(slug)}" data-a2="${escapeHtml(String(skippedIds[i]))}">${t('app.rename.redeploy_values')}</button>`).join('')}`;
    el.style.display = '';
  }

  async function renameDevices(slug) {
    let ids, copyIds, copyLines;
    try {
      ({ ids, copyIds, copyLines } = await _deviceRenameLines(slug, _runningWorkerIds(slug), {}));
    } catch (err) {
      toast(t('app.rename.check_failed', { error: err.message }), 'error');
      return;
    }
    const base = ids.length && await _confirmDeviceRenames(slug, ids, {});
    const copies = copyIds.length && window.confirm(t('app.rename.copies_confirm', { slug, lines: copyLines.join('\n') }));
    if (!base && !copies) return;
    let ok = 0;
    // A box with only copies left: rebuild those, never its renamed original.
    const jobs = [
      ...(base ? ids : []).map(id => [id, `/api/deploy/${slug}?worker_id=${id}`, { method: 'POST', body: { env: {}, rename_devices: true, replace_existing: true } }]),
      ...(copies ? copyIds : []).map(id => [id, `/api/deploy/${slug}/device-names/copies?worker_id=${id}`, { method: 'POST', body: { replace_existing: true } }]),
    ];
    for (const [id, url, opts] of jobs) {
      try {
        // No env: the redeploy keeps every setting this box was deployed with.
        const res = await api(url, opts);
        // A proxied copy that kept its old name says so here.
        const kept = res && res.kept_from_previous_deployment;
        if (Array.isArray(kept) && kept.length) toast(t('app.dep.redeploy_notes_colon', { slug, notes: kept.join('; ') }), 'warning');
        ok++;
      } catch (err) {
        const box = ((_detailWorkers || []).find(w => w.id === id) || {}).name || t('app.dep.node_n', { id });
        toast(t('app.rename.failed', { box, error: err.message }), 'error');
      }
    }
    if (ok) toast(t('app.rename.done', { slug, n: ok }), 'success');
    openServiceDetail(slug);
  }

  // A box that runs the service with no record of a required value: redeploy
  // it with what is typed in the deploy form, which a blank redeploy cannot send.
  async function redeployWithValues(slug, workerId) {
    // The form is folded away under the boxes list; open it so a missing value shows.
    document.querySelectorAll('details.sd-more').forEach(d => { d.open = true; });
    // The form shows catalog defaults, not what this box was deployed with, so
    // a stored value with no default is a blank required box here. The server
    // checks required values against the box's record and names any still
    // missing, so the blank boxes are not refused in the browser.
    const routeRoot = document.getElementById('service-detail-body');
    const wid = parseInt(workerId);
    if (await _deployToWorkers(slug, [wid], { rescaleOnly: true, routeRoot, replaceWorkers: [wid] })) openServiceDetail(slug);
  }

  async function redeployOnWorker(slug, workerId) {
    if (!window.confirm(t('app.redeploy.confirm', { slug }))) return;
    const body = { env: {}, replace_existing: true };
    if (await _confirmDeviceRenames(slug, [workerId], {})) body.rename_devices = true;
    try {
      const res = await api(`/api/deploy/${slug}?worker_id=${workerId}`, { method: 'POST', body });
      // The same notes the deploy form shows: what the redeploy kept, and a
      // device the provider still needs linked, or it earns for nobody.
      const kept = res && res.kept_from_previous_deployment;
      if (Array.isArray(kept) && kept.length) toast(t('app.dep.redeploy_notes_colon', { slug, notes: kept.join('; ') }), 'warning');
      const link = res && res.device_link;
      if (link && link.id && !link.registered) toast(t('app.redeploy.link_device', { slug, id: link.id, steps: link.steps || '' }), 'warning');
      toast(t('app.redeploy.done', { slug }), 'success');
      loadServicesTable();
    } catch (err) {
      toast(t('app.redeploy.failed', { error: err.message }), 'error');
    }
  }

  async function redeployWithImage(slug) {
    const input = document.getElementById(`image-input-${slug}`);
    const statusEl = document.getElementById(`image-status-${slug}`);
    if (!input) return;
    const image = input.value.trim();
    const workers = (await api('/api/workers')).filter(w => w.status === 'online' && runsOn(w, slug));
    if (!workers.length) { toast(t('app.image.none_running'), 'warning'); return; }
    const what = image || t('app.image.catalog');
    if (!window.confirm(t('app.image.confirm', { slug, boxes: workers.map(w => w.name).join(', '), image: what }))) return;
    const renameDevices = await _confirmDeviceRenames(slug, workers.map(w => w.id), {});
    if (statusEl) statusEl.textContent = t('app.image.redeploying');
    let ok = 0, fail = 0;
    for (const w of workers) {
      try {
        // No env: a blank redeploy keeps the credentials this worker was deployed with.
        const body = { env: {}, image, replace_existing: true };
        if (renameDevices) body.rename_devices = true;
        const res = await api(`/api/deploy/${slug}?worker_id=${w.id}`, { method: 'POST', body });
        // A proxied copy that kept its old name says so here.
        const kept = res && res.kept_from_previous_deployment;
        if (Array.isArray(kept) && kept.length) toast(t('app.dep.redeploy_notes_on', { slug, box: w.name, notes: kept.join('; ') }), 'warning');
        ok++;
      } catch (err) {
        fail++;
        toast(t('app.image.redeploy_failed', { box: w.name, error: err.message }), 'error');
      }
    }
    input.dataset.initial = image;
    if (statusEl) {
      statusEl.textContent = fail === 0 ? t('app.image.redeployed', { n: ok }) : t('app.dep.ok_failed', { ok, fail });
      statusEl.style.color = fail === 0 ? 'var(--success)' : 'var(--error)';
    }
  }

  function renderServiceDetail(svc, workers) {
    const earning = svc.earnings
      ? t('app.detail.estimate', { low: svc.earnings.monthly_low, high: svc.earnings.monthly_high, per: svc.earnings.per || t('app.cat.month') })
      : t('app.detail.varies');

    const isDeployed = svc.deployed || false;
    const dashboardUrl = (svc.cashout && svc.cashout.dashboard_url) || svc.website || '';
    const signupUrl = svc.referral && svc.referral.signup_url
      ? svc.referral.signup_url
      : svc.website || '#';

    // --- Info grid (no referral bonus) ---
    let html = `
    <p class="sd-desc">${escapeHtml(svc.description || svc.short_description || '')}</p>
    <!-- Filled in by loadPayoutProgress once the modal is in the DOM. Hidden
         until it has a real answer: an empty "Payout progress" heading on a
         service that has never been collected is worse than no heading. -->
    <div id="payout-progress-card" data-slug="${escapeHtml(svc.slug || '')}"
         data-currency="${escapeHtml(svc.cashout?.currency || '')}" class="sd-block" style="display:none;">
      <h4 class="sd-h">${t('app.detail.payout_progress')}</h4>
      <div id="payout-progress-body"></div>
    </div>
    <!-- What running this actually does with the machine and the connection.
         Filled by loadDeployRisk once the modal exists. This belongs at the
         deploy step rather than in a FAQ nobody opens, which is what the
         backend's own comments say and what it never got. -->
    <div id="deploy-risk-card" class="sd-block deploy-risk-card" data-slug="${escapeHtml(svc.slug || '')}" style="display:none;">
      <div id="deploy-risk-body" class="deploy-risk-body"></div>
    </div>
    ${svc.custom ? '' : ratingBlock(svc)}
    <div class="detail-grid sd-facts">
      <div class="detail-item">
        <div class="detail-label">${t('app.detail.category')}</div>
        <div class="detail-value">${escapeHtml(categoryLabel(svc.category))}</div>
      </div>
      <div class="detail-item">
        <div class="detail-label">${t('app.detail.estimated')}</div>
        <div class="detail-value num">${earning}</div>
      </div>
      <div class="detail-item">
        <div class="detail-label">${t('app.detail.payout')}</div>
        <div class="detail-value">${t('app.detail.payout_value', { methods: escapeHtml((svc.payment?.methods || []).join(', ') || t('app.detail.na')), min: escapeHtml(svc.payment?.minimum_payout || t('app.detail.na')) })}</div>
      </div>
    </div>`;

    // --- Setup guide link ---
    const guideUrl = `https://geiserx.github.io/CashPilot/guides/${svc.slug}/`;
    html += `
    <div class="sd-links">
      <a href="${guideUrl}" target="_blank" rel="noopener" class="btn btn-ghost btn-sm">
        ${t('app.wiz.setup_guide')}
      </a>`;

    // --- Provider dashboard for deployed services, and Sign Up always ---
    // A deploy does not prove an account (a MystNodes node runs before anyone
    // signs up), and the referral only counts through this link.
    if (isDeployed && dashboardUrl) {
      html += `
        <a href="${escapeHtml(dashboardUrl)}" target="_blank" rel="noopener" class="btn btn-ghost btn-sm">
          ${t('app.detail.provider_dashboard')}
        </a>`;
    }
    html += `
        <a href="${escapeHtml(signupUrl)}" target="_blank" rel="noopener" class="btn ${isDeployed ? 'btn-ghost' : 'btn-primary'} btn-sm">
          ${!hasAccount(svc) ? t('app.wiz.visit_name', { name: escapeHtml(svc.name) }) : isDeployed ? t('app.detail.new_sign_up', { name: escapeHtml(svc.name) }) : t('app.detail.sign_up_or_in', { name: escapeHtml(svc.name) })}
        </a>
        ${referralNote(svc)}`;
    html += `</div>`;

    // --- Deploy section (worker-aware) ---
    // Built separately so a service that already runs shows its instances
    // first and keeps the deploy form folded away below them.
    // A custom service has no guide, sign-up, payout or risk facts to show:
    // its block says what it is and what CashPilot does and does not grant it.
    const infoHtml = svc.custom ? customServiceBanner(svc) : html;
    html = '';
    const hasDocker = svc.docker && svc.docker.image;
    if (hasDocker) {
      const envFields = envInputFields(svc, svc.docker.env, { withId: false, withHint: false });

      // Worker deploy targets
      const onlineWorkers = onlineDeployWorkers(workers);
      let workerRows = '';
      let allDeployed = true;
      ({ rows: workerRows, allDeployed } = workerCheckboxList(svc, onlineWorkers, 'deploy-worker-cb'));

      if (onlineWorkers.length === 0) {
        workerRows = `<p class="muted">${t('app.wiz.no_workers')}</p>`;
      }

      html += isDeployed ? '' : `<h4 class="sd-h">${t('app.detail.deploy')}</h4>`;
      html += envFields;
      // A custom service's image is edited in its definition, not per deploy.
      if (!svc.custom) html += imageChoiceSection(svc, workers);

      // Earnings tracking uses SEPARATE credentials (Settings → Earnings collection).
      // The fields above only configure the container that earns; they don't
      // let CashPilot read your balance. Make that explicit at deploy time.
      if (svc.has_collector) {
        html += collectorCredentialsNotice(svc.slug);
      }

      // A service that can run more than once keeps its node list on screen
      // when every node has it, since the Instances boxes are how it scales.
      if (allDeployed && onlineWorkers.length > 0 && !(svc.max_instances > 1)) {
        html += `<p class="sd-note">${t('app.detail.everywhere')}</p>`;
      } else {
        html += `
        <div class="sd-targets">
          <div class="form-label">${t('app.wiz.deploy_to')}</div>
          <div id="deploy-worker-list">${workerRows}</div>
          ${instancesHint(svc)}
          ${svc.custom ? '' : routeChoiceSection(svc)}
        </div>
        <div class="sd-actions">
          <button class="btn btn-primary" data-action="deployServiceToWorkers" data-a1="${svc.slug}"${_isOwner ? '' : ` disabled title="${t('app.owner_required')}"`}>${t('app.detail.deploy')}</button>
          <span id="deploy-status-${svc.slug}" class="sd-status"></span>
        </div>`;
      }
    }

    const deployHtml = html;
    html = '';

    // --- Container management (per worker) ---
    const onlineWorkers = (workers || []).filter(w => w.status === 'online');
    const instances = [];
    for (const w of onlineWorkers) {
      const copies = workerCopies(w, svc.slug)
        .sort((a, b) => (a.instance || 1) - (b.instance || 1));
      for (const container of copies) instances.push({ worker: w, container, several: copies.length > 1 });
    }

    if (instances.length > 0) {
      // Copies on one box count once: the heading is about boxes.
      const boxCount = new Set(instances.map(i => i.worker.id)).size;
      html += `
      <div class="sd-block sd-instances">
        <h4 class="sd-h">${t('app.detail.deployed_on', { n: boxCount })}</h4>
        ${_isOwner && !svc.unmanaged ? `<!-- Filled by loadDeviceRenames when a box still has the old shared device name. -->
        <div class="sd-note device-rename" id="device-rename-${escapeHtml(svc.slug)}" style="display:none;"></div>` : ''}`;
      for (const inst of instances) {
        const s = inst.container.status || 'unknown';
        const st = instanceState(s);
        html += `
        <div class="sd-inst">
          <span class="cell cell-${st}"></span>
          <strong class="sd-inst-box">${escapeHtml(inst.worker.name)}${inst.several ? ` #${inst.container.instance || 1}` : ''}</strong>
          <span class="state state-${st}">${escapeHtml(s)}</span>
          ${routeBadge(inst.container)}
          ${(svc.custom_images || {})[String(inst.worker.id)] ? `<span class="muted" title="${escapeHtml(svc.custom_images[String(inst.worker.id)])}">${t('app.detail.custom_image')}</span>` : ''}
          ${_canWrite ? `<div class="sd-inst-actions">
            <button class="btn btn-secondary btn-sm" data-action="workerAction" data-a1="${svc.slug}" data-a2="restart" data-a3="${inst.worker.id}" data-a4="${inst.container.instance || 1}">${t('app.row.restart')}</button>
            <button class="btn btn-secondary btn-sm" data-action="workerAction" data-a1="${svc.slug}" data-a2="stop" data-a3="${inst.worker.id}" data-a4="${inst.container.instance || 1}">${t('app.row.stop')}</button>
            <button class="btn btn-ghost btn-sm" data-action="loadWorkerLogs" data-a1="${svc.slug}" data-a2="${inst.worker.id}" data-a3="logs-${svc.slug}-${inst.worker.id}-${inst.container.instance || 1}" data-a4="${inst.container.instance || 1}">${t('app.logs')}</button>
            ${_isOwner && (inst.container.instance || 1) === 1 && ((svc.docker && svc.docker.env) || []).some(e => e.seed_file) ? `<button class="btn btn-ghost btn-sm" data-action="revealWalletSeed" data-a1="${escapeHtml(svc.slug)}" data-a2="${inst.worker.id}" data-a3="${escapeHtml(inst.worker.name)}">${t('app.detail.show_seed')}</button>` : ''}
            ${(inst.container.instance || 1) === 1 ? `<button class="btn btn-danger btn-sm" data-action="${svc.custom ? 'removeCustomFromBox' : 'removeService'}" data-a1="${escapeHtml(svc.slug)}" data-a2="${inst.worker.id}" data-a3="${escapeHtml(inst.worker.name)}">${t('app.detail.remove_box')}</button>` : ''}
          </div>` : ''}
        </div>
        <div class="log-viewer log-viewer-inline" id="logs-${svc.slug}-${inst.worker.id}-${inst.container.instance || 1}" style="display:none;"></div>`;
      }
      html += `</div>`;
    }
    html += restoreLeftoverRows(svc, onlineWorkers, instances);

    const instancesHtml = html;
    if (isDeployed && instancesHtml) {
      return infoHtml.replace('<p class="sd-desc">', instancesHtml + '<p class="sd-desc">')
        + (deployHtml ? `<details class="sd-more"><summary>${svc.custom ? t('app.detail.more_boxes') : t('app.detail.more_boxes_image')}</summary>${deployHtml}</details>` : '');
    }
    return infoHtml + deployHtml + instancesHtml;
  }

  // A restore that did not finish can leave only its half-written volume on a
  // box, with no container of the service to list. The worker names those
  // services in its heartbeat, so each such box still gets its Remove from this
  // box, which offers the owner the delete of that data.
  function restoreLeftoverRows(svc, onlineWorkers, instances) {
    const listed = new Set(instances.map(i => i.worker.id));
    const boxes = onlineWorkers.filter((w) => {
      const left = (w.system_info || {}).restore_unfinished;
      return !listed.has(w.id) && Array.isArray(left) && left.includes(svc.slug);
    });
    if (!boxes.length) return '';
    return `
      <div class="sd-block sd-instances">
        <h4 class="sd-h">${t('app.detail.restore_unfinished')}</h4>${boxes.map(w => `
        <div class="sd-inst">
          <span class="cell cell-warn"></span>
          <strong class="sd-inst-box">${escapeHtml(w.name)}</strong>
          <span class="state state-warn">${t('app.detail.partial_restore')}</span>
          ${_canWrite ? `<div class="sd-inst-actions">
            <button class="btn btn-danger btn-sm" data-action="removeService" data-a1="${escapeHtml(svc.slug)}" data-a2="${w.id}" data-a3="${escapeHtml(w.name)}" data-a4="leftover">${t('app.detail.remove_box')}</button>
          </div>` : ''}
        </div>`).join('')}
      </div>`;
  }

  // -----------------------------------------------------------
  // Custom services: the user's own image, deployed with the catalog's
  // restrictions and no earnings collector (app/custom_services.py).
  // -----------------------------------------------------------
  const CUSTOM_SERVICE_TITLE = t('app.custom.title');

  function customServiceBanner(svc) {
    const def = svc.definition || {};
    const docker = svc.docker || {};
    const mem = (docker.resources && docker.resources.mem_limit) || def.mem_limit || '';
    const warnings = (svc.warnings || []).map(w => `<p class="form-hint text-warn">${escapeHtml(w)}</p>`).join('');
    const actions = _isOwner ? `
        <div class="sd-actions">
          <button class="btn btn-secondary btn-sm" data-action="openCustomServiceEditor" data-a1="${escapeHtml(svc.slug)}">${t('app.custom.edit')}</button>
          <button class="btn btn-danger btn-sm" data-action="deleteCustomService" data-a1="${escapeHtml(svc.slug)}">${t('app.custom.delete')}</button>
        </div>` : '';
    return `
    <div class="inline-note inline-note-warn sd-block custom-service-banner">
      ${def.data_path
        ? t('app.custom.banner_data_html', { title: CUSTOM_SERVICE_TITLE, image: escapeHtml(docker.image || def.image || ''), mem: escapeHtml(mem), path: escapeHtml(def.data_path) })
        : t('app.custom.banner_html', { title: CUSTOM_SERVICE_TITLE, image: escapeHtml(docker.image || def.image || ''), mem: escapeHtml(mem) })}
      ${warnings}${actions}
    </div>
    <p class="sd-desc">${escapeHtml(svc.description || '')}</p>`;
  }

  let _customServices = [];

  async function loadCustomServices() {
    const box = document.getElementById('custom-services');
    if (!box) return;
    try {
      _customServices = await api('/api/custom-services');
    } catch (err) {
      _customServices = [];
    }
    if (!_customServices.length && !_isOwner) {
      box.innerHTML = '';
      return;
    }
    const rows = _customServices.map(svc => `
      <tr class="service-card cat-row" data-slug="${escapeHtml(svc.slug)}">
        <td class="cat-svc">
          <span class="service-name">${escapeHtml(svc.name)}</span>
          <span class="badge badge-category" title="${CUSTOM_SERVICE_TITLE}">${t('app.row.custom')}</span>
          <span class="service-desc"><code>${escapeHtml((svc.docker && svc.docker.image) || '')}</code></span>
        </td>
        <td class="cat-act"><button class="btn btn-secondary btn-sm" data-action="openServiceDetail" data-a1="${escapeHtml(svc.slug)}">${t('app.cat.manage')}</button></td>
      </tr>`).join('');
    box.innerHTML = `
      <div class="custom-services-head">
        <h3 class="sd-h">${t('app.custom.yours')}</h3>
        ${_isOwner ? `<button class="btn btn-secondary btn-sm" data-action="openCustomServiceEditor">${t('app.custom.add')}</button>` : ''}
      </div>
      ${rows
        ? `<table class="catalog-table"><tbody>${rows}</tbody></table>`
        : `<p class="sd-note">${t('app.custom.empty')}</p>`}`;
  }

  function _customEnvRow(env) {
    const e = env || { key: '', value: '', secret: false, is_set: false };
    const placeholder = e.secret && e.is_set ? t('app.custom.unchanged') : t('app.custom.value');
    return `
      <div class="custom-env-row">
        <input class="form-input" type="text" data-env="key" value="${escapeHtml(e.key || '')}" placeholder="${t('app.custom.name_placeholder')}" spellcheck="false" autocomplete="off" aria-label="${t('app.custom.var_name')}">
        <input class="form-input" type="${e.secret ? 'password' : 'text'}" data-env="value" value="${escapeHtml(e.secret ? '' : (e.value || ''))}" placeholder="${placeholder}" spellcheck="false" autocomplete="off" aria-label="${t('app.custom.value_label')}">
        <label class="custom-env-secret"><input type="checkbox" data-env="secret"${e.secret ? ' checked' : ''}> ${t('app.custom.secret')}</label>
        <button class="btn btn-ghost btn-sm" data-action="removeCustomEnvRow" data-a1="event">${t('app.cashout.remove')}</button>
      </div>`;
  }

  function addCustomEnvRow() {
    document.getElementById('custom-env-rows')?.insertAdjacentHTML('beforeend', _customEnvRow());
  }

  function removeCustomEnvRow(event) {
    event.target.closest('.custom-env-row')?.remove();
  }

  async function openCustomServiceEditor(slug) {
    let def = { name: '', image: '', env: [], command: '', data_path: '', mem_limit: '512m' };
    if (slug) {
      try {
        def = (await api(`/api/services/${encodeURIComponent(slug)}`)).definition || def;
      } catch (err) {
        toast(t('app.custom.load_failed', { slug, error: err.message }), 'error');
        return;
      }
    }
    closeModal('service-detail-modal');
    const title = document.getElementById('custom-service-title');
    const body = document.getElementById('custom-service-body');
    if (!body) return;
    if (title) title.textContent = slug ? t('app.custom.edit_name', { name: def.name }) : t('app.custom.add');
    body.innerHTML = `
      <div class="inline-note inline-note-warn">
        ${t('app.custom.editor_warning')}
      </div>
      <div class="form-group">
        <label class="form-label" for="custom-name">${t('app.custom.name')}</label>
        <input class="form-input" type="text" id="custom-name" maxlength="60" value="${escapeHtml(def.name)}" autocomplete="off">
      </div>
      <div class="form-group">
        <label class="form-label" for="custom-image">${t('app.image.label')}</label>
        <input class="form-input" type="text" id="custom-image" value="${escapeHtml(def.image)}" placeholder="publisher/image:1.2.3" spellcheck="false" autocomplete="off">
        <div class="form-hint">${t('app.custom.image_hint')}</div>
      </div>
      <div class="form-group">
        <div class="form-label">${t('app.custom.env')}</div>
        <div id="custom-env-rows">${(def.env || []).map(_customEnvRow).join('')}</div>
        <button class="btn btn-ghost btn-sm" data-action="addCustomEnvRow">${t('app.custom.add_var')}</button>
        <div class="form-hint">${t('app.custom.env_hint')}</div>
      </div>
      <div class="form-group">
        <label class="form-label" for="custom-command">${t('app.custom.command')}</label>
        <input class="form-input" type="text" id="custom-command" value="${escapeHtml(def.command || '')}" spellcheck="false" autocomplete="off">
      </div>
      <div class="form-group">
        <label class="form-label" for="custom-data-path">${t('app.custom.data_path')}</label>
        <input class="form-input" type="text" id="custom-data-path" value="${escapeHtml(def.data_path || '')}" placeholder="/data" spellcheck="false" autocomplete="off">
        <div class="form-hint">${t('app.custom.data_hint')}</div>
      </div>
      <div class="form-group">
        <label class="form-label" for="custom-mem">${t('app.custom.mem')}</label>
        <input class="form-input" type="text" id="custom-mem" value="${escapeHtml(def.mem_limit || '512m')}" placeholder="512m" spellcheck="false" autocomplete="off">
      </div>
      <div id="custom-service-notes"></div>
      <div class="sd-actions">
        <button class="btn btn-primary" data-action="saveCustomService" data-a1="${escapeHtml(slug || '')}">${t('app.save')}</button>
        <button class="btn btn-ghost" data-action="closeModal" data-a1="custom-service-modal">${t('app.cancel')}</button>
        <span id="custom-service-status" class="sd-status"></span>
      </div>`;
    openModal('custom-service-modal');
  }

  async function saveCustomService(slug) {
    const value = (id) => (document.getElementById(id)?.value || '').trim();
    const env = Array.from(document.querySelectorAll('#custom-env-rows .custom-env-row')).map(row => ({
      key: row.querySelector('[data-env="key"]').value.trim(),
      value: row.querySelector('[data-env="value"]').value,
      secret: row.querySelector('[data-env="secret"]').checked,
    })).filter(e => e.key || e.value);
    const body = {
      name: value('custom-name'),
      image: value('custom-image'),
      env,
      command: value('custom-command'),
      data_path: value('custom-data-path'),
      mem_limit: value('custom-mem'),
    };
    const statusEl = document.getElementById('custom-service-status');
    const notes = document.getElementById('custom-service-notes');
    if (statusEl) statusEl.textContent = t('app.custom.saving');
    let res;
    try {
      res = slug
        ? await api(`/api/custom-services/${encodeURIComponent(slug)}`, { method: 'PUT', body })
        : await api('/api/custom-services', { method: 'POST', body });
    } catch (err) {
      if (statusEl) statusEl.textContent = '';
      toast(err.message, 'error');
      return;
    }
    const target = slug || res.slug;
    const warnings = (res.warnings || []).map(w => `<p class="form-hint text-warn">${escapeHtml(w)}</p>`).join('');
    loadCustomServices();
    if (slug && res.deployed) {
      // The running containers keep the old definition until they are redeployed.
      if (statusEl) statusEl.textContent = t('app.custom.saved_status');
      if (notes) {
        notes.innerHTML = `${warnings}
          <div class="inline-note">${t('app.custom.old_settings')}
            <button class="btn btn-secondary btn-sm" data-action="redeployCustomService" data-a1="${escapeHtml(target)}">${t('app.custom.redeploy_running')}</button>
          </div>`;
      }
      return;
    }
    (res.warnings || []).forEach(w => toast(w, 'warning'));
    toast(slug ? t('app.custom.saved') : t('app.custom.added'), 'success');
    closeModal('custom-service-modal');
    openServiceDetail(target);
  }

  async function redeployCustomService(slug) {
    const workers = (await api('/api/workers')).filter(w => w.status === 'online' && (w.containers || []).some(c => c.slug === slug));
    if (!workers.length) { toast(t('app.image.none_running'), 'warning'); return; }
    if (!window.confirm(t('app.custom.redeploy_confirm', { slug, boxes: workers.map(w => w.name).join(', ') }))) return;
    let ok = 0;
    for (const w of workers) {
      try {
        await api(`/api/deploy/${encodeURIComponent(slug)}?worker_id=${w.id}`, { method: 'POST', body: { env: {}, replace_existing: true } });
        ok++;
      } catch (err) {
        toast(t('app.image.redeploy_failed', { box: w.name, error: err.message }), 'error');
      }
    }
    if (ok) toast(t('app.custom.redeployed', { slug, n: ok }), 'success');
    closeModal('custom-service-modal');
    loadServicesTable();
  }

  async function deleteCustomService(slug) {
    if (!window.confirm(t('app.custom.delete_confirm', { slug }))) return;
    try {
      await api(`/api/custom-services/${encodeURIComponent(slug)}`, { method: 'DELETE' });
    } catch (err) {
      toast(err.message, 'error');
      return;
    }
    toast(t('app.custom.deleted', { slug }), 'success');
    closeModal('service-detail-modal');
    loadCustomServices();
  }

  // Removing a custom container from a box. Its data volume stays unless the
  // owner asks for it to go too: the worker cannot judge whether a volume of
  // a service its catalog does not know is irreplaceable, so it only deletes
  // one with allow_delete_critical and the set of volumes it named, which is
  // owner-only on the server too and asks for the owner's password (api()
  // shows the prompt) after the owner reviewed that set.
  async function removeCustomFromBox(slug, workerId, boxName) {
    if (!window.confirm(t('app.custom.remove_confirm', { slug, box: boxName }))) return;
    let query = `?worker_id=${encodeURIComponent(workerId)}`;
    const withData = _isOwner && window.confirm(t('app.custom.remove_data_confirm', { box: boxName }));
    if (withData) query += '&delete_volumes=true';
    const path = `/api/services/${encodeURIComponent(slug)}${query}`;
    try {
      let result;
      try {
        result = await api(path, { method: 'DELETE' });
      } catch (err) {
        // The box names the volumes it cannot judge (its catalog does not know
        // this service): the owner reviews exactly those, then the password.
        if (!withData || err.code !== 'critical_volume') throw err;
        if (_desktopKeepsCriticalData(slug, workerId, boxName)) return;
        const reviewed = confirmCriticalVolumes(slug, boxName, err.refusal);
        if (!reviewed) return;
        result = await api(`${path}&allow_delete_critical=true&${reviewed}`, { method: 'DELETE', body: {} });
      }
      _removeToast(t('app.svc.removed_from', { slug, box: boxName }), result, boxName);
    } catch (err) {
      toast(t('app.custom.remove_failed', { error: err.message }), 'error');
    }
    openServiceDetail(slug);
  }

  async function deployServiceToWorkers(slug) {
    const picked = `.deploy-worker-cb[data-slug="${slug}"]:checked:not(:disabled)`;
    const fresh = _selectedWorkerIds(`${picked}:not([data-routed])`);
    // A routed box ticked to leave its route (_routeSwitchBoxes) already runs the service.
    const switching = _selectedWorkerIds(`${picked}[data-routed]`);
    // Unlocked by Direct, a routed box leaves its route only by its own tick,
    // never through a changed Instances count (route 0 would go with it).
    const switchable = _selectedWorkerIds(`.deploy-worker-cb[data-slug="${slug}"][data-routed]:not(:disabled)`);
    const rescaled = _rescaledWorkerIds(slug).filter((id) => !fresh.includes(id) && !switchable.includes(id));
    if (rescaled.length && !window.confirm(t('app.dep.rescale_confirm', { slug }))) return;
    const again = [...switching, ...rescaled];
    // Only nodes that already run the service: their recorded credentials are
    // reused, so the empty credential boxes are not missing.
    await _deployToWorkers(slug, [...fresh, ...again], {
      rescaleOnly: fresh.length === 0 && again.length > 0,
      replaceWorkers: rescaled,
      routeRoot: document.getElementById('service-detail-body'),
    });
  }

  // `?instance=` only for copies 2+: the first copy is addressed the way it always was.
  function _instanceQuery(instance) {
    const n = parseInt(instance);
    return n > 1 ? `&instance=${n}` : '';
  }

  async function workerAction(slug, action, workerId, instance) {
    try {
      const out = await api(`/api/services/${slug}/${action}?worker_id=${workerId}${_instanceQuery(instance)}`, { method: 'POST' });
      // A routed copy the worker started or stopped, but could not make that last through a power cut.
      if (out && out.warning) toast(out.warning, 'warning');
      // Refresh the modal
      openServiceDetail(slug);
    } catch (err) {
      toast(t('app.svc.action_failed', { action, error: err.message }), 'error');
    }
  }

  async function loadWorkerLogs(slug, workerId, elemId, instance) {
    const viewer = document.getElementById(elemId);
    if (!viewer) return;
    if (viewer.style.display === 'none') {
      viewer.style.display = 'block';
      logNote(viewer, 'Loading...');
      try {
        const data = await api(`/api/services/${slug}/logs?worker_id=${workerId}&lines=100${_instanceQuery(instance)}`);
        renderLogs(viewer, data.logs || '(no logs)');
      } catch (err) {
        logNote(viewer, `Error: ${err.message}`);
      }
    } else {
      viewer.style.display = 'none';
    }
  }

  async function loadDetailLogs(slug) {
    // Legacy — kept for backward compat
    const viewer = document.getElementById(`detail-logs-${slug}`);
    if (!viewer) return;
    logNote(viewer, 'Loading...');
    try {
      const data = await api(`/api/services/${slug}/logs?lines=100`);
      renderLogs(viewer, data.logs || '(no logs)');
    } catch (err) {
      logNote(viewer, `Error: ${err.message}`);
    }
  }

  // -----------------------------------------------------------
  // Settings
  // -----------------------------------------------------------
  // Which stored credentials are about to stop working.
  //
  // Several providers issue session cookies measured in hours. When one dies,
  // collection stops and nothing says so — the dashboard keeps showing the last
  // balance it managed to read, which is indistinguishable from a service that
  // simply is not earning. This is the warning before that, not after.
  //
  // Worst first, because the only rows that need acting on are the bad ones.
  const CREDENTIAL_STATUS = {
    likely_expired: {rank: 0, label: t('app.credh.likely_expired'), tone: 'text-fail'},
    expiring_soon: {rank: 1, label: t('app.credh.expiring_soon'), tone: 'text-warn'},
    no_known_expiry: {rank: 2, label: t('app.credh.no_known_expiry'), tone: 'muted'},
    fresh: {rank: 3, label: t('app.credh.fresh'), tone: 'text-ok'},
  };

  async function loadCredentialHealth() {
    const card = document.getElementById('credential-health-card');
    const body = document.getElementById('credential-health-body');
    if (!card || !body) return;

    let rows;
    try {
      rows = await api('/api/credentials/health');
    } catch (err) {
      // Leave it hidden. An empty "Credential health" heading would read as
      // "nothing is configured", which is a different and reassuring claim.
      console.warn('Could not load credential health:', err);
      return;
    }
    const indexLink = document.getElementById('credential-health-link');
    if (!Array.isArray(rows) || !rows.length) {
      card.style.display = 'none';
      if (indexLink) indexLink.hidden = true;
      return;
    }
    if (indexLink) indexLink.hidden = false;

    const meta = status => CREDENTIAL_STATUS[status] || CREDENTIAL_STATUS.no_known_expiry;
    rows.sort((a, b) => meta(a.status).rank - meta(b.status).rank);

    card.style.display = '';
    body.innerHTML = rows.map(row => {
      const info = meta(row.status);
      const age = row.age_hours >= 48
        ? t('app.credh.days_old', { n: Math.round(row.age_hours / 24) })
        : t('app.credh.hours_old', { n: Math.round(row.age_hours) });
      const lifetime = row.expected_lifetime_hours
        ? (row.expected_lifetime_hours >= 48
          ? t('app.credh.lasts_days', { n: Math.round(row.expected_lifetime_hours / 24) })
          : t('app.credh.lasts_hours', { n: row.expected_lifetime_hours }))
        : '';
      // A JWT states its own expiry; that date is the fact, the lifetime a guess.
      const expires = row.expires_at
        ? t('app.credh.expires', { date: new Date(row.expires_at).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) })
        : '';
      // The durable alternative is the actual fix, not a nag: swapping to it
      // ends the expiry cycle instead of restarting it.
      const durable = (row.durable_alternative_missing || []).length
        ? `<div class="credential-health-hint">${t('app.credh.durable', { fields: escapeHtml(row.durable_alternative_missing.join(', ')) })}</div>`
        : '';
      const why = row.why ? `<div class="credential-health-hint">${escapeHtml(row.why)}</div>` : '';
      const needsAction = row.status === 'likely_expired' || row.status === 'expiring_soon';
      return `
        <div class="credential-health-item">
          <div>
            <div class="credential-health-name">${escapeHtml(row.service)} <span class="optional">${escapeHtml(String(row.field).replace(/_/g, ' '))}</span></div>
            <div class="credential-health-detail">${escapeHtml(age)}${escapeHtml(lifetime)}${escapeHtml(expires)}</div>
            ${why}${durable}
          </div>
          <div class="credential-health-actions">
            <span class="credential-health-status ${info.tone}">${escapeHtml(info.label)}</span>
            ${needsAction && _isOwner ? `<button class="btn btn-ghost btn-sm" data-action="openCredentialModal" data-a1="${escapeHtml(row.service)}">${t('app.credh.update')}</button>` : ''}
          </div>
        </div>
      `;
    }).join('');
  }

  async function loadSettings() {
    populateCurrencyDropdown();
    // Independent of /api/config on purpose: a failed config load must not
    // leave the update card stuck on "Loading..." — it has its own error path.
    loadUpdateCard();
    // Same for the device ids: they do not need the config, and loadIdentities
    // writes its own error into its panel.
    loadIdentities();
    try {
      const [config, envInfo, collectorsMeta] = await Promise.all([
        api('/api/config'),
        api('/api/env-info').catch(() => []),
        api('/api/collectors/meta').catch(() => []),
      ]);
      renderEnvVars(envInfo, config);
      renderCollectors(collectorsMeta, config);
      loadCredentialHealth();
    } catch (err) {
      // Say what happened. /api/env-info and /api/collectors/meta each carry
      // their own .catch, so the only call that can reject is /api/config —
      // and its rejection aborts the whole Promise.all before either render
      // runs. Both panels then keep the template's "Loading..." forever, and
      // this catch used to be empty, so nothing ever corrected it: an expired
      // session or a restarting server looked like a page that simply never
      // finished loading (CashPilot-cn3).
      //
      // Every other loader here writes a reason into its own container; this
      // one was the outlier.
      settingsPanelsFailed(err);
    }
  }

  // --- Device ids (issue #740) ----------------------------------------------

  // The ledger's rows as HTML. Pure, so the harness can run it: every value
  // arrives masked, and the full one only ever comes from the reveal route.
  function identityRowsHtml(rows) {
    if (!Array.isArray(rows) || !rows.length) {
      return `<p class="muted">${t('app.ids.empty')}</p>`;
    }
    return rows.map(r => {
      const where = [r.worker, r.copy].filter(Boolean).join(', ');
      const backup = r.kind === 'backup';
      const state = backup
        ? (r.source === 'restore' ? t('app.ids.restored_here') : r.source === 'pending' ? t('app.ids.restore_sent') : t('app.ids.downloaded'))
        : (r.kind === 'manual' ? t('app.ids.entered') : (r.status === 'active' ? t('app.ids.in_use') : t('app.ids.removed')));
      // The ledger's times are UTC, "YYYY-MM-DD HH:MM:SS"; minutes are enough here.
      const when = stamp => (stamp ? t('app.ids.utc', { time: escapeHtml(String(stamp).slice(0, 16)) }) : t('app.place.status_unknown'));
      const seen = `<div class="credential-health-hint">${t('app.ids.seen', { first: when(r.first_seen), last: when(r.last_seen) })}</div>`;
      const reported = r.source === 'node'
        ? `<div class="credential-health-hint">${t('app.ids.by_node')}</div>`
        : (backup ? `<div class="credential-health-hint">${t('app.ids.backup')}</div>` : '');
      const id = escapeHtml(String(r.id));
      const buttons = r.readable
        ? `<button class="btn btn-ghost btn-sm" data-action="revealIdentity" data-a1="${id}">${t('app.ids.show')}</button>
           <button class="btn btn-ghost btn-sm" data-action="copyIdentity" data-a1="${id}">${t('app.ref.copy')}</button>`
        : `<span class="muted">${t('app.ids.unreadable')}</span>`;
      // An unconfirmed deploy's hold only once the server says its deploy can
      // no longer land (r.forgettable): before that the box may still start it.
      const held = r.pending && r.status !== 'retired';
      const forget = r.forgettable
        ? `<button class="btn btn-ghost btn-sm" data-action="forgetIdentity" data-a1="${id}"${held ? ' data-a2="pending"' : ''}>${t('app.attn.forget')}</button>` : '';
      // An id a deploy set that the box runs now: the server decides (r.changeable).
      const change = r.changeable
        ? `<button class="btn btn-ghost btn-sm" data-action="openIdentityChange" data-a1="${id}">${t('app.ids.change')}</button>` : '';
      const unconfirmed = held && !r.forgettable
        ? `<div class="credential-health-hint">${t('app.ids.unconfirmed_deploy')}</div>`
        : (backup && r.source === 'pending' && !r.forgettable
          ? `<div class="credential-health-hint">${t('app.ids.unconfirmed_restore')}</div>` : '');
      return `
        <div class="credential-health-item identity-row" data-identity="${id}">
          <div>
            <div class="credential-health-name">${escapeHtml(r.service)} <span class="optional">${escapeHtml(r.label)}</span></div>
            <div class="credential-health-detail"><code class="identity-value" id="identity-value-${id}">${escapeHtml(r.masked)}</code>
              · ${escapeHtml(where)} · ${escapeHtml(state)}</div>
            ${seen}${reported}${unconfirmed}
            ${r.changeable ? `<div class="identity-change" id="identity-change-${id}"></div>` : ''}
          </div>
          <div class="credential-health-actions">${buttons}${change}${forget}</div>
        </div>`;
    }).join('');
  }

  // The Change form of one row. Pure, so the harness can run it. Its input and
  // its pick box carry the deploy form's data attributes, so "Use one this
  // service had before" and its Use buttons fill it as they fill the deploy form.
  function identityChangeHtml(r) {
    const id = escapeHtml(String(r.id));
    const slug = escapeHtml(r.slug);
    const key = escapeHtml(r.key);
    return `
      <label class="form-label" for="identity-change-value-${id}">${t('app.ids.new_label', { label: escapeHtml(r.label) })}</label>
      <button type="button" class="btn btn-link btn-sm" data-action="pickPreviousIdentity" data-a1="${slug}" data-a2="${key}" data-a3="${escapeHtml(String(r.worker_id))}">${t('app.dep.pick_identity')}</button>
      <input type="text" class="form-input" id="identity-change-value-${id}" data-slug="${slug}" data-key="${key}"
        maxlength="256" autocomplete="off" spellcheck="false">
      <div class="identity-pick" data-pick-slug="${slug}" data-pick-key="${key}"></div>
      <p class="form-hint">${t('app.ids.change_hint', { service: escapeHtml(r.service), box: escapeHtml(r.worker) })}</p>
      <div class="credential-health-actions">
        <button type="button" class="btn btn-primary btn-sm" data-action="changeIdentity" data-a1="${id}">${t('app.ids.change')}</button>
        <button type="button" class="btn btn-ghost btn-sm" data-action="closeIdentityChange">${t('app.cancel')}</button>
      </div>`;
  }

  // The form for an id CashPilot did not deploy with. Pure, so the harness can
  // run it: service and box names come from the catalog and the fleet, as text.
  function identityFieldOptions(svc) {
    const env = ((svc && svc.docker && svc.docker.env) || []).filter(isIdentityField);
    return env.map(e => `<option value="${escapeHtml(e.key)}">${escapeHtml(e.label || e.key)}</option>`).join('');
  }

  function identityFormHtml(services, workers) {
    const svcs = (Array.isArray(services) ? services : []).filter(s => s && s.slug)
      .sort((a, b) => String(a.name || a.slug).localeCompare(String(b.name || b.slug)));
    const boxes = (Array.isArray(workers) ? workers : []).filter(w => w && w.id !== undefined);
    if (!svcs.length || !boxes.length) {
      return `<p class="form-hint">${t('app.ids.add_first')}</p>`;
    }
    const svcOptions = svcs.map(s =>
      `<option value="${escapeHtml(s.slug)}">${escapeHtml(s.name || s.slug)}</option>`).join('');
    const boxOptions = boxes.map(w =>
      `<option value="${escapeHtml(String(w.id))}">${escapeHtml(w.name || t('app.dep.worker_id', { id: w.id }))}</option>`).join('');
    return `
      <p class="form-hint">${t('app.ids.add_hint')}</p>
      <label class="form-label" for="identity-add-service">${t('app.ids.service')}</label>
      <select class="form-input" id="identity-add-service">${svcOptions}</select>
      <label class="form-label" for="identity-add-worker">${t('app.ids.box')}</label>
      <select class="form-input" id="identity-add-worker">${boxOptions}</select>
      <label class="form-label" for="identity-add-copy">${t('app.ids.copy')}</label>
      <input type="number" class="form-input" id="identity-add-copy" min="1" max="32" value="1">
      <label class="form-label" for="identity-add-label">${t('app.ids.field')}</label>
      <input type="text" class="form-input" id="identity-add-label" list="identity-add-fields" maxlength="64"
        autocomplete="off" placeholder="${t('app.ids.field_placeholder')}">
      <datalist id="identity-add-fields">${identityFieldOptions(svcs[0])}</datalist>
      <label class="form-label" for="identity-add-value">${t('app.ids.id')}</label>
      <input type="text" class="form-input" id="identity-add-value" maxlength="256" autocomplete="off" spellcheck="false">
      <div class="credential-health-actions">
        <button type="button" class="btn btn-primary btn-sm" data-action="addIdentity">${t('app.save')}</button>
        <button type="button" class="btn btn-ghost btn-sm" data-action="closeIdentityForm">${t('app.cancel')}</button>
      </div>`;
  }

  // The rows last listed, by id, for the Change form, and the row whose Change form is open.
  let _identityRows = {};
  let _identityChangeOpen = null;

  async function loadIdentities() {
    const body = document.getElementById('identities-container');
    if (!body) return;
    try {
      const rows = await api('/api/identities');
      // The list is drawn again when a change, a save or a forget ends: a Change
      // form opened meanwhile, and what the owner typed in it, stay.
      const open = _identityChangeOpen;
      const input = open === null ? null : document.getElementById(`identity-change-value-${open}`);
      const typed = input ? input.value : '';
      _identityRows = Object.fromEntries((Array.isArray(rows) ? rows : []).map(r => [String(r.id), r]));
      body.innerHTML = identityRowsHtml(rows);
      _identityChangeOpen = null;
      if (open !== null && _identityRows[open] && _identityRows[open].changeable) openIdentityChange(open, typed);
    } catch (err) {
      // A list already drawn stays, with any Change form open on it.
      if (Object.keys(_identityRows).length) {
        toast(t('app.ids.reload_failed', { error: err.message }), 'error');
        return;
      }
      body.innerHTML = `<p class="text-fail">${t('app.ids.load_failed', { error: escapeHtml(err.message) })}</p>`;
    }
  }

  async function openIdentityForm() {
    const box = document.getElementById('identity-add');
    if (!box) return;
    let services;
    let workers;
    try {
      [services, workers] = await Promise.all([api('/api/services/available'), api('/api/workers')]);
    } catch (err) {
      toast(t('app.ids.form_failed', { error: err.message }), 'error');
      return;
    }
    box.innerHTML = identityFormHtml(services, workers);
    const select = document.getElementById('identity-add-service');
    const list = document.getElementById('identity-add-fields');
    if (select && list) {
      select.addEventListener('change', () => {
        list.innerHTML = identityFieldOptions((services || []).find(s => s.slug === select.value));
      });
    }
  }

  function closeIdentityForm() {
    const box = document.getElementById('identity-add');
    if (box) box.innerHTML = '';
  }

  async function addIdentity() {
    // The form this save came from: a Cancel and a new form while it saves must
    // keep the new one and what the owner is typing in it.
    const field = document.getElementById('identity-add-value');
    const val = id => { const el = document.getElementById(id); return el ? el.value.trim() : ''; };
    const body = {
      slug: val('identity-add-service'),
      worker_id: Number(val('identity-add-worker')),
      copy: Number(val('identity-add-copy') || 1),
      label: val('identity-add-label'),
      value: val('identity-add-value'),
    };
    try {
      await api('/api/identities', { method: 'POST', body });
      toast(t('app.ids.saved'), 'success');
      if (field && field.isConnected) closeIdentityForm();
      loadIdentities();
    } catch (err) {
      toast(t('app.ids.save_failed', { error: err.message }), 'error');
    }
  }

  // One Change form at a time: "Use" fills every input of its service and field.
  function closeIdentityChange() {
    document.querySelectorAll('.identity-change').forEach(el => { el.innerHTML = ''; });
    _identityChangeOpen = null;
  }

  function openIdentityChange(id, typed = '') {
    const row = _identityRows[String(id)];
    const box = document.getElementById(`identity-change-${id}`);
    if (!row || !box) return;
    closeIdentityChange();
    box.innerHTML = identityChangeHtml(row);
    _identityChangeOpen = String(id);
    const input = document.getElementById(`identity-change-value-${id}`);
    if (input) {
      input.value = typed;
      input.focus();
    }
  }

  // A redeploy of that one service on that one box. The server checks the value
  // and asks first when another box runs it (api() shows that question).
  async function changeIdentity(id) {
    const row = _identityRows[String(id)];
    const input = document.getElementById(`identity-change-value-${id}`);
    const value = input ? input.value.trim() : '';
    if (!row || !value) { toast(t('app.ids.type_first'), 'warning'); return; }
    if (!window.confirm(t('app.ids.change_confirm', { label: row.label, service: row.service, box: row.worker }))) return;
    try {
      const res = await api(`/api/identities/${encodeURIComponent(id)}/change`, { method: 'POST', body: { value, replace_existing: true } });
      // The notes a redeploy shows: what it kept, a proxied copy left on its old
      // id, and a device the provider still needs linked, or it earns for nobody.
      const kept = res && res.kept_from_previous_deployment;
      if (Array.isArray(kept) && kept.length) toast(t('app.ids.change_notes', { service: row.service, notes: kept.join('; ') }), 'warning');
      const link = res && res.device_link;
      if (link && link.id && !link.registered) toast(t('app.redeploy.link_device', { slug: row.service, id: link.id, steps: link.steps || '' }), 'warning');
      toast(t('app.ids.changed', { service: row.service, box: row.worker, label: row.label }), 'success');
      // This row's form is done; another one opened meanwhile stays open.
      if (_identityChangeOpen === String(id)) closeIdentityChange();
      loadIdentities();
    } catch (err) {
      toast(t('app.ids.change_failed', { error: err.message }), 'error');
    }
  }

  // Every id in full, as a file. The server asks for the password first (api()
  // shows the prompt) and writes the download to the audit log before it answers.
  async function exportIdentities() {
    let data;
    try {
      data = await api('/api/identities/export', { method: 'POST', body: {} });
    } catch (err) {
      toast(t('app.ids.export_failed', { error: err.message }), 'error');
      return;
    }
    const name = `cashpilot-device-ids-${new Date().toISOString().slice(0, 10)}.json`;
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast(t('app.ids.exported', { name }), 'success');
  }

  // Every reveal is written to the audit log by the server before it answers.
  async function _revealIdentity(id) {
    const res = await api(`/api/identities/${encodeURIComponent(id)}/reveal`, { method: 'POST' });
    return res && res.value;
  }

  async function revealIdentity(id) {
    const el = document.getElementById(`identity-value-${id}`);
    try {
      const value = await _revealIdentity(id);
      if (el && value) el.textContent = value;
    } catch (err) {
      toast(t('app.ids.show_failed', { error: err.message }), 'error');
    }
  }

  async function copyIdentity(id) {
    try {
      const value = await _revealIdentity(id);
      if (value) await copyText(value);
    } catch (err) {
      toast(t('app.ids.copy_failed', { error: err.message }), 'error');
    }
  }

  async function forgetIdentity(id, kind) {
    const text = kind === 'pending'
      ? t('app.ids.forget_pending')
      : t('app.ids.forget');
    if (!window.confirm(text)) return;
    try {
      await api(`/api/identities/${encodeURIComponent(id)}`, { method: 'DELETE' });
      loadIdentities();
    } catch (err) {
      toast(t('app.ids.forget_failed', { error: err.message }), 'error');
    }
  }

  // The deploy form's "use one this service had before": the removed ids of this
  // field, masked, each saying where it still runs, so two boxes never end up on
  // one id without the owner seeing it first.
  function identityOffersHtml(slug, key, offers) {
    if (!Array.isArray(offers) || !offers.length) {
      return `<p class="form-hint">${t('app.ids.no_offers')}</p>`;
    }
    return offers.map(o => {
      const busy = (o.in_use_on || []).length
        ? ` <span class="text-warn">${t('app.ids.in_use_on', { boxes: escapeHtml(o.in_use_on.join(', ')) })}</span>` : '';
      return `<div class="form-hint">
        <code>${escapeHtml(o.masked)}</code> · ${t('app.ids.last_on', { where: escapeHtml([o.worker, o.copy].filter(Boolean).join(', ')) })}${busy}
        <button type="button" class="btn btn-ghost btn-sm" data-action="useIdentity" data-a1="${escapeHtml(slug)}"
          data-a2="${escapeHtml(key)}" data-a3="${escapeHtml(String(o.id))}" data-a4="${escapeHtml((o.in_use_on || []).join(', '))}">${t('app.ids.use')}</button>
      </div>`;
    }).join('');
  }

  function _identityPicks(slug, key) {
    return [...document.querySelectorAll('.identity-pick')]
      .filter(el => el.dataset.pickSlug === slug && el.dataset.pickKey === key);
  }

  async function pickPreviousIdentity(slug, key, workerId) {
    let offers;
    // The box this form deploys to, when exactly one is picked: the server leaves
    // it out of "in use on", as the deploy's shared-id check leaves it out. The
    // Change form names its box itself.
    const target = workerId !== undefined && workerId !== '' ? Number(workerId) : _identityTargetWorker(slug);
    const query = `?key=${encodeURIComponent(key)}${target === null ? '' : `&worker_id=${target}`}`;
    try {
      offers = await api(`/api/identities/reuse/${encodeURIComponent(slug)}${query}`);
    } catch (err) {
      toast(t('app.ids.offers_failed', { error: err.message }), 'error');
      return;
    }
    const html = identityOffersHtml(slug, key, offers);
    _identityPicks(slug, key).forEach(el => { el.innerHTML = html; });
  }

  function _identityTargetWorker(slug) {
    const picked = _selectedWorkerIds(`.deploy-worker-cb[data-slug="${slug}"]:checked:not(:disabled), `
      + `.setup-deploy-worker-cb[data-slug="${slug}"]:checked:not(:disabled)`);
    const ids = [...new Set([...picked, ..._rescaledWorkerIds(slug)])];
    return ids.length === 1 ? ids[0] : null;
  }

  // The latest Use per field: a reveal that answers after a later click lost.
  const _identityChoice = {};

  async function useIdentity(slug, key, id, inUseOn) {
    if (inUseOn && !window.confirm(t('app.ids.use_confirm', { boxes: inUseOn }))) return;
    const field = `${slug}\n${key}`;
    const turn = (_identityChoice[field] || 0) + 1;
    _identityChoice[field] = turn;
    const inputs = () => [...document.querySelectorAll('input[data-slug][data-key]')]
      .filter(input => input.dataset.slug === slug && input.dataset.key === key);
    // What each field held at the click: one the owner typed into while the
    // reveal was out keeps what they typed.
    const before = new Map(inputs().map(input => [input, input.value]));
    let value;
    try {
      value = await _revealIdentity(id);
    } catch (err) {
      if (_identityChoice[field] === turn) toast(t('app.ids.read_failed', { error: err.message }), 'error');
      return;
    }
    if (!value || _identityChoice[field] !== turn) return;
    inputs().forEach(input => {
      if (before.has(input) && before.get(input) === input.value) input.value = value;
    });
    _identityPicks(slug, key).forEach(el => { el.innerHTML = ''; });
  }

  // --- Restore from a backup file (issue #741, docs/backup.md) ---------------

  // What the restore will create and where it may go, as HTML. Pure, so the
  // harness can run it. Everything in it is text: the service and box names
  // come from the catalog and the fleet, and where the file was made only from
  // this CashPilot's own ledger, never from the file.
  function restorePreviewHtml(p) {
    const creates = (p.creates || []).map(c =>
      `<li>${t('app.restore.volume_html', { volume: escapeHtml(c.volume), target: escapeHtml(c.target) })}</li>`).join('');
    const history = (p.history || []).map(h =>
      `<li>${t('app.restore.history', { what: escapeHtml(h.what), box: escapeHtml(h.worker), when: escapeHtml(fmtTimestamp(h.when).text) })}</li>`).join('');
    const origin = p.known
      ? `<p>${t('app.restore.known')}</p><ul>${history}</ul>`
      : `<p class="text-warn">${t('app.restore.unknown_html', { service: escapeHtml(p.service) })}</p>
         <input type="text" class="form-input" id="restore-confirm" autocomplete="off" spellcheck="false">`;
    const live = (p.live_on || []).length
      ? `<p class="text-fail">${t('app.restore.live', { boxes: escapeHtml(p.live_on.join(', ')) })}</p>` : '';
    // A file from before CashPilot recorded its backups is unknown too: it may
    // be a backup of a node that runs now.
    const elsewhere = !p.known && !(p.live_on || []).length && (p.runs_on || []).length
      ? `<p class="text-warn">${t('app.restore.elsewhere', { service: escapeHtml(p.service), boxes: escapeHtml(p.runs_on.join(', ')) })}</p>` : '';
    const plain = (p.workers || []).some(w => w.ok && w.plain_http)
      ? `<label class="form-hint"><input type="checkbox" id="restore-plain-http"> ${t('app.restore.plain_http')}</label>` : '';
    const options = (p.workers || []).map(w =>
      `<option value="${escapeHtml(String(w.id))}"${w.ok ? '' : ' disabled'}>${escapeHtml(w.name)}${
        w.ok ? (w.plain_http ? t('app.restore.plain_option') : '')
          : ` (${escapeHtml(w.why)})`}</option>`).join('');
    // A box the identity may already be on is disabled with its reason; the one
    // a restore was sent to with no answer may take it again.
    const usable = (p.workers || []).some(w => w.ok);
    return `
      <p>${t('app.restore.creates_html', { service: escapeHtml(p.service), container: escapeHtml(p.container) })}</p>
      <ul>${creates}</ul>
      <p class="form-hint">${t('app.restore.never_overwrites', { service: escapeHtml(p.service) })}</p>
      ${origin}${live}${elsewhere}
      <label class="form-label" for="restore-worker">${t('app.ids.box')}</label>
      <select class="form-input" id="restore-worker">${options || `<option disabled>${t('app.restore.no_box')}</option>`}</select>
      <label class="form-label" for="restore-passphrase">${t('app.restore.passphrase')}</label>
      <input type="password" class="form-input" id="restore-passphrase" autocomplete="off">
      ${plain}
      <div class="credential-health-actions">
        <button type="button" class="btn btn-primary btn-sm" data-action="submitRestore"
          data-a1="${escapeHtml(p.upload_id)}"${usable ? '' : ' disabled'}>${t('app.restore.restore')}</button>
      </div>`;
  }

  // Which file check is the newest: a slower answer for a file chosen before
  // must not replace the preview of the one chosen after it.
  let restoreCheckSeq = 0;
  // The File object behind the preview on screen: Restore sends that
  // preview's upload, so it goes only while the picker still holds that very
  // object. Two files can share a name, a size and a date.
  let previewedFile = null;

  // A file picked in the picker: the preview on screen is of another one, so
  // it goes, and a check or a restore of the old file still running no longer
  // writes the page or clears the picker.
  function restoreFileChanged() {
    restoreCheckSeq++;
    previewedFile = null;
    const out = document.getElementById('restore-preview');
    if (out) out.innerHTML = '';
  }

  async function checkRestoreFile() {
    const input = document.getElementById('restore-file');
    const out = document.getElementById('restore-preview');
    const file = input && input.files && input.files[0];
    if (!file || !out) return;
    const seq = ++restoreCheckSeq;
    previewedFile = null;
    out.innerHTML = `<p class="loading-line">${t('app.restore.checking')}</p>`;
    let html;
    let checked = null;
    try {
      // The raw file as the body: never JSON, never base64 in the page.
      const res = await fetch('/api/restore/upload', {
        method: 'POST', body: file, headers: { 'Content-Type': 'application/octet-stream' },
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        let detail = data && data.detail;
        if (detail && typeof detail === 'object') detail = detail.message;
        throw new Error(detail || t('app.api.error_status', { status: res.status }));
      }
      html = restorePreviewHtml(data);
      checked = file;
    } catch (err) {
      html = `<p class="text-fail">${escapeHtml(err.message)}</p>`;
    }
    if (seq === restoreCheckSeq) {
      out.innerHTML = html;
      previewedFile = checked;
    }
  }

  async function submitRestore(uploadId) {
    const picker = document.getElementById('restore-file');
    const sent = picker && picker.files && picker.files[0];
    if (!previewedFile || sent !== previewedFile) {
      toast(t('app.restore.not_checked'), 'error');
      return;
    }
    const pass = document.getElementById('restore-passphrase');
    const worker = document.getElementById('restore-worker');
    const confirmBox = document.getElementById('restore-confirm');
    const body = {
      upload_id: uploadId,
      worker_id: Number(worker && worker.value),
      passphrase: pass ? pass.value : '',
    };
    if (confirmBox) body.confirm_name = confirmBox.value;
    const plain = document.getElementById('restore-plain-http');
    if (plain && plain.checked) body.allow_plain_http = true;
    // Out of the page as soon as it is sent; the server keeps it nowhere either.
    if (pass) pass.value = '';
    const out = document.getElementById('restore-preview');
    // The file this restore is for: if the owner checks another one while it
    // runs, its success must not wipe that newer preview and file choice.
    const seq = restoreCheckSeq;
    // One click, one restore: a second one while the worker works could put
    // the file on a second box (the server refuses it too).
    const button = document.querySelector('[data-action="submitRestore"]');
    if (button) button.disabled = true;
    try {
      // api() asks for the owner's password when the server answers step_up_required.
      const res = await api('/api/restore', { method: 'POST', body });
      toast(res.started
        ? t('app.restore.done_started', { service: res.service, box: res.worker, n: res.files })
        : t('app.restore.done_fenced', { service: res.service, box: res.worker, n: res.files }), 'success');
      // Only while the picker still holds the file sent and nothing was
      // checked or picked since: a newer choice keeps its file and preview.
      const input = document.getElementById('restore-file');
      if (seq === restoreCheckSeq && input && input.files && input.files[0] === sent) {
        if (out) out.innerHTML = '';
        input.value = '';
        previewedFile = null;
      }
      loadIdentities();
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      if (button) button.disabled = false;
    }
  }

  // Exported for the harness: the message is the whole point of the fix, so it
  // has to be reachable without a browser.
  function settingsLoadFailureMessage(err) {
    const detail = (err && err.message) ? String(err.message) : '';
    return detail ? t('app.settings.load_failed_detail', { error: detail }) : t('app.settings.load_failed');
  }

  function settingsPanelsFailed(err) {
    const message = settingsLoadFailureMessage(err);
    ['env-vars-container', 'collectors-container'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.innerHTML = `<p class="text-fail">${escapeHtml(message)}</p>`;
    });
  }

  // --- About & Updates (issue #342) ---------------------------------------

  // The worker whose install the card inspects/updates. Multi-worker fleets
  // get a selector; _resolve_worker_id would otherwise 400 the whole card.
  let updateCardWorkerId = null;
  // The worker may not recreate the dashboard on its server: it updates itself only.
  let updateCardWorkerOnly = false;

  async function loadUpdateCard() {
    const container = document.getElementById('update-card-container');
    if (!container) return;
    try {
      const workers = await api('/api/workers').catch(() => []);
      // Only Docker workers answer /api/update-info; a Desktop updates itself and a phone has no URL.
      const online = onlineDeployWorkers(workers).filter(w => !isDesktopWorker(w));
      if (!online.length) {
        container.innerHTML = `<p class="block-empty">${t('app.update.no_worker')}</p>`;
        return;
      }
      if (!online.some(w => w.id === updateCardWorkerId)) updateCardWorkerId = online[0].id;
      const info = await api(`/api/update-info?worker_id=${updateCardWorkerId}`);
      renderUpdateCard(info, online);
    } catch (err) {
      // The card must render something honest even with the worker down — the
      // rest of the settings page is still usable.
      const detail = (err && err.message) ? err.message : '';
      container.innerHTML = `<p class="block-empty">${escapeHtml(detail ? t('app.update.read_failed_detail', { error: detail }) : t('app.update.read_failed'))}</p>`;
    }
  }

  function selectUpdateWorker(sel) {
    updateCardWorkerId = parseInt(sel.value, 10);
    loadUpdateCard();
  }

  // The URL comes from the worker, so only a link into this project's
  // repository becomes clickable; anything else is shown as text.
  function proxyPolicyLink(url) {
    const text = escapeHtml(url);
    return String(url || '').startsWith('https://github.com/GeiserX/CashPilot/')
      ? `<a href="${text}" target="_blank" rel="noopener">${text}</a>`
      : text;
  }

  function renderUpdateCard(info, onlineWorkers) {
    updateCardWorkerOnly = !!info.ui_by_hand;
    const container = document.getElementById('update-card-container');
    if (!container) return;
    const current = info.current_display || info.current || 'dev';
    const latest = (info.known && info.latest) ? `v${String(info.latest).replace(/^v/, '')}` : null;
    const line = (label, value) => `
      <div class="kv-row">
        <div class="kv-key">${escapeHtml(label)}</div>
        <div class="kv-val mono">${escapeHtml(value)}</div>
      </div>`;
    let html = '';
    if ((onlineWorkers || []).length > 1) {
      const options = onlineWorkers.map(w =>
        `<option value="${escapeHtml(String(w.id))}" ${w.id === updateCardWorkerId ? 'selected' : ''}>${escapeHtml(w.name || t('app.dep.worker_id', { id: w.id }))}</option>`
      ).join('');
      html += `
      <div class="kv-row">
        <div class="kv-key">${t('app.update.server')}</div>
        <div><select id="update-worker-select" class="form-input form-input-select">${options}</select></div>
      </div>`;
    }
    html += line(t('app.update.running'), current);
    if (info.worker_image) html += line(t('app.update.worker_image'), info.worker_image);
    if (info.ui_image) html += line(t('app.update.ui_image'), info.ui_image);
    html += line(t('app.update.latest'), latest || t('app.update.latest_unknown'));
    // The proxy's policy lives in the compose file, which no image update
    // changes; the worker says which release's policy it needs and how to take it.
    const fix = info.proxy_policy_fix;
    if (fix) {
      html += `
      <p class="form-hint text-warn">${escapeHtml(t('app.update.proxy_policy', { release: fix.release }))}</p>
      <pre class="mono">${escapeHtml(fix.command)}\n${escapeHtml(fix.recreate)}</pre>
      <p class="form-hint">${escapeHtml(t('app.update.proxy_copy'))} ${proxyPolicyLink(fix.url)}</p>`;
    }

    let action;
    if (info.updater_running) {
      action = `<p class="kv-note">${t('app.update.already_running')}</p>`;
    } else if (!info.compose_managed) {
      action = `<p class="kv-note muted">${t('app.update.not_compose_html')}</p>`;
    } else {
      let label; let note;
      if (info.patch_available) {
        label = t('app.update.update_to', { version: latest });
        note = t('app.update.patch_note');
      } else if (info.behind) {
        label = t('app.update.pull_patches');
        note = t('app.update.behind_note', { version: latest });
      } else {
        label = t('app.update.repull');
        note = latest
          ? t('app.update.newest_note')
          : t('app.update.unknown_note');
      }
      if (info.ui_by_hand) {
        note += ' ' + t('app.update.worker_only_note');
      }
      action = `
      <div class="kv-actions">
        <button class="btn btn-primary" data-action="runSelfUpdate">${escapeHtml(label)}</button>
        <span id="update-run-status" class="form-hint"></span>
      </div>
      <div class="form-hint">${escapeHtml(note)}</div>`;
      if (info.behind && !info.patch_available) {
        action += `<div class="form-hint"><a href="https://github.com/GeiserX/CashPilot/blob/main/UPGRADING.md" target="_blank" rel="noopener noreferrer">${t('app.update.read_upgrading')}</a></div>`;
      }
    }
    container.innerHTML = html + action;
    const sel = container.querySelector('#update-worker-select');
    if (sel) sel.addEventListener('change', e => selectUpdateWorker(e.target));
  }

  async function runSelfUpdate() {
    const question = updateCardWorkerOnly
      ? t('app.update.confirm_worker')
      : t('app.update.confirm');
    if (!confirm(question)) return;
    const status = document.getElementById('update-run-status');
    if (status) status.textContent = t('app.update.starting');
    try {
      // Same worker the card inspected — info and action must not diverge.
      const q = updateCardWorkerId != null ? `?worker_id=${updateCardWorkerId}` : '';
      await api(`/api/update${q}`, { method: 'POST' });
      if (status) {
        status.textContent = updateCardWorkerOnly
          ? t('app.update.started_worker')
          : t('app.update.started');
      }
    } catch (err) {
      // A 409 carries the worker's honest refusal (e.g. not compose-managed,
      // or an update already running) — show it verbatim, it IS the answer.
      if (status) status.textContent = (err && err.message) ? err.message : t('app.update.failed');
    }
  }

  function renderEnvVars(envInfo, config) {
    const container = document.getElementById('env-vars-container');
    if (!container) return;
    if (!envInfo.length) {
      container.innerHTML = `<p class="block-empty">${t('app.env.none')}</p>`;
      return;
    }
    const rows = envInfo.map(v => {
      const fromEnv = v.set_via_env;
      const locked = fromEnv || v.read_only;
      const dbVal = config[v.key] || '';
      // Secret rows never carry a plaintext value from the API — render empty and
      // drive status off the is_set flag. Non-secret rows still show their value.
      const isSet = v.secret ? !!v.is_set : !!(dbVal || v.value);
      const displayVal = v.secret ? '' : (dbVal || v.value);
      const inputType = v.secret ? 'password' : 'text';
      const lockIcon = locked
        ? `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="kv-lock" aria-label="${t('app.env.locked')}"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>`
        : '';
      let badge;
      if (fromEnv) badge = `<span class="badge badge-deployed kv-badge">${t('app.env.from_env')}</span>`;
      else if (v.read_only) badge = `<span class="badge kv-badge">${t('app.env.read_only')}</span>`;
      // No "DB" badge. It asserted that a stored value was in force, and
      // nothing reads these from the database: every one is resolved once from
      // the environment at import (main.py:639-640, auth.py, fleet_key.py), so
      // a saved value could never take effect. A stored-but-inert value is
      // worth flagging as exactly that.
      else if (dbVal) badge = `<span class="badge badge-warning kv-badge" title="${t('app.env.stored_title')}">${t('app.env.stored')}</span>`;
      else if (isSet) badge = `<span class="badge kv-badge muted">${t('app.env.default')}</span>`;
      else badge = `<span class="badge kv-badge muted">${t('app.env.not_set')}</span>`;
      // Secret fields render empty; placeholder communicates whether a value is stored.
      const placeholder = v.secret
        ? (isSet ? t('app.cred.set_keep') : t('app.env.not_set'))
        : v.description;
      return `
      <div class="kv-row">
        <div>
          <div class="kv-key">${escapeHtml(v.label)}${lockIcon}${badge}</div>
          <div class="kv-sub mono">${escapeHtml(v.key)}</div>
        </div>
        <div>
          <div class="inline-field">
            <input class="form-input env-var-input" type="${inputType}" id="env-${v.key}"
                   data-env-key="${escapeHtml(v.key)}"
                   value="${escapeHtml(displayVal)}"
                   placeholder="${escapeHtml(placeholder)}"
                   ${v.secret ? 'autocomplete="new-password"' : ''}
                   ${locked ? 'disabled' : ''}>
          </div>
          <div class="form-hint">${escapeHtml(v.description)}</div>
        </div>
      </div>`;
    }).join('');
    container.innerHTML = rows + `
    <div class="form-hint kv-note">
      ${t('app.env.note_html')}
    </div>
    <div class="kv-actions kv-actions-end">
      <button class="btn btn-ghost" data-action="saveEnvSettings" title="${t('app.env.save_title')}">${t('app.env.save_anyway')}</button>
    </div>`;
  }

  function toggleEnvSecret(inputId, btn) {
    const input = document.getElementById(inputId);
    if (!input) return;
    const showing = input.type === 'text';
    input.type = showing ? 'password' : 'text';
    btn.title = showing ? t('app.ids.show') : t('app.env.hide');
    btn.innerHTML = showing
      ? '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>'
      : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';
  }

  async function saveEnvSettings() {
    const inputs = document.querySelectorAll('.env-var-input:not(:disabled)');
    const data = {};
    inputs.forEach(input => {
      const val = input.value.trim();
      if (val) {
        data[input.dataset.envKey] = val;
      }
    });
    if (Object.keys(data).length === 0) {
      toast(t('app.env.no_changes'), 'info');
      return;
    }
    try {
      await api('/api/config', { method: 'POST', body: { data } });
      toast(t('app.env.saved'), 'success');
    } catch (err) {
      toast(t('app.save_failed', { error: err.message }), 'error');
    }
  }

  function renderCollectors(meta, config) {
    const container = document.getElementById('collectors-container');
    if (!container) return;
    if (!meta.length) {
      container.innerHTML = `<p class="block-empty">${t('app.coll.none')}</p>`;
      return;
    }
    const secrets = config._secrets || {};
    const items = meta.map((col, i) => {
      // A collector is "configured" if any secret field has a stored value
      // (per _secrets) or any non-secret field carries a real value.
      // EVERY required field, not any field.
      //
      // `.some` meant a service needing an email AND a password showed
      // "Configured" with only the email set — while the server's own
      // make_collectors skipped it for the missing one, so it silently never
      // collected. The badge asserted the opposite of what was happening.
      const isSet = f => (f.secret ? !!secrets[f.key] : !!(config[f.key] || '').trim());
      const required = col.fields.filter(f => f.required);
      const setCount = required.filter(isSet).length;
      const configured = required.length > 0 && setCount === required.length;
      const partial = setCount > 0 && setCount < required.length;
      const statusBadge = partial
        ? `<span class="badge badge-warning" title="${t('app.coll.incomplete_title')}">${t('app.coll.incomplete')}</span>`
        : configured
        ? `<span class="badge badge-deployed">${t('app.coll.configured')}</span>`
        : `<span class="badge badge-category">${t('app.coll.not_configured')}</span>`;
      const fields = col.fields.map(f => {
        // Secret fields never receive a plaintext value from /api/config — render
        // them empty (write-only). Submitting blank preserves the stored secret.
        const isSecretSet = f.secret && !!secrets[f.key];
        const savedVal = f.secret ? '' : (config[f.key] || '');
        const inputType = f.secret ? 'password' : 'text';
        const inputId = `cred-${f.key}`;
        const placeholder = f.secret
          ? (isSecretSet ? t('app.cred.set_keep') : t('app.env.not_set'))
          : f.label;
        return `
        <div class="form-group">
          <label class="form-label">${escapeHtml(f.label)}${f.required ? '' : ` <span class="optional">${t('app.cred.optional')}</span>`}</label>
          <div class="inline-field">
            <input class="form-input collector-input" type="${inputType}" id="${inputId}"
                   data-config="${escapeHtml(f.key)}"
                   value="${escapeHtml(savedVal)}"
                   placeholder="${escapeHtml(placeholder)}"
                   ${f.secret ? 'autocomplete="new-password"' : ''}>
          </div>
        </div>`;
      }).join('');
      const clearBtn = configured && _isOwner
        ? `<div class="kv-actions kv-actions-end"><button class="btn btn-danger btn-sm" data-action="clearServiceCredentials" data-a1="${escapeHtml(col.slug)}" data-a2="${escapeHtml(col.name)}">${t('app.coll.clear')}</button></div>`
        : '';
      return `
      <details class="collector-section" id="collector-${col.slug}" style="order:${i}">
        <summary class="collector-header">
          <span class="collector-name">${escapeHtml(col.name)}</span>
          ${statusBadge}
        </summary>
        <div class="collector-body">
          ${col.hint ? `<div class="form-hint collector-hint">${sanitizeHint(col.hint)}</div>` : ''}
          ${fields}
          ${clearBtn}
        </div>
      </details>`;
    });
    // Two independent stacks, not one grid: in a grid an opened card stretches
    // its whole row and leaves a gap under the card beside it. Left gets the
    // 1st, 3rd, 5th... so the reading order stays row by row; on a phone the
    // stacks dissolve (display: contents) and `order` restores that sequence.
    const left = items.filter((_, i) => i % 2 === 0).join('');
    const right = items.filter((_, i) => i % 2 === 1).join('');
    container.innerHTML = `<div class="collectors-grid"><div class="collectors-col">${left}</div><div class="collectors-col">${right}</div></div>`;
    // A link such as /settings#collector-ocean (the setup wizard's) opens that collector.
    if (/^#collector-[a-z0-9-]+$/.test(location.hash)) {
      const target = document.getElementById(location.hash.slice(1));
      if (target) {
        target.open = true;
        target.scrollIntoView({ block: 'center' });
      }
    }
  }

  async function saveCollectorCredentials() {
    const inputs = document.querySelectorAll('.collector-input');
    const data = {};
    inputs.forEach(input => {
      const key = input.dataset.config;
      const val = input.value.trim();
      if (val) {
        data[key] = val;
      }
    });

    if (Object.keys(data).length === 0) {
      toast(t('app.coll.nothing'), 'warning');
      return;
    }

    try {
      await api('/api/config', { method: 'POST', body: { data } });
      toast(t('app.coll.saved'), 'success');
      loadSettings();
    } catch (err) {
      toast(t('app.save_failed', { error: err.message }), 'error');
    }
  }

  async function clearServiceCredentials(slug, name) {
    if (!confirm(t('app.coll.clear_confirm', { name }))) return;
    try {
      await api(`/api/config/${encodeURIComponent(slug)}`, { method: 'DELETE' });
      toast(t('app.coll.cleared', { name }), 'success');
      // The caller used to close the modal in a second inline call; folded in
      // here so the button declares one action rather than two.
      closeModal('cred-modal');
      loadSettings();
    } catch (err) {
      toast(t('app.coll.clear_failed', { error: err.message }), 'error');
    }
  }

  async function testCollectors() {
    const statusEl = document.getElementById('collector-save-status');
    if (statusEl) statusEl.textContent = t('app.coll.running');
    try {
      await api('/api/collect', { method: 'POST' });
      toast(t('app.coll.started'), 'success');
      if (statusEl) statusEl.textContent = t('app.coll.triggered');
    } catch (err) {
      toast(t('app.coll.failed', { error: err.message }), 'error');
      if (statusEl) statusEl.textContent = '';
    }
  }

  // -----------------------------------------------------------
  // Utility
  // -----------------------------------------------------------
  // Which currency formatCurrency will ACTUALLY label its result as.
  //
  // Not the same question as "what is the display currency": an unpriced token
  // is shown raw, and a display currency with no fiat rate falls back to USD.
  // Callers that want to avoid printing the same figure twice need the answer
  // to this, not to the simpler question — comparing against _displayCurrency
  // printed "24.90 USD (≈ $24.90)" whenever the rate was missing.
  function effectiveDisplayCurrency(nativeCurrency) {
    nativeCurrency = nativeCurrency || 'USD';
    const priced = nativeCurrency === 'USD'
      || (_exchangeRates.crypto_usd && _exchangeRates.crypto_usd[nativeCurrency]);
    if (!priced) return nativeCurrency;
    if (_displayCurrency !== 'USD' && _exchangeRates.fiat && _exchangeRates.fiat[_displayCurrency]) {
      return _displayCurrency;
    }
    return 'USD';
  }

  function formatCurrency(val, nativeCurrency, digits) {
    nativeCurrency = nativeCurrency || 'USD';
    const fractionDigits = digits ?? 2;
    const amount = parseFloat(val || 0);

    // Convert to USD first
    let usdAmount;
    if (nativeCurrency === 'USD') {
      usdAmount = amount;
    } else if (_exchangeRates.crypto_usd && _exchangeRates.crypto_usd[nativeCurrency]) {
      usdAmount = amount * _exchangeRates.crypto_usd[nativeCurrency];
    } else {
      // Unknown token with no rate — show raw value, in full: toFixed(2)
      // showed 0.000613902892 XMR as "0.00 XMR" whenever XMR had no price.
      return formatAmount(amount, nativeCurrency) + ' ' + nativeCurrency;
    }

    // Convert USD to the display currency — but ONLY label it as the display
    // currency if a rate was actually applied.
    //
    // This used to stamp the display currency's symbol on an unconverted USD
    // figure whenever its rate was missing, so $24.90 rendered as "£24.90": not
    // a conversion, the same number wearing a different sign. Caught in a
    // browser against a freshly restarted server, which is exactly when it
    // bites — rates are fetched asynchronously, so on every page load before
    // they arrive EVERY figure on the dashboard was mislabelled, and a user
    // whose currency simply has no rate saw it permanently.
    let displayAmount = usdAmount;
    let currency = 'USD';
    if (_displayCurrency === 'USD') {
      currency = 'USD';
    } else if (_exchangeRates.fiat && _exchangeRates.fiat[_displayCurrency]) {
      displayAmount = usdAmount * _exchangeRates.fiat[_displayCurrency];
      currency = _displayCurrency;
    }
    // else: no rate, so the value stays in USD and says so.

    try {
      return new Intl.NumberFormat(undefined, {
        style: 'currency',
        currency,
        minimumFractionDigits: fractionDigits,
        maximumFractionDigits: fractionDigits,
      }).format(displayAmount);
    } catch {
      return displayAmount.toFixed(fractionDigits) + ' ' + currency;
    }
  }

  function formatNative(val, currency) {
    if (!currency || currency === 'USD') return null;
    return formatAmount(parseFloat(val || 0), currency) + ' ' + currency;
  }

  // Fiat is USD plus every currency the rate table priced; a missing code is USD.
  function isFiatCurrency(currency) {
    const code = String(currency || 'USD').trim().toUpperCase();
    return code === 'USD' || Boolean(_exchangeRates.fiat && _exchangeRates.fiat[code]);
  }

  // A balance or payout in its own unit, without dropping a coin's small units.
  // Fiat keeps two decimals. Anything else (BTC, XMR, a provider's token) shows
  // at least eight decimals (one satoshi), and more for a small amount so that
  // eight significant digits show, up to twelve (one piconero). Trailing zeros
  // are trimmed back to two. toFixed(2) turned a 0.01599128 BTC payout into
  // "0.02", and toFixed(4) turned 0.000613902892 XMR into "0.0006". Same rule
  // as payouts.format_amount.
  function formatAmount(val, currency) {
    const amount = Number(val);
    if (isFiatCurrency(currency)) return amount.toFixed(2);
    const places = Number.isFinite(amount) && amount !== 0
      ? Math.min(12, Math.max(8, 7 - Math.floor(Math.log10(Math.abs(amount)))))
      : 8;
    return amount.toFixed(places).replace(/(\.\d\d\d*?)0+$/, '$1');
  }

  function setTextContent(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  function setChangeIndicator(id, pct) {
    const el = document.getElementById(id);
    if (!el) return;
    // null means the comparison was never computed — not "no change".
    // month_change used to be a hardcoded 0.0, so this rendered "+0.0%" in the
    // positive style forever, and `pct.toFixed` would now throw on the honest
    // null. Blank is the only truthful rendering of an unmeasured figure.
    if (pct === null || pct === undefined || Number.isNaN(Number(pct))) {
      el.textContent = '';
      el.className = 'stat-change';
      return;
    }
    const sign = pct >= 0 ? '+' : '';
    el.textContent = `${sign}${pct.toFixed(1)}%`;
    // Uncoloured on purpose: colour means state only, the sign says the direction.
    el.className = 'stat-change';
  }

  function debounce(fn, ms) {
    let timer;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), ms);
    };
  }

  // -----------------------------------------------------------
  // Notification bell (collector alerts)
  // -----------------------------------------------------------
  function initNotifications() {
    const toggle = document.getElementById('notify-toggle');
    const dropdown = document.getElementById('notify-dropdown');
    if (!toggle || !dropdown) return;

    toggle.addEventListener('click', (e) => {
      e.stopPropagation();
      dropdown.classList.toggle('open');
    });

    document.addEventListener('click', (e) => {
      if (!dropdown.contains(e.target) && e.target !== toggle) {
        dropdown.classList.remove('open');
      }
    });

    // Fetch alerts now and every 60s
    loadCollectorAlerts();
    setInterval(loadCollectorAlerts, 60000);

    // Once per page load. The server refreshes daily; polling more often would
    // only re-read the same cached value.
    checkForUpdate();
  }

  // A newer release is available (CashPilot-w0ss).
  //
  // Three rules, and they are what keep this from being unwelcome:
  //   * SILENT when unknown. Offline, disabled, never-run, or a dev build all
  //     produce `known: false`, and an unknown state renders NOTHING -- never a
  //     spinner, an error, or a reassuring "up to date" it has not earned.
  //   * NEVER auto-updates. It tells you; you decide.
  //   * Dismissible PER VERSION. Dismiss 1.20.1 and it stays gone until 1.20.2
  //     exists, so it cannot become wallpaper.
  async function checkForUpdate() {
    const banner = document.getElementById('update-banner');
    if (!banner) return;
    let state;
    try {
      state = await api('/api/update-status');
    } catch (err) {
      return; // Unknown. Say nothing at all.
    }
    if (!state || !state.known || !state.behind || !state.latest) return;

    // Per-version dismissal. Keyed on the version so a NEW release re-appears.
    let dismissed = null;
    try {
      dismissed = localStorage.getItem('cp-update-dismissed');
    } catch (err) {
      dismissed = null; // private mode / storage disabled: just show it
    }
    if (dismissed === state.latest) return;

    const text = document.getElementById('update-banner-text');
    const link = document.getElementById('update-banner-link');
    if (text) {
      text.textContent = t('app.banner.update', { latest: state.latest, current: state.current });
    }
    if (link) {
      link.href = `https://github.com/GeiserX/CashPilot/releases/tag/${encodeURIComponent(state.latest)}`;
    }
    const dismiss = document.getElementById('update-banner-dismiss');
    if (dismiss) {
      dismiss.onclick = () => {
        banner.hidden = true;
        try {
          localStorage.setItem('cp-update-dismissed', state.latest);
        } catch (err) {
          /* storage disabled: it will reappear next load, which is acceptable */
        }
      };
    }
    banner.hidden = false;
  }

  // The full ids and links of devices a provider says are not on the account.
  // The server sends them to the owner only; the notice text every role sees,
  // and every push, names each device by a masked suffix. A link is shown only
  // when it is https, so a bad catalog value never becomes a clickable URL.
  function notifyDevicesHtml(a) {
    if (!_isOwner || !Array.isArray(a.devices) || a.devices.length === 0) return '';
    const rows = a.devices.map(d => {
      const url = typeof d.url === 'string' && /^https:\/\//i.test(d.url) ? d.url : '';
      const link = url
        ? ` <a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${t('app.bell.add_to_account')}</a>`
        : '';
      return `<li><code>${escapeHtml(d.id)}</code>${link}</li>`;
    }).join('');
    const steps = a.device_steps ? `<div>${escapeHtml(a.device_steps)}</div>` : '';
    return `<div class="notify-item-devices">${steps}<ul>${rows}</ul></div>`;
  }

  async function loadCollectorAlerts() {
    const container = document.getElementById('topbar-notifications');
    const badge = document.getElementById('notify-badge');
    const list = document.getElementById('notify-list');
    if (!container || !badge || !list) return;

    try {
      // Warn BEFORE the gap, not after it (CashPilot-5bdm): a credential the
      // lifetime table says is about to lapse (or already past it, which is
      // strictly worse and must not vanish from the bell the moment the
      // forecast comes true) joins the bell while collection may still be
      // working. The endpoint is any-authenticated and value-free; a failed
      // fetch just means no early warnings, never a broken bell. A forecast
      // gets its OWN category ('expiring') — it is a prediction, not an
      // observed rejection, and the bell must not assert a 401 that never
      // happened.
      const read = ++_attentionReads;
      const [payload, health] = await Promise.all([
        api('/api/collector-alerts'),
        api('/api/credentials/health').catch(() => []),
      ]);
      const alerts = payload.alerts || [];
      refreshAttentionOnAlertChange(alerts, read);
      for (const row of (Array.isArray(health) ? health : [])) {
        if (row.status !== 'expiring_soon' && row.status !== 'likely_expired') continue;
        if (alerts.some(a => a.platform === row.service && a.kind === 'collector')) continue;
        alerts.push({
          kind: 'collector',
          category: 'expiring',
          platform: row.service,
          error: row.status === 'likely_expired'
            ? t('app.bell.cred_expired', { field: row.field || t('app.bell.credential') })
            : t('app.bell.cred_expiring', { field: row.field || t('app.bell.credential') }),
        });
      }
      // Clear any muted "alerts unavailable" styling left over from a prior
      // failed poll now that the fetch succeeded.
      badge.style.background = '';
      badge.title = '';
      if (alerts.length === 0) {
        badge.style.display = 'none';
        // "Healthy" is a claim about something that was CHECKED. On a fresh
        // install, or after a restart before the first collection, nothing has
        // been — and saying so is the same absent-equals-true this codebase
        // rejects everywhere else. The bell's failure path already gets this
        // right ("Alerts unavailable"), which made the never-ran case the
        // outlier (CashPilot-tb5).
        // "Healthy" additionally requires the collection machinery to be
        // ALIVE: the collected latch is permanent, so after a scheduler death
        // the bell would otherwise affirm health forever on the strength of a
        // collection that stopped happening. The server decides staleness.
        if (payload.collected && payload.collection_stale) {
          const mins = Math.floor((payload.last_run_age_seconds || 0) / 60);
          list.innerHTML = `<div class="notify-empty">${t('app.bell.stale', { mins })}</div>`;
          return;
        }
        list.innerHTML = payload.collected
          ? `<div class="notify-empty">${t('app.bell.healthy')}</div>`
          : `<div class="notify-empty">${t('app.bell.never_ran')}</div>`;
        return;
      }

      badge.style.display = '';
      badge.textContent = alerts.length;
      // A bell full of nothing but forecasts is advice, not an incident: mute
      // the badge so a healthy install with an ageing cookie is not shown the
      // same red count as a broken one.
      if (alerts.every(a => a.category === 'expiring')) {
        badge.style.background = 'var(--text-muted)';
      }
      // A payout is a question, not a fault. Rendering it with the warning
      // triangle and an "Update credentials" button would tell the user
      // something is broken at the exact moment they got paid.
      const WARNING_ICON = '<path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>';
      const PAYOUT_ICON = '<circle cx="12" cy="12" r="10"/><path d="M12 6v12M15 9.5a2.5 2.5 0 00-2.5-1.5h-1a2 2 0 000 4h1a2 2 0 010 4h-1A2.5 2.5 0 019 14.5"/>';
      // A notice is a caveat about a reading that WORKED — "this figure is
      // withdrawable balance only", not "this is broken". Same reasoning as the
      // payout case above: the warning triangle and an "Update credentials"
      // button would tell the user something is wrong and point them at the one
      // action that cannot help.
      const NOTICE_ICON = '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>';
      list.innerHTML = alerts.map(a => {
        const isPayout = a.kind === 'payout';
        // A quiet balance is a heads-up, not a fault, and no credential fixes it.
        const isQuiet = a.kind === 'flatline' && a.platform !== 'flatline check';
        const isNotice = a.kind === 'notice' || isQuiet;
        // A stopped container: the fix is starting it, never a credential.
        const isContainer = a.kind === 'container';
        // Recorded as deployed and no box runs it: redeploy or forget, never a credential.
        const isMissing = a.kind === 'missing';
        // The provider turned the account off: no credential or restart fixes it.
        const isDisabled = a.kind === 'account_disabled';
        // What an earner did on the network (the Activity page): no credential fixes it.
        const isActivity = (a.kind || '').startsWith('activity_');
        // A proxy reached its traffic cap: the fix is on the fleet page, never a credential.
        const isProxyCap = a.kind === 'proxy_cap';
        // A proxied copy or its tunnel is gone or down: start or re-add it on the fleet page.
        const isProxied = a.kind === 'proxied';
        // A worker that cannot reach Docker: the fix is on that machine, never a credential.
        const isDocker = a.kind === 'docker';
        // A running copy that carries almost no traffic: look at it, never a credential.
        const isStall = a.kind === 'stall';
        // The failure TAXONOMY (CashPilot-5bdm). Only 'auth' means "your
        // credential needs replacing"; a transient provider outage self-heals
        // and a shape change is our bug, so pointing the user at their
        // credential for either teaches them the one alert that DOES need
        // them is ignorable. Absent means unknown — the button stays, because
        // unknown might be an auth failure the collector could not classify.
        const category = a.category || '';
        const isTransient = category === 'transient';
        const isShape = category === 'shape';
        const isAuth = category === 'auth';
        const isExpiring = category === 'expiring';
        const icon = isPayout ? PAYOUT_ICON : (isNotice || isTransient) ? NOTICE_ICON : WARNING_ICON;
        const suffix = isPayout ? t('app.bell.s.payout')
          : isActivity ? (a.kind === 'activity_spike' ? t('app.bell.s.unusual_hour') : t('app.bell.s.network'))
          : isContainer ? t('app.bell.s.not_running')
          : isProxyCap ? t('app.bell.s.traffic_cap')
          : isProxied ? t('app.bell.s.proxied_down')
          : isDocker ? t('app.bell.s.docker')
          : isStall ? t('app.bell.s.stall')
          : isDisabled ? t('app.bell.s.disabled')
          : isMissing ? (a.everywhere === false ? t('app.bell.s.gone_from_box') : a.everywhere ? t('app.bell.s.runs_nowhere') : t('app.bell.s.missing'))
          : isQuiet ? t('app.bell.s.quiet')
          : isNotice ? t('app.bell.s.note')
          : isAuth ? t('app.bell.s.auth')
          : isExpiring ? t('app.bell.s.expiring')
          : isTransient ? t('app.bell.s.transient')
          : isShape ? t('app.bell.s.shape')
          : '';
        const muted = isNotice || isTransient;
        const showFix = !isPayout && !isNotice && !isTransient && !isShape && _isOwner && !isContainer && !isMissing && !isDisabled && !isActivity && !isProxyCap && !isStall && !isProxied && !isDocker;
        return `
        <div class="notify-item" data-platform="${escapeHtml(a.platform)}" data-kind="${escapeHtml(a.kind || 'collector')}"${category ? ` data-category="${escapeHtml(category)}"` : ''}>
          <div class="notify-item-icon${muted ? ' muted' : ''}">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">${icon}</svg>
          </div>
          <div class="notify-item-body">
            <div class="notify-item-platform">${escapeHtml(a.platform)}${suffix}</div>
            <div class="notify-item-msg" title="${escapeHtml(a.error)}">${escapeHtml(a.error)}</div>
            ${notifyDevicesHtml(a)}
          </div>
          ${showFix ? `<button class="btn btn-ghost btn-sm" data-action="openCredentialModal" data-stop="1" data-a1="${escapeHtml(a.platform)}">${isAuth ? t('app.bell.fix_credential') : t('app.credh.update')}</button>` : ''}
          ${isDocker ? `<a class="btn btn-ghost btn-sm" href="${DOCKER_LOST_DOC}" target="_blank" rel="noopener">${t('app.how_to_fix')}</a>` : ''}
        </div>
      `;
      }).join('');
    } catch {
      // The bell's own fetch failed — this is unknown, not healthy. Show a
      // neutral/muted indicator rather than hiding the badge (which would
      // read as "all collectors healthy").
      badge.style.display = '';
      badge.style.background = 'var(--text-muted)';
      badge.textContent = '?';
      badge.title = t('app.bell.unavailable');
      list.innerHTML = `<div class="notify-empty">${t('app.bell.unavailable_text')}</div>`;
    }
  }

  function openCollectorSection(platform) {
    const details = document.getElementById('collector-' + platform);
    if (!details) return;
    details.open = true;
    details.scrollIntoView({ behavior: 'smooth', block: 'center' });
    details.classList.add('highlight-flash');
    setTimeout(() => details.classList.remove('highlight-flash'), 2000);
  }

  // -----------------------------------------------------------
  // Currency selector (settings page)
  // -----------------------------------------------------------
  function partitionFiatCodes(fiat) {
    const codes = Object.keys(fiat).sort();
    const popular = ['USD', 'EUR', 'GBP', 'JPY', 'CAD', 'AUD', 'CHF', 'CNY', 'INR', 'BRL', 'MXN', 'PLN', 'SEK', 'NOK', 'DKK', 'CZK', 'HUF', 'RON'];
    return [popular.filter(code => codes.includes(code)), codes.filter(code => !popular.includes(code))];
  }

  async function populateCurrencyDropdown() {
    const select = document.getElementById('settings-currency');
    if (!select) return;

    await loadExchangeRates();
    const [popular, remaining] = partitionFiatCodes(_exchangeRates.fiat || {});
    const options = [];

    for (const code of popular) {
      options.push(`<option value="${code}"${code === _displayCurrency ? ' selected' : ''}>${code}</option>`);
    }

    if (remaining.length > 0) {
      options.push('<option disabled>──────────</option>');
      for (const code of remaining) {
        options.push(`<option value="${code}"${code === _displayCurrency ? ' selected' : ''}>${code}</option>`);
      }
    }

    select.innerHTML = options.join('');
    select.addEventListener('change', () => {
      _displayCurrency = select.value;
      localStorage.setItem('cp-display-currency', select.value);
      toast(t('app.currency.set', { code: select.value }), 'success');
      // The fiat half of the staleness notice depends on which currency is being
      // read, so it has to be recomputed when that changes.
      renderStaleRateNotice();
      const topbarSelect = document.getElementById('topbar-currency');
      if (topbarSelect) topbarSelect.value = select.value;
    });
  }

  // -----------------------------------------------------------
  // Init on DOMContentLoaded
  // -----------------------------------------------------------
  // -----------------------------------------------------------
  // Theme
  // -----------------------------------------------------------
  // The built-in themes (app/themes.json), picked in the avatar menu by any
  // signed-in role. The choice is saved to the account. The server writes it
  // into <html data-theme> on every signed-in page, so that page paints it from
  // the first frame on any browser; the pre-paint script
  // (templates/_theme_prepaint.html) mirrors it into localStorage 'cp-theme'
  // for the sign-in pages and leaves the list in window.CP_THEMES.
  function themeConfig() {
    return window.CP_THEMES || {ids: [], default: null};
  }

  function currentTheme() {
    const theme = document.documentElement.getAttribute('data-theme');
    const cfg = themeConfig();
    return cfg.ids.includes(theme) ? theme : cfg.default;
  }

  function applyTheme(theme) {
    if (!themeConfig().ids.includes(theme)) return;
    document.documentElement.setAttribute('data-theme', theme);
    // Blocked storage throws; the account still keeps the choice.
    try { localStorage.setItem('cp-theme', theme); } catch (e) { /* storage blocked */ }
    document.querySelectorAll('[data-theme-choice]').forEach(b => {
      b.setAttribute('aria-pressed', String(b.dataset.themeChoice === theme));
    });
  }

  function chooseTheme(theme) {
    applyTheme(theme);
    api('/api/preferences', { method: 'POST', body: { theme } })
      .catch(err => toast(t('app.theme.not_saved', { error: err.message }), 'error'));
  }

  function initThemePicker() {
    applyTheme(currentTheme());
    document.querySelectorAll('[data-theme-choice]').forEach(b => {
      b.addEventListener('click', () => chooseTheme(b.dataset.themeChoice));
    });
  }

  function initAvatarDropdown() {
    const toggle = document.getElementById('avatar-toggle');
    const dropdown = document.getElementById('avatar-dropdown');

    // Submit the change-password modal on Enter from any of its fields.
    ['chpw-current', 'chpw-new', 'chpw-confirm'].forEach(id => {
      const el = document.getElementById(id);
      if (el) {
        el.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            submitPasswordChange();
          }
        });
      }
    });

    if (!toggle || !dropdown) return;
    toggle.addEventListener('click', (e) => {
      e.stopPropagation();
      dropdown.classList.toggle('open');
    });
    document.addEventListener('click', (e) => {
      if (!dropdown.contains(e.target) && e.target !== toggle) {
        dropdown.classList.remove('open');
      }
    });
  }

  async function initTopbarCurrency() {
    const select = document.getElementById('topbar-currency');
    if (!select) return;
    await loadExchangeRates();
    const fiatCodes = Object.keys(_exchangeRates.fiat || {}).sort();
    const popular = ['USD', 'EUR', 'GBP', 'JPY', 'CAD', 'AUD', 'CHF'];
    const popularSet = new Set(popular);
    select.innerHTML = '';
    for (const code of popular) {
      if (_exchangeRates.fiat[code] !== undefined) {
        const opt = document.createElement('option');
        opt.value = code; opt.textContent = code;
        select.appendChild(opt);
      }
    }
    const rest = fiatCodes.filter(c => !popularSet.has(c));
    if (rest.length && popular.length) {
      const sep = document.createElement('option');
      sep.disabled = true; sep.textContent = '---';
      select.appendChild(sep);
    }
    for (const code of rest) {
      const opt = document.createElement('option');
      opt.value = code; opt.textContent = code;
      select.appendChild(opt);
    }
    select.value = _displayCurrency;
    select.addEventListener('change', () => {
      _displayCurrency = select.value;
      localStorage.setItem('cp-display-currency', select.value);
      renderStaleRateNotice();
      // Re-render dashboard if on that page
      if (document.body.dataset.page === 'dashboard') {
        loadDashboardStats();
        loadServicesTable();
        loadUsagePanel();
      }
      // Also sync settings page dropdown if present
      const settingsSelect = document.getElementById('settings-currency');
      if (settingsSelect) settingsSelect.value = select.value;
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    initSidebar();
    initThemePicker();
    initNotifications();
    initAvatarDropdown();

    // Detect or restore display currency preference
    _displayCurrency = localStorage.getItem('cp-display-currency') || detectDefaultCurrency();
    initTopbarCurrency();

    // Load topbar earnings on every page
    loadTopbarEarnings();

    const page = document.body.dataset.page;
    switch (page) {
      case 'dashboard':
        loadDashboard();
        break;
      case 'setup':
        initWizard();
        break;
      case 'catalog':
        loadCatalog();
        initCatalogFilters();
        break;
      case 'settings': {
        loadSettings();
        const restoreFile = document.getElementById('restore-file');
        if (restoreFile) restoreFile.addEventListener('change', restoreFileChanged);
        // Auto-open collector section if ?highlight= param present
        const hl = new URLSearchParams(window.location.search).get('highlight');
        if (hl) setTimeout(() => openCollectorSection(hl), 300);
        break;
      }
    }
  });

  // -----------------------------------------------------------
  // Public API
  // -----------------------------------------------------------
  // The frontend had NO date formatting of any kind — grep for toLocaleString,
  // toLocaleDateString or `new Date(` across app.js and fleet.html returned zero
  // hits — so every timestamp reached the user as whatever the server
  // serialised. The DB writes datetime('now'), which SQLite produces in UTC, and
  // it was rendered raw and unlabelled: a viewer in CEST read a worker that
  // heartbeated five minutes ago as two hours stale, right next to the words
  // "This host is not reachable" and one click from Remove (CashPilot-2dh).
  function fmtTimestamp(value) {
    if (!value) return { text: t('app.time.never'), title: '' };
    // SQLite's "YYYY-MM-DD HH:MM:SS" carries no zone designator, so Date.parse
    // treats it as LOCAL time and silently shifts it. Say UTC explicitly.
    const iso = String(value).trim().replace(' ', 'T');
    const parsed = new Date(/[Zz]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso}Z`);
    if (Number.isNaN(parsed.getTime())) {
      // Unparseable is not a licence to invent a time. Show what we were given.
      return { text: String(value), title: t('app.time.unreadable') };
    }
    return { text: parsed.toLocaleString(), title: t('app.ids.utc', { time: value }) };
  }

  return {
    api,
    partitionFiatCodes,
    checkForUpdate,
    toast,
    openModal,
    closeModal,
    closeAllModals,
    loadEarningsChart,
    loadUsagePanel,
    setUsageDays,
    restartService,
    stopService,
    stopEverywhere,
    startService,
    removeService,
    forgetDeployment,
    viewLogs,
    stopLogPolling,
    toggleLogWrap,
    deployService,
    copyText,
    toggleWizardService,
    wizardNext,
    wizardPrev,
    openServiceDetail,
    loadDetailLogs,
    saveCollectorCredentials,
    testCollectors,
    saveEnvSettings,
    toggleEnvSecret,
    filterCatalog,
    refreshServices,
    openClaimModal,
    loadServicesTable,
    toggleInstances,
    deployServiceToWorkers,
    redeployWithImage,
    redeployOnWorker,
    redeployWithValues,
    renameDevices,
    openCustomServiceEditor,
    saveCustomService,
    addCustomEnvRow,
    removeCustomEnvRow,
    redeployCustomService,
    deleteCustomService,
    removeCustomFromBox,
    ignoreDrift,
    workerAction,
    loadWorkerLogs,
    openCredentialModal,
    saveCredentialModal,
    clearServiceCredentials,
    openChangePasswordModal,
    submitPasswordChange,
    loadPayoutQueue,
    loadCredentialHealth,
    loadIdentities,
    revealIdentity,
    copyIdentity,
    forgetIdentity,
    openIdentityChange,
    closeIdentityChange,
    changeIdentity,
    openIdentityForm,
    closeIdentityForm,
    addIdentity,
    exportIdentities,
    checkRestoreFile,
    submitRestore,
    pickPreviousIdentity,
    useIdentity,
    walletChoice,
    revealWalletSeed,
    loadPayoutProgress,
    loadDeployRisk,
    confirmPayout,
    rejectPayout,
    obligationDone,
    obligationSnooze,
    obligationMute,
    obligationUnmute,
    runSelfUpdate,
    // Exposed for import.js, so a deploy from an import asks the same
    // preflight question as every other deploy.
    confirmPreflight: _confirmPreflight,
    // Exposed for fleet.html, which rendered running costs with a bare
    // Number(v).toFixed(2) — no unit at all, on figures that mixed USD earnings
    // with a tariff in the user's own currency. The API is canonical USD now,
    // and this is the one place that knows the viewer's display currency.
    formatCurrency,
    // Shared, so the next timestamp added does not repeat CashPilot-2dh.
    fmtTimestamp,
    brk,
  };
})();
