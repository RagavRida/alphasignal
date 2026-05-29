/* AlphaSignal Sales Intelligence — Dashboard JavaScript
   Works both standalone (/sales) and embedded in the unified dashboard (/) */

const API = '';
let salesWs = null;         // renamed from 'ws' to avoid conflict with app.js
let allLeads = [];
let currentLeadId = null;
let currentEmails = [];
let currentTab = 0;
let sortKey = 'score';
let sortDir = -1;

// ── WebSocket (standalone /sales page only) ───────────────────────────────────

function _salesConnectWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  salesWs = new WebSocket(`${proto}://${location.host}/ws/sales`);

  salesWs.onopen = () => {
    const dot   = document.getElementById('ws-dot');
    const label = document.getElementById('ws-label');
    if (dot)   dot.classList.add('live');
    if (label) label.textContent = 'Live';
  };

  salesWs.onclose = () => {
    const dot   = document.getElementById('ws-dot');
    const label = document.getElementById('ws-label');
    if (dot)   dot.classList.remove('live');
    if (label) label.textContent = 'Reconnecting…';
    setTimeout(_salesConnectWS, 3000);
  };

  salesWs.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'new_lead')       onNewLead(msg.lead);
    if (msg.type === 'new_signal')     onNewSignal(msg.signal);
    if (msg.type === 'pipeline_step')  onPipelineStep(msg);
    if (msg.type === 'pipeline_done')  onPipelineDone(msg);
    if (msg.type === 'bd_activity')    onBDActivity(msg);
  };

  // Ping every 15s to keep connection alive
  const ping = setInterval(() => {
    if (salesWs && salesWs.readyState === WebSocket.OPEN) salesWs.send('ping');
    else clearInterval(ping);
  }, 15000);
}

// ── Pipeline control ──────────────────────────────────────────────────────────

async function runPipeline() {
  const icp = document.getElementById('icp-input').value.trim();
  if (!icp) {
    document.getElementById('icp-input').focus();
    return;
  }

  // Support both button IDs (standalone: 'run-btn', unified: 'run-pipeline-btn')
  const btn = document.getElementById('run-pipeline-btn') || document.getElementById('run-btn');
  if (btn) { btn.disabled = true; btn.innerHTML = '<span>⏳</span> Running…'; }

  // Show progress
  const progress = document.getElementById('pipeline-progress');
  progress.style.display = 'block';
  resetProgress();
  activateStep('step-parse');
  updateStatus('Parsing ICP with AI/ML API…');

  // Clear old data immediately — show clean slate
  allLeads = [];
  renderLeads();
  document.getElementById('signals-list').innerHTML = '<div class="empty-state-small">Starting new run…</div>';
  // Reset stat counters
  const statIds = ['stat-leads','stat-emails','stat-signals','stat-avg-score'];
  statIds.forEach(id => { const el = document.getElementById(id); if (el) el.textContent = '0'; });
  // Reset nav badge
  const nb = document.getElementById('nav-leads-inline') || document.getElementById('nav-lead-count');
  if (nb) nb.textContent = '0';

  try {
    const resp = await fetch('/api/sales/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        icp_text:    icp,
        max_leads:   parseInt(document.getElementById('max-leads').value),
        competitor:  document.getElementById('competitor-input').value.trim(),
        auto_send:   document.getElementById('auto-send').checked,
      }),
    });

    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    // Pipeline runs async; results arrive via WebSocket
    doneStep('step-parse');
    activateStep('step-discover');
    updateStatus('Discovering leads via Bright Data MCP…');

    // Poll for results if WebSocket misses events
    setTimeout(loadLeads, 15000);
    setTimeout(loadLeads, 30000);
    setTimeout(loadLeads, 60000);

  } catch (err) {
    updateStatus(`Error: ${err.message}`);
    const btn2 = document.getElementById('run-pipeline-btn') || document.getElementById('run-btn');
    if (btn2) { btn2.disabled = false; btn2.innerHTML = '<span>⚡</span> Run Pipeline'; }
  }
}

function setExample(el) {
  document.getElementById('icp-input').value = el.textContent.trim();
}

// ── Demo mode ─────────────────────────────────────────────────────────────────

