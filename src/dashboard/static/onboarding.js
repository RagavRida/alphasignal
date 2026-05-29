/* ══════════════════════════════════════════════════════════════════
   AlphaSignal — Onboarding v2: Brand-name only, AI does the rest
══════════════════════════════════════════════════════════════════ */

let _analyzedProfile = null;   // stores AI result before save
let _competitors     = [];     // editable competitor list

// ── Overlay control ───────────────────────────────────────────────

function showOnboarding() {
  document.getElementById('onboarding-overlay').classList.add('visible');
}
function hideOnboarding() {
  document.getElementById('onboarding-overlay').classList.remove('visible');
}
function editProfile() {
  obBackToInput();
  fetch('/api/profile').then(r=>r.json()).then(d=>{
    const p = d.profile || {};
    if (p.company_name) document.getElementById('ob-brand-input').value = p.company_name;
    if (p.website)      document.getElementById('ob-website-input').value = p.website;
  }).catch(()=>{});
  showOnboarding();
}

// ── State transitions ─────────────────────────────────────────────

function obBackToInput() {
  document.getElementById('ob-state-input').style.display  = '';
  document.getElementById('ob-state-review').style.display = 'none';
  document.getElementById('ob-analyzing').style.display    = 'none';
  document.getElementById('ob-analyze-btn').disabled       = false;
  document.getElementById('ob-analyze-btn').innerHTML      = '<span class="ob-analyze-icon">🔍</span><span>Analyze with AI</span>';
  // reset analyzing steps
  ['oas-serp','oas-claude','oas-done'].forEach(id => {
    const el = document.getElementById(id);
    if (el) { el.classList.remove('active','done'); }
  });
}

function tryBrand(name) {
  document.getElementById('ob-brand-input').value = name;
  analyzeBrand();
}

// ── Core: Analyze brand name ──────────────────────────────────────

async function analyzeBrand() {
  const brand = document.getElementById('ob-brand-input').value.trim();
  if (!brand) {
    document.getElementById('ob-brand-input').style.borderColor = '#ef4444';
    document.getElementById('ob-brand-input').placeholder = 'Please enter a brand name';
    setTimeout(()=>{
      document.getElementById('ob-brand-input').style.borderColor = '';
      document.getElementById('ob-brand-input').placeholder = 'Type your brand name… e.g. HubSpot, Stripe, Notion';
    }, 1800);
    return;
  }

  // Show analyzing state
  const website = document.getElementById('ob-website-input')?.value.trim() || '';
  const btn = document.getElementById('ob-analyze-btn');
  btn.disabled = true;
  btn.innerHTML = '<div class="ob-btn-spinner"></div><span>Analyzing…</span>';
  document.getElementById('ob-analyzing').style.display = 'block';

  // Animate steps with delays
  await _animateStep('oas-serp',   300);
  await _animateStep('oas-claude', 4000);

  try {
    const resp = await fetch('/api/profile/analyze', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ brand_name: brand, website_url: website }),
    });
    const data = await resp.json();
    if (!data.success) throw new Error(data.error || 'Analysis failed');

    _analyzedProfile = data.profile;
    const snippetCount = data.serp_snippets ?? 0;

    await _animateStep('oas-done', 200);
    await _sleep(500);

    // Switch to review state
    _showReview(_analyzedProfile, snippetCount);

  } catch (err) {
    document.getElementById('ob-analyzing').style.display = 'none';
    btn.disabled = false;
    btn.innerHTML = '<span class="ob-analyze-icon">🔍</span><span>Analyze with AI</span>';

    const hint = document.getElementById('ob-brand-input');
    hint.style.borderColor = '#ef4444';
    hint.style.boxShadow   = '0 0 0 3px #ef444430';
    document.querySelector('#ob-brand-hint').textContent = `✗ ${err.message} — try again`;
    document.querySelector('#ob-brand-hint').style.color = '#ef4444';
    setTimeout(()=>{
      hint.style.borderColor = '';
      hint.style.boxShadow   = '';
      document.querySelector('#ob-brand-hint').textContent = 'Website is scraped first for accurate data — then Bright Data SERP — then AI/ML API knowledge';
      document.querySelector('#ob-brand-hint').style.color = '';
      btn.disabled = false;
      btn.innerHTML = '<span class="ob-analyze-icon">🔍</span><span>Analyze with AI</span>';
    }, 3000);
  }
}

async function _animateStep(id, delay) {
  await _sleep(delay);
  const el = document.getElementById(id);
  if (el) {
    el.classList.add('active');
    setTimeout(() => el.classList.replace('active','done'), 1200);
  }
}
function _sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ── Populate review panel ─────────────────────────────────────────

