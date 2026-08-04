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
    } catch (err) {
      console.warn('Could not refresh exchange rates, keeping previous values:', err);
    }
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
    ]);

    // Auto-refresh every hour
    if (refreshTimer) clearInterval(refreshTimer);
    refreshTimer = setInterval(() => {
      loadDashboardStats();
      loadServicesTable();
      loadPayoutQueue();
    }, 3600000);
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
      return;
    }

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
      const native = `${Number(p.amount).toFixed(2)} ${nativeCurrency}`;
      // Compare CURRENCY CODES, not the formatted strings. formatCurrency
      // returns "$24.90" via Intl while `native` is "24.90 USD", so a string
      // comparison finds them different for a USD payout on a USD dashboard
      // and renders "24.90 USD (≈ $24.90)" — the duplication this is meant to
      // suppress. The codes are the thing that actually decides whether a
      // conversion happened.
      const approx = effectiveDisplayCurrency(nativeCurrency) !== nativeCurrency
        ? ` <span style="color:var(--text-muted);">(≈ ${escapeHtml(formatCurrency(p.amount, nativeCurrency))})</span>`
        : '';
      return `
        <div class="payout-queue-item" data-payout-id="${escapeHtml(String(p.id))}">
          <div class="payout-queue-body">
            <div class="payout-queue-platform">${escapeHtml(p.platform || '')}</div>
            <div class="payout-queue-detail">Balance dropped by ${escapeHtml(native)}${approx}${p.detected_at ? ` on ${escapeHtml(String(p.detected_at).slice(0, 10))}` : ''}</div>
          </div>
          <div class="payout-queue-actions">
            ${_canWrite ? `
            <button class="btn btn-primary btn-sm" data-action="confirmPayout" data-a1="${escapeHtml(String(p.id))}" data-a2="${escapeHtml(p.platform || '')}">Yes, I was paid</button>
            <button class="btn btn-ghost btn-sm" data-action="rejectPayout" data-a1="${escapeHtml(String(p.id))}" data-a2="${escapeHtml(p.platform || '')}">No, not a payout</button>
            ` : `<span style="font-size:0.72rem; color:var(--text-muted);">Writer access required to answer this.</span>`}
          </div>
        </div>
      `;
    }).join('');
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
             aria-label="${escapeHtml(pct.toFixed(0))}% of the ${escapeHtml(threshold.toFixed(2))} minimum">
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
    const money = value => (unit ? `${Number(value).toFixed(2)} ${unit}` : formatCurrency(value));

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
    if (!data.balance_known && !paid) {
      card.style.display = 'none';
      return;
    }
    card.style.display = '';
    body.innerHTML = `
      <div class="detail-grid">
        <div class="detail-item">
          <div class="detail-label">Balance now</div>
          <div class="detail-value">${data.balance_known ? escapeHtml(money(balance)) : '<span style="color:var(--text-muted);">not collected yet</span>'}</div>
        </div>
        <div class="detail-item">
          <div class="detail-label">Earned in total</div>
          <div class="detail-value">${data.balance_known || paid ? escapeHtml(money(data.lifetime_earned || 0)) : '<span style="color:var(--text-muted);">not collected yet</span>'}</div>
          ${paid ? `<div style="font-size:0.7rem; color:var(--text-muted);">includes ${escapeHtml(String(paid))} confirmed payout${paid === 1 ? '' : 's'}</div>` : ''}
        </div>
      </div>
      ${bar}
      <p style="margin-top:12px; color:var(--text-secondary); font-size:0.85rem;">${escapeHtml(projection.summary || '')}</p>
    `;
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
  async function loadDeployRisk() {
    const card = document.getElementById('deploy-risk-card');
    const body = document.getElementById('deploy-risk-body');
    if (!card || !body) return;
    const slug = card.dataset.slug;
    if (!slug) return;

    let risk;
    try {
      risk = await api(`/api/services/${encodeURIComponent(slug)}/deploy-risk`);
    } catch (err) {
      console.warn('Could not load deploy risk:', err);
      return;
    }

    const attribution = risk.attribution;
    const isolation = risk.isolation || {};
    if (!attribution && !isolation.summary) { card.style.display = 'none'; return; }

    let html = '';
    if (attribution) {
      // documented === false means nobody checked, which is a different claim
      // from "no risk" and is styled to say so rather than to reassure.
      const tone = attribution.documented ? 'var(--warning)' : 'var(--text-muted)';
      html += `
        <div class="deploy-risk-block" style="border-left-color:${tone};">
          <div class="deploy-risk-headline">${escapeHtml(attribution.headline || '')}</div>
          <div class="deploy-risk-body-text">${escapeHtml(attribution.body || '')}</div>
          ${attribution.lateral_note ? `<div class="deploy-risk-body-text">${escapeHtml(attribution.lateral_note)}</div>` : ''}
          ${attribution.source ? `<div class="deploy-risk-source">Source: ${escapeHtml(attribution.source)}</div>` : ''}
        </div>`;
    }
    if (isolation.summary) {
      html += `
        <div class="deploy-risk-block" style="border-left-color:var(--border-color);">
          <div class="deploy-risk-headline">Keeping it off your LAN</div>
          <div class="deploy-risk-body-text">${escapeHtml(isolation.summary)}</div>
        </div>`;
    }
    card.style.display = '';
    body.innerHTML = html;
  }

  async function confirmPayout(payoutId, platform) {
    try {
      await api(`/api/earnings/payouts/${encodeURIComponent(payoutId)}/confirm`, { method: 'POST' });
      toast(`Recorded the ${platform || 'payout'} as paid.`, 'success');
      // The totals move as a direct result, so refresh them alongside the queue
      // rather than leaving the user to wonder whether it took effect.
      await Promise.all([loadPayoutQueue(), loadDashboardStats(), loadCollectorAlerts()]);
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function rejectPayout(payoutId, platform) {
    // Rejection DELETES the row, and there is no undo, so it asks first.
    if (!window.confirm(`Discard the detected ${platform || ''} payout? This cannot be undone.`)) return;
    try {
      await api(`/api/earnings/payouts/${encodeURIComponent(payoutId)}/reject`, { method: 'POST' });
      toast('Discarded — it will not count as earnings.', 'success');
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
      setTextContent('active-services', data.active_services || 0);

      const nothingYet = document.getElementById('no-readings-note');
      if (nothingYet) nothingYet.style.display = data.has_readings === false ? '' : 'none';

      // Show promo offset footnote under total
      const bonusNote = document.getElementById('total-bonus-note');
      if (bonusNote) {
        if (totalBonus > 0) {
          bonusNote.textContent = `\u2212${formatCurrency(totalBonus)} promo`;
          bonusNote.style.display = '';
        } else {
          bonusNote.style.display = 'none';
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
      toast(err.message || 'Could not refresh dashboard', 'error');
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
        case 'payout': {
          const coA = a.cashout || {};
          const coB = b.cashout || {};
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
          <div class="empty-state" style="padding:32px 0; text-align:center;">
            <div class="empty-state-title">No services deployed yet</div>
            <div class="empty-state-text">Get started by deploying your first passive income service.</div>
            <a href="/setup" class="btn btn-primary" style="margin-top:12px;">Setup Wizard</a>
          </div>`
          : `
          <div class="empty-state" style="padding:32px 0; text-align:center;">
            <div class="empty-state-title">Can't reach ${unreachable > 0 ? escapeHtml(String(unreachable)) + ' worker' + (unreachable === 1 ? '' : 's') : 'the workers'}</div>
            <div class="empty-state-text">Services running on ${unreachable === 1 ? 'it' : 'them'} are not shown here — this does not mean they stopped. Containers keep running and earning while a worker is offline.</div>
            <a href="/fleet" class="btn btn-ghost" style="margin-top:12px;">Check the fleet</a>
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
      // Keep the existing table on a refresh failure. Only replace the
      // perpetual "Loading..." spinner with a clear error + retry affordance
      // when there was nothing on screen yet.
      if (!container.querySelector('.breakdown-table')) {
        container.innerHTML = `
          <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; gap:8px; padding:24px 0; color:var(--text-muted); text-align:center;">
            <span>Couldn't load services${err && err.message ? `: ${escapeHtml(err.message)}` : ''}.</span>
            <button class="btn btn-ghost btn-sm" data-action="loadServicesTable">Retry</button>
          </div>`;
      }
    }
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
      return `
      <div class="form-group">
        ${label}
        <input class="form-input" type="${inputType}"${withId ? ` id="${id}"` : ''}
               data-slug="${svc.slug}" data-key="${env.key}"
               placeholder="${escapeHtml(defaultIsTemplate ? String(env.default) : (env.description || ''))}"
               value="${escapeHtml(defaultIsTemplate ? '' : (env.default || ''))}"
               ${env.required ? 'required' : ''}>
        ${hint}
      </div>`;
    }).join('');
  }

  // The class is a parameter rather than unified, deliberately: the setup wizard
  // and the detail view can both be in the DOM at once, and their deploy
  // handlers select by class. One shared class would make each pick up the
  // other's checkboxes.
  function workerCheckboxList(svc, onlineWorkers, checkboxClass) {
    let rows = '';
    let allDeployed = true;
    for (const w of onlineWorkers) {
      const deployed = (w.containers || []).map((c) => c.slug).includes(svc.slug);
      if (!deployed) allDeployed = false;
      rows += `
      <label style="display:flex; align-items:center; gap:8px; padding:6px 0; ${deployed ? 'opacity:0.5;' : ''}">
        <input type="checkbox" class="${checkboxClass}" data-slug="${svc.slug}" data-wid="${w.id}" ${deployed ? 'disabled checked' : ''}>
        <span>${escapeHtml(w.name)}</span>
        ${deployed
          ? '<span class="badge badge-deployed" style="font-size:0.75rem;">Deployed</span>'
          : '<span class="badge badge-available" style="font-size:0.75rem;">Available</span>'}
      </label>`;
    }
    return { rows, allDeployed };
  }

  function renderServiceRow(svc, bk) {
    const isExternal = svc.container_status === 'external';
    const statusClass = isExternal ? 'external' : (svc.container_status || 'stopped').toLowerCase();
    const statusLabel = isExternal ? 'External' : statusClass.charAt(0).toUpperCase() + statusClass.slice(1);
    const instances = svc.instances || 0;
    const details = svc.instance_details || [];
    const isMulti = details.length > 1;

    // Service name — linked to dashboard for deployed services, referral URL otherwise
    const name = escapeHtml(svc.name);
    const dashUrl = (svc.cashout && svc.cashout.dashboard_url) || svc.website || '';
    const nameLink = dashUrl || svc.referral_url;
    const nameTitle = dashUrl ? 'Open dashboard' : 'Referral link';
    const nameHtml = nameLink
      ? `<a href="${escapeHtml(nameLink)}" target="_blank" rel="noopener" title="${nameTitle}" style="color:var(--accent); text-decoration:none; font-weight:600;">${name}</a>`
      : `<span style="font-weight:600;">${name}</span>`;

    // Subtitle: image for Docker, empty for external
    const subtitle = svc.image
      ? escapeHtml(svc.image)
      : (isExternal ? 'App / Browser' : '');

    // Health badge — external services always show --
    let healthBadge = '<span style="color:var(--text-muted);">--</span>';
    if (!isExternal && svc.health_score !== null && svc.health_score !== undefined) {
      const score = svc.health_score;
      const crashes = svc.crashes_7d || 0;
      const restarts = svc.restarts_7d || 0;
      const unstable = svc.unstable === true;
      // Unstable (repeated crashes in the 7-day window) takes the worst tone + an explicit
      // label so a crash-looping service is legible at a glance, not just via a low number.
      const hClass = (unstable || score < 50) ? 'badge-stopped' : score >= 80 ? 'badge-running' : 'badge-error';
      const uptime = (svc.uptime_pct !== null && svc.uptime_pct !== undefined) ? `${svc.uptime_pct}% uptime · ` : '';
      const title = `Health ${score}/100 · ${uptime}${restarts} restarts · ${crashes} crashes (7d)`;
      const label = unstable ? `unstable · ${crashes} crashes` : String(score);
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
    const deltaClass = delta > 0 ? 'positive' : delta < 0 ? 'negative' : '';
    const deltaStr = delta !== 0 ? `${deltaSign}${formatCurrency(delta, currency)}` : '--';
    const displayBalance = signupBonus > 0 ? balanceAdj : balance;
    const nativeLabel = formatNative(displayBalance, currency);
    const bonusLabel = signupBonus > 0
      ? `<div style="font-size:0.6rem; color:var(--text-muted);">\u2212${formatCurrency(signupBonus, currency)} promo</div>`
      : '';
    // Image drift: the running container no longer matches the catalog image
    // (provider migrated or re-pinned). Prompt a re-deploy — otherwise a retired
    // image keeps looking healthy while it silently stops earning.
    const outdatedBadge = svc.image_outdated === true
      ? ` <span class="badge badge-stopped" title="This service is running an image that no longer matches the catalog (the provider changed or re-pinned it). Re-deploy it from the catalog to update.">update available</span>`
      : '';

    // Earnings-collector state. "disconnected" = collector ran and failed
    // (e.g. wrong credentials). "needs setup" = the service is deployed and
    // earning, but its (separate) earnings-tracking credentials aren't set yet.
    let disconnectedLabel = '';
    if (svc.collector_disconnected) {
      disconnectedLabel = `<div title="CashPilot couldn't read this balance — check the earnings-tracking credentials" style="font-size:0.6rem; color:var(--error); font-weight:500; display:flex; align-items:center; justify-content:flex-end; gap:4px;">can't read balance${_isOwner ? ` <button class="btn btn-ghost" data-action="openCredentialModal" data-stop="1" data-a1="${escapeHtml(svc.slug)}" style="font-size:0.6rem; padding:1px 5px; line-height:1.2; color:var(--error); border:1px solid #ef4444; border-radius:3px; cursor:pointer;">fix</button>` : ''}</div>`;
    } else if (svc.collector_needs_setup) {
      disconnectedLabel = `<div title="This service is running and earning. To show its balance here, add its earnings-tracking credentials." style="font-size:0.6rem; color:var(--text-muted); font-weight:500; display:flex; align-items:center; justify-content:flex-end; gap:4px;">tracking not set up${_isOwner ? ` <button class="btn btn-ghost" data-action="openCredentialModal" data-stop="1" data-a1="${escapeHtml(svc.slug)}" style="font-size:0.6rem; padding:1px 5px; line-height:1.2; color:var(--text-muted); border:1px solid var(--border); border-radius:3px; cursor:pointer;">set up</button>` : ''}</div>`;
    }
    let balanceHtml;
    if (!balanceKnown) {
      // Never read. An em dash, not a number — the user must be able to tell
      // "nothing has looked at this" from "this earned nothing".
      balanceHtml = `<span style="color:var(--text-muted);" title="CashPilot has not read a balance for this service yet">&mdash;</span>${disconnectedLabel}`;
    } else if (nativeLabel) {
      balanceHtml = `${formatCurrency(displayBalance, currency)}<div style="font-size:0.65rem;color:var(--text-muted);">${nativeLabel}</div>${bonusLabel}${disconnectedLabel}`;
    } else {
      balanceHtml = `${formatCurrency(displayBalance, currency)}${bonusLabel}${disconnectedLabel}`;
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
    const claimBtn = `<button class="btn btn-icon ${eligible ? 'btn-success' : ''}" data-action="openClaimModal" data-a1="${escapeHtml(svc.slug)}" title="${claimTitle}"${claimDisabled ? ' disabled' : ''}>
           <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/></svg>
         </button>`;

    // Instance badge (shown next to status)
    const instanceLabel = !isExternal && instances > 0
      ? ` <span class="badge badge-instances" title="${instances} instance${instances > 1 ? 's' : ''}">${instances}x</span>`
      : '';

    // Settings gear (owner-only) — opens credential + bonus modal
    const settingsBtn = _isOwner
      ? `<button class="btn btn-icon" data-action="openCredentialModal" data-stop="1" data-a1="${escapeHtml(svc.slug)}" title="Credentials &amp; settings">
           <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg>
         </button>` : '';

    // For multi-instance: expand chevron, no container action buttons in main row
    // For single instance: show action buttons directly
    let actionBtns;
    if (isMulti) {
      const chevron = `<button class="btn btn-icon expand-toggle" data-action="toggleInstances" data-stop="1" data-a1="${escapeHtml(svc.slug)}" title="Expand instances">
        <svg class="expand-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
      </button>`;
      actionBtns = `<div class="action-btns">${claimBtn}${settingsBtn}${chevron}</div>`;
    } else if (isExternal) {
      actionBtns = `<div class="action-btns">${claimBtn}${settingsBtn}</div>`;
    } else {
      // Single instance — build container buttons targeting the right node
      const inst = details[0] || {};
      const wParam = inst.worker_id != null ? `', ${inst.worker_id}` : `'`;
      const noDocker = !inst.has_docker || inst.is_android;
      const disabledAttr = noDocker ? ' disabled title="No Docker access"' : '';
      actionBtns = `<div class="action-btns">
          ${claimBtn}
          ${settingsBtn}
          ${_canWrite ? `
          <button class="btn btn-icon" data-action="restartService" data-a1="'${escapeHtml(svc.slug)}${wParam}" title="Restart"${disabledAttr}>
            ${ICON_RESTART}
          </button>
          <button class="btn btn-icon" data-action="stopService" data-a1="'${escapeHtml(svc.slug)}${wParam}" title="Stop"${disabledAttr}>
            ${ICON_STOP}
          </button>
          <button class="btn btn-icon" data-action="viewLogs" data-a1="'${escapeHtml(svc.slug)}${wParam}" title="Logs"${disabledAttr}>
            ${ICON_LOGS}
          </button>` : ''}
        </div>`;
    }

    // Main row
    let html = `
    <tr class="breakdown-row${isMulti ? ' expandable' : ''}" data-slug="${escapeHtml(svc.slug)}"${isMulti ? ` data-action="toggleInstances" data-a1="${escapeHtml(svc.slug)}" data-a2="event" style="cursor:pointer;"` : ''}>
      <td>${nameHtml}<div style="font-size:0.7rem; color:var(--text-muted);">${subtitle}</div></td>
      <td style="text-align:center;"><span class="badge badge-${statusClass}"><span class="status-dot ${statusClass}"></span> ${statusLabel}</span>${instanceLabel}${outdatedBadge}</td>
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
        const iNoDocker = !inst.has_docker || inst.is_android;
        const disabledAttr = iNoDocker ? ' disabled title="No Docker access"' : '';
        const subLabel = inst.is_android ? '' : escapeHtml(inst.container_name);
        const cpuCell = inst.is_android ? `↑ ${fmtNetBytes(inst.net_tx_24h)}` : `${inst.cpu || '0'}%`;
        const memCell = inst.is_android ? `↓ ${fmtNetBytes(inst.net_rx_24h)}` : (inst.memory || '0 MB');
        html += `
        <tr class="instance-row" data-parent="${escapeHtml(svc.slug)}" style="display:none;">
          <td style="padding-left:28px;">
            <span class="instance-node-label">${nodeLabel}</span>
            ${subLabel ? `<span style="font-size:0.7rem; color:var(--text-muted); margin-left:4px;">${subLabel}</span>` : ''}
          </td>
          <td style="text-align:center;"><span class="badge badge-${iStatus}"><span class="status-dot ${iStatus}"></span> ${iStatusLabel}</span></td>
          <td></td>
          <td></td>
          <td></td>
          <td style="text-align:right;">${cpuCell}</td>
          <td style="text-align:right;">${memCell}</td>
          <td></td>
          <td style="text-align:center; white-space:nowrap;">
            <div class="action-btns">
              ${_canWrite ? `
              <button class="btn btn-icon" data-action="restartService" data-a1="'${escapeHtml(svc.slug)}${wParam}" title="Restart on ${nodeLabel}"${disabledAttr}>
                ${ICON_RESTART}
              </button>
              <button class="btn btn-icon" data-action="stopService" data-a1="'${escapeHtml(svc.slug)}${wParam}" title="Stop on ${nodeLabel}"${disabledAttr}>
                ${ICON_STOP}
              </button>
              <button class="btn btn-icon" data-action="viewLogs" data-a1="'${escapeHtml(svc.slug)}${wParam}" title="Logs on ${nodeLabel}"${disabledAttr}>
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
    toast('Services refreshed', 'info');
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
            '<div class="empty-state" style="padding:32px 0;">'
            + '<div class="empty-state-text">Could not load earnings. This is not a reading of zero — '
            + 'the figures could not be fetched.</div>'
            + '<button class="btn btn-ghost btn-sm" data-action="loadEarningsChart" data-a1="'
            + escapeHtml(String(days)) + '" style="margin-top:10px;">Retry</button>'
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
    const textPrimary = cs.getPropertyValue('--text-primary').trim();
    const textSecondary = cs.getPropertyValue('--text-secondary').trim();
    const bgSecondary = cs.getPropertyValue('--bg-secondary').trim();
    const borderColor = cs.getPropertyValue('--border-color').trim();
    const accent = cs.getPropertyValue('--accent').trim();

    earningsChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          label: 'Daily Earnings',
          data: values,
          backgroundColor: accent + '66',
          borderColor: accent,
          borderWidth: 1,
          borderRadius: 4,
          hoverBackgroundColor: accent + '99',
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
            grid: { color: borderColor },
            ticks: { color: textMuted, font: { size: 11 } },
          },
          y: {
            beginAtZero: true,
            grid: { color: borderColor },
            ticks: {
              color: textMuted,
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
  // Credential Update Modal (inline from dashboard / notifications)
  // -----------------------------------------------------------
  let _collectorMetaCache = null;

  async function openCredentialModal(slug) {
    openModal('cred-modal');
    const title = document.getElementById('cred-modal-title');
    const body = document.getElementById('cred-modal-body');
    if (title) title.textContent = 'Update Credentials';
    if (body) body.innerHTML = '<div class="spinner" style="margin:24px auto;"></div>';

    try {
      if (!_collectorMetaCache) {
        _collectorMetaCache = await api('/api/collectors/meta');
      }
      const config = await api('/api/config');
      const col = _collectorMetaCache.find(c => c.slug === slug);
      if (!col || !col.fields.length) {
        if (body) body.innerHTML = '<p style="color:var(--text-muted);">No credentials needed for this service.</p>';
        return;
      }
      if (title) title.textContent = `${col.name} — Credentials`;

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
        const optionalSuffix = f.required ? '' : ' <span style="color:var(--text-muted); font-weight:400;">(optional)</span>';
        // Secret inputs are write-only: empty, with a placeholder that reflects
        // whether a value is already stored (per _secrets). Non-secret fields keep
        // their plain placeholder.
        const placeholder = f.secret
          ? (secrets[f.key] ? '•••••••• (set — leave blank to keep)' : escapeHtml(f.label))
          : escapeHtml(f.label);
        return `
        <div style="margin-bottom:10px;">
          <label style="display:block; font-size:0.8rem; color:var(--text-secondary); margin-bottom:4px;">${escapeHtml(f.label)}${optionalSuffix}</label>
          <input class="form-input cred-modal-input" type="${inputType}"
                 data-config="${escapeHtml(f.key)}"
                 value=""
                 placeholder="${placeholder}"
                 ${f.secret ? 'autocomplete="new-password"' : ''}
                 style="width:100%;">
        </div>`;
      }).join('');
      const hint = col.hint || '';

      // Signup bonus offset field — show current value from config
      const bonusKey = `${slug}_signup_bonus`;
      const currentBonus = config[bonusKey] || '';
      const payCurrency = col.currency || 'USD';
      const currencyLabel = payCurrency === 'USD' ? '$' : payCurrency;
      const bonusHtml = `
        <div style="margin-top:14px; padding-top:12px; border-top:1px solid var(--border);">
          <label style="display:block; font-size:0.8rem; color:var(--text-secondary); margin-bottom:4px;">Signup Bonus Offset (${escapeHtml(currencyLabel)})</label>
          <div style="display:flex; align-items:center; gap:6px;">
            <input class="form-input cred-modal-input" type="number" step="0.01" min="0"
                   data-config="${escapeHtml(bonusKey)}"
                   value="${escapeHtml(currentBonus)}"
                   placeholder="0.00"
                   style="width:100px;">
            <span style="font-size:0.75rem; color:var(--text-muted);">Subtract promotional credits from displayed balance</span>
          </div>
        </div>`;

      body.innerHTML = `
        ${hint ? `<p style="font-size:0.875rem; color:var(--text-secondary); margin:0 0 14px; line-height:1.5;">${sanitizeHint(hint)}</p>` : ''}
        ${fieldsHtml}
        ${bonusHtml}
        <div style="display:flex; gap:8px; margin-top:14px;">
          <button class="btn btn-primary btn-sm" data-action="saveCredentialModal" data-a1="${escapeHtml(slug)}">Save</button>
          <button class="btn btn-ghost btn-sm" data-action="closeModal" data-a1="cred-modal">Cancel</button>
          <button class="btn btn-ghost btn-sm" style="color:var(--error); margin-left:auto;" data-action="clearServiceCredentials" data-a1="${escapeHtml(slug)}" data-a2="${escapeHtml(col.name)}">Clear</button>
        </div>`;
    } catch (err) {
      if (body) body.innerHTML = `<p style="color:var(--error);">Failed to load: ${escapeHtml(err.message)}</p>`;
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
      toast('Enter at least one credential', 'warning');
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
        toast('Credentials saved — checking them\u2026', 'success');
        try {
          const verdict = await api(`/api/services/${encodeURIComponent(slug)}/test-credentials`, { method: 'POST' });
          toast(verdict.message || (verdict.ok ? 'Credentials work.' : 'Could not verify these credentials.'),
                verdict.ok ? 'success' : 'error');
        } catch (err) {
          // The CHECK failed, which is not the same as the credentials failing.
          // Saying "rejected" here would send someone to re-copy a token that
          // was fine.
          toast(`Saved, but could not check them right now: ${err.message}`, 'warning');
        }
      } else {
        toast('Credentials saved — collecting now\u2026', 'success');
      }

      // Trigger a collection so it picks up new creds immediately
      api('/api/collect', { method: 'POST' }).catch(() => {});
      // Silently refresh the dashboard after collection has time to finish
      setTimeout(() => loadServicesTable(), 8000);
    } catch (err) {
      toast(`Save failed: ${err.message}`, 'error');
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
      _setPwdError('Enter your current password.');
      currentEl.focus();
      return;
    }
    if (new_password.length < 10) {
      _setPwdError('New password must be at least 10 characters.');
      newEl.focus();
      return;
    }
    if (new_password !== confirm) {
      _setPwdError('New password and confirmation do not match.');
      confirmEl.focus();
      return;
    }
    if (new_password === current_password) {
      _setPwdError('New password must be different from the current one.');
      newEl.focus();
      return;
    }

    _setPwdError('');
    const btn = document.getElementById('pwd-submit');
    if (btn) { btn.disabled = true; btn.dataset.label = btn.textContent; btn.textContent = 'Saving…'; }

    try {
      await api('/api/users/me/password', {
        method: 'POST',
        body: { current_password, new_password },
      });
      // Cookie is re-minted server-side, so the session stays valid.
      toast('Password changed', 'success');
      closeModal('password-modal');
    } catch (err) {
      _setPwdError(err.message);
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = btn.dataset.label || 'Change Password'; }
    }
  }

  // -----------------------------------------------------------
  // Claim Modal
  // -----------------------------------------------------------
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

      if (title) title.textContent = `Claim — ${svc.name}`;

      const unknownIcon = '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="8" y1="12" x2="16" y2="12"/></svg>';
      const statusIcon = eligibilityUnknown
        ? unknownIcon
        : eligible
        ? '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--success)" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="16 8 10 16 7 13"/></svg>'
        : '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--warning)" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>';

      const statusText = eligibilityUnknown
        ? `<span style="color:var(--text-muted); font-weight:600; font-size:1.1rem;">Cannot tell yet</span>
           <div style="color:var(--text-muted); font-size:0.85rem; margin-top:6px;">
             This provider's minimum is set in ${escapeHtml(String(co.min_amount_currency || 'another currency'))} and the balance is
             recorded in ${escapeHtml(String(currency))}. Without an exchange rate the two cannot be compared, so
             CashPilot will not guess. Check the provider's own dashboard.
           </div>`
        : eligible
        ? `<span style="color:var(--success); font-weight:600; font-size:1.1rem;">Eligible for payout!</span>`
        : `<span style="color:var(--warning); font-weight:600; font-size:1.1rem;">Below minimum payout</span>`;

      const pctToMin = comparable && minAmount > 0 ? Math.min(100, (svc.balance / minAmount) * 100) : 0;
      const remaining = comparable ? Math.max(0, minAmount - svc.balance) : 0;

      const progressSection = comparable && minAmount > 0 ? `
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
        auto: 'Payouts happen automatically when the minimum threshold is reached.',
      };

      let actionSection = '';
      if (co.method === 'auto') {
        // Auto-settle services — always show the dashboard link (e.g. rewards page)
        actionSection = `<div style="margin-top:20px; text-align:center;">
             <p style="font-size:0.85rem; color:var(--text-secondary); margin-bottom:12px;">${methodLabel.auto}</p>
             ${co.dashboard_url ? `<a href="${escapeHtml(co.dashboard_url)}" target="_blank" rel="noopener" class="btn btn-primary btn-lg" style="min-width:200px;">
               <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
               Claim Rewards
             </a>` : ''}
           </div>`;
      } else if (eligible && co.dashboard_url) {
        actionSection = `<div style="margin-top:20px; text-align:center;">
             <p style="font-size:0.85rem; color:var(--text-secondary); margin-bottom:12px;">${methodLabel[co.method] || methodLabel.redirect}</p>
             <a href="${escapeHtml(co.dashboard_url)}" target="_blank" rel="noopener" class="btn btn-success btn-lg" style="min-width:200px;">
               <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
               Go to Dashboard
             </a>
           </div>`;
      } else if (!eligible) {
        actionSection = `<div style="margin-top:16px; text-align:center;">
               <p style="font-size:0.85rem; color:var(--text-muted);">Keep your service running to accumulate more earnings.</p>
             </div>`;
      }

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
    deployAttempted: false,
  };

  async function initWizard() {
    wizardState = { step: 1, categories: [], selectedServices: [], deployed: [], deployAttempted: false };

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
      if (wizardState.step === 4) {
        renderWizardOutcome();
        // Persist category/service selections
        api('/api/preferences', {
          method: 'POST',
          body: {
            selected_categories: JSON.stringify(wizardState.categories),
            timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
            setup_completed: 1,
          },
        }).catch(() => {});
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
        title.textContent = 'Setup saved';
        text.textContent = wanted.length
          ? 'Your choices are saved. Nothing was deployed yet — deploy them from the catalog whenever you are ready.'
          : 'Your preferences are saved. Nothing was deployed, because no services were selected.';
        return;
      }
      title.textContent = 'Nothing was deployed';
      text.textContent =
        'None of the selected services could be deployed. Your choices are saved — check the Fleet page for a worker that is online, then deploy from the catalog.';
      return;
    }
    const missed = wanted.filter(s => !done.includes(s));
    title.textContent = missed.length ? 'Partly deployed' : "You're all set!";
    const names = done.map(escapeHtml).join(', ');
    text.textContent = missed.length
      ? `Deployed: ${names}. ${missed.length} service${missed.length === 1 ? '' : 's'} could not be deployed — check the Fleet page.`
      : `Deployed: ${names}. Head to the dashboard to monitor status and earnings.`;
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
    <div class="${classes.join(' ')}" data-slug="${svc.slug}" data-action="toggleWizardService" data-a1="${svc.slug}">
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
    const isDeployed = svc.deployed || false;
    const dashboardUrl = (svc.cashout && svc.cashout.dashboard_url) || svc.website || '';
    const signupUrl = svc.referral && svc.referral.signup_url
      ? svc.referral.signup_url
      : svc.website || '#';
    const linkUrl = isDeployed && dashboardUrl ? dashboardUrl : signupUrl;
    const linkLabel = isDeployed && dashboardUrl ? 'Dashboard' : 'Sign Up';

    // Manual-only services: show signup link + earnings tracking notice + any env fields
    if (svc.manual_only) {
      const platforms = (svc.platforms || []).map(p => p.charAt(0).toUpperCase() + p.slice(1)).join(', ');
      const manualEnvFields = envInputFields(svc, svc.docker && svc.docker.env);
      const manualBtnLabel = isDeployed && dashboardUrl
        ? `Dashboard for ${escapeHtml(svc.name)}`
        : `Sign Up for ${escapeHtml(svc.name)}`;
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
          <a href="${escapeHtml(linkUrl)}" target="_blank" rel="noopener" class="btn btn-primary btn-sm">
            ${manualBtnLabel}
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
          </a>
          <a href="https://geiserx.github.io/CashPilot/guides/${svc.slug}/" target="_blank" rel="noopener" class="btn btn-ghost btn-sm" style="margin-left: 8px;">
            Setup Guide
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 3h6a4 4 0 014 4v14a3 3 0 00-3-3H2z"/><path d="M22 3h-6a4 4 0 00-4 4v14a3 3 0 013-3h7z"/></svg>
          </a>
          ${manualEnvFields ? `<div style="margin-top: 16px;">${manualEnvFields}</div>` : ''}
        </div>
      </div>`;
    }

    const envFields = envInputFields(svc, svc.docker && svc.docker.env);

    return `
    <div class="card" style="margin-bottom: 16px;" id="setup-${svc.slug}">
      <div class="card-header">
        <h3 class="section-title">${escapeHtml(svc.name)}</h3>
        <span class="badge badge-category">${escapeHtml(capFirst(svc.category))}</span>
      </div>

      <div style="margin-bottom: 16px;">
        <p style="color: var(--text-secondary); margin-bottom: 12px;">
          ${isDeployed && dashboardUrl ? '' : `New to ${escapeHtml(svc.name)}?`}
          <a href="${escapeHtml(linkUrl)}" target="_blank" rel="noopener" class="btn btn-primary btn-sm" style="margin-left: 8px;">
            ${linkLabel}
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
          </a>
          <a href="https://geiserx.github.io/CashPilot/guides/${svc.slug}/" target="_blank" rel="noopener" class="btn btn-ghost btn-sm" style="margin-left: 8px;">
            Setup Guide
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 3h6a4 4 0 014 4v14a3 3 0 00-3-3H2z"/><path d="M22 3h-6a4 4 0 00-4 4v14a3 3 0 013-3h7z"/></svg>
          </a>
        </p>
        <p style="color: var(--text-muted); font-size: 0.85rem;">Already have an account? Enter your credentials below.</p>
      </div>

      ${envFields}

      ${(() => {
        const onlineWorkers = (workers || []).filter(w => w.status === 'online');
        const { rows: workerRows, allDeployed } = workerCheckboxList(svc, onlineWorkers, 'setup-deploy-worker-cb');

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
          <button class="btn btn-success" data-action="deployService" data-a1="${svc.slug}"${_isOwner ? '' : ' disabled title="Owner access required"'}>
            Deploy ${escapeHtml(svc.name)}
          </button>
          <span class="deploy-status" id="deploy-status-${svc.slug}" style="margin-left: 4px; font-size: 0.85rem;"></span>
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
      assessments = await Promise.all(
        workerIds.map(id => api(`/api/services/${slug}/preflight?worker_id=${encodeURIComponent(id)}`))
      );
    } catch (err) {
      console.warn('Preflight unavailable, proceeding:', err);
      return true;
    }

    // Only the findings worth interrupting for. "check_these" is advisory —
    // surfacing it as a modal on every deploy would train people to click
    // through the one that matters.
    const serious = [];
    assessments.forEach((a, i) => {
      (a && a.findings ? a.findings : [])
        .filter(f => f.verdict === 'will_earn_nothing' || a.blocking)
        .forEach(f => serious.push({worker: workerIds[i], message: f.message}));
    });
    if (!serious.length) return true;

    const lines = serious.map(s => `• ${s.message}`).join('\n\n');
    return window.confirm(
      `${slug}: this may not work as expected.\n\n${lines}\n\nDeploy anyway?`
    );
  }

  async function _deployToWorkers(slug, workerIds) {
    const statusEl = document.getElementById(`deploy-status-${slug}`);
    if (workerIds.length === 0) {
      toast('Select at least one worker node', 'warning');
      if (statusEl) statusEl.textContent = 'Select at least one node.';
      return;
    }

    // Collect env vars (only env inputs carry data-key, not the worker checkboxes).
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
    await _deployToWorkers(slug, _selectedWorkerIds(`.setup-deploy-worker-cb[data-slug="${slug}"]:checked:not(:disabled)`));
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
      actionBtn = `<button class="btn btn-secondary btn-sm" data-action="openServiceDetail" data-a1="${svc.slug}">Manage</button>`;
    } else if (hasDocker) {
      actionBtn = `<button class="btn btn-primary btn-sm" data-action="openServiceDetail" data-a1="${svc.slug}">Deploy</button>`;
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
      // After the markup is in the DOM, not before: the container it fills is
      // created by the line above. Not awaited, so a slow earnings query never
      // holds up the rest of the modal.
      loadPayoutProgress();
      loadDeployRisk();
    } catch (err) {
      if (body) body.innerHTML = `<p class="empty-state-text">Could not load service: ${escapeHtml(err.message)}</p>`;
    }
  }

  function renderServiceDetail(svc, workers) {
    const earning = svc.earnings
      ? `$${svc.earnings.monthly_low}-$${svc.earnings.monthly_high} per ${svc.earnings.per || 'month'}`
      : 'Varies';

    const isDeployed = svc.deployed || false;
    const dashboardUrl = (svc.cashout && svc.cashout.dashboard_url) || svc.website || '';
    const signupUrl = svc.referral && svc.referral.signup_url
      ? svc.referral.signup_url
      : svc.website || '#';

    // --- Info grid (no referral bonus) ---
    let html = `
    <p style="color: var(--text-secondary); margin-bottom: 16px;">${escapeHtml(svc.description || svc.short_description || '')}</p>
    <!-- Filled in by loadPayoutProgress once the modal is in the DOM. Hidden
         until it has a real answer: an empty "Payout progress" heading on a
         service that has never been collected is worse than no heading. -->
    <div id="payout-progress-card" data-slug="${escapeHtml(svc.slug || '')}"
         data-currency="${escapeHtml(svc.cashout?.currency || '')}" style="display:none; margin-bottom:20px;">
      <div class="detail-label" style="margin-bottom:8px;">Payout progress</div>
      <div id="payout-progress-body"></div>
    </div>
    <!-- What running this actually does with the machine and the connection.
         Filled by loadDeployRisk once the modal exists. This belongs at the
         deploy step rather than in a FAQ nobody opens, which is what the
         backend's own comments say and what it never got. -->
    <div id="deploy-risk-card" data-slug="${escapeHtml(svc.slug || '')}" style="display:none; margin-bottom:20px;">
      <div id="deploy-risk-body"></div>
    </div>
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

    // --- Setup guide link ---
    const guideUrl = `https://geiserx.github.io/CashPilot/guides/${svc.slug}/`;
    html += `
    <div style="margin-bottom: 16px;">
      <a href="${guideUrl}" target="_blank" rel="noopener" class="btn btn-ghost btn-sm">
        Setup Guide
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 3h6a4 4 0 014 4v14a3 3 0 00-3-3H2z"/><path d="M22 3h-6a4 4 0 00-4 4v14a3 3 0 013-3h7z"/></svg>
      </a>
    </div>`;

    // --- Dashboard link for deployed services, Sign Up for non-deployed ---
    if (isDeployed && dashboardUrl) {
      html += `
      <div style="margin-bottom: 20px;">
        <a href="${escapeHtml(dashboardUrl)}" target="_blank" rel="noopener" class="btn btn-primary btn-sm">
          Open Dashboard
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
        </a>
      </div>`;
    } else if (!isDeployed) {
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
      const envFields = envInputFields(svc, svc.docker.env, { withId: false, withHint: false });

      // Worker deploy targets
      const onlineWorkers = (workers || []).filter(w => w.status === 'online');
      let workerRows = '';
      let allDeployed = true;
      ({ rows: workerRows, allDeployed } = workerCheckboxList(svc, onlineWorkers, 'deploy-worker-cb'));

      if (onlineWorkers.length === 0) {
        workerRows = '<p style="color:var(--text-muted); font-size:0.85rem;">No workers online.</p>';
      }

      html += `<h4 style="margin-bottom: 12px; font-size: 0.95rem;">Deploy</h4>`;
      html += envFields;

      // Earnings tracking uses SEPARATE credentials (Settings → Collectors).
      // The fields above only configure the container that earns; they don't
      // let CashPilot read your balance. Make that explicit at deploy time.
      if (svc.has_collector) {
        html += `
        <div style="font-size:0.8rem; color:var(--text-muted); background:var(--bg-subtle, rgba(255,255,255,0.03)); border:1px solid var(--border); border-radius:6px; padding:8px 10px; margin:10px 0;">
          The credentials above run the service. To also see its <strong>balance</strong> on the dashboard,
          add earnings-tracking credentials under
          <a href="#" data-action="openCredentialModal" data-prevent="1" data-a1="${escapeHtml(svc.slug)}" style="color:var(--accent, #3b82f6);">Settings → Collectors</a>
          after deploying. This is optional — the service earns either way.
        </div>`;
      }

      if (allDeployed && onlineWorkers.length > 0) {
        html += `<p style="color:var(--success); font-size:0.9rem; margin:12px 0;">Deployed on all nodes.</p>`;
      } else {
        html += `
        <div style="margin-bottom:12px;">
          <div style="font-size:0.85rem; color:var(--text-muted); margin-bottom:6px;">Select target nodes:</div>
          <div id="deploy-worker-list">${workerRows}</div>
        </div>
        <div style="display:flex; gap:8px; align-items:center;">
          <button class="btn btn-success" data-action="deployServiceToWorkers" data-a1="${svc.slug}"${_isOwner ? '' : ' disabled title="Owner access required"'}>Deploy</button>
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
          ${_canWrite ? `<div style="margin-left:auto; display:flex; gap:4px;">
            <button class="btn btn-secondary btn-sm" data-action="workerAction" data-a1="${svc.slug}" data-a2="restart" data-a3="${inst.worker.id}">Restart</button>
            <button class="btn btn-secondary btn-sm" data-action="workerAction" data-a1="${svc.slug}" data-a2="stop" data-a3="${inst.worker.id}">Stop</button>
            <button class="btn btn-ghost btn-sm" data-action="loadWorkerLogs" data-a1="${svc.slug}" data-a2="${inst.worker.id}" data-a3="logs-${svc.slug}-${inst.worker.id}">Logs</button>
          </div>` : ''}
        </div>
        <div class="log-viewer" id="logs-${svc.slug}-${inst.worker.id}" style="display:none; max-height:200px;"></div>`;
      }
      html += `</div>`;
    }

    return html;
  }

  async function deployServiceToWorkers(slug) {
    await _deployToWorkers(slug, _selectedWorkerIds(`.deploy-worker-cb[data-slug="${slug}"]:checked:not(:disabled)`));
  }

  async function workerAction(slug, action, workerId) {
    try {
      await api(`/api/services/${slug}/${action}?worker_id=${workerId}`, { method: 'POST' });
      // Refresh the modal
      openServiceDetail(slug);
    } catch (err) {
      toast(`${action} failed: ${err.message}`, 'error');
    }
  }

  async function loadWorkerLogs(slug, workerId, elemId) {
    const viewer = document.getElementById(elemId);
    if (!viewer) return;
    if (viewer.style.display === 'none') {
      viewer.style.display = 'block';
      viewer.textContent = 'Loading...';
      try {
        const data = await api(`/api/services/${slug}/logs?worker_id=${workerId}&lines=100`);
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
  // Which stored credentials are about to stop working.
  //
  // Several providers issue session cookies measured in hours. When one dies,
  // collection stops and nothing says so — the dashboard keeps showing the last
  // balance it managed to read, which is indistinguishable from a service that
  // simply is not earning. This is the warning before that, not after.
  //
  // Worst first, because the only rows that need acting on are the bad ones.
  const CREDENTIAL_STATUS = {
    likely_expired: {rank: 0, label: 'Likely expired', tone: 'var(--danger)'},
    expiring_soon: {rank: 1, label: 'Expiring soon', tone: 'var(--warning)'},
    no_known_expiry: {rank: 2, label: 'No known expiry', tone: 'var(--text-muted)'},
    fresh: {rank: 3, label: 'Fresh', tone: 'var(--success)'},
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
    if (!Array.isArray(rows) || !rows.length) {
      card.style.display = 'none';
      return;
    }

    const meta = status => CREDENTIAL_STATUS[status] || CREDENTIAL_STATUS.no_known_expiry;
    rows.sort((a, b) => meta(a.status).rank - meta(b.status).rank);

    card.style.display = '';
    body.innerHTML = rows.map(row => {
      const info = meta(row.status);
      const age = row.age_hours >= 48
        ? `${Math.round(row.age_hours / 24)} days old`
        : `${Math.round(row.age_hours)} hours old`;
      const lifetime = row.expected_lifetime_hours
        ? ` · expected to last about ${row.expected_lifetime_hours >= 48
            ? `${Math.round(row.expected_lifetime_hours / 24)} days`
            : `${row.expected_lifetime_hours} hours`}`
        : '';
      // The durable alternative is the actual fix, not a nag: swapping to it
      // ends the expiry cycle instead of restarting it.
      const durable = (row.durable_alternative_missing || []).length
        ? `<div class="credential-health-hint">A longer-lived credential exists for this service (${escapeHtml(row.durable_alternative_missing.join(', '))}) — setting it means not having to do this again.</div>`
        : '';
      const why = row.why ? `<div class="credential-health-hint">${escapeHtml(row.why)}</div>` : '';
      const needsAction = row.status === 'likely_expired' || row.status === 'expiring_soon';
      return `
        <div class="credential-health-item">
          <div>
            <div class="credential-health-name">${escapeHtml(row.service)} <span style="color:var(--text-muted); font-weight:400;">· ${escapeHtml(String(row.field).replace(/_/g, ' '))}</span></div>
            <div class="credential-health-detail">${escapeHtml(age)}${escapeHtml(lifetime)}</div>
            ${why}${durable}
          </div>
          <div class="credential-health-actions">
            <span class="credential-health-status" style="color:${info.tone};">${escapeHtml(info.label)}</span>
            ${needsAction && _isOwner ? `<button class="btn btn-ghost btn-sm" data-action="openCredentialModal" data-a1="${escapeHtml(row.service)}">Update</button>` : ''}
          </div>
        </div>
      `;
    }).join('');
  }

  async function loadSettings() {
    populateCurrencyDropdown();
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
      // Settings may not be available yet
    }
  }

  function renderEnvVars(envInfo, config) {
    const container = document.getElementById('env-vars-container');
    if (!container) return;
    if (!envInfo.length) {
      container.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem;">No environment variable info available.</p>';
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
        ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" stroke-width="2" style="vertical-align:middle;margin-left:6px;"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>'
        : '';
      let badge;
      if (fromEnv) badge = '<span class="badge badge-deployed" style="font-size:0.7rem;margin-left:8px;">ENV</span>';
      else if (v.read_only) badge = '<span class="badge" style="font-size:0.7rem;margin-left:8px;opacity:0.6;">Read-only</span>';
      // No "DB" badge. It asserted that a stored value was in force, and
      // nothing reads these from the database: every one is resolved once from
      // the environment at import (main.py:639-640, auth.py, fleet_key.py), so
      // a saved value could never take effect. A stored-but-inert value is
      // worth flagging as exactly that.
      else if (dbVal) badge = '<span class="badge badge-warning" style="font-size:0.7rem;margin-left:8px;" title="Stored in the database but NOT in use — these are read from the environment at startup">Stored, not applied</span>';
      else if (isSet) badge = '<span class="badge" style="font-size:0.7rem;margin-left:8px;opacity:0.5;">Default</span>';
      else badge = '<span class="badge" style="font-size:0.7rem;margin-left:8px;opacity:0.5;">Not set</span>';
      // Secret fields render empty; placeholder communicates whether a value is stored.
      const placeholder = v.secret
        ? (isSet ? '•••••••• (set — leave blank to keep)' : 'Not set')
        : v.description;
      return `
      <div style="display:grid;grid-template-columns:220px 1fr;gap:12px;align-items:start;padding:10px 0;border-bottom:1px solid var(--border-color);">
        <div>
          <div style="font-weight:600;font-size:0.9rem;color:var(--text-primary);">${escapeHtml(v.label)}${lockIcon}${badge}</div>
          <div style="font-size:0.75rem;color:var(--text-muted);margin-top:2px;font-family:monospace;">${escapeHtml(v.key)}</div>
        </div>
        <div>
          <div style="display:flex;gap:6px;align-items:center;">
            <input class="form-input env-var-input" type="${inputType}" id="env-${v.key}"
                   data-env-key="${escapeHtml(v.key)}"
                   value="${escapeHtml(displayVal)}"
                   placeholder="${escapeHtml(placeholder)}"
                   ${v.secret ? 'autocomplete="new-password"' : ''}
                   style="flex:1;${locked ? 'opacity:0.6;cursor:not-allowed;' : ''}"
                   ${locked ? 'disabled' : ''}>
          </div>
          <div class="form-hint">${escapeHtml(v.description)}</div>
        </div>
      </div>`;
    }).join('');
    container.innerHTML = rows + `
    <div class="form-hint" style="margin-top:12px;">
      These are read from the environment when CashPilot starts, so changing one
      here does not take effect. Set it in your <code>docker-compose.yml</code>
      (or Unraid template) and restart the container. Saving stores the value but
      nothing reads it back — the field is kept so an existing stored value stays
      visible rather than disappearing.
    </div>
    <div style="display:flex;justify-content:flex-end;margin-top:12px;">
      <button class="btn btn-ghost" data-action="saveEnvSettings" title="Stores the value; it will not take effect until it is set in the environment and the container restarts">Save anyway</button>
    </div>`;
  }

  function toggleEnvSecret(inputId, btn) {
    const input = document.getElementById(inputId);
    if (!input) return;
    const showing = input.type === 'text';
    input.type = showing ? 'password' : 'text';
    btn.title = showing ? 'Show' : 'Hide';
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
      toast('No changes to save', 'info');
      return;
    }
    try {
      await api('/api/config', { method: 'POST', body: { data } });
      toast('Variables saved', 'success');
    } catch (err) {
      toast(`Save failed: ${err.message}`, 'error');
    }
  }

  function renderCollectors(meta, config) {
    const container = document.getElementById('collectors-container');
    if (!container) return;
    if (!meta.length) {
      container.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem;">No collectors available.</p>';
      return;
    }
    const secrets = config._secrets || {};
    const items = meta.map(col => {
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
        ? '<span class="badge badge-warning" title="Some required credentials are missing, so this service is not being collected">Incomplete</span>'
        : configured
        ? '<span class="badge badge-deployed">Configured</span>'
        : '<span class="badge badge-category">Not configured</span>';
      const fields = col.fields.map(f => {
        // Secret fields never receive a plaintext value from /api/config — render
        // them empty (write-only). Submitting blank preserves the stored secret.
        const isSecretSet = f.secret && !!secrets[f.key];
        const savedVal = f.secret ? '' : (config[f.key] || '');
        const inputType = f.secret ? 'password' : 'text';
        const inputId = `cred-${f.key}`;
        const placeholder = f.secret
          ? (isSecretSet ? '•••••••• (set — leave blank to keep)' : 'Not set')
          : f.label;
        return `
        <div class="form-group" style="margin-bottom:8px;">
          <label class="form-label" style="font-size:0.8rem;">${escapeHtml(f.label)}${f.required ? '' : ' <span style="opacity:0.5;">(optional)</span>'}</label>
          <div style="display:flex;gap:6px;align-items:center;">
            <input class="form-input collector-input" type="${inputType}" id="${inputId}"
                   data-config="${escapeHtml(f.key)}"
                   value="${escapeHtml(savedVal)}"
                   placeholder="${escapeHtml(placeholder)}"
                   ${f.secret ? 'autocomplete="new-password"' : ''}
                   style="flex:1;">
          </div>
        </div>`;
      }).join('');
      const clearBtn = configured && _isOwner
        ? `<div style="margin-top:8px; text-align:right;"><button class="btn btn-ghost btn-sm" style="color:var(--error); font-size:0.75rem;" data-action="clearServiceCredentials" data-a1="${escapeHtml(col.slug)}" data-a2="${escapeHtml(col.name)}">Clear Credentials</button></div>`
        : '';
      return `
      <details class="collector-section" id="collector-${col.slug}">
        <summary class="collector-header">
          <span class="collector-name">${escapeHtml(col.name)}</span>
          ${statusBadge}
        </summary>
        <div class="collector-body">
          ${col.hint ? `<div class="form-hint" style="margin-bottom:12px;">${sanitizeHint(col.hint)}</div>` : ''}
          ${fields}
          ${clearBtn}
        </div>
      </details>`;
    }).join('');
    container.innerHTML = `<div class="collectors-grid">${items}</div>`;
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
      toast('No credentials to save', 'warning');
      return;
    }

    try {
      await api('/api/config', { method: 'POST', body: { data } });
      toast('Credentials saved', 'success');
      loadSettings();
    } catch (err) {
      toast(`Save failed: ${err.message}`, 'error');
    }
  }

  async function clearServiceCredentials(slug, name) {
    if (!confirm(`Remove all credentials for ${name}? This will stop earnings collection for this service.`)) return;
    try {
      await api(`/api/config/${encodeURIComponent(slug)}`, { method: 'DELETE' });
      toast(`${name} credentials cleared`, 'success');
      // The caller used to close the modal in a second inline call; folded in
      // here so the button declares one action rather than two.
      closeModal('cred-modal');
      loadSettings();
    } catch (err) {
      toast(`Clear failed: ${err.message}`, 'error');
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
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(displayAmount);
    } catch {
      return displayAmount.toFixed(2) + ' ' + currency;
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
      // Clear any muted "alerts unavailable" styling left over from a prior
      // failed poll now that the fetch succeeded.
      badge.style.background = '';
      badge.title = '';
      if (!alerts || alerts.length === 0) {
        badge.style.display = 'none';
        list.innerHTML = '<div class="notify-empty">All collectors healthy</div>';
        return;
      }

      badge.style.display = '';
      badge.textContent = alerts.length;
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
        const isNotice = a.kind === 'notice';
        const icon = isPayout ? PAYOUT_ICON : isNotice ? NOTICE_ICON : WARNING_ICON;
        return `
        <div class="notify-item" data-platform="${escapeHtml(a.platform)}" data-kind="${escapeHtml(a.kind || 'collector')}">
          <div class="notify-item-icon"${isNotice ? ' style="color:var(--text-muted);"' : ''}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">${icon}</svg>
          </div>
          <div class="notify-item-body">
            <div class="notify-item-platform">${escapeHtml(a.platform)}${isPayout ? ' — payout?' : ''}${isNotice ? ' — note' : ''}</div>
            <div class="notify-item-msg" title="${escapeHtml(a.error)}">${escapeHtml(a.error)}</div>
          </div>
          ${!isPayout && !isNotice && _isOwner ? `<button class="btn btn-ghost btn-sm" data-action="openCredentialModal" data-stop="1" data-a1="${escapeHtml(a.platform)}" style="font-size:0.65rem; padding:2px 6px; white-space:nowrap; flex-shrink:0;">Update</button>` : ''}
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
      badge.title = 'Alerts unavailable';
      list.innerHTML = '<div class="notify-empty">Alerts unavailable — could not reach the server</div>';
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
    workerAction,
    loadWorkerLogs,
    openCredentialModal,
    saveCredentialModal,
    clearServiceCredentials,
    openChangePasswordModal,
    submitPasswordChange,
    loadPayoutQueue,
    loadCredentialHealth,
    loadPayoutProgress,
    loadDeployRisk,
    confirmPayout,
    rejectPayout,
    // Exposed for fleet.html, which rendered running costs with a bare
    // Number(v).toFixed(2) — no unit at all, on figures that mixed USD earnings
    // with a tariff in the user's own currency. The API is canonical USD now,
    // and this is the one place that knows the viewer's display currency.
    formatCurrency,
  };
})();