async function runDemo() {
  const btn = document.getElementById('demo-btn');
  if (btn) { btn.disabled = true; btn.innerHTML = '⏳ Loading…'; }

  // Show progress and clear
  const progress = document.getElementById('pipeline-progress');
  if (progress) progress.style.display = 'block';
  resetProgress();
  activateStep('step-discover');
  updateStatus('Loading Natively AI demo data…');

  allLeads = [];
  renderLeads();
  const statIds = ['stat-leads','stat-emails','stat-signals','stat-avg-score'];
  statIds.forEach(id => { const el = document.getElementById(id); if (el) el.textContent = '0'; });
  const sigList = document.getElementById('signals-list');
  if (sigList) sigList.innerHTML = '<div class="empty-state-small">Loading demo signals…</div>';

  // Clear BD log
  const log = document.getElementById('bd-activity-log');
  if (log) log.innerHTML = '';
  _showBDLog(true);

  // Inject synthetic BD activity events — shows all 5 products firing
  const fakeCalls = [
    {product:'MCP Server',       action:'search_engine',      detail:'B2B SaaS Series A hiring SDRs India/US'},
    {product:'SERP API',         action:'google_search',      detail:'funded AI SaaS startups 2025 seed series-a hiring'},
    {product:'MCP Server',       action:'search_engine',      detail:'companies switching from Replit Builder.io alternatives'},
    {product:'Web Unlocker',     action:'scrape_as_html',     detail:'g2.com/products/replit/reviews'},
    {product:'SERP API',         action:'google_search',      detail:'site:reddit.com Replit frustrated OR switching OR alternative'},
    {product:'Web Unlocker',     action:'scrape_as_html',     detail:'glassdoor.com/Reviews/Landbase-reviews...'},
    {product:'Scraping Browser', action:'scrape_as_markdown', detail:'linkedin.com/jobs/search?keywords=Landbase&location=US'},
    {product:'MCP Server',       action:'search_engine',      detail:'Rho business banking Series A recent news 2025'},
    {product:'Scraping Browser', action:'scrape_as_markdown', detail:'landbase.com/blog'},
    {product:'Web Unlocker',     action:'scrape_as_html',     detail:'g2.com/products/builder-io/reviews'},
    {product:'SERP API',         action:'google_search',      detail:'site:news.ycombinator.com AI development platform'},
    {product:'Scraping Browser', action:'scrape_as_markdown', detail:'attio.com/blog/series-a'},
  ];

  for (let i = 0; i < fakeCalls.length; i++) {
    await new Promise(r => setTimeout(r, 200 + Math.random() * 300));
    onBDActivity({...fakeCalls[i], ts: new Date().toLocaleTimeString()});
  }

  try {
    await fetch('/api/sales/demo', { method: 'POST' });
    // Results come via WebSocket onNewLead / onPipelineDone
    setTimeout(loadLeads,    2000);
    setTimeout(loadSignals,  3000);
  } catch (err) {
    updateStatus('Demo load failed — ' + err.message);
  }

  if (btn) { btn.disabled = false; btn.innerHTML = '🎬 Demo'; }
}

// ── Bright Data Activity Log ───────────────────────────────────────────────────

const BD_ICONS = {
  'MCP Server':       {icon: '⚡', color: '#f97316'},
  'SERP API':         {icon: '🔍', color: '#3b82f6'},
  'Web Scraper':      {icon: '🕷',  color: '#a855f7'},
  'Scraping Browser': {icon: '🌐', color: '#06b6d4'},
  'Web Unlocker':     {icon: '🔓', color: '#22c55e'},
  'AI/ML API':        {icon: '🤖', color: '#f59e0b'},
};

function _showBDLog(visible) {
  const panel = document.getElementById('bd-log-panel');
  if (panel) panel.style.display = visible ? 'block' : 'none';
}

