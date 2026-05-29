"""
Company Profile — stores user's brand/product/ICP and auto-generates watch list.
Saves to data/company_profile.json and regenerates config.yaml watch_list daily.
"""

import json
import os
import re
import asyncio
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from src.llm import OpenAI

PROFILE_PATH = Path("data/company_profile.json")
CONFIG_PATH  = Path("config.yaml")


def load_profile() -> dict:
    """Load company profile. Returns {} if not set up yet."""
    if PROFILE_PATH.exists():
        return json.loads(PROFILE_PATH.read_text())
    return {}


def save_profile(profile: dict):
    """Persist the company profile."""
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    profile["updated_at"] = datetime.utcnow().isoformat() + "Z"
    PROFILE_PATH.write_text(json.dumps(profile, indent=2))


def needs_setup() -> bool:
    """True if the user has not set up their company profile yet."""
    p = load_profile()
    return not p.get("company_name")


def needs_watchlist_refresh() -> bool:
    """True if the watch list was not generated today."""
    p = load_profile()
    last = p.get("watchlist_generated_date", "")
    return last != str(date.today())


async def analyze_brand(brand_name: str, bd=None, website_url: str = "") -> dict:
    """
    Given a brand name (and optional website URL), build a full company profile.

    Priority order:
      0. Scrape the provided website URL via Bright Data Web Unlocker (most accurate)
      1. Bright Data SERP search (3 queries in parallel)
      2. AI/ML API training knowledge (fallback when no web data)
    """
    aiml_key   = os.getenv("AIML_API_KEY", "")
    aiml_url   = os.getenv("AIML_BASE_URL", "https://api.aimlapi.com/v1")
    aiml_model = os.getenv("AIML_MODEL", "claude-sonnet-4-20250514")

    website_content    = ""
    serp_context       = ""
    serp_snippet_count = 0
    source_used        = "ai_knowledge"

    # ── Step 0: Scrape the provided website URL (highest priority) ─────────
    if website_url and bd:
        print(f"  [BrandAnalyzer] Scraping website: {website_url}")
        try:
            # Try MCP Web Unlocker (scrape_as_markdown) first
            if bd.mcp:
                md = await bd.mcp.scrape_markdown(website_url)
                if md and len(md) > 200:
                    website_content = md[:6000]   # cap at 6k chars
                    print(f"  [BrandAnalyzer] ✓ Got {len(website_content)} chars from website (MCP)")
                    source_used = "website_scrape"
            # Fallback: also try /about page
            if not website_content and bd.mcp:
                base = website_url.rstrip("/")
                about_md = await bd.mcp.scrape_markdown(f"{base}/about")
                if about_md and len(about_md) > 100:
                    website_content = about_md[:3000]
                    print(f"  [BrandAnalyzer] ✓ Got {len(website_content)} chars from /about")
                    source_used = "website_scrape"
        except Exception as e:
            print(f"  [BrandAnalyzer] Website scrape error: {e} — falling back to SERP")

    # ── Step 1: SERP search (used if no website content or to supplement) ──
    if bd and not website_content:
        print(f"  [BrandAnalyzer] Researching '{brand_name}' via Bright Data SERP...")
        queries = [
            f"{brand_name} company product what they do",
            f"{brand_name} competitors alternatives",
            f"{brand_name} target customers ideal customer profile B2B",
        ]
        try:
            tasks        = [bd.serp_search(q, num_results=5) for q in queries]
            results_list = await asyncio.gather(*tasks, return_exceptions=True)
            snippets = []
            for results in results_list:
                if isinstance(results, list):
                    for r in results[:5]:
                        t = r.get("title", "")
                        s = r.get("snippet", "")
                        if t or s:
                            snippets.append(f"- {t}: {s}")
            serp_context       = "\n".join(snippets[:20])
            serp_snippet_count = len(snippets)
            if serp_snippet_count > 0:
                source_used = "serp"
            print(f"  [BrandAnalyzer] Got {serp_snippet_count} SERP snippets")
        except Exception as e:
            print(f"  [BrandAnalyzer] SERP error: {e} — using AI/ML API knowledge only")

    # ── Step 2: AI/ML API synthesizes ─ 3 modes by data quality ─────────────
    json_schema = f"""{{
  "company_name": "{brand_name}",
  "website": "{website_url or 'https://...'}",
  "industry": "B2B SaaS|Fintech|HealthTech|E-Commerce|DevTools|No-Code/AI Tools|HR Tech|Marketing Tech|Logistics|Other",
  "product_description": "1-2 sentences: what {brand_name} does and for whom — be specific",
  "icp_description": "Specific ICP: company size, funding stage, geography, job titles, pain points",
  "known_competitors": ["Competitor1", "Competitor2", "Competitor3", "Competitor4"],
  "watchlist_companies": [
    {{
      "name": "Company Name",
      "ticker": "TICK or ''",
      "pricing_url": "https://...",
      "category": "direct_competitor|icp_prospect|market_signal",
      "reason": "why monitor — specific signal to watch for",
      "suppliers": []
    }}
  ]
}}

For watchlist_companies include 10-12 total:
- 3-4 direct competitors (monitor their pricing, hiring, distress)
- 4-5 ICP-matching companies (potential buyers showing growth signals)
- 2-3 industry bellwethers
Return ONLY valid JSON. No markdown, no explanation."""

    if website_content:
        # BEST: scraped from their actual website via Bright Data Web Unlocker
        prompt = f"""You are a market intelligence analyst. A company's website has been scraped for you.
Extract their profile accurately from this content.

Company: {brand_name}
Website URL: {website_url}

--- SCRAPED WEBSITE CONTENT ---
{website_content}
--- END CONTENT ---

Based on the above website content, return this JSON:
{json_schema}"""

    elif serp_context:
        # GOOD: Bright Data SERP snippets
        prompt = f"""You are a market intelligence analyst. Analyze this company using Bright Data SERP results.

Company: {brand_name}

SERP snippets:
{serp_context}

Return this JSON:
{json_schema}"""

    else:
        # FALLBACK: AI/ML API training knowledge
        prompt = f"""You are a market intelligence expert with deep knowledge of tech companies and startups.

Search your training knowledge and recall everything you know about: "{brand_name}"
Website hint: {website_url or '(not provided)'}

Look for: what their product does, who their customers are, their competitors, their positioning.

Important: Use your ACTUAL knowledge of {brand_name}. Do NOT make up generic answers.
If you genuinely don't know this company, set product_description to "Unknown — please edit manually".

Return this JSON:
{json_schema}"""

    if not aiml_key:
        return _fallback_profile(brand_name)

    def _call():
        client = OpenAI(api_key=aiml_key, base_url=aiml_url)
        resp = client.chat.completions.create(
            model=aiml_model,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(raw)

    loop = asyncio.get_event_loop()
    try:
        data = await loop.run_in_executor(None, _call)
        data['serp_snippet_count'] = serp_snippet_count   # expose to frontend
        print(f"  [BrandAnalyzer] ✓ Profile generated for {brand_name} ({serp_snippet_count} SERP snippets)")
        return data
    except Exception as e:
        print(f"  [BrandAnalyzer] LLM error: {e}")
        return _fallback_profile(brand_name)


def _fallback_profile(brand_name: str) -> dict:
    return {
        "company_name":        brand_name,
        "website":             "",
        "industry":            "B2B SaaS",
        "product_description": f"{brand_name} — product description not available",
        "icp_description":     "B2B companies, 50-500 employees",
        "known_competitors":   [],
        "watchlist_companies": [],
    }


async def generate_watchlist(profile: dict) -> list[dict]:
    """
    Use AI/ML API to generate a dynamic watch list of competitors + relevant
    companies based on the user's company profile and ICP.
    Returns a list of company dicts compatible with config.yaml format.
    """
    aiml_key  = os.getenv("AIML_API_KEY", "")
    aiml_url  = os.getenv("AIML_BASE_URL", "https://api.aimlapi.com/v1")
    aiml_model = os.getenv("AIML_MODEL", "claude-sonnet-4-20250514")

    company_name = profile.get("company_name", "")
    product      = profile.get("product_description", "")
    icp          = profile.get("icp_description", "")
    competitors  = profile.get("known_competitors", [])
    industry     = profile.get("industry", "")

    prompt = f"""You are a market intelligence analyst. Generate a watch list of 8-12 companies
to monitor based on this company profile:

Company: {company_name}
Product: {product}
Industry: {industry}
ICP (target customers): {icp}
Known competitors: {', '.join(competitors) if competitors else 'not specified'}

Return ONLY valid JSON array. Each company object:
{{
  "name": "Company Name",
  "ticker": "TICK or empty string",
  "pricing_url": "https://their-pricing-page.com",
  "reason": "why monitor this",
  "category": "direct_competitor|icp_prospect|market_signal",
  "suppliers": []
}}

Include:
- 3-4 direct competitors (to track their pricing, hiring, distress signals)
- 3-4 companies that match the ICP (potential customers showing buying signals)
- 2-3 market signal companies (industry leaders whose trends affect the space)

No explanation. JSON array only."""

    if not aiml_key:
        # Fallback: use known competitors list
        return _fallback_watchlist(profile)

    def _call():
        client = OpenAI(api_key=aiml_key, base_url=aiml_url)
        resp = client.chat.completions.create(
            model=aiml_model,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(raw)

    loop = asyncio.get_event_loop()
    try:
        companies = await loop.run_in_executor(None, _call)
        return companies if isinstance(companies, list) else _fallback_watchlist(profile)
    except Exception as e:
        print(f"  [WatchList] LLM error: {e} — using fallback")
        return _fallback_watchlist(profile)


def _fallback_watchlist(profile: dict) -> list[dict]:
    """Simple fallback: use known competitors from profile."""
    companies = []
    for c in profile.get("known_competitors", []):
        companies.append({
            "name": c,
            "ticker": "",
            "pricing_url": f"https://www.{c.lower().replace(' ', '')}.com/pricing",
            "reason": "Known competitor",
            "category": "direct_competitor",
            "suppliers": [],
        })
    return companies or [
        {"name": "Competitor A", "ticker": "", "pricing_url": "", "reason": "Placeholder", "category": "direct_competitor", "suppliers": []}
    ]


def update_config_watchlist(companies: list[dict]):
    """Write the generated companies into config.yaml watch_list section."""
    import yaml

    if CONFIG_PATH.exists():
        config = yaml.safe_load(CONFIG_PATH.read_text()) or {}
    else:
        config = {}

    config.setdefault("watch_list", {})
    config["watch_list"]["companies"] = [
        {
            "name":        c.get("name", ""),
            "ticker":      c.get("ticker", ""),
            "pricing_url": c.get("pricing_url", ""),
            "category":    c.get("category", ""),
            "reason":      c.get("reason", ""),
            "suppliers":   c.get("suppliers", []),
        }
        for c in companies
    ]
    config["watch_list"]["generated_at"]    = datetime.utcnow().isoformat() + "Z"
    config["watch_list"]["generated_from"]  = "company_profile"

    CONFIG_PATH.write_text(yaml.dump(config, default_flow_style=False, allow_unicode=True))
    print(f"  [WatchList] ✓ Updated config.yaml with {len(companies)} companies")


async def refresh_watchlist_if_needed(profile: dict) -> bool:
    """
    Called on server startup and daily. Regenerates the watch list if it's stale.
    Returns True if the list was refreshed.
    """
    if not profile.get("company_name"):
        return False
    if not needs_watchlist_refresh():
        return False

    print(f"  [WatchList] Generating daily watch list for {profile['company_name']}...")
    companies = await generate_watchlist(profile)
    update_config_watchlist(companies)

    # Mark as refreshed today
    profile["watchlist_generated_date"] = str(date.today())
    profile["watchlist_companies"]      = companies
    save_profile(profile)
    return True
