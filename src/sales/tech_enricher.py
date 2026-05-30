"""
Tech Stack Enricher
====================
Detects what software a company uses (CRM, analytics, frameworks, hosting)
by scraping BuiltWith and Wappalyzer via Bright Data Datacenter Proxy.

Why proxy: BuiltWith blocks cloud IPs aggressively. A residential/datacenter
proxy exits from a clean IP that bypasses the block.

Output per domain:
  {
    "crm":        ["HubSpot", "Salesforce"],
    "analytics":  ["Mixpanel", "Segment"],
    "framework":  ["React", "Next.js"],
    "hosting":    ["AWS", "Vercel"],
    "marketing":  ["Intercom", "Mailchimp"],
    "payments":   ["Stripe"],
    "raw_stack":  ["HubSpot", ...],   # flat deduped list
  }
"""

import asyncio
import re
from typing import Optional

from src.bright_data_client import BrightDataClient


# Known tech → category mapping (grows over time)
TECH_CATEGORIES: dict[str, str] = {
    # CRM / Sales
    "hubspot":        "crm",
    "salesforce":     "crm",
    "pipedrive":      "crm",
    "zoho crm":       "crm",
    "close.io":       "crm",
    "attio":          "crm",
    # Analytics
    "mixpanel":       "analytics",
    "amplitude":      "analytics",
    "segment":        "analytics",
    "heap":           "analytics",
    "posthog":        "analytics",
    "google analytics": "analytics",
    "hotjar":         "analytics",
    # Marketing / Email
    "intercom":       "marketing",
    "mailchimp":      "marketing",
    "sendgrid":       "marketing",
    "klaviyo":        "marketing",
    "marketo":        "marketing",
    "outreach":       "marketing",
    "apollo":         "marketing",
    # Payments
    "stripe":         "payments",
    "braintree":      "payments",
    "chargebee":      "payments",
    "recurly":        "payments",
    # Frontend frameworks
    "react":          "framework",
    "next.js":        "framework",
    "vue":            "framework",
    "angular":        "framework",
    "svelte":         "framework",
    # Hosting / Infra
    "aws":            "hosting",
    "vercel":         "hosting",
    "cloudflare":     "hosting",
    "heroku":         "hosting",
    "google cloud":   "hosting",
    "azure":          "hosting",
    # Support
    "zendesk":        "support",
    "freshdesk":      "support",
    "drift":          "support",
    # Product
    "notion":         "productivity",
    "linear":         "productivity",
    "jira":           "productivity",
    "asana":          "productivity",
}


class TechEnricher:
    """
    Enriches a company domain with its detected tech stack.
    Uses Bright Data Datacenter Proxy to bypass BuiltWith's IP blocks.
    Falls back to scraping the company homepage for meta/script tags.
    """

    BUILTWITH_URL = "https://builtwith.com/{domain}"

    def __init__(self, bd: BrightDataClient):
        self.bd = bd

    async def enrich(self, domain: str) -> dict:
        """
        Returns categorized tech stack dict for the given domain.
        """
        domain = domain.lstrip("www.").strip("/").lower()
        if not domain:
            return {}

        # Step 1: BuiltWith via Datacenter Proxy
        stack = await self._from_builtwith(domain)

        # Step 2: Homepage script/meta scrape via MCP if BuiltWith empty
        if not stack:
            stack = await self._from_homepage(domain)

        return self._categorize(stack)

    async def _from_builtwith(self, domain: str) -> list[str]:
        url  = self.BUILTWITH_URL.format(domain=domain)
        html = await self.bd.proxy_fetch(url)
        if not html or len(html) < 500:
            # Try Web Unlocker fallback
            html = await self.bd.access_secured_site(url)
        return self._parse_builtwith_html(html)

    def _parse_builtwith_html(self, html: str) -> list[str]:
        if not html:
            return []
        # BuiltWith lists technologies in <span class="tech-name"> or similar
        techs = set()
        for pattern in [
            r'class="[^"]*tech[^"]*"[^>]*>([^<]{2,40})</span>',
            r'<h\d[^>]*class="[^"]*profile[^"]*"[^>]*>([^<]{2,40})</h\d>',
            r'"name"\s*:\s*"([A-Z][^"]{1,40})"',   # JSON-LD tech names
        ]:
            for m in re.finditer(pattern, html, re.I):
                name = m.group(1).strip()
                if 2 < len(name) < 45 and not name.startswith("<"):
                    techs.add(name)
        return list(techs)[:40]

    async def _from_homepage(self, domain: str) -> list[str]:
        """Scrape homepage <script src> and meta tags for tech signals."""
        url  = f"https://{domain}"
        html = ""
        if self.bd.mcp:
            try:
                html = await self.bd.mcp.scrape_html(url)
            except Exception:
                pass
        if not html:
            html = await self.bd.proxy_fetch(url)

        techs = set()
        # Script src patterns
        script_patterns = {
            "segment":       r"segment\.com|analytics\.js",
            "mixpanel":      r"mixpanel",
            "intercom":      r"intercom",
            "hubspot":       r"hubspot|hs-scripts",
            "stripe":        r"stripe\.com/v",
            "google analytics": r"google-analytics|gtag",
            "hotjar":        r"hotjar",
            "amplitude":     r"amplitude",
            "drift":         r"drift\.com",
            "zendesk":       r"zdassets|zendesk",
            "react":         r"react\.production|react-dom",
            "next.js":       r"_next/static",
            "vercel":        r"vercel\.app|_vercel",
            "cloudflare":    r"cloudflare",
        }
        for tech, pattern in script_patterns.items():
            if re.search(pattern, html, re.I):
                techs.add(tech.title())
        return list(techs)

    def _categorize(self, raw: list[str]) -> dict:
        if not raw:
            return {}
        categorized: dict[str, list[str]] = {}
        for tech in raw:
            key = tech.lower()
            cat = next(
                (TECH_CATEGORIES[k] for k in TECH_CATEGORIES if k in key),
                "other",
            )
            if cat != "other":
                categorized.setdefault(cat, [])
                if tech not in categorized[cat]:
                    categorized[cat].append(tech)

        categorized["raw_stack"] = list({t for t in raw})[:30]
        return categorized