function onBDActivity(event) {
  // Ensure the panel exists — create it if not
  let panel = document.getElementById('bd-log-panel');
  if (!panel) {
    panel = document.createElement('div');
    panel.id = 'bd-log-panel';
    panel.className = 'bd-log-panel';
    panel.innerHTML = `
      <div class="bd-log-header">
        <span>🟠 Bright Data — Live API Calls</span>
        <button class="bd-log-toggle" onclick="_showBDLog(false)">✕</button>
      </div>
      <div id="bd-activity-log" class="bd-activity-log"></div>
    `;
    // Insert before the pipeline progress or at top of ICP section
    const progress = document.getElementById('pipeline-progress');
    if (progress && progress.parentNode) {
      progress.parentNode.insertBefore(panel, progress.nextSibling);
    } else {
      document.body.appendChild(panel);
    }
  }
  panel.style.display = 'block';

  const log = document.getElementById('bd-activity-log');
  if (!log) return;

  const meta = BD_ICONS[event.product] || {icon: '🟠', color: '#f97316'};
  const item = document.createElement('div');
  item.className = 'bd-log-item';
  item.style.cssText = 'display:flex;align-items:baseline;gap:8px;padding:4px 0;border-bottom:1px solid #1e2d4230;font-size:11px;animation:fadeInUp 0.2s ease;';
  item.innerHTML = `
    <span style="font-size:13px;width:16px;flex-shrink:0;">${meta.icon}</span>
    <span style="color:${meta.color};font-weight:600;width:110px;flex-shrink:0;font-size:10px;text-transform:uppercase;letter-spacing:0.4px;">${event.product}</span>
    <span style="color:#64748b;width:90px;flex-shrink:0;font-family:var(--mono,monospace);font-size:10px;">${event.action}</span>
    <span style="color:#94a3b8;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${event.detail || ''}</span>
    <span style="color:#475569;flex-shrink:0;font-family:var(--mono,monospace);">${event.ts || ''}</span>
  `;
  log.insertBefore(item, log.firstChild);
  // Keep max 25 items
  while (log.children.length > 25) log.lastChild.remove();
}


const STEPS = ['step-parse', 'step-discover', 'step-intent', 'step-context', 'step-email'];

function resetProgress() {
  STEPS.forEach(s => {
    const el = document.getElementById(s);
    el.classList.remove('active', 'done');
  });
  document.querySelectorAll('.progress-line').forEach(l => l.classList.remove('done'));
}

function activateStep(id) {
  document.getElementById(id).classList.add('active');
}

function doneStep(id) {
  const el = document.getElementById(id);
  el.classList.remove('active');
  el.classList.add('done');
  // Animate the line after this step
  const idx = STEPS.indexOf(id);
  const lines = document.querySelectorAll('.progress-line');
  if (lines[idx]) lines[idx].classList.add('done');
}

function updateStatus(text) {
  document.getElementById('progress-status').textContent = text;
}

function onPipelineStep(msg) {
  const map = {
    'icp_parsed':    { done: 'step-parse',    next: 'step-discover', msg: 'Discovering leads via Bright Data…' },
    'leads_found':   { done: 'step-discover',  next: 'step-intent',   msg: 'Monitoring intent signals…' },
    'intent_done':   { done: 'step-intent',    next: 'step-context',  msg: 'Fetching personalization context…' },
    'context_done':  { done: 'step-context',   next: 'step-email',    msg: 'Generating email sequences with AI/ML API…' },
  };
  const step = map[msg.step];
  if (step) {
    doneStep(step.done);
    activateStep(step.next);
    updateStatus(step.msg);
  }
}

function onPipelineDone(msg) {
  STEPS.forEach(doneStep);
  const demoTag = msg.demo ? ' [Demo Data]' : '';
  updateStatus(`✓ Complete${demoTag} — ${msg.leads} leads, ${msg.emails} emails, ${msg.signals} signals`);
  const btn = document.getElementById('run-pipeline-btn') || document.getElementById('run-btn');
  if (btn) { btn.disabled = false; btn.innerHTML = '<span>⚡</span> Run Pipeline'; }
  loadLeads();
  loadSignals();
  updateStats(msg);
}

// ── Data loading ──────────────────────────────────────────────────────────────

async function loadLeads() {
  try {
    const resp  = await fetch('/api/sales/leads');
    const data  = await resp.json();
    allLeads    = data.leads || [];
    renderLeads();
    updateStatsFromLeads();
  } catch (e) { /* silent */ }
}

async function loadSignals() {
  try {
    const resp = await fetch('/api/sales/signals');
    const data = await resp.json();
    const list = document.getElementById('signals-list');
    list.innerHTML = '';
    (data.signals || []).slice(0, 20).forEach(s => {
      list.appendChild(buildSignalCard(s));
    });
  } catch (e) { /* silent */ }
}

