# AlphaSignal

**Autonomous market intelligence and B2B sales engine.** AlphaSignal watches competitors, detects buying signals, and generates personalized outreach — continuously, without human input.

[![Live Demo](https://img.shields.io/badge/Live%20Demo-alphasignal--86xn.onrender.com-brightgreen?style=flat-square)](https://alphasignal-86xn.onrender.com)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue?style=flat-square)](https://python.org)
[![Bright Data](https://img.shields.io/badge/Bright%20Data-5%20products-orange?style=flat-square)](https://brightdata.com)

---

## The Problem It Solves

Sales teams spend 60–80% of their time on research that goes stale within days. A company that raised funding yesterday, posted three SDR roles this morning, and has frustrated customers posting on G2 right now is a near-perfect sales target — but by the time a human connects those dots, the window is gone.

AlphaSignal connects those dots in real time.

---

## How It Actually Works

There are three layers of original logic between a raw web page and a structured sales alert:

### Layer 1 — Signal Detection (7 parallel detectors)

Every hour, AlphaSignal runs seven independent detectors against each company in the watch list. Each detector uses a different Bright Data product because each target site has different protection mechanisms:

| Detector | Data Source | What It Reads | Bright Data Product |
|---|---|---|---|
| `HiringVelocityDetector` | LinkedIn Jobs | Open roles, hiring rate, layoff patterns | Scraping Browser (JS-rendered) |
| `PricingChangeDetector` | Pricing pages | Price changes vs. last cached baseline | Web Scraper API |
| `FundingDetector` | TechCrunch, Crunchbase | Round size, stage, lead investors | SERP API |
| `NewsDetector` | Google News | Acquisitions, launches, exec departures | SERP API |
| `FinancialHealthDetector` | SEC EDGAR | 10-Q filings, cash burn (public companies) | Web Unlocker (CAPTCHA) |
| `SupplierRiskDetector` | Trade databases, forums | Supply chain disruption signals | SERP API + Web Unlocker |
| `WebTrafficDetector` | SimilarWeb, competitor blogs | Traffic growth/decline trends | Web Scraper API |

Each detector returns a normalized signal object: `{type, company, value, delta, confidence, raw_evidence}`.

### Layer 2 — Signal Correlation (5 thesis rules)

Raw signals are useless in isolation. A company posting 20 jobs could be growing or backfilling after mass layoffs. AlphaSignal's `signal_correlator.py` runs five cross-signal thesis rules:

```
growth_thesis        = funding_detected AND hiring_velocity > +50% AND news_positive
competitive_threat   = competitor_pricing_dropped AND their_hiring_accelerated
financial_distress   = sec_filing_negative AND hiring_freeze AND traffic_declining
supplier_risk        = supply_disruption AND pricing_change_imminent
market_disruption    = news_score < -0.6 AND traffic_delta < -30%
```

A single matched thesis fires an alert. Two matched theses in the same cycle trigger a cross-signal alert with elevated confidence.

### Layer 3 — Alert Generation (Claude)

Only confirmed thesis matches reach Claude. The prompt includes: the matched thesis pattern, all supporting signal values, historical context, and the specific evidence URLs. Claude's job is not to decide whether something is significant — the correlation engine already did that. Claude writes the investment narrative in the style of a hedge fund research memo: what happened, why it matters, what the likely move is, and what to watch next.

This separation between detection logic and narrative generation is why alerts don't hallucinate. If the data doesn't trigger a thesis, no alert is generated.

---

## Engine 1 — Market Intelligence Monitor

Watches a configurable list of companies continuously. Alerts appear in the live feed as they're generated.

**What a real alert contains:**
- Which thesis was triggered and which signals fired it
- Confidence score (weighted by signal count and evidence quality)
- Investment direction: LONG / SHORT / WATCH / AVOID
- Specific evidence: job posting URLs, pricing page diffs, filing sections
- Recommended action and follow-up signal to watch

**Demo alert example (Growth Thesis — Coda):**
```
Coda hired 23 engineers in 30 days (+180% velocity). TechCrunch confirmed $80M Series D.
G2 reviews show 12 mentions of "switching from Notion" in the last 14 days.
Thesis: Aggressive expansion entering Notion's core market.
Direction: WATCH. Signal to confirm: pricing page change within 60 days.
Confidence: 87%
```

---

## Engine 2 — B2B Sales Pipeline

On-demand discovery and outreach for any ICP description.

**Step-by-step flow:**

```
1. ICP Parsing
   Input: "B2B SaaS, Series A, hiring SDRs, India/US"
   Output: 8 structured Google search queries targeting that exact profile

2. Lead Discovery
   Each query runs through Bright Data SERP API
   Results are de-duplicated, company pages are scraped
   Claude scores each company 0–100 against the ICP

3. Intent Monitoring
   For each scored lead (score ≥ 60):
   - G2 reviews scraped via Web Unlocker → buying intent signals
   - Reddit/HN mentions scraped → frustration signals with existing tools
   - Glassdoor job postings → budget/team signals

4. Context Fetching
   Company blog, recent press releases, job descriptions scraped via MCP Server
   → feeds into email personalization

5. Outreach Generation
   Claude writes a 4-step sequence using:
   - Your exact brand name, product, use case
   - Lead's specific signals ("saw you're hiring 3 SDRs", "noticed your G2 reviews mention X")
   - Competitor positioning if a competitor was specified
   Each lead also gets a LinkedIn DM variant, subject line, and send timing guidance
```

**What makes the outreach non-generic:** every email references a specific signal pulled from that company's live data. The system does not generate emails from a template — it generates emails from evidence.

---

## Cross-Signal Engine

When Engine 1 fires a funded companies alert, Engine 2 doesn't wait to be asked. It automatically:

1. Extracts the funded company's profile
2. Searches for 10 companies with similar characteristics (same stage, same sector, same hiring patterns)
3. Runs intent monitoring on all of them
4. Generates outreach for anyone showing buying signals

The reasoning: a company that just raised is in buying mode. Similar companies in the same stage are statistically likely to be in the same cycle. This is the logic that makes AlphaSignal useful as an outbound tool rather than just a research dashboard.

---

## Why Each Bright Data Product

This isn't "use whichever API is cheapest." Each product is chosen because other approaches fail on that specific target:

**MCP Server** — used for company blogs, LinkedIn profile pages, and Crunchbase. These are high-value structured data sources where the MCP server's `scrape_as_markdown` tool returns cleaner text than raw HTML scraping, directly usable as Claude context.

**SERP API** — used for discovery queries, news, and intent signals. The key property here is scale: lead discovery runs 8 queries per pipeline execution. Raw Google scraping at this frequency would get rate-limited within minutes. SERP API provides stable, structured results.

**Web Scraper API** — used specifically for pricing pages. Pricing pages are public but frequently updated. The Scraper API lets us cache a baseline and diff it against fresh scrapes — which is how `PricingChangeDetector` works. A 10% price drop on a competitor's enterprise tier is a high-confidence signal.

**Scraping Browser** — used for LinkedIn job pages. LinkedIn's job listings are JavaScript-rendered and the company count/velocity data only appears after client-side execution. A static scraper returns empty divs. The Scraping Browser executes the JS and returns the populated DOM.

**Web Unlocker** — used for G2.com, Glassdoor, and SEC EDGAR. These three specifically: G2 aggressively blocks scrapers (CAPTCHA + bot detection), Glassdoor requires geolocation headers, and SEC EDGAR blocks non-US IPs. Web Unlocker handles all three reliably.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     AlphaSignal                             │
│                                                             │
│  ┌──────────────┐      ┌──────────────────────────────────┐ │
│  │ Brand Setup  │      │     Market Monitor (hourly)      │ │
│  │              │      │                                  │ │
│  │ SERP → scrape│      │  7 Detectors (parallel)          │ │
│  │ Claude →     │      │  ├─ HiringVelocity               │ │
│  │ profile.json │      │  ├─ PricingChange                │ │
│  └──────────────┘      │  ├─ FundingDetector              │ │
│                        │  ├─ NewsDetector                 │ │
│  ┌──────────────┐      │  ├─ FinancialHealth              │ │
│  │ Sales Engine │      │  ├─ SupplierRisk                 │ │
│  │ (on demand)  │      │  └─ WebTraffic                   │ │
│  │              │      │         ↓                        │ │
│  │ ICP Parser   │      │  SignalCorrelator                 │ │
│  │ → Leads      │      │  (5 thesis patterns)             │ │
│  │ → Intent     │      │         ↓                        │ │
│  │ → Context    │◄─────│  AlertGenerator (Claude)         │ │
│  │ → Outreach   │      │  → structured alert + direction  │ │
│  └──────────────┘      └──────────────────────────────────┘ │
│                                   ↓                         │
│              SSE stream → live dashboard                     │
└─────────────────────────────────────────────────────────────┘
```

---

## Setup

### Prerequisites
- Python 3.11+
- [Bright Data account](https://brightdata.com) — free trial available
- [AI/ML API key](https://aimlapi.com) or Anthropic API key
- [Resend](https://resend.com) account for email sending (optional)

### Install and run

```bash
git clone https://github.com/RagavRida/alphasignal
cd alphasignal
pip install -r requirements.txt
cp .env.example .env   # fill in your keys
python main.py
```

Dashboard: `http://localhost:8080`

### Demo mode (no credentials needed)

```bash
python main.py --demo
```

Opens the dashboard with pre-loaded demo data for a Notion competitor analysis. Click **🎬 Demo** in the Sales tab to load 8 pre-curated leads with full email sequences.

### Environment variables

```bash
# Required for live mode
BRIGHT_DATA_API_TOKEN=       # Bright Data REST API token
BRIGHT_DATA_SERP_ZONE=       # Zone name from Bright Data dashboard
BRIGHT_DATA_MCP_URL=         # MCP server URL with token
AIML_API_KEY=                # AI/ML API key (Claude via OpenAI-compatible endpoint)

# Optional
RESEND_API_KEY=              # For email sending from the dashboard
SLACK_WEBHOOK_URL=           # For alert notifications
DEMO_MODE=false              # Set true to skip API calls
```

---

## Project Structure

```
alphasignal/
├── src/
│   ├── bright_data_client.py   # Unified async Bright Data client (all 5 products)
│   ├── signal_detectors.py     # 7 parallel detectors
│   ├── signal_correlator.py    # Cross-signal thesis engine (5 rules)
│   ├── alert_generator.py      # Claude-powered alert narration
│   ├── monitor.py              # Autonomous monitor loop
│   ├── state.py                # SQLite persistence
│   ├── company_profile.py      # Brand intelligence + watch list generation
│   ├── llm.py                  # Lightweight AIML/OpenAI-compatible HTTP client
│   └── sales/
│       ├── icp_parser.py       # Free-text ICP → structured search queries
│       ├── lead_discovery.py   # SERP → scored leads
│       ├── intent_monitor.py   # G2/Reddit/HN buying signals
│       ├── context_fetcher.py  # Blog/jobs scraping for email personalization
│       ├── competitive_radar.py# Competitor pricing + sentiment
│       ├── outreach_sequencer.py# 4-step email + LinkedIn DM generation
│       ├── pipeline.py         # Full pipeline orchestrator
│       └── sales_state.py      # SQLite for leads, emails, signals
├── src/dashboard/
│   ├── server.py               # FastAPI server + SSE endpoints
│   └── static/                 # Dashboard UI (market monitor + sales pipeline)
├── main.py                     # Entry point
├── config.yaml                 # Watch list + thresholds
└── requirements.txt
```

---

## Signal Thresholds

These are configurable in `config.yaml`:

| Signal | Default Threshold | What It Means |
|---|---|---|
| `hiring_velocity_alert` | +50% | Month-over-month open role increase |
| `hiring_freeze_threshold` | 90% drop | Month-over-month open role decrease |
| `pricing_change_alert` | 10% | Absolute price change on any plan |
| `traffic_growth_alert` | +30% | Month-over-month traffic increase |
| `funding_min_amount_m` | $10M | Minimum funding round to trigger |
| `minimum_confidence` | 65% | Minimum signal confidence to surface |
| `correlation_match_score` | 0.6 | Minimum thesis match to generate alert |

---

## Built With

- **[Bright Data](https://brightdata.com)** — web data infrastructure (MCP Server, SERP API, Web Scraper API, Scraping Browser, Web Unlocker)
- **[AI/ML API](https://aimlapi.com)** — Claude via OpenAI-compatible endpoint
- **[FastAPI](https://fastapi.tiangolo.com)** — async Python web framework
- **[Resend](https://resend.com)** — transactional email

---

*Built for the Bright Data Hackathon 2025.*
