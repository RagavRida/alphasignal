/* ═══════════════════════════════════════════════════════════════════════════
   AlphaSignal Dashboard — Real-time WebSocket Client
   ═══════════════════════════════════════════════════════════════════════════ */

const feed    = document.getElementById('alert-feed');
const wsStatus = document.getElementById('ws-status');
const statusText = document.getElementById('status-text');
const modeBadge = document.getElementById('mode-badge');

let alertStore   = [];
let activeFilter = 'all';

// ─── SSE ──────────────────────────────────────────────────────────────────────

function connectSSE() {
  const es = new EventSource('/sse');

  es.onopen = () => {
    if (wsStatus)  wsStatus.textContent = '● Live';
    if (wsStatus)  wsStatus.style.color = 'var(--green)';
    if (statusText) statusText.textContent = 'Monitoring Live';
    const badge = document.getElementById('status-badge');
    if (badge) badge.style.background = 'var(--green-dim)';
  };

  es.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'alert') handleNewAlert(msg.data);
  };

  es.onerror = () => {
    if (wsStatus)  wsStatus.textContent = '● Reconnecting…';
    if (wsStatus)  wsStatus.style.color = 'var(--yellow)';
    if (statusText) statusText.textContent = 'Reconnecting…';
    // EventSource retries automatically — no manual reconnect needed
  };
}

// ─── Alert Handling ───────────────────────────────────────────────────────────

function handleNewAlert(alert) {
  // Deduplicate
  if (alertStore.find(a => a.alert_id === alert.alert_id)) {
    return;
  }
  alertStore.unshift(alert);
  if (alertStore.length > 100) alertStore.pop();

  updateHeaderStats();
  updateDistribution();
  renderFeed();
}

function renderFeed() {
  const filtered = activeFilter === 'all'
    ? alertStore
    : alertStore.filter(a => (a.alert_type || a.correlation_type) === activeFilter);

  if (filtered.length === 0) {
    feed.innerHTML = `<div class="empty-state">
      <div class="spinner"></div>
      <p>Monitoring markets…</p>
      <p class="empty-sub">Alerts will appear here in real-time</p>
    </div>`;
    return;
  }

  feed.innerHTML = filtered.map(renderAlertCard).join('');
}

function renderAlertCard(alert) {
  const type = alert.alert_type || alert.correlation_type || 'growth_thesis';
  const conf = alert.confidence_score || 0;
  const signals = alert.signals || [];
  const rec = alert.recommendation || {};
  const direction = rec.direction || 'NEUTRAL';
  const badgeClass = {
    growth_thesis: 'badge-growth',
    competitive_threat: 'badge-threat',
    financial_distress: 'badge-distress',
    supplier_risk: 'badge-supplier',
    market_disruption: 'badge-disruption',
  }[type] || 'badge-growth';

  const labelMap = {
    growth_thesis: '📈 Growth Thesis',
    competitive_threat: '⚔️ Comp. Threat',
    financial_distress: '🚨 Distress',
    supplier_risk: '⛓️ Supplier Risk',
    market_disruption: '💥 Disruption',
  };

  const sensitivity = alert.time_sensitivity || 'moderate';
  const sensitivityColors = { immediate: 'var(--red)', urgent: 'var(--yellow)', moderate: 'var(--accent)', low: 'var(--text-muted)' };
  const sensColor = sensitivityColors[sensitivity] || 'var(--accent)';

  const signalPills = signals.slice(0, 5).map(s =>
    `<span class="signal-pill ${s.alert ? 'fired' : ''}">${s.signal_type?.replace('_', ' ') || ''}</span>`
  ).join('');

  const timeAgo = formatTimeAgo(alert.timestamp);

  return `
    <div class="alert-card ${type}" onclick="openModal('${alert.alert_id}')">
      <div class="alert-card-header">
        <div>
          <div class="alert-company">${alert.company}</div>
        </div>
        <div class="alert-meta">
          <span class="alert-type-badge ${badgeClass}">${labelMap[type] || type}</span>
          <span class="alert-confidence" style="color: ${conf >= 85 ? 'var(--green)' : conf >= 70 ? 'var(--yellow)' : 'var(--text-muted)'}">
            ${conf.toFixed(0)}%
          </span>
        </div>
      </div>

      <div class="alert-headline">${escHtml(alert.headline || '')}</div>
      <div class="alert-narrative">${escHtml(alert.narrative || '')}</div>

      <div class="alert-rec">
        <span class="rec-badge rec-${direction}">${direction}</span>
        <span class="rec-text">${escHtml(rec.trade || '')}</span>
      </div>

      <div class="alert-footer">
        <div class="alert-signals">${signalPills}</div>
        <div class="alert-time" style="color: ${sensColor}">
          ${sensitivity.toUpperCase()} · ${timeAgo}
        </div>
      </div>
    </div>`;
}