function _showReview(profile, serpSnippets) {
  document.getElementById('ob-state-input').style.display  = 'none';
  document.getElementById('ob-state-review').style.display = '';

  // ── Low-confidence warning if SERP had no data ───────────────────
  const reviewCards = document.querySelector('.ob-review-cards');
  const existingWarn = document.getElementById('ob-review-warn');
  if (existingWarn) existingWarn.remove();

  if (serpSnippets === 0) {
    const warn = document.createElement('div');
    warn.id        = 'ob-review-warn';
    warn.className = 'ob-review-warning';
    warn.innerHTML = `
      <span class="ob-review-warning-icon">⚠️</span>
      <span><strong>AI used training knowledge only</strong> — Bright Data SERP found no results for this brand.
      The fields below may be inaccurate. <strong>Please review and correct everything before saving.</strong></span>
    `;
    reviewCards.insertBefore(warn, reviewCards.firstChild);
  }

  // Fill fields
  document.getElementById('ob-review-brand').textContent = profile.company_name || '';
  document.getElementById('rv-product').value   = profile.product_description || '';
  document.getElementById('rv-industry').value  = profile.industry || '';
  document.getElementById('rv-website').value   = profile.website  || '';
  document.getElementById('rv-icp').value       = profile.icp_description || '';

  // Competitors
  _competitors = [...(profile.known_competitors || [])];
  _renderCompetitors();

  // Watch list preview
  const wlEl = document.getElementById('rv-watchlist');
  const wl   = profile.watchlist_companies || [];
  if (wl.length === 0) {
    wlEl.innerHTML = '<div class="ob-wl-empty">Generating after save…</div>';
  } else {
    const cats = { direct_competitor: '⚔️', icp_prospect: '🎯', market_signal: '📊' };
    wlEl.innerHTML = wl.map(c => `
      <div class="ob-wl-item">
        <span class="ob-wl-icon">${cats[c.category] || '📌'}</span>
        <div class="ob-wl-info">
          <span class="ob-wl-name">${_esc(c.name)}</span>
          <span class="ob-wl-reason">${_esc(c.reason || c.category || '')}</span>
        </div>
        ${c.ticker ? `<span class="ob-wl-ticker">${_esc(c.ticker)}</span>` : ''}
      </div>
    `).join('');
  }
}

// ── Competitor tag management ─────────────────────────────────────

function _renderCompetitors() {
  const el = document.getElementById('rv-competitors');
  el.innerHTML = _competitors.map((c, i) => `
    <span class="ob-comp-tag">
      ${_esc(c)}
      <button onclick="_removeCompetitor(${i})" class="ob-comp-remove">×</button>
    </span>
  `).join('');
}

function addCompetitor(val) {
  val = (val || '').trim();
  if (val && !_competitors.includes(val)) {
    _competitors.push(val);
    _renderCompetitors();
  }
  document.getElementById('rv-comp-add').value = '';
}

function _removeCompetitor(idx) {
  _competitors.splice(idx, 1);
  _renderCompetitors();
}

// ── Save ──────────────────────────────────────────────────────────

async function saveProfile() {
  const profile = _analyzedProfile || {};

  const payload = {
    company_name:        profile.company_name || document.getElementById('ob-brand-input').value.trim(),
    product_description: document.getElementById('rv-product').value.trim()  || profile.product_description || '',
    industry:            document.getElementById('rv-industry').value.trim() || profile.industry || '',
    website:             document.getElementById('rv-website').value.trim()  || profile.website  || '',
    icp_description:     document.getElementById('rv-icp').value.trim()      || profile.icp_description || '',
    known_competitors:   _competitors,
    sender_name:         document.getElementById('rv-sender-name').value.trim(),
    sender_title:        document.getElementById('rv-sender-title').value.trim(),
    // Pass the already-generated watch list so server doesn't need to re-generate
    watchlist_companies: profile.watchlist_companies || [],
  };

  if (!payload.company_name) return;

  document.getElementById('ob-save-btn').style.display  = 'none';
  document.getElementById('ob-saving').style.display    = 'flex';

  try {
    const resp = await fetch('/api/profile', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!data.success) throw new Error(data.error || 'Save failed');

    // Pre-fill dashboard
    const icpInput = document.getElementById('icp-input');
    if (icpInput && payload.icp_description) icpInput.value = payload.icp_description;
    const compInput = document.getElementById('competitor-input');
    if (compInput && _competitors.length) compInput.value = _competitors[0];

    // Update top bar
    const tb = document.getElementById('top-bar-title');
    if (tb) tb.textContent = `📈 ${payload.company_name} — Intelligence Platform`;

    hideOnboarding();

    // Reload sidebar watch list after a moment
    setTimeout(() => { if (typeof loadCompanies === 'function') loadCompanies(); }, 2000);

  } catch (err) {
    document.getElementById('ob-saving').style.display   = 'none';
    document.getElementById('ob-save-btn').style.display = 'flex';
    document.getElementById('ob-save-btn').textContent   = `✗ ${err.message}`;
    setTimeout(() => {
      document.getElementById('ob-save-btn').textContent = '⚡ Set Up AlphaSignal';
    }, 3000);
  }
}

// ── Init ──────────────────────────────────────────────────────────

function _esc(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

document.addEventListener('DOMContentLoaded', () => {
  fetch('/api/profile')
    .then(r => r.json())
    .then(data => {
      if (data.needs_setup) {
        setTimeout(showOnboarding, 500);
      } else {
        const p = data.profile || {};
        // Pre-fill ICP from saved profile
        const icpInput = document.getElementById('icp-input');
        if (icpInput && p.icp_description) icpInput.value = p.icp_description;
        const compInput = document.getElementById('competitor-input');
        if (compInput && p.known_competitors?.length) compInput.value = p.known_competitors[0];
        if (p.company_name) {
          const tb = document.getElementById('top-bar-title');
          if (tb) tb.textContent = `📈 ${p.company_name} — Intelligence Platform`;
        }
      }
    })
    .catch(() => {});
});
