"""
ICP Parser — Uses Claude (AI/ML API) to convert free-text user input
into a structured ICP object with search queries.

Input:  "B2B SaaS companies, 50-500 employees, raised Series A last 6 months, hiring SDRs"
Output: ICP(industry=["SaaS"], stage=["Series_A"], signals=["hiring_sdrs"], ...)
"""

import json
import os
from src.llm import OpenAI
from src.sales.models import ICP


SYSTEM_PROMPT = """You are an expert B2B sales strategist. Parse the user's ICP (Ideal Customer Profile)
description into structured JSON. Be specific and practical.

Return ONLY valid JSON — no markdown fences."""

PARSE_PROMPT = """Parse this ICP description into structured parameters.

ICP Description: {text}

Return JSON with these exact fields:
{{
  "mode": "discovery" or "displacement",
  "industry": ["list of industries, e.g. SaaS, Fintech, HealthTech"],
  "geo": ["list of countries/regions, e.g. India, US, Southeast Asia"],
  "stage": ["funding stages: Seed, Series_A, Series_B, Series_C, Public"],
  "size_min": minimum headcount (integer),
  "size_max": maximum headcount (integer),
  "signals": ["hiring_sdrs", "raised_recently", "hiring_sales", "hiring_marketing", "product_launch", "new_office"],
  "competitor": "competitor company name if displacement mode, else empty string",
  "keywords": ["3-5 key terms that define this ICP"],
  "search_queries": [
    "5-8 specific Google search queries to find these companies",
    "Make them specific: 'Series A SaaS startups hiring SDR India 2025'",
    "Include Crunchbase/LinkedIn/AngelList specific queries"
  ]
}}"""


class ICPParser:

    def __init__(self, api_key: str = "", base_url: str = "https://api.aimlapi.com/v1",
                 model: str = "claude-sonnet-4-20250514"):
        self.model = model
        self.client = None
        if api_key:
            self.client = OpenAI(api_key=api_key, base_url=base_url)

    def parse(self, text: str) -> ICP:
        """Parse free-text ICP description → structured ICP object."""
        icp = ICP(raw_text=text)

        # Detect displacement mode
        displacement_keywords = ["competitor", "alternative", "users of", "customers of",
                                 "switching from", "displacing", "replace"]
        if any(kw in text.lower() for kw in displacement_keywords):
            icp.mode = "displacement"

        if not self.client:
            return self._fallback_parse(text, icp)

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                max_tokens=800,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": PARSE_PROMPT.format(text=text)},
                ],
            )
            raw = resp.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            data = json.loads(raw)

            icp.mode            = data.get("mode", icp.mode)
            icp.industry        = data.get("industry", [])
            icp.geo             = data.get("geo", [])
            icp.stage           = data.get("stage", [])
            icp.size_min        = int(data.get("size_min", 10))
            icp.size_max        = int(data.get("size_max", 5000))
            icp.signals         = data.get("signals", [])
            icp.competitor      = data.get("competitor", "")
            icp.keywords        = data.get("keywords", [])
            icp.search_queries  = data.get("search_queries", [])
        except Exception as e:
            print(f"  [ICPParser] LLM parse failed: {e} — using fallback")
            icp = self._fallback_parse(text, icp)

        return icp

    def _fallback_parse(self, text: str, icp: ICP) -> ICP:
        """Rule-based fallback parser."""
        text_lower = text.lower()

        # Industry
        industry_map = {
            "saas": "SaaS", "fintech": "Fintech", "healthtech": "HealthTech",
            "edtech": "EdTech", "e-commerce": "E-Commerce", "ecommerce": "E-Commerce",
            "martech": "MarTech", "hrtech": "HRTech", "legaltech": "LegalTech",
            "b2b": "B2B", "enterprise": "Enterprise Software",
        }
        icp.industry = [v for k, v in industry_map.items() if k in text_lower] or ["B2B SaaS"]

        # Stage
        stage_map = {
            "seed": "Seed", "series a": "Series_A", "series b": "Series_B",
            "series c": "Series_C", "public": "Public", "ipo": "Public",
        }
        icp.stage = [v for k, v in stage_map.items() if k in text_lower] or ["Series_A", "Series_B"]

        # Geo
        geo_map = {"india": "India", "us": "US", "usa": "US", "europe": "Europe",
                   "singapore": "Singapore", "uk": "UK", "southeast asia": "Southeast Asia"}
        icp.geo = [v for k, v in geo_map.items() if k in text_lower] or ["US", "India"]

        # Signals
        signal_map = {
            "sdr": "hiring_sdrs", "sales rep": "hiring_sales", "ae": "hiring_ae",
            "marketing": "hiring_marketing", "raised": "raised_recently",
            "funding": "raised_recently", "product": "product_launch",
        }
        icp.signals = list({v for k, v in signal_map.items() if k in text_lower}) or ["raised_recently"]

        # Generate basic search queries
        stage_str = " ".join(icp.stage).replace("_", " ")
        ind_str   = icp.industry[0] if icp.industry else "B2B SaaS"
        geo_str   = icp.geo[0] if icp.geo else "US"
        icp.search_queries = [
            f"{stage_str} {ind_str} startups {geo_str} 2025",
            f"{ind_str} companies hiring SDRs {geo_str}",
            f"site:crunchbase.com {ind_str} {stage_str}",
            f"site:linkedin.com/company {ind_str} {geo_str} {stage_str}",
            f"{ind_str} startups raised funding {geo_str} 2025",
        ]
        icp.keywords = icp.industry + icp.stage

        return icp