// ─── Modal ────────────────────────────────────────────────────────────────────

function openModal(alertId) {
  const alert = alertStore.find(a => a.alert_id === alertId);
  if (!alert) return;

  const content = document.getElementById('modal-content');
  const type = alert.alert_type || alert.correlation_type || 'growth_thesis';
  const rec = alert.recommendation || {};
  const fi = alert.financial_impact || {};
  const dq = alert.data_quality || {};
  const signals = alert.signals || [];
  const watchFor = alert.next_monitoring?.watch_for || [];

  content.innerHTML = `
    <div class="modal-alert-id">${escHtml(alert.alert_id || '')}</div>

    <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px">
      <span class="alert-type-badge ${{ growth_thesis:'badge-growth',competitive_threat:'badge-threat',financial_distress:'badge-distress',supplier_risk:'badge-supplier',market_disruption:'badge-disruption' }[type]}">${alert.correlation_label || type}</span>
      <span style="font-size:13px;font-weight:700;color:var(--accent)">${alert.company}</span>
      <span style="font-size:12px;color:var(--text-muted);margin-left:auto">${formatTimeAgo(alert.timestamp)}</span>
    </div>

    <div class="modal-headline">${escHtml(alert.headline || '')}</div>

    <div class="modal-section">
      <div class="modal-section-title">Analysis</div>
      <div class="modal-narrative">${escHtml(alert.narrative || '')}</div>
    </div>

    ${alert.thesis ? `
    <div class="modal-section">
      <div class="modal-section-title">Investment Thesis</div>
      <div class="modal-narrative">${escHtml(alert.thesis)}</div>
    </div>` : ''}

    <div class="modal-section">
      <div class="modal-section-title">Signals (${signals.filter(s=>s.alert).length}/${signals.length} fired)</div>
      <div class="modal-signals-grid">
        ${signals.map(s => `
          <div class="modal-signal-item ${s.alert ? 'fired' : ''}">
            <div class="modal-sig-type">${(s.signal_type||'').replace(/_/g,' ')}</div>
            <div class="modal-sig-metric">${escHtml(s.metric || '')}</div>
            <div class="modal-sig-variance" style="color:${parseFloat(s.variance_pct||0)>0?'var(--green)':'var(--red)'}">
              ${s.variance_pct || ''}
            </div>
            <div style="font-size:10px;color:var(--text-muted)">${escHtml(s.source||'')}</div>
          </div>`).join('')}
      </div>
    </div>

    <div class="modal-section">
      <div class="modal-section-title">Financial Impact</div>
      <div class="modal-impact-grid">
        <div class="modal-impact-item">
          <div class="modal-impact-label">Revenue</div>
          <div class="modal-impact-value">${escHtml(fi.revenue_impact||'N/A')}</div>
        </div>
        <div class="modal-impact-item">
          <div class="modal-impact-label">Margins</div>
          <div class="modal-impact-value">${escHtml(fi.margin_impact||'N/A')}</div>
        </div>
        <div class="modal-impact-item">
          <div class="modal-impact-label">Timeline</div>
          <div class="modal-impact-value">${escHtml(fi.timeline||'N/A')}</div>
        </div>
      </div>
    </div>

    <div class="modal-section">
      <div class="modal-section-title">Recommendation</div>
      <div class="modal-rec-box">
        <div class="modal-trade">${escHtml(rec.trade||'N/A')}</div>
        ${[
          ['Conviction', rec.conviction],
          ['Direction', rec.direction],
          ['Risk', rec.risk],
          ['Hedge', rec.hedge],
        ].filter(([,v])=>v).map(([k,v])=>`
          <div class="modal-rec-row">
            <span class="modal-rec-key">${k}</span>
            <span>${escHtml(String(v))}</span>
          </div>`).join('')}
      </div>
    </div>

    ${watchFor.length ? `
    <div class="modal-section">
      <div class="modal-section-title">Watch For (next 48h)</div>
      <ul class="modal-watch-list">
        ${watchFor.map(w=>`<li>${escHtml(w)}</li>`).join('')}
      </ul>
    </div>` : ''}

    <div class="modal-section">
      <div class="modal-section-title">Data Quality</div>
      <div class="modal-data-quality" style="margin-bottom:12px">
        <div class="dq-item"><div class="dq-value">${dq.sources_used||0}</div><div class="dq-label">Sources</div></div>
        <div class="dq-item"><div class="dq-value">${dq.signals_fired||0}/${dq.signals_total||0}</div><div class="dq-label">Signals Fired</div></div>
        <div class="dq-item"><div class="dq-value">${dq.false_positive_risk||'N/A'}</div><div class="dq-label">FP Risk</div></div>
      </div>
      <div class="bd-products-used">
        ${(dq.bright_data_products||[]).map(p=>`<span class="bd-pill">${escHtml(p)}</span>`).join('')}
      </div>
    </div>`;

  document.getElementById('modal-overlay').classList.add('open');
}