// ── Lead table ────────────────────────────────────────────────────────────────

function onNewLead(lead) {
  // Avoid duplicates
  if (!allLeads.find(l => l.id === lead.id)) {
    allLeads.push(lead);
  }
  renderLeads();
  updateStatsFromLeads();
}

function renderLeads() {
  const tbody  = document.getElementById('leads-tbody');
  if (!tbody) return;   // not in DOM yet (view not visible)
  const filterEl = document.getElementById('lead-filter');
  const filter = (filterEl ? filterEl.value : '').toLowerCase();

  let rows = allLeads.filter(l =>
    !filter ||
    (l.company_name || '').toLowerCase().includes(filter) ||
    (l.domain || '').toLowerCase().includes(filter) ||
    (l.industry || '').toLowerCase().includes(filter)
  );

  // Sort
  rows.sort((a, b) => {
    let av = a[sortKey] ?? 0;
    let bv = b[sortKey] ?? 0;
    if (typeof av === 'string') av = av.toLowerCase();
    if (typeof bv === 'string') bv = bv.toLowerCase();
    return av < bv ? -sortDir : av > bv ? sortDir : 0;
  });

  if (rows.length === 0) {
    tbody.innerHTML = `<tr class="empty-row"><td colspan="8">
      <div class="empty-state">
        <div class="empty-icon">${allLeads.length ? '🔍' : '🎯'}</div>
        <div class="empty-text">${allLeads.length ? 'No leads match filter' : 'Run the pipeline to discover leads'}</div>
      </div></td></tr>`;
    return;
  }

  tbody.innerHTML = rows.map(lead => `
    <tr onclick="openDrawer('${lead.id}')">
      <td>${scoreTag(lead.score)}</td>
      <td>
        <div class="company-cell">
          <span class="company-name">${esc(lead.company_name || '–')}</span>
          <span class="company-domain">${esc(lead.domain || '')}</span>
        </div>
      </td>
      <td>${lead.funding_amount ? `<span class="tag tag-stage">${esc(lead.funding_amount)}</span>` : '–'}</td>
      <td>${lead.funding_stage ? `<span class="tag tag-stage">${esc(lead.funding_stage.replace('_',' '))}</span>` : '–'}</td>
      <td>${lead.geo ? `<span class="tag tag-geo">${esc(lead.geo)}</span>` : '–'}</td>
      <td>${signalTags(lead.hiring_signals || [])}</td>
      <td>${statusBadge(lead.status || 'new')}</td>
      <td><button class="view-btn" onclick="event.stopPropagation();openDrawer('${lead.id}')">View Emails →</button></td>
    </tr>
  `).join('');
}

function scoreTag(score) {
  score = parseFloat(score) || 0;
  const cls = score >= 70 ? 'score-high' : score >= 50 ? 'score-medium' : 'score-low';
  return `<span class="score-badge ${cls}">${score.toFixed(0)}</span>`;
}

function signalTags(signals) {
  if (!signals || !signals.length) return '–';
  return signals.slice(0, 2).map(s => `<span class="tag tag-signal">${esc(s)}</span>`).join(' ');
}

function statusBadge(status) {
  const labels = { new: '🔵 New', emailed: '📧 Emailed', replied: '💬 Replied', enriched: '✓ Enriched' };
  const cls    = { new: 'status-new', emailed: 'status-emailed', replied: 'status-replied' };
  return `<span class="status-badge ${cls[status] || 'status-new'}">${labels[status] || status}</span>`;
}

function filterLeads() { renderLeads(); }

function sortTable(key) {
  if (sortKey === key) sortDir *= -1;
  else { sortKey = key; sortDir = -1; }
  renderLeads();
}

// ── Signal cards ──────────────────────────────────────────────────────────────

function onNewSignal(signal) {
  const list = document.getElementById('signals-list');
  if (!list) return;
  const empty = list.querySelector('.empty-state-small');
  if (empty) empty.remove();
  list.prepend(buildSignalCard(signal));
  const statEl = document.getElementById('stat-signals');
  statEl.textContent = parseInt(statEl.textContent || '0') + 1;
}

