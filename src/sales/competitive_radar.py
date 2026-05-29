"""
Competitive Displacement Radar
================================
Tool: SERP API + Web Scraper API (scrape_as_markdown via MCP)

Monitors competitor signals daily:
  1. Branded search volume / negative sentiment spikes
  2. Competitor pricing page changes
  3. G2 / Capterra negative review spikes
  4. Bad press / controversy

When a competitor raises prices or gets bad press → flag
their known customers for outreach.
"""

import asyncio
import re
from datetime import datetime
from typing import Optional

from src.bright_data_client import BrightDataClient
from src.sales.models import IntentSignal
import hashlib


NEGATIVE_PRESS_PATTERNS = [
    r"raises? prices?", r"pricing (?:increase|hike|change)",
    r"data breach", r"security incident", r"outage", r"downtime",
    r"layoffs?", r"cuts? jobs?", r"restructur",
    r"lawsuit", r"ftc", r"gdpr violation",
    r"(?:poor|terrible|awful) (?:support|service|product)",
    r"(\d+)% price increase",
]


class CompetitiveRadar:

    def __init__(self, bd: BrightDataClient):
        self.bd = bd

    async def scan(self, competitors: list[str]) -> list[IntentSignal]:
        """
        Scan all competitors for displacement signals.
        Returns list of IntentSignal with intent_type="switching_intent".
        """
        if not competitors:
            return []

        print(f"\n  [CompetitiveRadar] Scanning {len(competitors)} competitors...")
        tasks = [self._scan_competitor(c) for c in competitors]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        signals = []
        for r in results:
            if isinstance(r, list):
                signals.extend(r)

        return sorted(signals, key=lambda s: s.confidence, reverse=True)

    async def _scan_competitor(self, competitor: str) -> list[IntentSignal]:
        """Run all checks for a single competitor."""
        signals = []
        tasks   = [
            self._check_negative_press(competitor),
            self._check_price_increase(competitor),
            self._check_review_spike(competitor),
            self._find_disgruntled_customers(competitor),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, list):
                signals.extend(r)
        return signals

    async def _check_negative_press(self, competitor: str) -> list[IntentSignal]:
        """Search for recent negative press about the competitor."""
        signals = []
        try:
            results = await self.bd.serp_search(
                f'"{competitor}" price increase OR outage OR breach OR lawsuit OR layoffs 2025',
                num_results=10,
            )
            for r in results:
                text = r.get("title", "") + " " + r.get("snippet", "")
                for pattern in NEGATIVE_PRESS_PATTERNS:
                    m = re.search(pattern, text, re.I)
                    if m:
                        signals.append(IntentSignal(
                            id=hashlib.md5(r.get("url","").encode()).hexdigest()[:10],
                            intent_type="switching_intent",
                            source="press",
                            source_url=r.get("url",""),
                            quote=text[:300],
                            company_mentioned=competitor,
                            confidence=80.0,
                        ))
                        break
        except Exception as e:
            print(f"    [Radar] press error for {competitor}: {e}")
        return signals

    async def _check_price_increase(self, competitor: str) -> list[IntentSignal]:
        """Scrape competitor pricing page and detect changes."""
        signals = []
        try:
            # Search for pricing page
            results = await self.bd.serp_search(
                f'"{competitor}" pricing site:{competitor.lower().replace(" ","")}.com OR "{competitor}" pricing page',
                num_results=3,
            )
            pricing_url = next((r.get("url","") for r in results
                                if "pricing" in r.get("url","").lower()), "")
            if not pricing_url or not self.bd.mcp:
                return signals

            md = await self.bd.mcp.scrape_markdown(pricing_url)
            if not md:
                return signals

            # Look for price increase signals in the content
            price_matches = re.findall(r"\$\s*([\d,]+)(?:\s*/\s*(?:mo|month|yr|year|user))?", md)
            prices = [float(p.replace(",","")) for p in price_matches if p]

            if prices:
                max_price = max(prices)
                # Flag if pricing seems high (heuristic)
                if max_price > 500:
                    signals.append(IntentSignal(
                        id=hashlib.md5(pricing_url.encode()).hexdigest()[:10],
                        intent_type="switching_intent",
                        source="pricing_page",
                        source_url=pricing_url,
                        quote=f"{competitor} pricing detected: max ${max_price:,.0f}/mo — potential displacement opportunity",
                        company_mentioned=competitor,
                        confidence=70.0,
                    ))
        except Exception as e:
            print(f"    [Radar] pricing error for {competitor}: {e}")
        return signals

    async def _check_review_spike(self, competitor: str) -> list[IntentSignal]:
        """Check G2 / Capterra for negative review spikes."""
        signals = []
        try:
            results = await self.bd.serp_search(
                f'site:g2.com OR site:capterra.com "{competitor}" reviews "1 star" OR "poor" OR "disappointed" 2025',
                num_results=8,
            )
            neg_count = 0
            for r in results:
                text = r.get("title","") + " " + r.get("snippet","")
                if any(neg in text.lower() for neg in
                       ["disappointed", "terrible", "poor support", "overpriced", "not worth", "cancel"]):
                    neg_count += 1

            if neg_count >= 2:
                signals.append(IntentSignal(
                    id=hashlib.md5(f"{competitor}_reviews".encode()).hexdigest()[:10],
                    intent_type="switching_intent",
                    source="g2",
                    source_url=f"https://www.g2.com/products/{competitor.lower().replace(' ','-')}/reviews",
                    quote=f"{competitor}: {neg_count} negative review signals detected recently",
                    company_mentioned=competitor,
                    confidence=75.0,
                ))
        except Exception as e:
            print(f"    [Radar] reviews error for {competitor}: {e}")
        return signals

    async def _find_disgruntled_customers(self, competitor: str) -> list[IntentSignal]:
        """Find users publicly expressing frustration with the competitor."""
        signals = []
        try:
            results = await self.bd.serp_search(
                f'"{competitor}" frustrated OR "looking for alternative" OR "switching from {competitor}" site:reddit.com OR site:twitter.com',
                num_results=10,
            )
            for r in results:
                text = r.get("snippet","") + " " + r.get("title","")
                if any(kw in text.lower() for kw in
                       ["alternative", "switch", "frustrated", "tired of", "hate", "cancel"]):
                    signals.append(IntentSignal(
                        id=hashlib.md5(r.get("url","").encode()).hexdigest()[:10],
                        intent_type="switching_intent",
                        source="social",
                        source_url=r.get("url",""),
                        quote=text[:300],
                        company_mentioned=competitor,
                        confidence=82.0,
                    ))
        except Exception as e:
            print(f"    [Radar] customers error for {competitor}: {e}")
        return signals[:5]
