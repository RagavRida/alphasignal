"""
Lead Discovery Engine
=====================
Tool: SERP API (search_engine via MCP) + Web Scraper API (scrape_as_markdown)

Flow:
  1. Generate targeted search queries from ICP
  2. Run all queries in parallel via Bright Data MCP search_engine
  3. Extract company names + URLs from results
  4. Scrape LinkedIn + Crunchbase for each company → enrich
  5. Score each lead 0–100 against ICP
  6. Return top N enriched Lead objects
"""

import asyncio
import hashlib
import json
import re
from datetime import datetime
from typing import Optional
from src.llm import OpenAI

from src.bright_data_client import BrightDataClient
from src.sales.models import ICP, Lead, Contact


# ── Known company patterns to skip ────────────────────────────────────────────
SKIP_DOMAINS = {"google.com", "linkedin.com", "crunchbase.com", "techcrunch.com",
                "bloomberg.com", "forbes.com", "medium.com", "twitter.com",
                "facebook.com", "youtube.com", "wikipedia.org", "reuters.com"}

# ── Funding stage keyword mapping ──────────────────────────────────────────────
STAGE_KEYWORDS = {
    "seed": "Seed", "pre-seed": "Pre-Seed",
    "series a": "Series_A", "series b": "Series_B",
    "series c": "Series_C", "series d": "Series_D",
    "growth": "Growth", "ipo": "Public", "public": "Public",
}

# ── Headcount ranges ───────────────────────────────────────────────────────────
SIZE_RANGES = [
    (1, 10, "1-10"), (11, 50, "11-50"), (51, 200, "51-200"),
    (201, 500, "201-500"), (501, 1000, "501-1000"), (1001, 5000, "1001-5000"),
]


def _lead_id(company_name: str) -> str:
    return hashlib.md5(company_name.lower().encode()).hexdigest()[:10]


def _domain_from_url(url: str) -> str:
    m = re.search(r"https?://(?:www\.)?([^/]+)", url)
    return m.group(1).lower() if m else ""