function closeModal() {
  document.getElementById('modal-overlay').classList.remove('open');
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

// ─── Filters ──────────────────────────────────────────────────────────────────

document.querySelectorAll('.filter-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    activeFilter = btn.dataset.filter;
    renderFeed();
  });
});

// ─── Stats & sidebar ──────────────────────────────────────────────────────────

async function loadStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();
    const stats = data.alert_stats || {};

    document.getElementById('total-alerts').textContent = stats.total_alerts || 0;
    document.getElementById('avg-confidence').textContent = stats.avg_confidence ? `${stats.avg_confidence}%` : '—';
    document.getElementById('companies-count').textContent = data.companies_monitored?.length || '—';

    if (data.demo_mode) {
      modeBadge.textContent = 'DEMO';
      modeBadge.classList.add('demo');
    }

    updateDistributionFromStats(stats.by_type || {});
  } catch(e) {
    console.warn('Status fetch failed:', e);
  }
}

async function loadCompanies() {
  try {
    const res = await fetch('/api/companies');
    const data = await res.json();
    const list = document.getElementById('company-list');
    list.innerHTML = (data.companies || []).map(c => `
      <div class="company-item" onclick="filterByCompany('${c.name}')">
        <div class="company-avatar">${c.name.charAt(0)}</div>
        <div class="company-info">
          <div class="company-name">${c.name}</div>
          <div class="company-ticker">${c.ticker || ''}</div>
        </div>
      </div>`).join('');
  } catch(e) {
    console.warn('Companies fetch failed:', e);
  }
}

function filterByCompany(name) {
  activeFilter = 'all';
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  document.querySelector('[data-filter="all"]').classList.add('active');
  const filtered = alertStore.filter(a => a.company === name);
  feed.innerHTML = filtered.length
    ? filtered.map(renderAlertCard).join('')
    : `<div class="empty-state"><p>No alerts for ${name} yet</p></div>`;
}

function updateHeaderStats() {
  document.getElementById('total-alerts').textContent = alertStore.length;
  const confidences = alertStore.map(a => a.confidence_score || 0);
  const avg = confidences.length ? (confidences.reduce((a,b) => a+b, 0) / confidences.length).toFixed(1) : '—';
  document.getElementById('avg-confidence').textContent = avg ? `${avg}%` : '—';
}

function updateDistribution() {
  const counts = { growth_thesis: 0, competitive_threat: 0, financial_distress: 0, supplier_risk: 0, market_disruption: 0 };
  alertStore.forEach(a => {
    const t = a.alert_type || a.correlation_type;
    if (t in counts) counts[t]++;
  });
  updateDistributionFromStats(counts);
}

function updateDistributionFromStats(byType) {
  const total = Object.values(byType).reduce((a, b) => a + b, 0) || 1;
  const ids = { growth_thesis: 'dist-growth', competitive_threat: 'dist-threat', financial_distress: 'dist-distress', supplier_risk: 'dist-supplier', market_disruption: 'dist-disruption' };
  Object.entries(ids).forEach(([type, id]) => {
    const count = byType[type] || 0;
    const pct = (count / total * 100).toFixed(0);
    const el = document.getElementById(id);
    if (el) el.textContent = count;
    const bar = document.querySelector(`.dist-bar[data-type="${type}"]`);
    if (bar) bar.style.width = `${pct}%`;
  });
}

// ─── Run cycle button ─────────────────────────────────────────────────────────

document.getElementById('btn-run-once')?.addEventListener('click', async () => {
  const btn = document.getElementById('btn-run-once');
  btn.disabled = true;
  btn.textContent = '⏳ Running…';
  try {
    await fetch('/api/trigger-cycle', { method: 'POST' }).catch(() => {});
    setTimeout(() => { btn.disabled = false; btn.textContent = '▶ Run Cycle'; }, 5000);
  } catch(e) {
    btn.disabled = false;
    btn.textContent = '▶ Run Cycle';
  }
});

// ─── Utilities ────────────────────────────────────────────────────────────────

function escHtml(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function formatTimeAgo(ts) {
  if (!ts) return '';
  const secs = Math.floor((Date.now() - new Date(ts).getTime()) / 1000);
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs/60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs/3600)}h ago`;
  return `${Math.floor(secs/86400)}d ago`;
}

// ─── Init ─────────────────────────────────────────────────────────────────────

connectSSE();
loadStatus();
loadCompanies();

// Refresh sidebar stats periodically
setInterval(loadStatus, 30000);
