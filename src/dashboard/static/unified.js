/* ═══════════════════════════════════════════════════════════════════
   AlphaSignal — Unified Platform Controller
   Bridges Market Intelligence ↔ Sales Pipeline
═══════════════════════════════════════════════════════════════════ */

// ── State ─────────────────────────────────────────────────────────────────────
let currentView      = 'market';
let unifiedEvents    = [];       // all events from both streams
let unifiedFilter    = 'all';
let _currentAlertForCross = null;  // market alert that triggered cross-signal

// ── View Switching ────────────────────────────────────────────────────────────

function switchView(view, btn) {
  currentView = view;

  // Update sidebar buttons
  document.querySelectorAll('.sn-item').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');

  // Show/hide views
  document.querySelectorAll('.view').forEach(v => v.classList.add('hidden'));
  const target = document.getElementById(`view-${view}`);
  if (target) target.classList.remove('hidden');

  // Update top bar title
  const titles = {
    market:  '📈 Market Intelligence',
    sales:   '🎯 Sales Pipeline',
    unified: '⚡ Unified Signal Feed',
  };
  const tb = document.getElementById('top-bar-title');
  if (tb) tb.textContent = titles[view] || view;

  // When switching to sales, auto-populate ICP + show brand banner
  if (view === 'sales' && typeof _loadProfileIntoUI === 'function') {
    _loadProfileIntoUI();
  }
}

function toggleSidebar() {
  const nav = document.getElementById('sidebar-nav');
  nav.classList.toggle('collapsed');
  nav.classList.toggle('open');
}

// ── WS: Bridge sales WebSocket into unified feed ──────────────────────────────

function connectSalesWS() {
  const salesES = new EventSource('/sse/sales');

  salesES.onopen = () => updateSidebarWS(true);

  salesES.onmessage = (e) => {
    const msg = JSON.parse(e.data);

    if (msg.type === 'initial_data') {
      // Populate leads table + signals from existing DB data
      if (msg.leads)   { allLeads = msg.leads; renderLeads(); updateStatsFromLeads(); }
      if (msg.signals) { msg.signals.forEach(s => onNewSignal(s)); }
      const navLeadCount = document.getElementById('nav-lead-count');
      const navLeadsInline = document.getElementById('nav-leads-inline');
      if (navLeadCount) navLeadCount.textContent = (msg.leads || []).length;
      if (navLeadsInline) navLeadsInline.textContent = (msg.leads || []).length;
    }

    if (msg.type === 'new_lead') {
      onNewLead(msg.lead);
      const count = allLeads.length;
      const navLeadCount = document.getElementById('nav-lead-count');
      const navLeadsInline = document.getElementById('nav-leads-inline');
      if (navLeadCount) navLeadCount.textContent = count;
      if (navLeadsInline) navLeadsInline.textContent = count;

      // Push to unified feed
      pushUnifiedEvent({
        source:     'sales',
        title:      `New Lead: ${msg.lead.company || 'Company'}`,
        body:       `Score: ${msg.lead.score?.toFixed(0) || '?'}/100 · ${msg.lead.funding || ''} · ${msg.lead.stage || ''}`,
        confidence: msg.lead.score || 0,
        action:     () => {
          switchView('sales', document.querySelector('[data-view="sales"]'));
          setTimeout(() => openDrawer(msg.lead.id), 100);
        },
        actionLabel: 'View Emails →',
        raw:        msg.lead,
      });
    }

    if (msg.type === 'new_signal') {
      onNewSignal(msg.signal);
      const sigEl = document.getElementById('nav-signal-count');
      if (sigEl) sigEl.textContent = parseInt(sigEl.textContent || '0') + 1;

      pushUnifiedEvent({
        source:     'sales',
        title:      `Intent Signal: ${msg.signal.intent_type?.replace(/_/g, ' ')}`,
        body:       `"${(msg.signal.quote || '').substring(0, 120)}…" — via ${msg.signal.source}`,
        confidence: msg.signal.confidence || 0,
        raw:        msg.signal,
      });
    }

    if (msg.type === 'pipeline_step' && typeof onPipelineStep === 'function') {
      onPipelineStep(msg);
    }

    if (msg.type === 'pipeline_done') {
      if (typeof onPipelineDone === 'function') onPipelineDone(msg);
      pushUnifiedEvent({
        source: 'sales',
        title:  '✅ Sales Pipeline Complete',
        body:   `${msg.leads} leads discovered · ${msg.emails} emails generated · ${msg.signals} intent signals`,
        confidence: 100,
      });
    }

    if (msg.type === 'bd_activity' && typeof onBDActivity === 'function') {
      onBDActivity(msg);
    }
  };

  salesES.onerror = () => {
    updateSidebarWS(false);
    // EventSource auto-reconnects — no manual retry needed
  };
}

