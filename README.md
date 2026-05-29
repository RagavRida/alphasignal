# AlphaSignal — AI Sales Intelligence + Market Monitor
## Bright Data Hackathon 2025

> Autonomous B2B sales pipeline and hedge-fund-grade market intelligence — powered by **all 5 Bright Data products** and **AI/ML API (Claude)**.

![Python](https://img.shields.io/badge/Python-3.10+-blue?style=flat-square)
![Bright Data](https://img.shields.io/badge/Bright%20Data-MCP%20%7C%20SERP%20%7C%20Scraper%20%7C%20Browser%20%7C%20Unlocker-orange?style=flat-square)
![AI/ML API](https://img.shields.io/badge/AI%2FML%20API-Claude-purple?style=flat-square)
![FastAPI](https://img.shields.io/badge/FastAPI-WebSocket-green?style=flat-square)

---

## What It Does

**AlphaSignal** is a unified intelligence platform with two engines running on the same Bright Data infrastructure:

### 🎯 Engine 1 — B2B Sales Pipeline
Enter your brand name → AlphaSignal researches your product automatically, discovers matching leads, monitors their buying intent in real-time, and generates a personalized 4-step email sequence for each — fully brand-aware, no manual prompting.

### 📈 Engine 2 — Market Intelligence Monitor  
Add companies to your watchlist → AlphaSignal monitors 7 signals (hiring velocity, pricing changes, funding, news, SEC filings, supplier risk, web traffic) and generates hedge-fund-grade investment alerts 24/7.

### 🔗 Cross-Signal Engine (Unique)
Market alerts automatically surface sales opportunities. A funding announcement triggers: "This company just raised $8M — they have budget. Find leads like them."

---

## Bright Data Products Used

| Product | Where Used | What It Does |
|---|---|---|
| **MCP Server** | `bright_data_client.py → MCPClient` | Primary orchestration: `search_engine`, `scrape_as_markdown`, `extract` tools |
| **SERP API** | `bright_data_client.py → _serp_rest()` | Fallback Google search — lead discovery, intent signals, funding news |
| **Web Scraper API** | `bright_data_client.py → scrape_pricing_page()` | Pricing page scraping for the Pricing Change Detector |
| **Scraping Browser** | `bright_data_client.py → scrape_linkedin_jobs()` | LinkedIn job pages, company blogs (JS-rendered) |
| **Web Unlocker** | `bright_data_client.py → extract()` | SEC EDGAR, G2.com reviews, Glassdoor (CAPTCHA-protected sites) |

### Live API Activity Log
Every Bright Data API call is broadcast in real-time to the dashboard — you can watch `[SERP API]`, `[MCP Server]`, `[Web Unlocker]` calls appear as the pipeline runs.

---

## AI/ML API (Claude) — 7 Use Cases

| Function | What Claude Does |
|---|---|
| `icp_parser.py → parse()` | Converts free-text ICP to structured JSON (industry, stage, geo, queries) |
| `lead_discovery.py → score()` | Scores each company 0–100 against ICP criteria |
| `outreach_sequencer.py → generate_sequence()` | Writes 4-step personalized email pitch for your brand |
| `outreach_sequencer.py → generate_linkedin_dm()` | Writes matching LinkedIn DM for each step |
| `alert_generator.py → generate_alert()` | Writes hedge-fund investment narrative |
| `signal_correlator.py → correlate()` | Cross-correlates signals to detect investment thesis |
| `company_profile.py → analyze_brand()` | Researches brand from website + SERP to auto-fill profile |

---

## Quick Start

### 1. Install
```bash
pip install -r requirements.txt
```

### 2. Configure
```bash
cp .env.example .env
# Fill in: ANTHROPIC_API_KEY, BRIGHT_DATA_API_TOKEN, RESEND_API_KEY
```

### 3. Run (Live Mode)
```bash
python main.py
# Dashboard: http://localhost:8080
```

### 4. Demo Mode (No credentials required)
```bash
python main.py --demo
# Click "🎬 Demo" button in the Sales tab to load pre-curated results
```

---

## Architecture

```
Brand Onboarding
  └─ company_profile.py
       └─ Bright Data MCP: scrape_as_markdown(website)
       └─ Bright Data SERP: search("Brand ICP competitors")
       └─ AI/ML API (Claude): synthesize profile

Sales Pipeline (on demand)
  ├─ icp_parser.py → AI/ML API → structured ICP
  ├─ lead_discovery.py
  │    └─ Bright Data SERP (8 queries) → candidates
  │    └─ AI/ML API → score 0–100
  ├─ intent_monitor.py
  │    └─ Bright Data SERP (G2, Reddit, HN, Glassdoor)
  ├─ competitive_radar.py
  │    └─ Bright Data SERP (competitor reviews)
  └─ context_fetcher.py + outreach_sequencer.py
       └─ Bright Data MCP: scrape_as_markdown (blog/jobs)
       └─ AI/ML API: generate 4-step email sequence

Market Monitor (every 60 min)
  ├─ HiringVelocityDetector  → Bright Data SERP (LinkedIn jobs)
  ├─ PricingChangeDetector   → Bright Data Web Scraper
  ├─ FundingDetector         → Bright Data SERP (TechCrunch)
  ├─ NewsDetector            → Bright Data SERP
  ├─ FinancialHealthDetector → Bright Data Web Unlocker (SEC EDGAR)
  ├─ SupplierRiskDetector    → Bright Data SERP + Web Unlocker
  └─ WebTrafficDetector      → Bright Data Web Scraper
       └─ signal_correlator.py (5 thesis rules)
       └─ alert_generator.py → AI/ML API → structured alert
```

---

## Key Features

- **🟠 Live Bright Data API Call Log** — Watch every API call in real-time as leads are discovered
- **🎬 Instant Demo Mode** — Load pre-curated Natively AI demo data without waiting for pipeline
- **🔗 Cross-Signal Detection** — Market alerts trigger sales opportunities automatically
- **📧 Brand-Aware Emails** — Every email pitch references your exact brand, product, and use case
- **💼 Email Pattern Guesser** — Auto-generates 5 likely email patterns when contact email isn't found
- **⚡ WebSocket Streaming** — Leads appear in real-time as they're discovered
- **🌐 Unified Dashboard** — Market intelligence + sales pipeline + cross-signal feed in one view

---

## Business Model (Market Opportunity)

| Tier | Price | Target |
|---|---|---|
| Starter (1 brand, 10 leads/day) | $200/month | Founders, solo GTM |
| Professional (3 brands, 50 leads/day) | $800/month | Early-stage teams |
| Enterprise (unlimited) | $3,000+/month | Sales-led companies |

**Alternative data** for hedge funds:
| Tier | Price |
|---|---|
| 2 companies monitored | $50K/year |
| 10 companies | $200K/year |
| Unlimited | $500K+/year |