function buildSignalCard(s) {
  const typeLabels = {
    switching_intent:  '🔴 Switching Intent',
    active_evaluation: '🟡 Evaluating',
    budget_available:  '🟢 Budget Available',
    pain_point:        '🟣 Pain Point',
  };
  const div = document.createElement('div');
  div.className = `signal-card ${s.intent_type}`;
  div.innerHTML = `
    <div class="signal-header">
      <span class="signal-type">${typeLabels[s.intent_type] || s.intent_type}</span>
      <span class="signal-source">${s.source}</span>
    </div>
    <div class="signal-quote">"${esc((s.quote || '').substring(0, 160))}…"</div>
    <div class="signal-meta">
      <span>🏢 ${esc(s.company_mentioned || '–')}</span>
      <span class="signal-conf">⚡ ${parseFloat(s.confidence || 0).toFixed(0)}%</span>
    </div>
  `;
  if (s.source_url) div.onclick = () => window.open(s.source_url, '_blank');
  return div;
}

// ── Email Drawer ──────────────────────────────────────────────────────────────

async function openDrawer(leadId) {
  currentLeadId = leadId;
  const lead = allLeads.find(l => l.id === leadId) || {};
  const contact = (lead.contacts || [])[0] || {};

  // ── Header: company + contact ──────────────────────────────────────────
  document.getElementById('drawer-company').textContent = lead.company_name || 'Lead';

  const contactEl = document.getElementById('drawer-contact');
  let contactParts = [];
  if (contact.name)  contactParts.push(contact.name);
  if (contact.title) contactParts.push(contact.title);
  contactEl.textContent = contactParts.join(' · ') || lead.domain || '';

  // ── Contact meta row (email + LinkedIn) ────────────────────────────────
  let metaEl = document.getElementById('drawer-contact-meta');
  if (!metaEl) {
    metaEl = document.createElement('div');
    metaEl.id = 'drawer-contact-meta';
    metaEl.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;margin-top:6px;';
    contactEl.parentNode.insertBefore(metaEl, contactEl.nextSibling);
  }

  // ─ Field name fix: Contact model uses .linkedin (not .linkedin_url)
  const liUrl   = contact.linkedin || contact.linkedin_url || lead.linkedin_url || '';
  const email   = contact.email || '';
  const domain  = lead.domain || '';
  const website = domain ? `https://${domain}` : '';

  metaEl.innerHTML = [
    liUrl   ? `<a href="${esc(liUrl)}" target="_blank" class="drawer-pill pill-linkedin">💼 LinkedIn ↗</a>` : '',
    email   ? `<span class="drawer-pill pill-email">✉ ${esc(email)}</span>` : '',
    website ? `<a href="${esc(website)}" target="_blank" class="drawer-pill pill-web">🌐 Website ↗</a>` : '',
  ].filter(Boolean).join('');

  // ── Email input + guesses section ──────────────────────────────────────
  let inputSection = document.getElementById('drawer-email-input-section');
  if (!inputSection) {
    inputSection = document.createElement('div');
    inputSection.id = 'drawer-email-input-section';
    inputSection.style.cssText = 'padding:12px 24px;border-bottom:1px solid #1e2d42;background:#080c14;';
    const tabs = document.getElementById('email-tabs');
    tabs.parentNode.insertBefore(inputSection, tabs);
  }

  // Guess email patterns from contact name + domain
  const guesses = _guessEmails(contact.name, domain);

  inputSection.innerHTML = `
    <div style="font-size:10px;color:#64748b;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">
      📬 Send To
    </div>
    <div style="display:flex;gap:8px;margin-bottom:${guesses.length ? '10px' : '0'};">
      <input id="drawer-manual-email-input" type="email"
        placeholder="Enter recipient email…"
        value="${esc(email)}"
        oninput="_onManualEmailInput(this.value)"
        style="flex:1;background:#0d1420;border:1px solid #1e2d42;border-radius:8px;padding:7px 12px;color:#e2e8f0;font-size:13px;font-family:inherit;outline:none;transition:border 0.2s;"
        onfocus="this.style.borderColor='#3b82f6'"
        onblur="this.style.borderColor='#1e2d42'"/>
      <button onclick="openMailto()" style="padding:7px 14px;border-radius:8px;background:#3b82f615;border:1px solid #3b82f640;color:#60a5fa;font-size:12px;cursor:pointer;white-space:nowrap;font-family:inherit;">
        ✉ Open in Mail
      </button>
    </div>
    ${guesses.length ? `
    <div style="font-size:10px;color:#64748b;margin-bottom:6px;">
      💡 Likely email patterns — click to use:
    </div>
    <div style="display:flex;gap:6px;flex-wrap:wrap;">
      ${guesses.map(g => `
        <button onclick="_useEmailGuess('${g}')"
          style="padding:3px 10px;border-radius:20px;font-size:11px;background:#3b82f610;border:1px solid #3b82f630;color:#93c5fd;cursor:pointer;font-family:monospace;transition:all 0.15s;"
          onmouseover="this.style.background='#3b82f625'"
          onmouseout="this.style.background='#3b82f610'">
          ${g}
        </button>`).join('')}
    </div>` : ''}
    ${!liUrl && !email ? `
    <div style="margin-top:10px;padding:10px;background:#0d1f38;border-radius:8px;border:1px solid #1e3a5f;font-size:12px;color:#94a3b8;">
      🔍 No contact found yet.
      ${contact.name ? `Search LinkedIn for <strong style="color:#e2e8f0;">${esc(contact.name)}</strong> at ${esc(lead.company_name || domain)}` : `Search LinkedIn for decision makers at <strong style="color:#e2e8f0;">${esc(lead.company_name || domain)}</strong>`}
      — <a href="https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent((contact.name || '') + ' ' + (lead.company_name || ''))}" target="_blank" style="color:#60a5fa;">Search LinkedIn ↗</a>
    </div>` : ''}
  `;

  _onManualEmailInput(email);

  document.getElementById('email-viewer').innerHTML = '<div class="email-loading">Loading emails…</div>';
  document.getElementById('email-tabs').innerHTML = '';
  document.getElementById('email-drawer').classList.add('open');

  try {
    const resp = await fetch(`/api/sales/emails/${leadId}`);
    const data = await resp.json();
    currentEmails = data.emails || [];
    renderEmailTabs();
    showEmail(0);
  } catch (e) {
    document.getElementById('email-viewer').innerHTML = '<div class="email-loading">Error loading emails</div>';
  }
}

