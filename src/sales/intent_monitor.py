"""
Intent Signal Monitor
=====================
Bright Data Products:
  PRIMARY: Web Unlocker (access_secured_site) — scrapes G2 reviews + Glassdoor directly
  SECONDARY: SERP API (serp_search) — Reddit, Hacker News, and SERP-based intent signals

Monitors G2, Glassdoor, Reddit, Hacker News for buying signals.
Triggers outreach when a high-intent signal fires.
"""

import asyncio
import hashlib
import re
from datetime import datetime
from typing import Optional

from src.bright_data_client import BrightDataClient
from src.sales.models import ICP, IntentSignal


SWITCHING_PATTERNS = [
    r"looking for (?:an? )?alternative to",
    r"switching (?:from|away from)",
    r"(?:replacing|replace|ditching|leaving|moving away from)",
    r"tired of .{0,40}",
    r"frustrated with .{0,40}",
    r"(?:bad|terrible|awful|horrible) (?:experience|support|service) with",
    r"cancel(?:ling|ed) .{0,30} subscription",
]
EVALUATION_PATTERNS = [
    r"comparing .{0,30} vs .{0,30}",
    r"(?:evaluating|testing|trialing|piloting) .{0,30}",
    r"which .{0,30} (?:should|would) you (?:recommend|choose|use)",
    r"recommendations? for .{0,30}",
    r"(?:best|top|good) (?:alternatives?|options?) for",
]
BUDGET_PATTERNS = [
    r"budget (?:approved|available|allocated) for",
    r"looking to (?:invest|spend|purchase|buy) .{0,30}",
    r"rfp|request for proposal",
    r"vendor (?:evaluation|selection|comparison)",
]
PAIN_PATTERNS = [
    r"(?:can't|cannot|doesn't|does not|won't) (?:scale|integrate|work with)",
    r"(?:too|very) expensive",
    r"pricing (?:increased|went up|changed|raised)",
    r"support (?:is|was) (?:terrible|awful|slow|unresponsive)",
    r"missing (?:feature|functionality|integration)",
]
ALL_PATTERNS = {
    "switching_intent": SWITCHING_PATTERNS,
    "active_evaluation": EVALUATION_PATTERNS,
    "budget_available": BUDGET_PATTERNS,
    "pain_point": PAIN_PATTERNS,
}


