"""
Personalization Context Fetcher
================================
Tool: Web Unlocker + MCP scrape_as_markdown

Fetches live context for each lead before email generation:
  - Latest blog post / press release
  - Recent job openings (reveals pain points)
  - Funding news (congratulate + pitch angle)
  - Tech stack signals (from job descriptions)

Returns PersonalizationContext with ranked talking points.
"""

import asyncio
import re
from datetime import datetime
from typing import Optional

from src.bright_data_client import BrightDataClient
from src.sales.models import Lead, PersonalizationContext


class ContextFetcher:

    def __init__(self, bd: BrightDataClient):
        self.bd = bd

    async def fetch(self, lead: Lead) -> PersonalizationContext:
        """Fetch all personalization context for a lead in parallel."""
        ctx = PersonalizationContext(lead_id=lead.id)

        tasks = [
            self._fetch_blog(lead, ctx),
            self._fetch_jobs(lead, ctx),
            self._fetch_funding_news(lead, ctx),
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

        ctx.talking_points = self._rank_talking_points(ctx, lead)
        return ctx

    async def _fetch_blog(self, lead: Lead, ctx: PersonalizationContext):
        """Fetch the company's latest blog post or press release."""
        if not lead.domain:
            return

        blog_urls = [
            f"https://{lead.domain}/blog",
            f"https://{lead.domain}/news",
            f"https://{lead.domain}/press",
        ]

        # First try SERP to find the latest post
        try:
            results = await self.bd.serp_search(
                f"site:{lead.domain} blog OR news OR press release 2025",
                num_results=3,
            )
            if results:
                top = results[0]
                ctx.blog_title   = top.get("title", "")
                ctx.blog_url     = top.get("url", "")
                ctx.blog_excerpt = top.get("snippet", "")[:300]

                # Try to scrape the actual post for more detail
                if ctx.blog_url and self.bd.mcp:
                    try:
                        md = await self.bd.mcp.scrape_markdown(ctx.blog_url)
                        if md and len(md) > 200:
                            # Extract first meaningful paragraph
                            paras = [p.strip() for p in md.split("\n\n") if len(p.strip()) > 80]
                            if paras:
                                ctx.blog_excerpt = paras[0][:400]
                    except Exception:
                        pass
        except Exception as e:
            print(f"    [ContextFetcher] blog error for {lead.domain}: {e}")

    async def _fetch_jobs(self, lead: Lead, ctx: PersonalizationContext):
        """Fetch recent job postings to infer pain points and needs."""
        if not lead.company_name:
            return
        try:
            results = await self.bd.serp_search(
                f'"{lead.company_name}" jobs hiring 2025 site:linkedin.com OR site:greenhouse.io OR site:lever.co',
                num_results=8,
            )
            job_titles = []
            pain_hints = []
            for r in results:
                title   = r.get("title", "")
                snippet = r.get("snippet", "")
                text    = (title + " " + snippet).lower()

                # Extract job titles
                jt_match = re.search(r"(?:hiring|looking for|opening)[:\s]+([^|,\n]{5,50})", text, re.I)
                if jt_match:
                    job_titles.append(jt_match.group(1).strip())

                # Infer pain points from job requirements
                pain_map = {
                    "scale": "Scaling infrastructure",
                    "automat": "Seeking process automation",
                    "integrat": "Integration challenges",
                    "enterprise": "Moving upmarket to enterprise",
                    "revenu": "Accelerating revenue growth",
                    "pipeline": "Building sales pipeline",
                    "outbound": "Ramping outbound motion",
                    "data": "Data and analytics gap",
                }
                for kw, pain in pain_map.items():
                    if kw in text and pain not in pain_hints:
                        pain_hints.append(pain)

            ctx.job_openings = job_titles[:5]
            ctx.pain_points  = pain_hints[:4]
        except Exception as e:
            print(f"    [ContextFetcher] jobs error for {lead.company_name}: {e}")

    async def _fetch_funding_news(self, lead: Lead, ctx: PersonalizationContext):
        """Fetch recent funding news for congratulatory angle."""
        if not lead.company_name:
            return
        try:
            results = await self.bd.serp_search(
                f'"{lead.company_name}" funding raised million 2025',
                num_results=5,
            )
            for r in results:
                text = r.get("title", "") + " " + r.get("snippet", "")
                m    = re.search(r"\$\s*([\d.]+)\s*([MBK])", text)
                if m:
                    amount = f"${m.group(1)}{m.group(2)}"
                    ctx.recent_funding = f"Congratulations on raising {amount}!"
                    ctx.achievements.append(f"Recently raised {amount} in funding")
                    break

            # Also check for product launches, awards, milestones
            results2 = await self.bd.serp_search(
                f'"{lead.company_name}" launched OR milestone OR partnership OR award 2025',
                num_results=3,
            )
            for r in results2:
                title = r.get("title", "")
                if any(kw in title.lower() for kw in ["launch", "partner", "award", "milestone", "announce"]):
                    ctx.achievements.append(title[:120])
                    break
        except Exception as e:
            print(f"    [ContextFetcher] funding error for {lead.company_name}: {e}")

    def _rank_talking_points(self, ctx: PersonalizationContext, lead: Lead) -> list[str]:
        """Rank and combine all context into ordered talking points for the email."""
        points = []

        # Most powerful: recent funding (freshest, most congratulatory)
        if ctx.recent_funding:
            points.append(ctx.recent_funding)

        # Blog/press release — shows you did your homework
        if ctx.blog_title:
            points.append(f"Read your recent piece: \"{ctx.blog_title[:80]}\"")

        # Pain points inferred from jobs — most relevant to pitch
        for p in ctx.pain_points[:2]:
            points.append(f"Noticed you're hiring for {p.lower()}")

        # Other achievements
        for a in ctx.achievements[:1]:
            if a not in points:
                points.append(a[:100])

        # Hiring signals (show growth awareness)
        for job in ctx.job_openings[:2]:
            points.append(f"Hiring: {job}")

        return points[:5]