// Generate likely email patterns from a contact's full name + domain
function _guessEmails(name, domain) {
  if (!name || !domain) return [];
  const parts = name.trim().toLowerCase().replace(/[^a-z\s]/g, '').split(/\s+/);
  if (parts.length < 2) return [`${parts[0]}@${domain}`];
  const [first, ...rest] = parts;
  const last = rest[rest.length - 1];
  const guesses = [
    `${first}@${domain}`,
    `${first}.${last}@${domain}`,
    `${first}${last}@${domain}`,
    `${first[0]}${last}@${domain}`,
    `${first[0]}.${last}@${domain}`,
  ];
  return [...new Set(guesses)]; // dedupe
}

function _useEmailGuess(email) {
  const input = document.getElementById('drawer-manual-email-input');
  if (input) {
    input.value = email;
    input.style.borderColor = '#3b82f6';
    _onManualEmailInput(email);
    // Briefly flash green to confirm selection
    input.style.borderColor = '#22c55e';
    setTimeout(() => { input.style.borderColor = '#3b82f6'; }, 600);
  }
}

function _onManualEmailInput(val) {
  const sendBtn = document.getElementById('send-btn');
  if (!sendBtn) return;
  if (val && val.includes('@')) {
    sendBtn.textContent = '📨 Send via Resend';
    sendBtn.disabled = false;
    sendBtn.style.opacity = '1';
  } else if (!val) {
    const lead = allLeads.find(l => l.id === currentLeadId) || {};
    const email = (lead.contacts || [])[0]?.email || '';
    if (!email) {
      sendBtn.textContent = '✉ Add email to send';
      sendBtn.disabled = true;
      sendBtn.style.opacity = '0.5';
    }
  }
}

function openMailto() {
  const email = currentEmails[currentTab];
  const manualEmail = document.getElementById('drawer-manual-email-input')?.value.trim();
  const to = manualEmail || '';
  if (!email) return;
  const subject = encodeURIComponent(email.subject);
  const body    = encodeURIComponent(email.body);
  window.open(`mailto:${to}?subject=${subject}&body=${body}`, '_blank');
}


function closeDrawer() {
  document.getElementById('email-drawer').classList.remove('open');
  currentLeadId = null;
}