class IntentMonitor:

    def __init__(self, bd: BrightDataClient):
        self.bd = bd

    async def monitor(self, icp: ICP, competitors: list[str] = None) -> list[IntentSignal]:
        terms = list(icp.keywords) + (competitors or [])
        if icp.competitor:
            terms.append(icp.competitor)
        terms = list(set(terms))[:5]

        print(f"\n  [IntentMonitor] Monitoring {len(terms)} terms across 4 sources...")
        tasks = []
        for term in terms:
            tasks.extend([
                self._monitor_reddit(term),
                self._monitor_hacker_news(term),
                self._monitor_g2(term),
                self._monitor_glassdoor(term),
            ])

        results = await asyncio.gather(*tasks, return_exceptions=True)
        signals = []
        for r in results:
            if isinstance(r, list):
                signals.extend(r)

        seen, unique = set(), []
        for s in signals:
            key = hashlib.md5(s.quote[:80].encode()).hexdigest()
            if key not in seen:
                seen.add(key)
                unique.append(s)
        return sorted(unique, key=lambda s: s.confidence, reverse=True)[:20]

    async def _serp_to_signals(self, query: str, source: str, term: str,
                               conf_boost: float = 0) -> list[IntentSignal]:
        signals = []
        try:
            results = await self.bd.serp_search(query, num_results=8)
            for r in results:
                text = r.get("title", "") + " " + r.get("snippet", "")
                for intent_type, quote, conf in self._detect_intent(text, term):
                    signals.append(IntentSignal(
                        id=hashlib.md5((r.get("url","") + quote[:20]).encode()).hexdigest()[:10],
                        intent_type=intent_type,
                        source=source,
                        source_url=r.get("url",""),
                        quote=quote[:300],
                        company_mentioned=term,
                        confidence=min(conf + conf_boost, 99),
                    ))
        except Exception as e:
            print(f"    [{source}] error: {e}")
        return signals

    async def _monitor_reddit(self, term: str) -> list[IntentSignal]:
        q = f'site:reddit.com "{term}" alternative OR switching OR frustrated'
        return await self._serp_to_signals(q, "reddit", term)

    async def _monitor_hacker_news(self, term: str) -> list[IntentSignal]:
        q = f'site:news.ycombinator.com "Ask HN" "{term}" alternative OR recommendation'
        return await self._serp_to_signals(q, "hacker_news", term)

    async def _monitor_g2(self, term: str) -> list[IntentSignal]:
        """Primary: Web Unlocker — directly scrape G2 reviews page for this product."""
        signals = []

        # Step 1: Web Unlocker — scrape G2 reviews page directly (bypasses bot protection)
        try:
            slug = term.lower().replace(" ", "-").replace(".", "")
            g2_url = f"https://www.g2.com/products/{slug}/reviews"
            html = await self.bd.access_secured_site(g2_url)
            if html and len(html) > 200:
                # Extract review snippets from the HTML
                import re as _re
                snippets = _re.findall(r'<p[^>]*class="[^"]*review[^"]*"[^>]*>([^<]{50,400})</p>', html, _re.I)
                if not snippets:
                    # Fallback: grab any paragraph-ish text
                    snippets = _re.findall(r'<p[^>]*>([A-Z][^<]{60,300})</p>', html)[:10]

                for snippet in snippets[:5]:
                    clean = _re.sub(r'<[^>]+>', '', snippet).strip()
                    for intent_type, quote, conf in self._detect_intent(clean, term):
                        signals.append(IntentSignal(
                            id=hashlib.md5((g2_url + quote[:20]).encode()).hexdigest()[:10],
                            intent_type=intent_type,
                            source="g2_direct",
                            source_url=g2_url,
                            quote=quote[:300],
                            company_mentioned=term,
                            confidence=min(conf + 15, 99),  # G2 direct = higher confidence
                        ))
        except Exception as e:
            print(f"    [G2 Web Unlocker] {e}")

        # Step 2: SERP fallback if Web Unlocker returned nothing
        if not signals:
            q = f'site:g2.com "{term}" "looking for alternative" OR switching OR frustrated'
            signals.extend(await self._serp_to_signals(q, "g2", term, conf_boost=10))

        return signals

    async def _monitor_glassdoor(self, term: str) -> list[IntentSignal]:
        """Web Unlocker — directly scrape Glassdoor reviews to find tech migration signals."""
        signals = []

        # Step 1: Web Unlocker — scrape Glassdoor reviews directly
        try:
            slug = term.lower().replace(" ", "-")
            gd_url = f"https://www.glassdoor.com/Reviews/{slug}-reviews-SRCH_KE0,{len(slug)}.htm"
            html = await self.bd.access_secured_site(gd_url)
            if html and len(html) > 200:
                import re as _re
                # Extract review text fragments
                snippets = _re.findall(r'<p[^>]*>((?:[^<]|<(?!/p))+)</p>', html)[:15]
                for snippet in snippets:
                    clean = _re.sub(r'<[^>]+>', '', snippet).strip()
                    if len(clean) > 40:
                        if any(kw in clean.lower() for kw in ["migrate", "replace", "new system",
                                                                "transition", "modernize", "switching",
                                                                "outdated", "legacy"]):
                            signals.append(IntentSignal(
                                id=hashlib.md5((gd_url + clean[:20]).encode()).hexdigest()[:10],
                                intent_type="pain_point",
                                source="glassdoor_direct",
                                source_url=gd_url,
                                quote=clean[:300],
                                company_mentioned=term,
                                confidence=60.0,
                            ))
        except Exception as e:
            print(f"    [Glassdoor Web Unlocker] {e}")

        # Step 2: SERP fallback
        if not signals:
            q = f'site:glassdoor.com "{term}" migrate OR "replace" OR "new system" job'
            try:
                results = await self.bd.serp_search(q, num_results=8)
                for r in results:
                    text = r.get("title","") + " " + r.get("snippet","")
                    if any(kw in text.lower() for kw in ["migrate", "replace", "transition", "modernize"]):
                        signals.append(IntentSignal(
                            id=hashlib.md5(r.get("url","").encode()).hexdigest()[:10],
                            intent_type="pain_point",
                            source="glassdoor",
                            source_url=r.get("url",""),
                            quote=text[:300],
                            company_mentioned=term,
                            confidence=55.0,
                        ))
            except Exception as e:
                print(f"    [glassdoor SERP fallback] {e}")

        return signals

    def _detect_intent(self, text: str, term: str) -> list[tuple[str, str, float]]:
        matches    = []
        text_lower = text.lower()
        conf_map   = {"switching_intent": 85, "active_evaluation": 75,
                      "budget_available": 90, "pain_point": 70}
        for intent_type, patterns in ALL_PATTERNS.items():
            for pattern in patterns:
                m = re.search(pattern, text_lower)
                if m:
                    start = max(0, m.start() - 20)
                    end   = min(len(text), m.end() + 100)
                    quote = text[start:end].strip()
                    conf  = conf_map[intent_type] + (10 if term.lower() in text_lower else 0)
                    matches.append((intent_type, quote, float(conf)))
                    break
        return matches