function updateSidebarWS(live) {
  const dot   = document.getElementById('sn-ws-dot');
  const label = document.getElementById('sn-ws-label');
  if (live) {
    dot.classList.add('live');
    label.textContent = 'Live — both feeds';
  } else {
    dot.classList.remove('live');
    label.textContent = 'Reconnecting…';
  }
}

// ── Bridge: Market alert → Unified feed ──────────────────────────────────────

// Monkey-patch handleNewAlert so every market alert also goes to unified feed
const _origHandleAlert = window.handleNewAlert;
window.handleNewAlert = function(alert) {
  _origHandleAlert(alert);

  // Update nav badge
  const cnt = document.getElementById('nav-alert-count');
  if (cnt) cnt.textContent = alertStore.length;
  document.getElementById('total-alerts').textContent = alertStore.length;

  // Push to unified feed
  pushUnifiedEvent({
    source:     'market',
    title:      alert.headline || `Alert: ${alert.company}`,
    body:       (alert.narrative || '').substring(0, 180) + '…',
    confidence: alert.confidence_score || 0,
    action:     () => openModal(alert.alert_id),
    actionLabel:'View Alert →',
    raw:        alert,
  });

  // Signal count badge
  const sigEl = document.getElementById('nav-signal-count');
  if (sigEl) sigEl.textContent = parseInt(sigEl.textContent || '0') + 1;

  // Detect cross-signal opportunity
  checkCrossSignal(alert);
};

// ── Cross-Signal Detection ────────────────────────────────────────────────────

function checkCrossSignal(alert) {
  const type = alert.alert_type || alert.correlation_type || '';

  // If a company is in distress or has supplier risk → their competitors' customers are sales targets
  const opportunityTypes = ['financial_distress', 'supplier_risk', 'competitive_threat', 'market_disruption'];
  if (!opportunityTypes.includes(type)) return;

  const company = alert.company;
  const typeLabels = {
    financial_distress:  `${company} is in financial distress — their customers are looking to switch`,
    supplier_risk:       `${company}'s supply chain is disrupted — competitors will steal market share`,
    competitive_threat:  `${company} faces competitive threats — their customers may be evaluating alternatives`,
    market_disruption:   `${company}'s market is disrupted — displacement opportunities are emerging`,
  };

  // Push cross-signal to unified feed
  pushUnifiedEvent({
    source:      'cross',
    title:       `🔗 Cross-Signal: Sales Opportunity from ${company} Alert`,
    body:        typeLabels[type] || `${company} market alert creates sales displacement opportunity`,
    confidence:  alert.confidence_score || 0,
    action:      () => {
      _currentAlertForCross = alert;
      openSalesFromAlert();
    },
    actionLabel: '🎯 Find Leads →',
    raw:         alert,
  });
}

// ── Open Sales pipeline from a market alert ───────────────────────────────────

function openSalesFromAlert() {
  const alert = _currentAlertForCross;
  if (!alert) return;

  closeModal();

  const company = alert.company;
  const type    = alert.alert_type || alert.correlation_type || '';
  const icpMap  = {
    financial_distress:  `Companies that are customers of ${company} or would benefit from their distress — similar industry, considering switching vendors`,
    supplier_risk:       `Companies in the same supply chain as ${company} — looking for alternative suppliers or competitive displacement of ${company}`,
    competitive_threat:  `Customers switching from ${company} — companies evaluating alternatives to ${company}`,
    market_disruption:   `B2B companies affected by market disruption in the ${company} sector — looking for new solutions`,
  };

  const icp = icpMap[type] || `Companies that compete with or are customers of ${company}`;

  // Switch to sales view and pre-fill ICP
  switchView('sales', document.querySelector('[data-view="sales"]'));
  setTimeout(() => {
    const ta = document.getElementById('icp-input');
    if (ta) ta.value = icp;
    const comp = document.getElementById('competitor-input');
    if (comp) comp.value = company;
  }, 150);
}