function renderEmailTabs() {
  const tabsEl = document.getElementById('email-tabs');
  const labels = ['Step 1 — Initial', 'Step 2 — Day 3', 'Step 3 — Day 7', 'Step 4 — Day 14'];
  tabsEl.innerHTML = currentEmails.map((e, i) => `
    <button class="email-tab ${i === 0 ? 'active' : ''}" onclick="showEmail(${i})" id="tab-${i}">
      ${labels[i] || `Step ${e.sequence_step}`}
    </button>
  `).join('');
}

function showEmail(idx) {
  currentTab = idx;
  document.querySelectorAll('.email-tab').forEach((t, i) => {
    t.classList.toggle('active', i === idx);
  });
  const email = currentEmails[idx];
  if (!email) return;

  const viewer = document.getElementById('email-viewer');
  viewer.innerHTML = `
    <div class="email-subject">📧 ${esc(email.subject)}</div>
    <div class="email-body">${esc(email.body)}</div>
    ${email.linkedin_dm ? `
      <div class="linkedin-dm-section">
        <div class="linkedin-dm-label">💼 LinkedIn DM</div>
        <div class="linkedin-dm-body">${esc(email.linkedin_dm)}</div>
      </div>
    ` : ''}
  `;

  // Show/hide DM copy button
  document.getElementById('copy-dm-btn').style.display = email.linkedin_dm ? '' : 'none';
}

function copyEmail() {
  const email = currentEmails[currentTab];
  if (!email) return;
  navigator.clipboard.writeText(`Subject: ${email.subject}\n\n${email.body}`);
  flashBtn('copy-btn', '✓ Copied!');
}

function copyDM() {
  const email = currentEmails[currentTab];
  if (!email || !email.linkedin_dm) return;
  navigator.clipboard.writeText(email.linkedin_dm);
  flashBtn('copy-dm-btn', '✓ Copied!');
}

async function sendEmail() {
  const email = currentEmails[0]; // Always send Step 1
  if (!email) return;

  // Use manual email input if provided, else fall back to contact email
  const manualEmail = document.getElementById('drawer-manual-email-input')?.value.trim();
  const lead = allLeads.find(l => l.id === currentLeadId) || {};
  const toEmail = manualEmail || (lead.contacts || [])[0]?.email || '';

  if (!toEmail || !toEmail.includes('@')) {
    openMailto();
    return;
  }

  const btn = document.getElementById('send-btn');
  btn.textContent = '📨 Sending…';
  btn.disabled = true;

  try {
    const resp = await fetch('/api/sales/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lead_id: currentLeadId, email_id: email.id, to_email: toEmail }),
    });
    const data = await resp.json();
    if (data.success) {
      btn.textContent = '✓ Sent!';
      btn.style.background = '#22c55e20';
      // Mark lead as emailed in table
      const l = allLeads.find(x => x.id === currentLeadId);
      if (l) { l.status = 'emailed'; renderLeads(); }
    } else {
      throw new Error(data.error || 'Send failed');
    }
  } catch (err) {
    btn.textContent = `✗ ${err.message}`;
    btn.disabled = false;
  }
}

function flashBtn(id, label) {
  const btn = document.getElementById(id);
  const orig = btn.textContent;
  btn.textContent = label;
  setTimeout(() => btn.textContent = orig, 1500);
}

// ── Stats ─────────────────────────────────────────────────────────────────────

function updateStatsFromLeads() {
  const leads    = allLeads;
  const leadsEl  = document.getElementById('stat-leads');
  const scoreEl  = document.getElementById('stat-avg-score');
  if (leadsEl) leadsEl.textContent = leads.length;
  if (scoreEl && leads.length) {
    const avg = leads.reduce((s, l) => s + (parseFloat(l.score) || 0), 0) / leads.length;
    scoreEl.textContent = avg.toFixed(0);
  }
}

function updateStats(msg) {
  const leadsEl   = document.getElementById('stat-leads');
  const emailsEl  = document.getElementById('stat-emails');
  const signalsEl = document.getElementById('stat-signals');
  if (msg.leads   && leadsEl)   leadsEl.textContent   = msg.leads;
  if (msg.emails  && emailsEl)  emailsEl.textContent  = msg.emails;
  if (msg.signals && signalsEl) signalsEl.textContent = msg.signals;
}