class LeadDiscoveryEngine:

    def __init__(self, bd: BrightDataClient, llm_client: Optional[OpenAI] = None,
                 llm_model: str = "claude-sonnet-4-20250514"):
        self.bd         = bd
        self.llm        = llm_client
        self.llm_model  = llm_model

    async def discover(self, icp: ICP, max_leads: int = 20) -> list[Lead]:
        """
        Main entry point: run all queries → scrape → score → return top leads.
        """
        print(f"\n  [LeadDiscovery] Running {len(icp.search_queries)} queries...")

        # Step 1: Run all search queries in parallel
        search_tasks = [self.bd.serp_search(q, num_results=10) for q in icp.search_queries]
        all_results  = await asyncio.gather(*search_tasks, return_exceptions=True)

        # Step 2: Extract unique company candidates
        candidates = {}  # domain → {name, url, snippets}
        for results in all_results:
            if isinstance(results, Exception):
                continue
            for r in results:
                domain = _domain_from_url(r.get("url", ""))
                if not domain or domain in SKIP_DOMAINS:
                    continue
                if domain not in candidates:
                    candidates[domain] = {
                        "name":     self._name_from_result(r),
                        "domain":   domain,
                        "url":      r.get("url", ""),
                        "snippets": [],
                    }
                candidates[domain]["snippets"].append(r.get("snippet", "") + " " + r.get("title", ""))

        print(f"  [LeadDiscovery] Found {len(candidates)} candidate companies")

        # Step 3: Enrich top candidates in parallel (limit to 30 to control API usage)
        top_domains = list(candidates.values())[:30]
        enrich_tasks = [self._enrich_lead(c, icp) for c in top_domains]
        enriched = await asyncio.gather(*enrich_tasks, return_exceptions=True)

        leads = []
        for result in enriched:
            if isinstance(result, Lead):
                leads.append(result)

        # Step 4: Score and rank
        scored = sorted(leads, key=lambda l: l.score, reverse=True)
        return scored[:max_leads]

    async def _enrich_lead(self, candidate: dict, icp: ICP) -> Lead:
        """Scrape LinkedIn/Crunchbase for a candidate company."""
        domain   = candidate["domain"]
        name     = candidate["name"]
        snippets = " ".join(candidate["snippets"])

        lead = Lead(
            id=_lead_id(name),
            company_name=name,
            domain=domain,
            source_urls=[candidate["url"]],
        )

        # Try to enrich from snippet text first (fast, no extra API call)
        lead = self._enrich_from_snippets(lead, snippets)

        # Try LinkedIn page scrape
        linkedin_url = f"https://www.linkedin.com/company/{domain.split('.')[0]}/"
        lead.linkedin_url = linkedin_url
        try:
            md = await self.bd.mcp.scrape_markdown(linkedin_url) if self.bd.mcp else ""
            if md and len(md) > 200:
                lead = self._parse_linkedin_markdown(lead, md)
        except Exception:
            pass

        # Try Crunchbase scrape for funding data
        crunchbase_url = f"https://www.crunchbase.com/organization/{domain.split('.')[0]}"
        lead.crunchbase_url = crunchbase_url
        try:
            md = await self.bd.mcp.scrape_markdown(crunchbase_url) if self.bd.mcp else ""
            if md and len(md) > 100:
                lead = self._parse_crunchbase_markdown(lead, md)
        except Exception:
            pass

        # Score against ICP
        lead.score, lead.score_reasons = self._score_lead(lead, icp)
        return lead

    def _name_from_result(self, r: dict) -> str:
        """Extract company name from search result."""
        title = r.get("title", "")
        url   = r.get("url", "")

        # Try domain
        domain = _domain_from_url(url)
        if domain:
            name = domain.split(".")[0].replace("-", " ").title()
            return name

        # Try title — take first part before | or -
        parts = re.split(r"[\|–\-]", title)
        return parts[0].strip()[:50] if parts else title[:50]

    def _enrich_from_snippets(self, lead: Lead, text: str) -> Lead:
        """Extract structured info from search snippet text."""
        text_lower = text.lower()

        # Funding stage
        for kw, stage in STAGE_KEYWORDS.items():
            if kw in text_lower:
                lead.funding_stage = stage
                break

        # Funding amount
        m = re.search(r"\$\s*([\d.]+)\s*([MBK])\s*(?:funding|raised|round|investment|series)", text, re.I)
        if m:
            lead.funding_amount = f"${m.group(1)}{m.group(2)}"

        # Geo
        geo_keywords = {"india": "India", "us": "US", "usa": "US", "singapore": "Singapore",
                        "uk": "UK", "london": "UK", "new york": "US", "san francisco": "US",
                        "bangalore": "India", "mumbai": "India", "europe": "Europe"}
        for kw, geo in geo_keywords.items():
            if kw in text_lower:
                lead.geo = geo
                break

        # Hiring signals
        hiring_signals = []
        if any(w in text_lower for w in ["hiring sdr", "sales development", "sdr"]): hiring_signals.append("Hiring SDRs")
        if any(w in text_lower for w in ["account executive", "ae", "sales rep"]): hiring_signals.append("Hiring AEs")
        if any(w in text_lower for w in ["head of marketing", "growth", "demand gen"]): hiring_signals.append("Hiring Marketing")
        if any(w in text_lower for w in ["vp sales", "chief revenue", "cro"]): hiring_signals.append("Building Sales Org")
        lead.hiring_signals = hiring_signals

        # Industry
        ind_map = {"saas": "SaaS", "fintech": "Fintech", "healthtech": "HealthTech",
                   "edtech": "EdTech", "ecommerce": "E-Commerce", "b2b": "B2B"}
        for kw, ind in ind_map.items():
            if kw in text_lower:
                lead.industry = ind
                break

        return lead

    def _parse_linkedin_markdown(self, lead: Lead, md: str) -> Lead:
        """Extract structured data from LinkedIn company page markdown."""
        # Headcount
        size_match = re.search(r"(\d[\d,]+)\s*employees?", md, re.I)
        if size_match:
            count = int(size_match.group(1).replace(",", ""))
            for lo, hi, label in SIZE_RANGES:
                if lo <= count <= hi:
                    lead.headcount = label
                    break
            else:
                lead.headcount = f"{count}+"

        # Specialties / tech stack
        spec_match = re.search(r"specialties?:?\s*([^\n]+)", md, re.I)
        if spec_match:
            techs = [t.strip() for t in spec_match.group(1).split(",")][:6]
            lead.tech_stack = [t for t in techs if len(t) < 40]

        # Description
        desc_match = re.search(r"about\s*\n+([^\n]{50,300})", md, re.I)
        if desc_match:
            lead.description = desc_match.group(1).strip()

        # Website
        web_match = re.search(r"website:?\s*(https?://[^\s\n]+)", md, re.I)
        if web_match and not lead.domain:
            lead.domain = _domain_from_url(web_match.group(1))

        return lead

    def _parse_crunchbase_markdown(self, lead: Lead, md: str) -> Lead:
        """Extract funding data from Crunchbase markdown."""
        # Funding round
        for kw, stage in STAGE_KEYWORDS.items():
            if kw in md.lower() and not lead.funding_stage:
                lead.funding_stage = stage
                break

        # Amount
        m = re.search(r"\$\s*([\d.]+)\s*([MBK])", md)
        if m and not lead.funding_amount:
            lead.funding_amount = f"${m.group(1)}{m.group(2)}"

        # Date
        date_m = re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}", md)
        if date_m:
            lead.funding_date = date_m.group(0)

        # Headcount from Crunchbase if not already set
        if not lead.headcount:
            emp_m = re.search(r"(\d+)[-–](\d+)\s*employees", md, re.I)
            if emp_m:
                lead.headcount = f"{emp_m.group(1)}-{emp_m.group(2)}"

        return lead

    def _score_lead(self, lead: Lead, icp: ICP) -> tuple[float, list[str]]:
        """Score lead 0–100 against ICP parameters."""
        score   = 0.0
        reasons = []

        # Industry match (25pts)
        if lead.industry and icp.industry:
            if any(ind.lower() in lead.industry.lower() or
                   lead.industry.lower() in ind.lower()
                   for ind in icp.industry):
                score += 25
                reasons.append(f"✓ Industry match: {lead.industry}")
            else:
                score += 5
        else:
            score += 10  # unknown = some credit

        # Funding stage match (25pts)
        if lead.funding_stage and icp.stage:
            if any(lead.funding_stage.replace("_", " ").lower() in s.lower() or
                   s.lower() in lead.funding_stage.lower()
                   for s in icp.stage):
                score += 25
                reasons.append(f"✓ Funding stage: {lead.funding_stage}")
            else:
                score += 5

        # Hiring signals (20pts)
        if lead.hiring_signals:
            for sig in lead.hiring_signals:
                if any(kw in sig.lower() for kw in ["sdr", "sales", "ae", "marketing", "revenue"]):
                    score += 10
                    reasons.append(f"✓ Hiring signal: {sig}")
                    break
            score += min(len(lead.hiring_signals) * 2, 10)

        # Geo match (10pts)
        if lead.geo and icp.geo:
            if any(lead.geo.lower() in g.lower() or g.lower() in lead.geo.lower()
                   for g in icp.geo):
                score += 10
                reasons.append(f"✓ Geo match: {lead.geo}")

        # Funding amount (10pts — more funding = better prospect)
        if lead.funding_amount:
            score += 10
            reasons.append(f"✓ Funding: {lead.funding_amount}")

        # Contacts found (10pts)
        if lead.contacts:
            score += min(len(lead.contacts) * 5, 10)
            reasons.append(f"✓ {len(lead.contacts)} contacts identified")

        # Tech stack (bonus 5pts)
        if lead.tech_stack:
            score += 5

        return min(round(score, 1), 100.0), reasons