// Show cross-action in modal for qualifying alerts
const _origOpenModal = window.openModal;
window.openModal = function(alertId) {
  _origOpenModal(alertId);
  const alert = alertStore.find(a => a.alert_id === alertId);
  if (!alert) return;

  const opportunityTypes = ['financial_distress', 'supplier_risk', 'competitive_threat', 'market_disruption'];
  const cross = document.getElementById('modal-cross-action');
  const desc  = document.getElementById('cross-action-desc');

  if (opportunityTypes.includes(alert.alert_type || alert.correlation_type)) {
    _currentAlertForCross = alert;
    const msgs = {
      financial_distress:  `${alert.company} shows financial stress — their customers are prime targets. Auto-fill the sales pipeline to find switching opportunities.`,
      supplier_risk:       `${alert.company}'s supply chain is at risk — displacement leads are available now.`,
      competitive_threat:  `${alert.company} faces competitive pressure — find their customers before rivals do.`,
      market_disruption:   `${alert.company}'s sector is disrupted — capture leads before the market settles.`,
    };
    if (desc) desc.textContent = msgs[alert.alert_type] || msgs[alert.correlation_type] || '';
    if (cross) cross.style.display = 'block';
  } else {
    if (cross) cross.style.display = 'none';
  }
};

// ── Unified Feed ──────────────────────────────────────────────────────────────

function pushUnifiedEvent(event) {
  const ts = new Date();
  unifiedEvents.unshift({ ...event, ts });
  if (unifiedEvents.length > 200) unifiedEvents.pop();
  renderUnifiedFeed();
}

function filterUnified(filter, btn) {
  unifiedFilter = filter;
  document.querySelectorAll('[data-uf]').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  renderUnifiedFeed();
}

function renderUnifiedFeed() {
  const feed = document.getElementById('unified-feed');
  if (!feed) return;

  const events = unifiedFilter === 'all'
    ? unifiedEvents
    : unifiedEvents.filter(e => e.source === unifiedFilter);

  if (events.length === 0) {
    feed.innerHTML = '<div class="empty-state"><div class="spinner"></div><p>Waiting for signals…</p></div>';
    return;
  }

  feed.innerHTML = events.slice(0, 50).map((e, i) => `
    <div class="unified-card ${e.source}" onclick="handleUnifiedClick(${i})" id="uc-${i}">
      <div class="uc-header">
        <span class="uc-source ${e.source}">${
          e.source === 'market' ? '📈 Market Alert' :
          e.source === 'sales'  ? '🎯 Sales Signal' :
                                  '🔗 Cross-Signal'
        }</span>
        <span class="uc-time">${formatUCTime(e.ts)}</span>
      </div>
      <div class="uc-title">${escUC(e.title)}</div>
      <div class="uc-body">${escUC(e.body)}</div>
      <div class="uc-meta">
        <span class="uc-conf" style="color:${
          (e.confidence||0) >= 85 ? '#22c55e' :
          (e.confidence||0) >= 65 ? '#f59e0b' : '#64748b'
        }">${e.confidence ? e.confidence.toFixed(0) + '%' : ''}</span>
        ${e.actionLabel ? `<button class="uc-action-btn" onclick="event.stopPropagation();handleUnifiedClick(${i})">${e.actionLabel}</button>` : ''}
      </div>
    </div>
  `).join('');
}

// Store events array ref for click handler
function handleUnifiedClick(idx) {
  const events = unifiedFilter === 'all'
    ? unifiedEvents
    : unifiedEvents.filter(e => e.source === unifiedFilter);
  const e = events[idx];
  if (e && e.action) e.action();
}

function formatUCTime(ts) {
  if (!ts) return '';
  const secs = Math.floor((Date.now() - ts.getTime()) / 1000);
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  return `${Math.floor(secs / 3600)}h ago`;
}

function escUC(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── Pipeline trigger ──────────────────────────────────────────────────────────

function triggerCycle() {
  const btn = document.getElementById('btn-run-once');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Running…'; }
  fetch('/api/trigger-cycle', { method: 'POST' })
    .then(() => {
      setTimeout(() => {
        if (btn) { btn.disabled = false; btn.textContent = '▶ Run Cycle'; }
      }, 8000);
    })
    .catch(() => {
      if (btn) { btn.disabled = false; btn.textContent = '▶ Run Cycle'; }
    });
}

// ── Sales helpers (needed by inline handlers in the unified index.html) ────────

function setICP(el) {
  const ta = document.getElementById('icp-input');
  if (ta) ta.value = el.textContent.trim();
}

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  // Start sales WebSocket (market WS started in app.js)
  connectSalesWS();

  // Initial view
  switchView('market', document.querySelector('[data-view="market"]'));

  // Load brand profile into sales panel immediately (fills banner + ICP + competitor)
  if (typeof _loadProfileIntoUI === 'function') {
    _loadProfileIntoUI();
  }

  // Refresh unified feed timestamps every 30s
  setInterval(renderUnifiedFeed, 30000);
});