// ── Export ────────────────────────────────────────────────────────────────────

function exportLeads() {
  const rows = [
    ['Brand', 'Run Date', 'Company', 'Domain', 'Score', 'Stage', 'Funding', 'Geo', 'Signals', 'Status'],
    ...allLeads.map(l => [
      _currentBrand,
      new Date().toISOString().slice(0,10),
      l.company_name, l.domain, l.score,
      l.funding_stage, l.funding_amount, l.geo,
      (l.hiring_signals || []).join('; '), l.status,
    ])
  ];
  const csv = rows.map(r => r.map(c => `"${(c ?? '').toString().replace(/"/g, '""')}"`).join(',')).join('\n');
  const a = document.createElement('a');
  a.href = `data:text/csv;charset=utf-8,${encodeURIComponent(csv)}`;
  a.download = `${(_currentBrand || 'alphasignal').toLowerCase().replace(/\s+/g,'-')}-leads-${new Date().toISOString().slice(0,10)}.csv`;
  a.click();
}

// ── Utils ─────────────────────────────────────────────────────────────────────

function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Init ──────────────────────────────────────────────────────────────────────
// Only auto-connect WebSocket on the standalone /sales page.
// On the unified dashboard (/), unified.js's connectSalesWS() handles it.

let _currentBrand = '';
let _currentBrandDesc = '';

async function _loadProfileIntoUI() {
  try {
    const resp = await fetch('/api/profile');
    const data = await resp.json();
    if (data.needs_setup) return;

    const p = data.profile || {};
    _currentBrand     = p.company_name || '';
    _currentBrandDesc = p.product_description || '';

    // 1. Auto-fill ICP from profile if field is empty
    const icpEl = document.getElementById('icp-input');
    if (icpEl && (!icpEl.value || icpEl.value.trim() === '')) {
      icpEl.value = p.icp_description || '';
    }

    // 2. Auto-fill competitor from profile's first known competitor
    const compEl = document.getElementById('competitor-input');
    if (compEl && (!compEl.value || compEl.value.trim() === '')) {
      const comp = (p.known_competitors || [])[0] || '';
      if (comp) compEl.value = comp;
    }

    // 3. Show brand context banner
    _renderBrandBanner(p);

  } catch(e) { /* silent */ }
}

function _renderBrandBanner(p) {
  const wrap = document.getElementById('sales-brand-banner');
  if (!wrap) return;

  const name = p.company_name || '';
  const desc = p.product_description || '';
  const site = p.website || '';
  const icp  = p.icp_description || '';
  const comp = (p.known_competitors || []).slice(0, 4);

  if (!name) { wrap.style.display = 'none'; return; }

  // Update the ICP section title
  const lbl = document.getElementById('icp-brand-label');
  if (lbl) lbl.textContent = name;

  wrap.style.display = 'flex';
  wrap.innerHTML = `
    <div class="sbb-left">
      <div class="sbb-brand">
        <span class="sbb-dot"></span>
        <span class="sbb-name">${esc(name)}</span>
        ${site ? `<a class="sbb-site" href="${esc(site)}" target="_blank">↗ ${esc(site.replace(/https?:\/\//, ''))}</a>` : ''}
      </div>
      <div class="sbb-desc">${esc(desc)}</div>
    </div>
    <div class="sbb-right">
      <div class="sbb-meta-row">
        <span class="sbb-label">Finding buyers for:</span>
        <span class="sbb-icp">${esc(icp.slice(0, 100))}${icp.length > 100 ? '…' : ''}</span>
      </div>
      ${comp.length ? `<div class="sbb-meta-row">
        <span class="sbb-label">Monitoring competitors:</span>
        ${comp.map(c => `<span class="sbb-comp-pill">${esc(c)}</span>`).join('')}
      </div>` : ''}
    </div>
    <button class="sbb-edit" onclick="editProfile()" title="Edit brand profile">✏️ Edit</button>
  `;
}

document.addEventListener('DOMContentLoaded', () => {
  const isStandalone = window.location.pathname === '/sales';
  if (isStandalone) {
    _salesConnectWS();
  }
  // Always pre-load existing leads/signals from DB
  loadLeads();
  loadSignals();
  // NEW: auto-populate ICP + show brand banner from saved profile
  _loadProfileIntoUI();
});
