"""
Alternative Lead Sources
=========================
GitHub and Product Hunt lead sourcing via Bright Data.

GitHub   — finds companies actively building with relevant tech stacks.
           High buying intent: they're hiring engineers + shipping product.

Product Hunt — finds companies that recently launched.
               Launch = growth mode = budget + buying intent.

Both are called as agent tools and surface results directly into the lead
discovery pipeline alongside SERP-sourced leads.
"""

import re
from datetime import datetime
from typing import Optional

from src.bright_data_client import BrightDataClient


class GitHubSourcer:
    """
    Finds companies on GitHub by:
    1. SERP API — "site:github.com <tech stack> company"
    2. BD MCP scrape — parse org profile for company name, website, headcount
    """

    def __init__(self, bd: BrightDataClient):
        self.bd = bd

    async def find_companies(
        self,
        tech_keywords: list[str],
        min_stars: int = 50,
        limit: int = 10,
    ) -> list[dict]:
        """
        Returns: [{ name, github_url, website, description, language, stars }]
        """
        results = []
        for kw in tech_keywords[:3]:   # cap to 3 keywords to stay within budget
            query = f"site:github.com {kw} company OR startup"
            serp  = await self.bd.serp_search(query, num_results=10)
            for r in serp:
                url = r.get("url", "")
                if "github.com/" not in url:
                    continue
                # Only org-level URLs (github.com/org, not github.com/org/repo)
                parts = url.replace("https://github.com/", "").strip("/").split("/")
                if len(parts) == 1 and parts[0]:
                    org = parts[0]
                    profile = await self._scrape_org(org)
                    if profile:
                        results.append(profile)
                if len(results) >= limit:
                    break
            if len(results) >= limit:
                break
        return results[:limit]

    async def _scrape_org(self, org: str) -> Optional[dict]:
        url = f"https://github.com/{org}"
        try:
            if self.bd.mcp:
                md = await self.bd.mcp.scrape_markdown(url)
            else:
                md = await self.bd.proxy_fetch(url)
            if not md or len(md) < 100:
                return None
            website = ""
            m = re.search(r"https?://(?!github)[^\s\)>\"']{4,50}", md)
            if m:
                website = m.group(0)
            desc_m = re.search(r"\n([A-Z][^\n]{20,120})\n", md)
            description = desc_m.group(1).strip() if desc_m else ""
            return {
                "name":        org,
                "github_url":  url,
                "website":     website,
                "description": description,
                "source":      "GitHub",
                "discovered_at": datetime.utcnow().isoformat() + "Z",
            }
        except Exception:
            return None


class ProductHuntSourcer:
    """
    Scrapes recent Product Hunt launches via Bright Data MCP.
    Launched = growth mode = budget allocated, team hiring, buying intent high.
    """

    PH_URL = "https://www.producthunt.com/time-travel/month"

    def __init__(self, bd: BrightDataClient):
        self.bd = bd

    async def find_recent_launches(
        self,
        category_keywords: Optional[list[str]] = None,
        limit: int = 10,
    ) -> list[dict]:
        """
        Returns recent PH launches as lead candidates.
        [{ name, tagline, website, upvotes, category, ph_url }]
        """
        launches = await self._scrape_ph(limit * 2)
        if category_keywords:
            kws = [k.lower() for k in category_keywords]
            launches = [
                l for l in launches
                if any(kw in (l.get("tagline", "") + l.get("name", "")).lower()
                       for kw in kws)
            ]
        return launches[:limit]

    async def _scrape_ph(self, limit: int) -> list[dict]:
        launches = []
        try:
            # Try SERP first for speed
            results = await self.bd.serp_search(
                "site:producthunt.com new launch startup tool 2026", 15
            )
            for r in results:
                url = r.get("url", "")
                if "producthunt.com/posts/" in url:
                    name = r.get("title", "").split(" - ")[0].strip()
                    tagline = r.get("snippet", "")[:120]
                    launches.append({
                        "name":     name,
                        "tagline":  tagline,
                        "ph_url":   url,
                        "website":  "",
                        "source":   "Product Hunt",
                        "discovered_at": datetime.utcnow().isoformat() + "Z",
                    })

            # Enrich top results with website via MCP scrape
            for launch in launches[:5]:
                if not launch["website"] and self.bd.mcp:
                    try:
                        md = await self.bd.mcp.scrape_markdown(launch["ph_url"])
                        m  = re.search(r"https?://(?!producthunt)[^\s\)>\"']{4,60}", md or "")
                        if m:
                            launch["website"] = m.group(0)
                    except Exception:
                        pass
        except Exception as e:
            print(f"  [ProductHunt] scrape error: {e}", flush=True)

        return launches[:limit]
