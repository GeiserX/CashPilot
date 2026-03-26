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

  async function loadDashboard() {
    await Promise.all([
      loadDashboardStats(),
      loadDashboardServices(),
      loadEarningsChart('7'),
    ]);

    // Auto-refresh every 60 seconds
    if (refreshTimer) clearInterval(refreshTimer);
    refreshTimer = setInterval(() => {
      loadDashboardStats();
      loadDashboardServices();
    }, 60000);
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
      setTextContent('total-earnings', '$0.00');
      setTextContent('today-earnings', '$0.00');
      setTextContent('month-earnings', '$0.00');
      setTextContent('active-services', '0');
      setTextContent('topbar-total', '$0.00');
    }
  }

  async function loadDashboardServices() {
    const container = document.getElementById('services-list');
    if (!container) return;

    try {
      const services = await api('/api/services/deployed');
      if (!services || services.length === 0) {
        container.innerHTML = `
          <div class="empty-state">
            <div class="empty-state-icon">&#x1f680;</div>
            <div class="empty-state-title">No services deployed yet</div>
            <div class="empty-state-text">Get started by deploying your first passive income service.</div>
            <a href="/setup" class="btn btn-primary btn-lg">Setup Wizard</a>
          </div>`;
        return;
      }
      container.innerHTML = services.map(renderServiceCard).join('');
    } catch (err) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">&#x1f680;</div>
          <div class="empty-state-title">No services deployed yet</div>
          <div class="empty-state-text">Get started by deploying your first passive income service.</div>
          <a href="/setup" class="btn btn-primary btn-lg">Setup Wizard</a>
        </div>`;
    }
  }

  function renderServiceCard(svc) {
    const statusClass = (svc.container_status || 'stopped').toLowerCase();
    const statusLabel = statusClass.charAt(0).toUpperCase() + statusClass.slice(1);
    const initial = (svc.name || svc.slug || '?')[0].toUpperCase();

    // Cashout button: show when balance >= min_amount and cashout is configured
    let cashoutBtn = '';
    if (svc.cashout && svc.cashout.dashboard_url) {
      const minAmount = parseFloat(svc.cashout.min_amount) || 0;
      const balance = parseFloat(svc.balance) || 0;
      const canCashout = balance >= minAmount && minAmount > 0;
      cashoutBtn = `
        <a href="${escapeHtml(svc.cashout.dashboard_url)}" target="_blank" rel="noopener"
           class="btn btn-sm ${canCashout ? 'btn-success' : 'btn-ghost'}" title="${canCashout ? 'Cash out now' : `Min $${minAmount}`}"
           style="font-size:0.75rem; padding:4px 8px;">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/></svg>
          Cash Out
        </a>`;
    }

    return `
    <div class="service-card" data-slug="${escapeHtml(svc.slug)}">
      <div class="service-card-header">
        <div class="service-icon">${initial}</div>
        <div>
          <div class="service-name">${escapeHtml(svc.name)}</div>
          <span class="badge badge-${statusClass}"><span class="status-dot ${statusClass}"></span> ${statusLabel}</span>
        </div>
      </div>
      <div class="service-stats">
        <div class="service-balance">${formatCurrency(svc.balance || 0)}</div>
        <div class="service-usage">
          <span>CPU ${svc.cpu || '0'}%</span>
          <span>MEM ${svc.memory || '0 MB'}</span>
        </div>
      </div>
      <div class="service-actions">
        ${cashoutBtn}
        <button class="btn btn-ghost btn-sm btn-icon" onclick="CP.restartService('${svc.slug}')" title="Restart">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/></svg>
        </button>
        <button class="btn btn-ghost btn-sm btn-icon" onclick="CP.stopService('${svc.slug}')" title="Stop">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>
        </button>
        <button class="btn btn-ghost btn-sm btn-icon" onclick="CP.viewLogs('${svc.slug}')" title="Logs">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
        </button>
      </div>
    </div>`;
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
          label: 'Earnings ($)',
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
              label: (ctx) => `$${ctx.parsed.y.toFixed(2)}`,
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
              callback: (v) => `$${v}`,
            },
          },
        },
      },
    });
  }

  // -----------------------------------------------------------
  // Service actions
  // -----------------------------------------------------------
  async function restartService(slug) {
    try {
      await api(`/api/services/${slug}/restart`, { method: 'POST' });
      toast(`${slug} restarting...`, 'success');
      loadDashboardServices();
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function stopService(slug) {
    try {
      await api(`/api/services/${slug}/stop`, { method: 'POST' });
      toast(`${slug} stopped`, 'success');
      loadDashboardServices();
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function startService(slug) {
    try {
      await api(`/api/services/${slug}/start`, { method: 'POST' });
      toast(`${slug} starting...`, 'success');
      loadDashboardServices();
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function removeService(slug) {
    if (!confirm(`Remove ${slug}? This will stop and delete the container.`)) return;
    try {
      await api(`/api/services/${slug}`, { method: 'DELETE' });
      toast(`${slug} removed`, 'success');
      loadDashboardServices();
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  // -----------------------------------------------------------
  // Log viewer
  // -----------------------------------------------------------
  let logPollTimer = null;

  async function viewLogs(slug) {
    openModal('logs-modal');
    const title = document.getElementById('logs-modal-title');
    const viewer = document.getElementById('log-content');
    if (title) title.textContent = `Logs: ${slug}`;
    if (viewer) viewer.textContent = 'Loading logs...';

    if (logPollTimer) clearInterval(logPollTimer);

    async function fetchLogs() {
      try {
        const data = await api(`/api/services/${slug}/logs?lines=200`);
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

  function initWizard() {
    wizardState = { step: 1, categories: [], selectedServices: [], deployed: [] };
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

  async function loadWizardServices() {
    const container = document.getElementById('wizard-services');
    if (!container) return;

    try {
      const services = await api('/api/services/available');
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
    const checked = wizardState.selectedServices.includes(svc.slug) ? 'selected' : '';
    const earning = svc.earnings
      ? `$${svc.earnings.monthly_low}-$${svc.earnings.monthly_high}/${svc.earnings.per || 'mo'}`
      : 'Varies';

    return `
    <div class="service-card ${checked}" data-slug="${svc.slug}" onclick="CP.toggleWizardService('${svc.slug}', this)">
      <div class="service-card-header">
        <div class="service-icon">${(svc.name || '?')[0]}</div>
        <div>
          <div class="service-name">${escapeHtml(svc.name)}</div>
          <span class="badge badge-category">${escapeHtml(svc.category)}</span>
        </div>
      </div>
      <div class="service-desc">${escapeHtml(svc.short_description || '')}</div>
      <div class="service-meta" style="margin-top: 8px;">
        <span class="badge badge-available">${earning}</span>
        ${svc.requirements && svc.requirements.residential_ip ? '<span class="badge badge-residential">Residential IP</span>' : ''}
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
      const services = await api('/api/services/available');
      const selected = services.filter(s => wizardState.selectedServices.includes(s.slug));
      container.innerHTML = selected.map(renderServiceSetupForm).join('');
    } catch (err) {
      container.innerHTML = '<p class="empty-state-text">Could not load service details.</p>';
    }
  }

  function renderServiceSetupForm(svc) {
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

    const signupUrl = svc.referral && svc.referral.signup_url
      ? svc.referral.signup_url.replace('{code}', svc.referral.code || '')
      : svc.website || '#';

    return `
    <div class="card" style="margin-bottom: 16px;" id="setup-${svc.slug}">
      <div class="card-header">
        <h3 class="section-title">${escapeHtml(svc.name)}</h3>
        <span class="badge badge-category">${escapeHtml(svc.category)}</span>
      </div>

      <div style="margin-bottom: 16px;">
        <p style="color: var(--text-secondary); margin-bottom: 12px;">
          New to ${escapeHtml(svc.name)}?
          <a href="${escapeHtml(signupUrl)}" target="_blank" rel="noopener" class="btn btn-secondary btn-sm" style="margin-left: 8px;">
            Sign Up
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
          </a>
        </p>
        <p style="color: var(--text-muted); font-size: 0.85rem;">Already have an account? Enter your credentials below.</p>
      </div>

      ${envFields}

      <button class="btn btn-success" onclick="CP.deployService('${svc.slug}')">
        Deploy ${escapeHtml(svc.name)}
      </button>
      <span class="deploy-status" id="deploy-status-${svc.slug}" style="margin-left: 12px; font-size: 0.85rem;"></span>
    </div>`;
  }

  async function deployService(slug) {
    const statusEl = document.getElementById(`deploy-status-${slug}`);
    if (statusEl) {
      statusEl.innerHTML = '<span class="spinner" style="display:inline-block;width:14px;height:14px;vertical-align:middle;"></span> Deploying...';
    }

    // Collect env vars
    const envInputs = document.querySelectorAll(`input[data-slug="${slug}"]`);
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

    try {
      await api(`/api/deploy/${slug}`, { method: 'POST', body: { env } });
      toast(`${slug} deployed successfully!`, 'success');
      if (statusEl) statusEl.innerHTML = '<span style="color:var(--success);">Deployed!</span>';
      if (!wizardState.deployed.includes(slug)) {
        wizardState.deployed.push(slug);
      }
    } catch (err) {
      toast(`Deploy failed: ${err.message}`, 'error');
      if (statusEl) statusEl.innerHTML = `<span style="color:var(--error);">${escapeHtml(err.message)}</span>`;
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

    const platforms = (svc.platforms || []).map(p =>
      `<span class="platform-badge">${escapeHtml(p)}</span>`
    ).join('');

    const actionBtn = isDeployed
      ? `<button class="btn btn-secondary btn-sm" onclick="CP.openServiceDetail('${svc.slug}')">Manage</button>`
      : `<button class="btn btn-primary btn-sm" onclick="CP.openServiceDetail('${svc.slug}')">Deploy</button>`;

    return `
    <div class="service-card" data-slug="${svc.slug}">
      <div class="service-card-header">
        <div class="service-icon">${initial}</div>
        <div style="flex:1;">
          <div class="service-name">${escapeHtml(svc.name)}</div>
          <div class="service-desc" style="margin-top:2px;">${escapeHtml(svc.short_description || '')}</div>
        </div>
      </div>
      <div class="service-meta">
        <span class="badge badge-category">${escapeHtml(svc.category)}</span>
        ${statusBadge}
        <span class="badge badge-available">${earning}</span>
        ${svc.requirements && svc.requirements.residential_ip ? '<span class="badge badge-residential">Residential IP</span>' : ''}
        ${svc.docker ? '<span class="badge badge-docker">Docker</span>' : ''}
      </div>
      ${platforms ? `<div class="platform-badges" style="margin-top:8px;">${platforms}</div>` : ''}
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
  async function openServiceDetail(slug) {
    openModal('service-detail-modal');
    const body = document.getElementById('service-detail-body');
    const title = document.getElementById('service-detail-title');
    if (body) body.innerHTML = '<div class="spinner" style="margin:24px auto;"></div>';
    if (title) title.textContent = 'Loading...';

    try {
      const svc = await api(`/api/services/${slug}`);
      if (title) title.textContent = svc.name;
      if (body) body.innerHTML = renderServiceDetail(svc);
    } catch (err) {
      if (body) body.innerHTML = `<p class="empty-state-text">Could not load service: ${escapeHtml(err.message)}</p>`;
    }
  }

  function renderServiceDetail(svc) {
    const earning = svc.earnings
      ? `$${svc.earnings.monthly_low}-$${svc.earnings.monthly_high} per ${svc.earnings.per || 'month'}`
      : 'Varies';

    const envFields = (svc.docker && svc.docker.env || []).map(env => {
      const inputType = env.secret ? 'password' : 'text';
      return `
      <div class="form-group">
        <label class="form-label">${escapeHtml(env.label)}</label>
        <input class="form-input" type="${inputType}" data-slug="${svc.slug}" data-key="${env.key}"
               placeholder="${escapeHtml(env.description || '')}" value="${escapeHtml(env.default || '')}"
               ${env.required ? 'required' : ''}>
      </div>`;
    }).join('');

    const referralHtml = svc.referral ? `
      <div class="detail-item">
        <div class="detail-label">Referral Bonus</div>
        <div class="detail-value">${escapeHtml(svc.referral.bonus?.referee || 'N/A')}</div>
      </div>` : '';

    const signupUrl = svc.referral && svc.referral.signup_url
      ? svc.referral.signup_url.replace('{code}', svc.referral.code || '')
      : svc.website || '#';

    return `
    <p style="color: var(--text-secondary); margin-bottom: 16px;">${escapeHtml(svc.description || svc.short_description || '')}</p>

    <div class="detail-grid" style="margin-bottom: 20px;">
      <div class="detail-item">
        <div class="detail-label">Category</div>
        <div class="detail-value">${escapeHtml(svc.category)}</div>
      </div>
      <div class="detail-item">
        <div class="detail-label">Estimated Earnings</div>
        <div class="detail-value" style="color: var(--success);">${earning}</div>
      </div>
      <div class="detail-item">
        <div class="detail-label">Payout</div>
        <div class="detail-value">${escapeHtml((svc.payment?.methods || []).join(', ') || 'N/A')} (min ${escapeHtml(svc.payment?.minimum_payout || 'N/A')})</div>
      </div>
      ${referralHtml}
    </div>

    <div style="margin-bottom: 20px;">
      <a href="${escapeHtml(signupUrl)}" target="_blank" rel="noopener" class="btn btn-secondary btn-sm">
        Sign Up for ${escapeHtml(svc.name)}
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
      </a>
    </div>

    <h4 style="margin-bottom: 12px; font-size: 0.95rem;">Deploy</h4>
    ${envFields}
    <div style="display:flex; gap:8px; align-items:center;">
      <button class="btn btn-success" onclick="CP.deployService('${svc.slug}')">Deploy</button>
      <span id="deploy-status-${svc.slug}" style="font-size:0.85rem;"></span>
    </div>

    ${svc.deployed ? `
    <div style="margin-top: 24px; padding-top: 16px; border-top: 1px solid var(--border-color);">
      <h4 style="margin-bottom: 12px; font-size: 0.95rem;">Container</h4>
      <div style="display: flex; gap: 8px; margin-bottom: 12px;">
        <button class="btn btn-secondary btn-sm" onclick="CP.startService('${svc.slug}')">Start</button>
        <button class="btn btn-secondary btn-sm" onclick="CP.restartService('${svc.slug}')">Restart</button>
        <button class="btn btn-secondary btn-sm" onclick="CP.stopService('${svc.slug}')">Stop</button>
        <button class="btn btn-danger btn-sm" onclick="CP.removeService('${svc.slug}')">Remove</button>
      </div>
      <h4 style="margin-bottom: 8px; font-size: 0.95rem;">Logs</h4>
      <div class="log-viewer" id="detail-logs-${svc.slug}">Click "Load Logs" to view.</div>
      <button class="btn btn-ghost btn-sm" style="margin-top:8px;" onclick="CP.loadDetailLogs('${svc.slug}')">Load Logs</button>
    </div>` : ''}`;
  }

  async function loadDetailLogs(slug) {
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
    try {
      const config = await api('/api/config');
      populateSettings(config);
    } catch (err) {
      // Settings may not be available yet
    }
  }

  function populateSettings(config) {
    // Referral codes
    const referralsEl = document.getElementById('settings-referrals');
    if (referralsEl && config.referral_codes) {
      referralsEl.innerHTML = Object.entries(config.referral_codes).map(([slug, code]) => `
        <div class="form-group">
          <label class="form-label">${escapeHtml(slug)}</label>
          <input class="form-input" data-referral="${slug}" value="${escapeHtml(code || '')}">
        </div>
      `).join('');
    }

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

    // Referral codes
    const referralInputs = document.querySelectorAll('[data-referral]');
    if (referralInputs.length > 0) {
      config.referral_codes = {};
      referralInputs.forEach(input => {
        config.referral_codes[input.dataset.referral] = input.value;
      });
    }

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
    // Open a prompt-style flow to edit credentials
    toast(`Edit credentials for ${slug} — coming soon`, 'info');
  }

  // -----------------------------------------------------------
  // Utility
  // -----------------------------------------------------------
  function formatCurrency(val) {
    return '$' + parseFloat(val || 0).toFixed(2);
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
  // Init on DOMContentLoaded
  // -----------------------------------------------------------
  // -----------------------------------------------------------
  // Theme toggle
  // -----------------------------------------------------------
  function initThemeToggle() {
    const btn = document.getElementById('theme-toggle');
    if (!btn) return;
    btn.addEventListener('click', () => {
      const current = document.documentElement.getAttribute('data-theme') || 'dark';
      const next = current === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('cp-theme', next);
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    initSidebar();
    initThemeToggle();

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
    editCredentials,
    filterCatalog,
  };
})();
