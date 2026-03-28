/* ============================================================
   CashPilot — Frontend Application (Vanilla JS)
   ============================================================ */

const CP = (() => {
  'use strict';

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
        const msg = (data && data.detail) || `Error ${res.status}`;
        throw new Error(msg);
      }
      return data;
    } catch (err) {
      if (err.name === 'TypeError') {
        throw new Error('Network error — is the server running?');
      }
      throw err;
    }
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

  function escapeHtml(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
  }

  function capFirst(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : ''; }

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
  // Sidebar toggle (mobile)
  // -----------------------------------------------------------
  function initSidebar() {
    const hamburger = document.querySelector('.hamburger');
    const sidebar = document.querySelector('.sidebar');
    const overlay = document.querySelector('.sidebar-overlay');

    if (!hamburger) return;

    hamburger.addEventListener('click', () => {
      sidebar.classList.toggle('open');
      overlay.classList.toggle('open');
    });

    if (overlay) {
      overlay.addEventListener('click', () => {
        sidebar.classList.remove('open');
        overlay.classList.remove('open');
      });
    }
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

  async function loadExchangeRates() {
    try {
      _exchangeRates = await api('/api/exchange-rates');
    } catch { /* keep defaults */ }
  }

  async function loadTopbarEarnings() {
    try {
      await loadExchangeRates();
      const data = await api('/api/earnings/summary');
      setTextContent('topbar-total', formatCurrency(data.total || 0));
    } catch {
      setTextContent('topbar-total', formatCurrency(0));
    }
  }

  async function loadDashboard() {
    await loadExchangeRates();
    await Promise.all([
      loadDashboardStats(),
      loadServicesTable(),
      loadEarningsChart('7'),
    ]);

    // Auto-refresh every hour
    if (refreshTimer) clearInterval(refreshTimer);
    refreshTimer = setInterval(() => {
      loadDashboardStats();
      loadServicesTable();
    }, 3600000);
  }

  async function loadDashboardStats() {
    try {
      const data = await api('/api/earnings/summary');
      setTextContent('total-earnings', formatCurrency(data.total || 0));
      setTextContent('today-earnings', formatCurrency(data.today || 0));
      setTextContent('month-earnings', formatCurrency(data.month || 0));
      setTextContent('active-services', data.active_services || 0);

      // Update topbar
      setTextContent('topbar-total', formatCurrency(data.total || 0));

      // Change indicators
      if (data.today_change !== undefined) {
        setChangeIndicator('today-change', data.today_change);
      }
      if (data.month_change !== undefined) {
        setChangeIndicator('month-change', data.month_change);
      }
    } catch (err) {
      // API not yet implemented — fill with placeholder
      setTextContent('total-earnings', formatCurrency(0));
      setTextContent('today-earnings', formatCurrency(0));
      setTextContent('month-earnings', formatCurrency(0));
      setTextContent('active-services', '0');
      setTextContent('topbar-total', formatCurrency(0));
    }
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
          va = (ba && ba.balance) || a.balance || 0;
          vb = (bb && bb.balance) || b.balance || 0;
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
        case 'payout': {
          const coA = a.cashout || {};
          const coB = b.cashout || {};
          const balA = (breakdownMap[a.slug] && breakdownMap[a.slug].balance) || a.balance || 0;
          const balB = (breakdownMap[b.slug] && breakdownMap[b.slug].balance) || b.balance || 0;
          va = coA.min_amount > 0 ? (balA / coA.min_amount) : -1;
          vb = coB.min_amount > 0 ? (balB / coB.min_amount) : -1;
          break;
        }
        default:
          va = 0; vb = 0;
      }
      if (_sortCol !== 'name') {
        return _sortAsc ? va - vb : vb - va;
      }
      return 0;
    });
  }

  async function loadServicesTable() {
    const container = document.getElementById('services-table-container');
    if (!container) return;

    // Show spinner while loading (only on first load, not refresh)
    if (!container.querySelector('.breakdown-table')) {
      container.innerHTML = `<div style="display:flex; align-items:center; justify-content:center; gap:8px; padding:24px 0; color:var(--text-muted);"><div class="spinner"></div> Loading services...</div>`;
    }

    try {
      const [services, breakdown] = await Promise.all([
        api('/api/services/deployed'),
        api('/api/earnings/breakdown').catch(() => []),
      ]);

      if (!services || services.length === 0) {
        container.innerHTML = `
          <div class="empty-state" style="padding:32px 0; text-align:center;">
            <div class="empty-state-title">No services deployed yet</div>
            <div class="empty-state-text">Get started by deploying your first passive income service.</div>
            <a href="/setup" class="btn btn-primary" style="margin-top:12px;">Setup Wizard</a>
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
      const sortTh = (col, label, align) => {
        const style = align ? ` style="text-align:${align};"` : '';
        return `<th class="sortable" data-sort="${col}"${style}>${label}${sortIcon(col)}</th>`;
      };

      container.innerHTML = `
        <table class="breakdown-table">
          <thead>
            <tr>
              ${sortTh('name', 'Service', '')}
              ${sortTh('status', 'Status', 'center')}
              ${sortTh('health', 'Health', 'center')}
              ${sortTh('balance', 'Balance', 'right')}
              ${sortTh('change', 'Change', 'right')}
              ${sortTh('cpu', 'CPU', 'right')}
              ${sortTh('memory', 'Memory', 'right')}
              ${sortTh('payout', 'Payout', 'center')}
              <th style="text-align:center;">Actions</th>
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
      // Keep existing table if we had one; only show spinner on truly empty state
      if (!container.querySelector('.breakdown-table')) {
        container.innerHTML = `<div style="display:flex; align-items:center; justify-content:center; gap:8px; padding:24px 0; color:var(--text-muted);"><div class="spinner"></div> Loading services...</div>`;
      }
    }
  }

  function renderServiceRow(svc, bk) {
    const isExternal = svc.container_status === 'external';
    const statusClass = isExternal ? 'external' : (svc.container_status || 'stopped').toLowerCase();
    const statusLabel = isExternal ? 'External' : statusClass.charAt(0).toUpperCase() + statusClass.slice(1);
    const instances = svc.instances || 0;
    const details = svc.instance_details || [];
    const isMulti = details.length > 1;

    // Service name — linked to referral URL if available
    const name = escapeHtml(svc.name);
    const nameHtml = svc.referral_url
      ? `<a href="${escapeHtml(svc.referral_url)}" target="_blank" rel="noopener" title="Referral link" style="color:var(--accent); text-decoration:none; font-weight:600;">${name}</a>`
      : `<span style="font-weight:600;">${name}</span>`;

    // Subtitle: image for Docker, empty for external
    const subtitle = svc.image
      ? escapeHtml(svc.image)
      : (isExternal ? 'App / Browser' : '');

    // Health badge — external services always show --
    let healthBadge = '<span style="color:var(--text-muted);">--</span>';
    if (!isExternal && svc.health_score !== null && svc.health_score !== undefined) {
      const score = svc.health_score;
      const hClass = score >= 80 ? 'badge-running' : score >= 50 ? 'badge-error' : 'badge-stopped';
      healthBadge = `<span class="badge ${hClass}" title="Health ${score}/100">${score}</span>`;
    }

    // Balance + delta from breakdown
    const balance = (bk && bk.balance) || svc.balance || 0;
    const currency = (bk && bk.currency) || svc.currency || 'USD';
    const delta = bk ? bk.delta : 0;
    const deltaSign = delta > 0 ? '+' : '';
    const deltaClass = delta > 0 ? 'positive' : delta < 0 ? 'negative' : '';
    const deltaStr = delta !== 0 ? `${deltaSign}${formatCurrency(delta, currency)}` : '--';
    const nativeLabel = formatNative(balance, currency);
    const disconnectedLabel = svc.collector_disconnected
      ? '<div style="font-size:0.6rem; color:#ef4444; font-weight:500;">disconnected</div>'
      : '';
    let balanceHtml;
    if (nativeLabel) {
      balanceHtml = `${formatCurrency(balance, currency)}<div style="font-size:0.65rem;color:var(--text-muted);">${nativeLabel}</div>${disconnectedLabel}`;
    } else {
      balanceHtml = `${formatCurrency(balance, currency)}${disconnectedLabel}`;
    }

    // CPU/Memory — skip for external; show avg for multi-instance
    let cpuStr, memStr;
    if (isExternal) {
      cpuStr = '--';
      memStr = '--';
    } else if (isMulti && instances > 0) {
      const avgCpu = (parseFloat(svc.cpu) / instances).toFixed(2);
      const totalMem = parseFloat(svc.memory);
      const avgMem = (totalMem / instances).toFixed(1);
      cpuStr = `<span title="Average across ${instances} instances">~${avgCpu}%</span>`;
      memStr = `<span title="Average across ${instances} instances">~${avgMem} MB</span>`;
    } else {
      cpuStr = `${svc.cpu || '0'}%`;
      memStr = svc.memory || '0 MB';
    }

    // Payout progress
    const co = svc.cashout || {};
    const minAmount = co.min_amount || 0;
    const eligible = minAmount > 0 && balance >= minAmount;
    const pctToMin = minAmount > 0 ? Math.min(100, (balance / minAmount) * 100) : 0;
    const progressBar = minAmount > 0 ? `
      <div class="payout-progress" title="${formatCurrency(balance, currency)} / ${formatCurrency(minAmount, currency)}" style="min-width:60px;">
        <div class="payout-progress-bar ${eligible ? 'eligible' : ''}" style="width:${pctToMin.toFixed(0)}%"></div>
      </div>
      <span class="payout-label">${pctToMin.toFixed(0)}%</span>
    ` : '<span style="color:var(--text-muted);">--</span>';

    // Payout (claim) button — always visible in main row
    const claimTitle = co.dashboard_url
      ? (eligible ? 'Cash out earnings' : 'View payout details')
      : 'No payout info available';
    const claimDisabled = !co.dashboard_url;
    const claimBtn = `<button class="btn btn-icon ${eligible ? 'btn-success' : ''}" onclick="${claimDisabled ? '' : `CP.openClaimModal('${svc.slug}')`}" title="${claimTitle}"${claimDisabled ? ' disabled' : ''}>
           <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/></svg>
         </button>`;

    // Instance badge (shown next to status)
    const instanceLabel = !isExternal && instances > 0
      ? ` <span class="badge badge-instances" title="${instances} instance${instances > 1 ? 's' : ''}">${instances}x</span>`
      : '';

    // For multi-instance: expand chevron, no container action buttons in main row
    // For single instance: show action buttons directly
    let actionBtns;
    if (isMulti) {
      const chevron = `<button class="btn btn-icon expand-toggle" onclick="event.stopPropagation(); CP.toggleInstances('${svc.slug}')" title="Expand instances">
        <svg class="expand-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
      </button>`;
      actionBtns = `<div class="action-btns">${claimBtn}${chevron}</div>`;
    } else if (isExternal) {
      actionBtns = `<div class="action-btns">${claimBtn}</div>`;
    } else {
      // Single instance — build container buttons targeting the right node
      const inst = details[0] || {};
      const wParam = inst.worker_id != null ? `', ${inst.worker_id}` : `'`;
      const disabledAttr = !inst.has_docker ? ' disabled title="No Docker access"' : '';
      actionBtns = `<div class="action-btns">
          ${claimBtn}
          <button class="btn btn-icon" onclick="CP.restartService('${svc.slug}${wParam})" title="Restart"${disabledAttr}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/></svg>
          </button>
          <button class="btn btn-icon" onclick="CP.stopService('${svc.slug}${wParam})" title="Stop"${disabledAttr}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>
          </button>
          <button class="btn btn-icon" onclick="CP.viewLogs('${svc.slug}${wParam})" title="Logs"${disabledAttr}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
          </button>
        </div>`;
    }

    // Main row
    let html = `
    <tr class="breakdown-row${isMulti ? ' expandable' : ''}" data-slug="${escapeHtml(svc.slug)}"${isMulti ? ` onclick="CP.toggleInstances('${escapeHtml(svc.slug)}', event)" style="cursor:pointer;"` : ''}>
      <td>${nameHtml}<div style="font-size:0.7rem; color:var(--text-muted);">${subtitle}</div></td>
      <td style="text-align:center;"><span class="badge badge-${statusClass}"><span class="status-dot ${statusClass}"></span> ${statusLabel}</span>${instanceLabel}</td>
      <td style="text-align:center;">${healthBadge}</td>
      <td style="text-align:right; font-weight:600;">${balanceHtml}</td>
      <td style="text-align:right;"><span class="stat-change ${deltaClass}">${deltaStr}</span></td>
      <td style="text-align:right;">${cpuStr}</td>
      <td style="text-align:right;">${memStr}</td>
      <td style="text-align:center;">${progressBar}</td>
      <td style="text-align:center; white-space:nowrap;">${actionBtns}</td>
    </tr>`;

    // Sub-rows for multi-instance (hidden by default)
    if (isMulti) {
      for (const inst of details) {
        const iStatus = (inst.status || 'unknown').toLowerCase();
        const iStatusLabel = iStatus.charAt(0).toUpperCase() + iStatus.slice(1);
        const nodeLabel = inst.node === 'local' ? 'Local' : escapeHtml(inst.node);
        const wParam = inst.worker_id != null ? `', ${inst.worker_id}` : `'`;
        const disabledAttr = !inst.has_docker ? ' disabled title="No Docker access"' : '';
        html += `
        <tr class="instance-row" data-parent="${escapeHtml(svc.slug)}" style="display:none;">
          <td style="padding-left:28px;">
            <span class="instance-node-label">${nodeLabel}</span>
            <span style="font-size:0.7rem; color:var(--text-muted); margin-left:4px;">${escapeHtml(inst.container_name)}</span>
          </td>
          <td style="text-align:center;"><span class="badge badge-${iStatus}"><span class="status-dot ${iStatus}"></span> ${iStatusLabel}</span></td>
          <td></td>
          <td></td>
          <td></td>
          <td style="text-align:right;">${inst.cpu || '0'}%</td>
          <td style="text-align:right;">${inst.memory || '0 MB'}</td>
          <td></td>
          <td style="text-align:center; white-space:nowrap;">
            <div class="action-btns">
              <button class="btn btn-icon" onclick="CP.restartService('${svc.slug}${wParam})" title="Restart on ${nodeLabel}"${disabledAttr}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/></svg>
              </button>
              <button class="btn btn-icon" onclick="CP.stopService('${svc.slug}${wParam})" title="Stop on ${nodeLabel}"${disabledAttr}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>
              </button>
              <button class="btn btn-icon" onclick="CP.viewLogs('${svc.slug}${wParam})" title="Logs on ${nodeLabel}"${disabledAttr}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
              </button>
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
    toast('Services refreshed', 'info');
  }

  async function loadEarningsChart(days) {
    const ctx = document.getElementById('earnings-chart');
    if (!ctx) return;

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
      // Generate placeholder data
      const now = new Date();
      const count = parseInt(days) || 7;
      for (let i = count - 1; i >= 0; i--) {
        const d = new Date(now);
        d.setDate(d.getDate() - i);
        labels.push(d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }));
        values.push(0);
      }
    }

    if (earningsChart) {
      earningsChart.data.labels = labels;
      earningsChart.data.datasets[0].data = values;
      earningsChart.update();
      return;
    }

    earningsChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          label: 'Daily Earnings',
          data: values,
          backgroundColor: 'rgba(244, 63, 94, 0.4)',
          borderColor: 'rgba(244, 63, 94, 0.9)',
          borderWidth: 1,
          borderRadius: 4,
          hoverBackgroundColor: 'rgba(244, 63, 94, 0.6)',
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#0e0e1a',
            titleColor: '#e8e6f0',
            bodyColor: '#9d95b0',
            borderColor: 'rgba(139, 92, 246, 0.2)',
            borderWidth: 1,
            padding: 10,
            callbacks: {
              label: (ctx) => formatCurrency(ctx.parsed.y),
            },
          },
        },
        scales: {
          x: {
            grid: { color: 'rgba(139, 92, 246, 0.08)' },
            ticks: { color: '#6b6280', font: { size: 11 } },
          },
          y: {
            beginAtZero: true,
            grid: { color: 'rgba(139, 92, 246, 0.08)' },
            ticks: {
              color: '#6b6280',
              font: { size: 11 },
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
  // Claim Modal
  // -----------------------------------------------------------
  let _breakdownCache = [];

  async function openClaimModal(platform) {
    openModal('claim-modal');
    const title = document.getElementById('claim-modal-title');
    const body = document.getElementById('claim-modal-body');

    if (title) title.textContent = 'Checking eligibility...';
    if (body) body.innerHTML = '<div class="spinner" style="margin:24px auto;"></div>';

    try {
      const data = await api('/api/earnings/breakdown');
      const svc = data.find(s => s.platform === platform);
      if (!svc) {
        if (body) body.innerHTML = '<p>Service not found.</p>';
        return;
      }

      const co = svc.cashout || {};
      const eligible = co.eligible;
      const minAmount = co.min_amount || 0;
      const currency = svc.currency || 'USD';

      if (title) title.textContent = `Claim — ${svc.name}`;

      const statusIcon = eligible
        ? '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--success)" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="16 8 10 16 7 13"/></svg>'
        : '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--warning)" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>';

      const statusText = eligible
        ? `<span style="color:var(--success); font-weight:600; font-size:1.1rem;">Eligible for payout!</span>`
        : `<span style="color:var(--warning); font-weight:600; font-size:1.1rem;">Below minimum payout</span>`;

      const pctToMin = minAmount > 0 ? Math.min(100, (svc.balance / minAmount) * 100) : 0;
      const remaining = Math.max(0, minAmount - svc.balance);

      const progressSection = minAmount > 0 ? `
        <div style="margin: 20px 0;">
          <div style="display:flex; justify-content:space-between; font-size:0.85rem; margin-bottom:6px;">
            <span>Current: <strong>${formatCurrency(svc.balance, currency)}</strong></span>
            <span>Minimum: <strong>${formatCurrency(minAmount, currency)}</strong></span>
          </div>
          <div class="payout-progress" style="height:10px; border-radius:5px;">
            <div class="payout-progress-bar ${eligible ? 'eligible' : ''}" style="width:${pctToMin.toFixed(0)}%; height:100%; border-radius:5px;"></div>
          </div>
          ${!eligible ? `<div style="font-size:0.85rem; color:var(--text-muted); margin-top:8px;">Need ${formatCurrency(remaining, currency)} more to reach minimum payout.</div>` : ''}
        </div>` : '';

      const notesSection = co.notes
        ? `<div style="background:var(--bg-tertiary); border:1px solid var(--border-color); border-radius:var(--radius); padding:12px; margin:16px 0; font-size:0.85rem; color:var(--text-secondary);">
             <strong style="color:var(--text-primary);">Notes:</strong> ${escapeHtml(co.notes)}
           </div>`
        : '';

      const methodLabel = {
        redirect: 'You will be redirected to the service dashboard to complete the payout.',
        api: 'Payout will be triggered via the service API.',
        manual: 'Follow the instructions below to claim your earnings.',
      };

      const actionSection = eligible && co.dashboard_url
        ? `<div style="margin-top:20px; text-align:center;">
             <p style="font-size:0.85rem; color:var(--text-secondary); margin-bottom:12px;">${methodLabel[co.method] || methodLabel.redirect}</p>
             <a href="${escapeHtml(co.dashboard_url)}" target="_blank" rel="noopener" class="btn btn-success btn-lg" style="min-width:200px;">
               <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
               Go to Dashboard
             </a>
           </div>`
        : !eligible
          ? `<div style="margin-top:16px; text-align:center;">
               <p style="font-size:0.85rem; color:var(--text-muted);">Keep your service running to accumulate more earnings.</p>
             </div>`
          : '';

      if (body) body.innerHTML = `
        <div style="text-align:center; padding:8px 0;">
          ${statusIcon}
          <div style="margin-top:12px;">${statusText}</div>
        </div>
        ${progressSection}
        ${notesSection}
        ${actionSection}
      `;
    } catch (err) {
      if (body) body.innerHTML = `<p style="color:var(--error);">Error: ${escapeHtml(err.message)}</p>`;
    }
  }

  // -----------------------------------------------------------
  // Service actions
  // -----------------------------------------------------------
  async function restartService(slug, workerId) {
    const q = workerId != null ? `?worker_id=${workerId}` : '';
    try {
      await api(`/api/services/${slug}/restart${q}`, { method: 'POST' });
      toast(`${slug} restarting...`, 'success');
      loadServicesTable();
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function stopService(slug, workerId) {
    const q = workerId != null ? `?worker_id=${workerId}` : '';
    try {
      await api(`/api/services/${slug}/stop${q}`, { method: 'POST' });
      toast(`${slug} stopped`, 'success');
      loadServicesTable();
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function startService(slug, workerId) {
    const q = workerId != null ? `?worker_id=${workerId}` : '';
    try {
      await api(`/api/services/${slug}/start${q}`, { method: 'POST' });
      toast(`${slug} starting...`, 'success');
      loadServicesTable();
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function removeService(slug) {
    if (!confirm(`Remove ${slug}? This will stop and delete the container.`)) return;
    try {
      await api(`/api/services/${slug}`, { method: 'DELETE' });
      toast(`${slug} removed`, 'success');
      loadServicesTable();
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  // -----------------------------------------------------------
  // Log viewer
  // -----------------------------------------------------------
  let logPollTimer = null;

  async function viewLogs(slug, workerId) {
    openModal('logs-modal');
    const title = document.getElementById('logs-modal-title');
    const viewer = document.getElementById('log-content');
    const label = workerId != null ? `${slug} (worker #${workerId})` : slug;
    if (title) title.textContent = `Logs: ${label}`;
    if (viewer) viewer.textContent = 'Loading logs...';

    if (logPollTimer) clearInterval(logPollTimer);
    const q = workerId != null ? `lines=200&worker_id=${workerId}` : 'lines=200';

    async function fetchLogs() {
      try {
        const data = await api(`/api/services/${slug}/logs?${q}`);
        if (viewer) viewer.textContent = data.logs || '(no logs)';
        viewer.scrollTop = viewer.scrollHeight;
      } catch (err) {
        if (viewer) viewer.textContent = `Error loading logs: ${err.message}`;
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
  };

  async function initWizard() {
    wizardState = { step: 1, categories: [], selectedServices: [], deployed: [] };

    // Pre-populate from saved preferences
    try {
      const prefs = await api('/api/preferences');
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

    updateWizardUI();

    // Category card toggles
    document.querySelectorAll('.category-card').forEach(card => {
      card.addEventListener('click', () => {
        card.classList.toggle('selected');
        const cb = card.querySelector('input[type="checkbox"]');
        if (cb) cb.checked = card.classList.contains('selected');
        wizardState.categories = Array.from(document.querySelectorAll('.category-card.selected input'))
          .map(input => input.value);
      });
    });
  }

  function wizardNext() {
    if (wizardState.step === 1 && wizardState.categories.length === 0) {
      toast('Select at least one category', 'warning');
      return;
    }
    if (wizardState.step === 2 && wizardState.selectedServices.length === 0) {
      toast('Select at least one service to deploy', 'warning');
      return;
    }
    if (wizardState.step < 4) {
      wizardState.step++;
      updateWizardUI();
      if (wizardState.step === 2) loadWizardServices();
      if (wizardState.step === 3) loadWizardSetupForms();
    }
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
        nextBtn.textContent = 'Skip to Summary';
        nextBtn.style.display = '';
      } else {
        nextBtn.textContent = 'Next';
        nextBtn.style.display = '';
      }
    }
  }

  // Cached worker container data for wizard
  let _wizardWorkerSlugs = {};  // slug -> node count
  let _wizardWorkers = [];      // full workers array from /api/workers

  // Global worker cache for detail modal
  let _cachedWorkers = null;
  async function getCachedWorkers() {
    if (_cachedWorkers) return _cachedWorkers;
    try {
      _cachedWorkers = await api('/api/workers');
    } catch {
      _cachedWorkers = [];
    }
    return _cachedWorkers;
  }
  function invalidateWorkerCache() { _cachedWorkers = null; }

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
        container.innerHTML = '<p class="empty-state-text">No services found for the selected categories.</p>';
        return;
      }
      container.innerHTML = filtered.map(renderWizardServiceCard).join('');
    } catch (err) {
      container.innerHTML = '<p class="empty-state-text">Could not load services. Is the API running?</p>';
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
      const label = totalNodes === 1 ? 'Deployed on 1 node' : `Deployed on ${totalNodes} nodes`;
      deployedBadge = `<span class="deployed-badge"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg> ${label}</span>`;
    }

    // Platform notice for manual-only services
    let manualNotice = '';
    if (isManual) {
      const platforms = (svc.platforms || []).map(p => p.charAt(0).toUpperCase() + p.slice(1)).join('/');
      manualNotice = `<div class="manual-notice">${platforms || 'Desktop'} only — earnings tracking available</div>`;
    }

    return `
    <div class="${classes.join(' ')}" data-slug="${svc.slug}" onclick="CP.toggleWizardService('${svc.slug}', this)">
      <div class="service-card-header">
        <div class="service-icon">${(svc.name || '?')[0]}</div>
        <div>
          <div class="service-name">${escapeHtml(svc.name)}</div>
          <span class="badge badge-category">${escapeHtml(capFirst(svc.category))}</span>
        </div>
      </div>
      <div class="service-desc">${escapeHtml(svc.short_description || '')}</div>
      ${manualNotice}
      <div class="service-meta" style="margin-top: 8px;">
        ${svc.requirements && svc.requirements.residential_ip ? '<span class="badge badge-residential">Residential IP</span>' : ''}
        ${deployedBadge}
      </div>
    </div>`;
  }

  function toggleWizardService(slug, el) {
    const idx = wizardState.selectedServices.indexOf(slug);
    if (idx >= 0) {
      wizardState.selectedServices.splice(idx, 1);
      el.classList.remove('selected');
    } else {
      wizardState.selectedServices.push(slug);
      el.classList.add('selected');
    }
  }

  async function loadWizardSetupForms() {
    const container = document.getElementById('wizard-setup-forms');
    if (!container) return;

    container.innerHTML = '<div class="spinner" style="margin:24px auto;"></div>';

    try {
      const [services, workers] = await Promise.all([
        api('/api/services/available'),
        _wizardWorkers.length ? Promise.resolve(_wizardWorkers) : api('/api/workers').catch(() => []),
      ]);
      _wizardWorkers = workers;
      const selected = services.filter(s => wizardState.selectedServices.includes(s.slug));
      container.innerHTML = selected.map(svc => renderServiceSetupForm(svc, workers)).join('');
    } catch (err) {
      container.innerHTML = '<p class="empty-state-text">Could not load service details.</p>';
    }
  }

  function renderServiceSetupForm(svc, workers) {
    const signupUrl = svc.referral && svc.referral.signup_url
      ? svc.referral.signup_url
      : svc.website || '#';

    // Manual-only services: show signup link + earnings tracking notice + any env fields
    if (svc.manual_only) {
      const platforms = (svc.platforms || []).map(p => p.charAt(0).toUpperCase() + p.slice(1)).join(', ');
      const manualEnvFields = (svc.docker && svc.docker.env || []).map(env => {
        const inputType = env.secret ? 'password' : 'text';
        return `
        <div class="form-group">
          <label class="form-label" for="env-${svc.slug}-${env.key}">${escapeHtml(env.label)}</label>
          <input class="form-input" type="${inputType}" id="env-${svc.slug}-${env.key}"
                 data-slug="${svc.slug}" data-key="${env.key}"
                 placeholder="${escapeHtml(env.description || '')}"
                 value="${escapeHtml(env.default || '')}"
                 ${env.required ? 'required' : ''}>
          ${env.description ? `<div class="form-hint">${escapeHtml(env.description)}</div>` : ''}
        </div>`;
      }).join('');
      return `
      <div class="card" style="margin-bottom: 16px;" id="setup-${svc.slug}">
        <div class="card-header">
          <h3 class="section-title">${escapeHtml(svc.name)}</h3>
          <span class="badge badge-category">${escapeHtml(capFirst(svc.category))}</span>
        </div>
        <div style="padding: 8px 0;">
          <p style="color: var(--warning, #f59e0b); margin-bottom: 12px;">
            <strong>${platforms || 'Desktop'} only</strong> — no Docker image available for automated deployment.
          </p>
          <p style="color: var(--text-secondary); margin-bottom: 16px;">
            Install the app on your device, then CashPilot will track your earnings automatically.
          </p>
          <a href="${escapeHtml(signupUrl)}" target="_blank" rel="noopener" class="btn btn-primary btn-sm">
            Sign Up for ${escapeHtml(svc.name)}
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
          </a>
          ${manualEnvFields ? `<div style="margin-top: 16px;">${manualEnvFields}</div>` : ''}
        </div>
      </div>`;
    }

    const envFields = (svc.docker && svc.docker.env || []).map(env => {
      const inputType = env.secret ? 'password' : 'text';
      return `
      <div class="form-group">
        <label class="form-label" for="env-${svc.slug}-${env.key}">${escapeHtml(env.label)}</label>
        <input class="form-input" type="${inputType}" id="env-${svc.slug}-${env.key}"
               data-slug="${svc.slug}" data-key="${env.key}"
               placeholder="${escapeHtml(env.description || '')}"
               value="${escapeHtml(env.default || '')}"
               ${env.required ? 'required' : ''}>
        ${env.description ? `<div class="form-hint">${escapeHtml(env.description)}</div>` : ''}
      </div>`;
    }).join('');

    return `
    <div class="card" style="margin-bottom: 16px;" id="setup-${svc.slug}">
      <div class="card-header">
        <h3 class="section-title">${escapeHtml(svc.name)}</h3>
        <span class="badge badge-category">${escapeHtml(capFirst(svc.category))}</span>
      </div>

      <div style="margin-bottom: 16px;">
        <p style="color: var(--text-secondary); margin-bottom: 12px;">
          New to ${escapeHtml(svc.name)}?
          <a href="${escapeHtml(signupUrl)}" target="_blank" rel="noopener" class="btn btn-primary btn-sm" style="margin-left: 8px;">
            Sign Up
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
          </a>
        </p>
        <p style="color: var(--text-muted); font-size: 0.85rem;">Already have an account? Enter your credentials below.</p>
      </div>

      ${envFields}

      ${(() => {
        const onlineWorkers = (workers || []).filter(w => w.status === 'online');
        let workerRows = '';
        let allDeployed = true;
        for (const w of onlineWorkers) {
          const slugs = (w.containers || []).map(c => c.slug);
          const deployed = slugs.includes(svc.slug);
          if (!deployed) allDeployed = false;
          workerRows += `
          <label style="display:flex; align-items:center; gap:8px; padding:6px 0; ${deployed ? 'opacity:0.5;' : ''}">
            <input type="checkbox" class="setup-deploy-worker-cb" data-slug="${svc.slug}" data-wid="${w.id}" ${deployed ? 'disabled checked' : ''}>
            <span>${escapeHtml(w.name)}</span>
            ${deployed ? '<span class="badge badge-deployed" style="font-size:0.75rem;">Deployed</span>' : '<span class="badge badge-available" style="font-size:0.75rem;">Available</span>'}
          </label>`;
        }

        if (onlineWorkers.length === 0) {
          return `<p style="color:var(--text-muted); font-size:0.85rem; margin-bottom:12px;">No workers online.</p>`;
        }

        if (allDeployed) {
          return `<p style="color:var(--success); font-size:0.9rem; margin:12px 0;">Deployed on all nodes.</p>`;
        }

        return `
        <div style="margin-bottom:12px;">
          <div style="font-size:0.85rem; color:var(--text-muted); margin-bottom:6px;">Deploy to Workers:</div>
          <div id="setup-worker-list-${svc.slug}">${workerRows}</div>
        </div>
        <div style="display:flex; gap:8px; align-items:center;">
          <button class="btn btn-success" onclick="CP.deployService('${svc.slug}')">
            Deploy ${escapeHtml(svc.name)}
          </button>
          <span class="deploy-status" id="deploy-status-${svc.slug}" style="margin-left: 4px; font-size: 0.85rem;"></span>
        </div>`;
      })()}
    </div>`;
  }

  async function deployService(slug) {
    const statusEl = document.getElementById(`deploy-status-${slug}`);
    const checkboxes = document.querySelectorAll(`.setup-deploy-worker-cb[data-slug="${slug}"]:checked:not(:disabled)`);
    const workerIds = Array.from(checkboxes).map(cb => parseInt(cb.dataset.wid));

    if (workerIds.length === 0) {
      toast('Select at least one worker node', 'warning');
      if (statusEl) statusEl.textContent = 'Select at least one node.';
      return;
    }

    // Collect env vars (only env inputs, not worker checkboxes)
    const envInputs = document.querySelectorAll(`input[data-slug="${slug}"][data-key]`);
    const env = {};
    let missingRequired = false;
    envInputs.forEach(input => {
      env[input.dataset.key] = input.value;
      if (input.required && !input.value.trim()) {
        input.style.borderColor = 'var(--error)';
        missingRequired = true;
      } else {
        input.style.borderColor = '';
      }
    });

    if (missingRequired) {
      toast('Fill in all required fields', 'warning');
      if (statusEl) statusEl.textContent = '';
      return;
    }

    if (statusEl) {
      statusEl.innerHTML = '<span class="spinner" style="display:inline-block;width:14px;height:14px;vertical-align:middle;"></span> Deploying...';
    }

    let ok = 0, fail = 0;
    for (const wid of workerIds) {
      try {
        await api(`/api/deploy/${slug}?worker_id=${wid}`, { method: 'POST', body: { env } });
        ok++;
      } catch (err) {
        fail++;
        toast(`Deploy to worker ${wid} failed: ${err.message}`, 'error');
      }
    }

    if (statusEl) {
      statusEl.textContent = fail === 0 ? `Deployed to ${ok} node(s)` : `${ok} ok, ${fail} failed`;
      statusEl.style.color = fail === 0 ? 'var(--success)' : 'var(--error)';
    }
    if (ok > 0) {
      toast(`${slug} deployed to ${ok} node(s)`, 'success');
      if (!wizardState.deployed.includes(slug)) {
        wizardState.deployed.push(slug);
      }
    }
  }

  // -----------------------------------------------------------
  // Catalog
  // -----------------------------------------------------------
  let catalogServices = [];

  async function loadCatalog() {
    try {
      catalogServices = await api('/api/services/available');
    } catch (err) {
      catalogServices = [];
    }
    filterCatalog();
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
      container.innerHTML = '<div class="empty-state"><div class="empty-state-text">No services match your filters.</div></div>';
      return;
    }

    container.innerHTML = filtered.map(renderCatalogCard).join('');
  }

  function renderCatalogCard(svc) {
    const initial = (svc.name || '?')[0].toUpperCase();
    const earning = svc.earnings
      ? `$${svc.earnings.monthly_low}-$${svc.earnings.monthly_high}/${svc.earnings.per || 'mo'}`
      : 'Varies';
    const isDeployed = svc.deployed || false;
    const statusBadge = svc.status === 'broken'
      ? '<span class="badge badge-broken">Broken</span>'
      : isDeployed
        ? '<span class="badge badge-deployed">Deployed</span>'
        : '<span class="badge badge-available">Available</span>';

    const hasDocker = svc.docker && svc.docker.image;
    let actionBtn;
    if (isDeployed) {
      actionBtn = `<button class="btn btn-secondary btn-sm" onclick="CP.openServiceDetail('${svc.slug}')">Manage</button>`;
    } else if (hasDocker) {
      actionBtn = `<button class="btn btn-primary btn-sm" onclick="CP.openServiceDetail('${svc.slug}')">Deploy</button>`;
    } else {
      const url = (svc.referral && svc.referral.signup_url) || svc.website || '#';
      actionBtn = `<a href="${escapeHtml(url)}" target="_blank" rel="noopener" class="btn btn-ghost btn-sm">Visit</a>`;
    }

    // Platform list — add Docker if service has a Docker image
    const allPlatforms = [...(svc.platforms || [])];
    if (hasDocker && !allPlatforms.includes('docker')) allPlatforms.unshift('docker');
    const platformBadges = allPlatforms.map(p =>
      `<span class="platform-badge">${escapeHtml(p)}</span>`
    ).join('');

    const deployedClass = isDeployed ? ' service-card-deployed' : '';

    return `
    <div class="service-card${deployedClass}" data-slug="${svc.slug}">
      <div class="service-card-header">
        <div class="service-icon">${initial}</div>
        <div style="flex:1;">
          <div class="service-name">${escapeHtml(svc.name)}</div>
          <div class="service-desc" style="margin-top:2px;">${escapeHtml(svc.short_description || '')}</div>
        </div>
      </div>
      <div class="service-meta">
        <span class="badge badge-category">${escapeHtml(capFirst(svc.category))}</span>
        ${statusBadge}
        ${svc.requirements && svc.requirements.residential_ip ? '<span class="badge badge-residential">Residential IP</span>' : ''}
      </div>
      ${platformBadges ? `<div class="platform-badges" style="margin-top:8px;">${platformBadges}</div>` : ''}
      <div class="service-stats" style="margin-top:12px; padding-top:12px; border-top:1px solid var(--border-color);">
        <span></span>
        ${actionBtn}
      </div>
    </div>`;
  }

  function initCatalogFilters() {
    document.querySelectorAll('.filter-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        document.querySelectorAll('.filter-tab').forEach(t => t.classList.remove('active'));
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
    if (body) body.innerHTML = '<div class="spinner" style="margin:24px auto;"></div>';
    if (title) title.textContent = 'Loading...';

    try {
      const [svc, workers] = await Promise.all([
        api(`/api/services/${slug}`),
        api('/api/workers').catch(() => []),
      ]);
      _detailWorkers = workers;
      if (title) title.textContent = svc.name;
      if (body) body.innerHTML = renderServiceDetail(svc, workers);
    } catch (err) {
      if (body) body.innerHTML = `<p class="empty-state-text">Could not load service: ${escapeHtml(err.message)}</p>`;
    }
  }

  function renderServiceDetail(svc, workers) {
    const earning = svc.earnings
      ? `$${svc.earnings.monthly_low}-$${svc.earnings.monthly_high} per ${svc.earnings.per || 'month'}`
      : 'Varies';

    const signupUrl = svc.referral && svc.referral.signup_url
      ? svc.referral.signup_url
      : svc.website || '#';

    // --- Info grid (no referral bonus) ---
    let html = `
    <p style="color: var(--text-secondary); margin-bottom: 16px;">${escapeHtml(svc.description || svc.short_description || '')}</p>
    <div class="detail-grid" style="margin-bottom: 20px;">
      <div class="detail-item">
        <div class="detail-label">Category</div>
        <div class="detail-value">${escapeHtml(capFirst(svc.category))}</div>
      </div>
      <div class="detail-item">
        <div class="detail-label">Estimated Earnings</div>
        <div class="detail-value" style="color: var(--success);">${earning}</div>
      </div>
      <div class="detail-item">
        <div class="detail-label">Payout</div>
        <div class="detail-value">${escapeHtml((svc.payment?.methods || []).join(', ') || 'N/A')} (min ${escapeHtml(svc.payment?.minimum_payout || 'N/A')})</div>
      </div>
    </div>`;

    // --- Sign Up (only if NOT deployed anywhere) ---
    if (!svc.deployed) {
      html += `
      <div style="margin-bottom: 20px;">
        <a href="${escapeHtml(signupUrl)}" target="_blank" rel="noopener" class="btn btn-primary btn-sm">
          Sign Up / Log In for ${escapeHtml(svc.name)}
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
        </a>
      </div>`;
    }

    // --- Deploy section (worker-aware) ---
    const hasDocker = svc.docker && svc.docker.image;
    if (hasDocker) {
      const envFields = (svc.docker.env || []).map(env => {
        const inputType = env.secret ? 'password' : 'text';
        return `
        <div class="form-group">
          <label class="form-label">${escapeHtml(env.label)}</label>
          <input class="form-input" type="${inputType}" data-slug="${svc.slug}" data-key="${env.key}"
                 placeholder="${escapeHtml(env.description || '')}" value="${escapeHtml(env.default || '')}"
                 ${env.required ? 'required' : ''}>
        </div>`;
      }).join('');

      // Worker deploy targets
      const onlineWorkers = (workers || []).filter(w => w.status === 'online');
      let workerRows = '';
      let allDeployed = true;
      for (const w of onlineWorkers) {
        const slugs = (w.containers || []).map(c => c.slug);
        const deployed = slugs.includes(svc.slug);
        if (!deployed) allDeployed = false;
        workerRows += `
        <label style="display:flex; align-items:center; gap:8px; padding:6px 0; ${deployed ? 'opacity:0.5;' : ''}">
          <input type="checkbox" class="deploy-worker-cb" data-wid="${w.id}" ${deployed ? 'disabled checked' : ''}>
          <span>${escapeHtml(w.name)}</span>
          ${deployed ? '<span class="badge badge-deployed" style="font-size:0.75rem;">Deployed</span>' : '<span class="badge badge-available" style="font-size:0.75rem;">Available</span>'}
        </label>`;
      }

      if (onlineWorkers.length === 0) {
        workerRows = '<p style="color:var(--text-muted); font-size:0.85rem;">No workers online.</p>';
      }

      html += `<h4 style="margin-bottom: 12px; font-size: 0.95rem;">Deploy</h4>`;
      html += envFields;

      if (allDeployed && onlineWorkers.length > 0) {
        html += `<p style="color:var(--success); font-size:0.9rem; margin:12px 0;">Deployed on all nodes.</p>`;
      } else {
        html += `
        <div style="margin-bottom:12px;">
          <div style="font-size:0.85rem; color:var(--text-muted); margin-bottom:6px;">Select target nodes:</div>
          <div id="deploy-worker-list">${workerRows}</div>
        </div>
        <div style="display:flex; gap:8px; align-items:center;">
          <button class="btn btn-success" onclick="CP.deployServiceToWorkers('${svc.slug}')">Deploy</button>
          <span id="deploy-status-${svc.slug}" style="font-size:0.85rem;"></span>
        </div>`;
      }
    }

    // --- Container management (per worker) ---
    const onlineWorkers = (workers || []).filter(w => w.status === 'online');
    const instances = [];
    for (const w of onlineWorkers) {
      const container = (w.containers || []).find(c => c.slug === svc.slug);
      if (container) instances.push({ worker: w, container });
    }

    if (instances.length > 0) {
      html += `
      <div style="margin-top: 24px; padding-top: 16px; border-top: 1px solid var(--border-color);">
        <h4 style="margin-bottom: 12px; font-size: 0.95rem;">Running Instances</h4>`;
      for (const inst of instances) {
        const s = inst.container.status || 'unknown';
        const badgeClass = s === 'running' ? 'badge-deployed' : 'badge-broken';
        html += `
        <div style="display:flex; align-items:center; gap:10px; padding:8px 0; border-bottom:1px solid var(--border-color);">
          <strong style="min-width:100px;">${escapeHtml(inst.worker.name)}</strong>
          <span class="badge ${badgeClass}" style="font-size:0.75rem;">${escapeHtml(s)}</span>
          <div style="margin-left:auto; display:flex; gap:4px;">
            <button class="btn btn-secondary btn-sm" onclick="CP.workerAction('${svc.slug}','restart',${inst.worker.id})">Restart</button>
            <button class="btn btn-secondary btn-sm" onclick="CP.workerAction('${svc.slug}','stop',${inst.worker.id})">Stop</button>
            <button class="btn btn-ghost btn-sm" onclick="CP.loadWorkerLogs('${svc.slug}',${inst.worker.id},'logs-${svc.slug}-${inst.worker.id}')">Logs</button>
          </div>
        </div>
        <div class="log-viewer" id="logs-${svc.slug}-${inst.worker.id}" style="display:none; max-height:200px;"></div>`;
      }
      html += `</div>`;
    }

    return html;
  }

  async function deployServiceToWorkers(slug) {
    const statusEl = document.getElementById(`deploy-status-${slug}`);
    const checkboxes = document.querySelectorAll('.deploy-worker-cb:checked:not(:disabled)');
    const workerIds = Array.from(checkboxes).map(cb => parseInt(cb.dataset.wid));

    if (workerIds.length === 0) {
      if (statusEl) statusEl.textContent = 'Select at least one node.';
      return;
    }

    // Collect env vars
    const envInputs = document.querySelectorAll(`input[data-slug="${slug}"]`);
    const env = {};
    envInputs.forEach(input => { if (input.dataset.key) env[input.dataset.key] = input.value; });

    if (statusEl) statusEl.innerHTML = '<span class="spinner" style="display:inline-block;width:14px;height:14px;vertical-align:middle;"></span> Deploying...';

    let ok = 0, fail = 0;
    for (const wid of workerIds) {
      try {
        await api(`/api/deploy/${slug}?worker_id=${wid}`, { method: 'POST', body: { env } });
        ok++;
      } catch (err) {
        fail++;
      }
    }
    if (statusEl) {
      statusEl.textContent = fail === 0 ? `Deployed to ${ok} node(s)` : `${ok} ok, ${fail} failed`;
      statusEl.style.color = fail === 0 ? 'var(--success)' : 'var(--danger)';
    }
  }

  async function workerAction(slug, action, workerId) {
    try {
      await api(`/api/containers/${slug}/${action}?worker_id=${workerId}`, { method: 'POST' });
      // Refresh the modal
      openServiceDetail(slug);
    } catch (err) {
      alert(`${action} failed: ${err.message}`);
    }
  }

  async function loadWorkerLogs(slug, workerId, elemId) {
    const viewer = document.getElementById(elemId);
    if (!viewer) return;
    if (viewer.style.display === 'none') {
      viewer.style.display = 'block';
      viewer.textContent = 'Loading...';
      try {
        const data = await api(`/api/containers/${slug}/logs?worker_id=${workerId}&lines=100`);
        viewer.textContent = data.logs || '(no logs)';
        viewer.scrollTop = viewer.scrollHeight;
      } catch (err) {
        viewer.textContent = `Error: ${err.message}`;
      }
    } else {
      viewer.style.display = 'none';
    }
  }

  async function loadDetailLogs(slug) {
    // Legacy — kept for backward compat
    const viewer = document.getElementById(`detail-logs-${slug}`);
    if (!viewer) return;
    viewer.textContent = 'Loading...';
    try {
      const data = await api(`/api/services/${slug}/logs?lines=100`);
      viewer.textContent = data.logs || '(no logs)';
      viewer.scrollTop = viewer.scrollHeight;
    } catch (err) {
      viewer.textContent = `Error: ${err.message}`;
    }
  }

  // -----------------------------------------------------------
  // Settings
  // -----------------------------------------------------------
  async function loadSettings() {
    populateCurrencyDropdown();
    try {
      const config = await api('/api/config');
      populateSettings(config);

      // Populate collector credential fields from config
      document.querySelectorAll('.collector-input').forEach(input => {
        const key = input.dataset.config;
        if (config[key]) {
          // Mask passwords/tokens but show that a value exists
          if (input.type === 'password') {
            input.value = '********';
            input.placeholder = 'Value saved (enter new to replace)';
          } else {
            input.value = config[key];
          }
        }
      });
      updateCollectorStatuses();
    } catch (err) {
      // Settings may not be available yet
    }
  }

  function populateSettings(config) {
    // Credentials
    const credsEl = document.getElementById('settings-credentials');
    if (credsEl && config.credentials) {
      credsEl.innerHTML = Object.entries(config.credentials).map(([slug, creds]) => `
        <div class="credential-row">
          <span class="credential-name">${escapeHtml(slug)}</span>
          <span class="credential-value">${Object.keys(creds).map(k => `${k}: ********`).join(', ')}</span>
          <button class="btn btn-ghost btn-sm" onclick="CP.editCredentials('${slug}')">Edit</button>
        </div>
      `).join('');
    }

    // General settings
    const hostnameInput = document.getElementById('settings-hostname');
    if (hostnameInput && config.hostname_prefix) {
      hostnameInput.value = config.hostname_prefix;
    }

    const intervalInput = document.getElementById('settings-interval');
    if (intervalInput && config.collect_interval) {
      intervalInput.value = config.collect_interval;
    }

    const timezoneInput = document.getElementById('settings-timezone');
    if (timezoneInput && config.timezone) {
      timezoneInput.value = config.timezone;
    }
  }

  async function saveSettings() {
    const config = {};

    // General
    const hostnameInput = document.getElementById('settings-hostname');
    if (hostnameInput) config.hostname_prefix = hostnameInput.value;

    const intervalInput = document.getElementById('settings-interval');
    if (intervalInput) config.collect_interval = parseInt(intervalInput.value) || 60;

    const timezoneInput = document.getElementById('settings-timezone');
    if (timezoneInput) config.timezone = timezoneInput.value;

    try {
      await api('/api/config', { method: 'POST', body: config });
      toast('Settings saved', 'success');
    } catch (err) {
      toast(`Save failed: ${err.message}`, 'error');
    }
  }

  async function editCredentials(slug) {
    toast(`Edit credentials for ${slug} — coming soon`, 'info');
  }

  async function saveCollectorCredentials() {
    const inputs = document.querySelectorAll('.collector-input');
    const data = {};
    inputs.forEach(input => {
      const key = input.dataset.config;
      const val = input.value.trim();
      // Only save non-empty, non-masked values
      if (val && val !== '********') {
        data[key] = val;
      }
    });

    if (Object.keys(data).length === 0) {
      toast('No credentials to save', 'warning');
      return;
    }

    try {
      await api('/api/config', { method: 'POST', body: { data } });
      toast('Credentials saved', 'success');
      updateCollectorStatuses();
    } catch (err) {
      toast(`Save failed: ${err.message}`, 'error');
    }
  }

  async function testCollectors() {
    const statusEl = document.getElementById('collector-save-status');
    if (statusEl) statusEl.textContent = 'Running collection...';
    try {
      await api('/api/collect', { method: 'POST' });
      toast('Collection started. Check dashboard in a moment.', 'success');
      if (statusEl) statusEl.textContent = 'Collection triggered';
    } catch (err) {
      toast(`Collection failed: ${err.message}`, 'error');
      if (statusEl) statusEl.textContent = '';
    }
  }

  function updateCollectorStatuses() {
    const configuredServices = ['honeygain', 'earnapp', 'iproyal', 'traffmonetizer', 'mysterium', 'storj', 'grass', 'bytelixir'];
    configuredServices.forEach(slug => {
      const badge = document.getElementById(`status-${slug}`);
      if (!badge) return;
      const inputs = document.querySelectorAll(`.collector-input[data-config^="${slug}_"]`);
      let hasValue = false;
      inputs.forEach(input => {
        if (input.value.trim() && input.value !== '********') hasValue = true;
      });
      if (hasValue) {
        badge.textContent = 'Configured';
        badge.className = 'badge badge-deployed';
      }
    });
  }

  // -----------------------------------------------------------
  // Utility
  // -----------------------------------------------------------
  function formatCurrency(val, nativeCurrency) {
    nativeCurrency = nativeCurrency || 'USD';
    const amount = parseFloat(val || 0);

    // Convert to USD first
    let usdAmount;
    if (nativeCurrency === 'USD') {
      usdAmount = amount;
    } else if (_exchangeRates.crypto_usd && _exchangeRates.crypto_usd[nativeCurrency]) {
      usdAmount = amount * _exchangeRates.crypto_usd[nativeCurrency];
    } else {
      // Unknown token with no rate — show raw value
      return amount.toFixed(2) + ' ' + nativeCurrency;
    }

    // Convert USD to display currency
    let displayAmount = usdAmount;
    if (_displayCurrency !== 'USD' && _exchangeRates.fiat && _exchangeRates.fiat[_displayCurrency]) {
      displayAmount = usdAmount * _exchangeRates.fiat[_displayCurrency];
    }

    try {
      return new Intl.NumberFormat(undefined, {
        style: 'currency',
        currency: _displayCurrency,
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(displayAmount);
    } catch {
      return displayAmount.toFixed(2) + ' ' + _displayCurrency;
    }
  }

  function formatNative(val, currency) {
    if (!currency || currency === 'USD') return null;
    const amount = parseFloat(val || 0);
    return amount.toFixed(4) + ' ' + currency;
  }

  function setTextContent(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  function setChangeIndicator(id, pct) {
    const el = document.getElementById(id);
    if (!el) return;
    const sign = pct >= 0 ? '+' : '';
    el.textContent = `${sign}${pct.toFixed(1)}%`;
    el.className = `stat-change ${pct >= 0 ? 'positive' : 'negative'}`;
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
  }

  async function loadCollectorAlerts() {
    const container = document.getElementById('topbar-notifications');
    const badge = document.getElementById('notify-badge');
    const list = document.getElementById('notify-list');
    if (!container || !badge || !list) return;

    try {
      const alerts = await api('/api/collector-alerts');
      if (!alerts || alerts.length === 0) {
        badge.style.display = 'none';
        list.innerHTML = '<div class="notify-empty">All collectors healthy</div>';
        return;
      }

      badge.style.display = '';
      badge.textContent = alerts.length;
      list.innerHTML = alerts.map(a => `
        <div class="notify-item" data-platform="${escapeHtml(a.platform)}" onclick="CP.goToCollectorSettings('${escapeHtml(a.platform)}')">
          <div class="notify-item-icon">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
          </div>
          <div class="notify-item-body">
            <div class="notify-item-platform">${escapeHtml(a.platform)}</div>
            <div class="notify-item-msg" title="${escapeHtml(a.error)}">${escapeHtml(a.error)}</div>
          </div>
        </div>
      `).join('');
    } catch {
      badge.style.display = 'none';
    }
  }

  function goToCollectorSettings(platform) {
    // Navigate to settings and open the relevant collector section
    if (window.location.pathname === '/settings') {
      // Already on settings — just open the section
      openCollectorSection(platform);
    } else {
      window.location.href = '/settings?highlight=' + encodeURIComponent(platform);
    }
  }

  function openCollectorSection(platform) {
    const badge = document.getElementById('status-' + platform);
    if (!badge) return;
    const details = badge.closest('details.collector-section');
    if (details) {
      details.open = true;
      details.scrollIntoView({ behavior: 'smooth', block: 'center' });
      details.classList.add('highlight-flash');
      setTimeout(() => details.classList.remove('highlight-flash'), 2000);
    }
  }

  // -----------------------------------------------------------
  // Currency selector (settings page)
  // -----------------------------------------------------------
  async function populateCurrencyDropdown() {
    const select = document.getElementById('settings-currency');
    if (!select) return;

    await loadExchangeRates();
    const fiatCodes = Object.keys(_exchangeRates.fiat || {}).sort();

    const popular = ['USD', 'EUR', 'GBP', 'JPY', 'CAD', 'AUD', 'CHF', 'CNY', 'INR', 'BRL', 'MXN', 'PLN', 'SEK', 'NOK', 'DKK', 'CZK', 'HUF', 'RON'];
    const options = [];

    for (const code of popular) {
      if (fiatCodes.includes(code)) {
        options.push(`<option value="${code}"${code === _displayCurrency ? ' selected' : ''}>${code}</option>`);
      }
    }

    const remaining = fiatCodes.filter(c => !popular.includes(c));
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
      toast(`Display currency set to ${select.value}`, 'success');
      const topbarSelect = document.getElementById('topbar-currency');
      if (topbarSelect) topbarSelect.value = select.value;
    });
  }

  // -----------------------------------------------------------
  // Init on DOMContentLoaded
  // -----------------------------------------------------------
  // -----------------------------------------------------------
  // Theme toggle
  // -----------------------------------------------------------
  function initThemeToggle() {
    const btn = document.getElementById('theme-toggle');
    if (!btn) return;
    function updateLabel() {
      const label = btn.querySelector('.theme-label');
      if (label) {
        const current = document.documentElement.getAttribute('data-theme') || 'dark';
        label.textContent = current === 'dark' ? 'Light mode' : 'Dark mode';
      }
    }
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const current = document.documentElement.getAttribute('data-theme') || 'dark';
      const next = current === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('cp-theme', next);
      updateLabel();
    });
    updateLabel();
  }

  function initAvatarDropdown() {
    const toggle = document.getElementById('avatar-toggle');
    const dropdown = document.getElementById('avatar-dropdown');
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
      // Re-render dashboard if on that page
      if (document.body.dataset.page === 'dashboard') {
        loadDashboardStats();
        loadServicesTable();
      }
      // Also sync settings page dropdown if present
      const settingsSelect = document.getElementById('settings-currency');
      if (settingsSelect) settingsSelect.value = select.value;
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    initSidebar();
    initThemeToggle();
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
      case 'settings':
        loadSettings();
        // Auto-open collector section if ?highlight= param present
        const hl = new URLSearchParams(window.location.search).get('highlight');
        if (hl) setTimeout(() => openCollectorSection(hl), 300);
        break;
    }
  });

  // -----------------------------------------------------------
  // Public API
  // -----------------------------------------------------------
  return {
    api,
    toast,
    openModal,
    closeModal,
    closeAllModals,
    loadEarningsChart,
    restartService,
    stopService,
    startService,
    removeService,
    viewLogs,
    stopLogPolling,
    deployService,
    toggleWizardService,
    wizardNext,
    wizardPrev,
    openServiceDetail,
    loadDetailLogs,
    saveSettings,
    saveCollectorCredentials,
    testCollectors,
    editCredentials,
    filterCatalog,
    refreshServices,
    openClaimModal,
    goToCollectorSettings,
    toggleInstances,
    populateCurrencyDropdown,
    deployServiceToWorkers,
    workerAction,
    loadWorkerLogs,
  };
})();
