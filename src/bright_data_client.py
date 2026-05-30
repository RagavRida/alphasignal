"""
Bright Data Client — Unified async wrapper for all Bright Data products.

PRIMARY: Bright Data MCP Server (Remote, Streamable HTTP / SSE)
  Protocol: JSON-RPC 2.0 with session handshake
  Step 1 — POST initialize → get Mcp-Session-Id header
  Step 2 — POST tools/call with Mcp-Session-Id header

  Available tools: search_engine, scrape_as_html, scrape_as_markdown, extract

FALLBACK: Direct REST API
  SERP API (serp_api1): POST https://api.brightdata.com/request
  Proxy:                POST https://api.brightdata.com/request (datacenter_proxy1)
"""

import asyncio
import json
import os
import random
import re
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import quote_plus

import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential

BD_REQUEST_URL    = "https://api.brightdata.com/request"
GOOGLE_SEARCH_URL = "https://www.google.com/search"

# ── Activity broadcast callback (set by server.py) ───────────────────────────
# Signature: async fn({product, action, detail, ts})
_activity_cb = None

def set_activity_callback(cb):
    global _activity_cb
    _activity_cb = cb

async def _emit(product: str, action: str, detail: str = ""):
    if _activity_cb:
        try:
            await _activity_cb({
                "product": product,
                "action":  action,
                "detail":  detail[:80] if detail else "",
                "ts":      datetime.utcnow().strftime("%H:%M:%S"),
            })
        except Exception:
            pass

# ─────────────────────────────────────────────────────────────────────────────
#  Demo / mock data generators
# ─────────────────────────────────────────────────────────────────────────────

def _demo_serp(query: str) -> list[dict]:
    return [
        {"title": f"Breaking: {query} — Market Update",    "url": "https://techcrunch.com/article",  "snippet": f"Significant activity detected around {query}..."},
        {"title": f"{query} Q3 Earnings Preview",           "url": "https://bloomberg.com/news",       "snippet": f"Analysts expect strong results..."},
        {"title": f"Investors eye {query}",                 "url": "https://reuters.com/business",     "snippet": f"Institutional investors increasing positions..."},
        {"title": f"{query} Strategic Announcement",        "url": "https://wsj.com/articles",         "snippet": f"Company announced major expansion plans..."},
    ]


def _demo_jobs(company: str) -> list[dict]:
    roles = [
        ("Senior Software Engineer", "Engineering", "Senior"),
        ("ML Research Scientist",    "Engineering", "Senior"),
        ("Manufacturing Engineer",   "Operations",  "Mid"),
        ("Product Manager",          "Product",     "Mid"),
        ("Data Scientist",           "Engineering", "Senior"),
        ("Sales Engineer",           "Sales",       "Mid"),
    ]
    count = random.randint(60, 180)
    now   = datetime.utcnow()
    return [
        {
            "title":      r[0], "department": r[1], "level": r[2],
            "company":    company,
            "location":   random.choice(["Austin TX", "Fremont CA", "Seattle WA"]),
            "posted":     (now - timedelta(days=random.randint(0, 7))).isoformat(),
        }
        for r in random.choices(roles, k=min(count, 8))
    ] + [{"_total_count": count}]


def _demo_prices(company: str) -> dict:
    pm = {
        "Tesla":  [{"name": "Model 3 LR",    "price": 42990, "change_30d": -2.3}],
        "Apple":  [{"name": "iPhone 15 Pro", "price": 999,   "change_30d":  0.0}],
        "Nvidia": [{"name": "RTX 4090",      "price": 1599,  "change_30d": 12.5}],
        "BYD":    [{"name": "BYD Seal",      "price": 31990, "change_30d": -15.2}],
        "Meta":   [{"name": "Quest 3 128GB", "price": 499,   "change_30d": -50.0}],
    }
    return {"company": company, "products": pm.get(company, [{"name": f"{company} Product", "price": 999, "change_30d": 0}])}


def _demo_traffic(company: str) -> dict:
    base   = {"Tesla": 18.4, "Apple": 287.3, "Nvidia": 42.1, "BYD": 3.2, "Meta": 124.5}.get(company, 10.0)
    change = random.uniform(-15, 45)
    return {
        "company": company,
        "monthly_visits_millions": round(base * (1 + change / 100), 2),
        "monthly_visits_prev_millions": round(base, 2),
        "change_pct": round(change, 1),
        "source": "demo",
        "scraped_at": datetime.utcnow().isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
#  MCP Client — proper two-step session protocol
# ─────────────────────────────────────────────────────────────────────────────

MCP_PROTOCOL_VERSION = "2024-11-05"


class MCPClient:
    """
    Bright Data MCP server via Streamable HTTP (JSON-RPC 2.0).

    Protocol:
      1. POST initialize  → response header: Mcp-Session-Id
      2. POST tools/call  → with Mcp-Session-Id header in every request

    The session is auto-initialized on first use and reused until closed.
    """

    def __init__(self, mcp_url: str):
        self.mcp_url    = mcp_url
        self._session_id: Optional[str] = None
        self._http: Optional[aiohttp.ClientSession] = None
        self._req_id    = 0
        self._lock      = asyncio.Lock()   # serialize session init

    async def _get_http(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=90),
            )
        return self._http

    # ── Session management ────────────────────────────────────────────────────

    async def _ensure_session(self):
        """Initialize MCP session if we don't have a valid session ID yet."""
        if self._session_id:
            return
        async with self._lock:
            if self._session_id:   # double-checked locking
                return
            self._req_id += 1
            payload = {
                "jsonrpc": "2.0",
                "id":      self._req_id,
                "method":  "initialize",
                "params":  {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities":    {},
                    "clientInfo":      {"name": "alphasignal", "version": "1.0.0"},
                },
            }
            http = await self._get_http()
            async with http.post(
                self.mcp_url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept":       "application/json, text/event-stream",
                },
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(f"MCP initialize failed {resp.status}: {body[:200]}")

                # Extract session ID from response header
                self._session_id = resp.headers.get("Mcp-Session-Id", "")
                if not self._session_id:
                    # Some implementations include it in the body
                    text  = await resp.text()
                    match = re.search(r'"sessionId"\s*:\s*"([^"]+)"', text)
                    if match:
                        self._session_id = match.group(1)

                if not self._session_id:
                    raise RuntimeError("MCP initialize succeeded but no session ID returned")

    # ── Tool calling ──────────────────────────────────────────────────────────

    async def call_tool(self, tool_name: str, arguments: dict) -> Any:
        """
        Call a Bright Data MCP tool.
        Auto-initializes session on first call.
        Returns the first text content from the tool result.
        """
        await self._ensure_session()

        self._req_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id":      self._req_id,
            "method":  "tools/call",
            "params":  {"name": tool_name, "arguments": arguments},
        }
        http = await self._get_http()
        async with http.post(
            self.mcp_url,
            json=payload,
            headers={
                "Content-Type":   "application/json",
                "Accept":         "application/json, text/event-stream",
                "Mcp-Session-Id": self._session_id,
            },
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                # Session may have expired — reset and let caller retry
                if resp.status in (400, 401):
                    self._session_id = None
                raise RuntimeError(f"MCP {tool_name} error {resp.status}: {body[:200]}")

            text = await resp.text()
            return self._parse_sse_or_json(text, tool_name)

    def _parse_sse_or_json(self, text: str, tool_name: str) -> Any:
        """Parse SSE (event:message / data:...) or plain JSON response."""
        # SSE format: lines starting with "data:"
        for line in text.splitlines():
            if line.startswith("data:"):
                try:
                    obj = json.loads(line[5:].strip())
                    return self._extract_content(obj)
                except json.JSONDecodeError:
                    continue

        # Plain JSON fallback
        try:
            obj = json.loads(text)
            return self._extract_content(obj)
        except json.JSONDecodeError:
            return text

    def _extract_content(self, obj: dict) -> Any:
        """Extract text content from JSON-RPC response."""
        if "error" in obj:
            raise RuntimeError(f"MCP tool error: {obj['error']}")
        result  = obj.get("result", {})
        content = result.get("content", [])
        if content:
            # Return combined text from all text content items
            texts = [item["text"] for item in content if item.get("type") == "text"]
            combined = "\n".join(texts)
            # Try to parse as JSON if it looks like JSON
            stripped = combined.strip()
            if stripped.startswith("{") or stripped.startswith("["):
                try:
                    return json.loads(stripped)
                except json.JSONDecodeError:
                    pass
            return combined
        return result

    # ── Convenience wrappers ──────────────────────────────────────────────────

    async def search(self, query: str) -> Any:
        """search_engine tool — returns structured JSON with organic results."""
        await _emit("MCP Server", "search_engine", query)
        return await self.call_tool("search_engine", {"query": query})

    async def scrape_markdown(self, url: str) -> str:
        """scrape_as_markdown tool — Markdown content of any URL."""
        await _emit("Scraping Browser", "scrape_as_markdown", url)
        result = await self.call_tool("scrape_as_markdown", {"url": url})
        return str(result) if result else ""

    async def scrape_html(self, url: str) -> str:
        """scrape_as_html tool — Raw HTML of any URL."""
        # Note: this is used both for general pages AND as the Web Unlocker path.
        # Callers that need Web Unlocker should call access_secured_site() which
        # emits the correct 'Web Unlocker' label.
        await _emit("Web Scraper", "scrape_as_html", url)
        result = await self.call_tool("scrape_as_html", {"url": url})
        return str(result) if result else ""

    async def scrape_html_unlocker(self, url: str) -> str:
        """scrape_as_html via Web Unlocker path — for CAPTCHA-protected sites."""
        await _emit("Web Unlocker", "scrape_as_html", url)
        result = await self.call_tool("scrape_as_html", {"url": url})
        return str(result) if result else ""

    async def extract(self, url: str, schema: dict) -> Any:
        """extract tool — AI-powered structured data extraction."""
        await _emit("Web Unlocker", "extract", url)
        return await self.call_tool("extract", {"url": url, "schema": schema})

    async def close(self):
        if self._http and not self._http.closed:
            await self._http.close()


# ─────────────────────────────────────────────────────────────────────────────
#  Main Bright Data Client
# ─────────────────────────────────────────────────────────────────────────────

class BrightDataClient:
    """
    Unified async client for all Bright Data products.

    Priority order per operation:
      1. Bright Data Datasets API   — pre-built structured data (jobs, funding, reviews, traffic)
      2. MCP Server                 — live scrape via scrape_as_markdown / search_engine / extract
      3. Datacenter Proxy tunnel    — route our own requests through brd.superproxy.io
      4. REST API endpoint          — POST api.brightdata.com/request (zone-based)
      5. Demo mode                  — synthetic data, zero API calls
    """

    def __init__(
        self,
        api_token:    str  = "",
        serp_zone:    str  = "serp_api1",
        scraper_zone: str  = "datacenter_proxy1",
        mcp_url:      str  = "",
        demo_mode:    bool = False,
        proxy_host:   str  = "",
        proxy_port:   int  = 33335,
        proxy_user:   str  = "",
        proxy_pass:   str  = "",
    ):
        self.api_token    = api_token
        self.serp_zone    = serp_zone
        self.scraper_zone = scraper_zone
        self.demo_mode    = demo_mode
        self._rest: Optional[aiohttp.ClientSession] = None

        # Datacenter proxy tunnel (brd.superproxy.io)
        self._proxy_url: Optional[str] = None
        self._proxy_session: Optional[aiohttp.ClientSession] = None
        if proxy_host and proxy_user and proxy_pass and not demo_mode:
            self._proxy_url = f"http://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}"
            print(f"  [BrightData] Datacenter proxy enabled → {proxy_host}:{proxy_port}")

        # MCP client (primary live-scrape path)
        self.mcp: Optional[MCPClient] = None
        if mcp_url and not demo_mode:
            self.mcp = MCPClient(mcp_url)
            print(f"  [BrightData] MCP enabled → {mcp_url[:60]}…")
        elif not demo_mode:
            print(f"  [BrightData] MCP disabled — using proxy + REST API (zone: {serp_zone})")

    @classmethod
    def from_env(cls) -> "BrightDataClient":
        """Construct from environment variables."""
        return cls(
            api_token    = os.getenv("BRIGHT_DATA_API_TOKEN", ""),
            serp_zone    = os.getenv("BRIGHT_DATA_SERP_ZONE", "serp_api1"),
            scraper_zone = os.getenv("BRIGHT_DATA_SCRAPER_ZONE", "datacenter_proxy1"),
            mcp_url      = os.getenv("BRIGHT_DATA_MCP_URL", ""),
            demo_mode    = os.getenv("DEMO_MODE", "false").lower() == "true",
            proxy_host   = os.getenv("BRIGHT_DATA_PROXY_HOST", ""),
            proxy_port   = int(os.getenv("BRIGHT_DATA_PROXY_PORT", "33335")),
            proxy_user   = os.getenv("BRIGHT_DATA_PROXY_USER", ""),
            proxy_pass   = os.getenv("BRIGHT_DATA_PROXY_PASS", ""),
        )

    def _rest_headers(self) -> dict:
        return {
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {self.api_token}",
        }

    async def _get_rest(self) -> aiohttp.ClientSession:
        if self._rest is None or self._rest.closed:
            self._rest = aiohttp.ClientSession(
                headers=self._rest_headers(),
                timeout=aiohttp.ClientTimeout(total=60),
            )
        return self._rest

    async def _get_proxy_session(self) -> Optional[aiohttp.ClientSession]:
        """Return an aiohttp session that tunnels through the Bright Data datacenter proxy."""
        if not self._proxy_url:
            return None
        if self._proxy_session is None or self._proxy_session.closed:
            self._proxy_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=60),
            )
        return self._proxy_session

    async def proxy_fetch(self, url: str, headers: Optional[dict] = None) -> str:
        """
        Fetch a URL by routing the request through the Bright Data datacenter proxy.
        This is the direct proxy tunnel — traffic exits from a Bright Data IP.
        Used for: geo-sensitive pages, rate-limited APIs, sites that block cloud IPs.
        """
        await _emit("Datacenter Proxy", "GET", url)
        session = await self._get_proxy_session()
        if not session:
            return ""
        try:
            async with session.get(
                url,
                proxy=self._proxy_url,
                headers=headers or {"User-Agent": "Mozilla/5.0 (compatible; AlphaSignal/1.0)"},
                ssl=False,
            ) as resp:
                if resp.status == 200:
                    return await resp.text()
                return ""
        except Exception as e:
            print(f"  [Proxy fetch error] {url}: {e}")
            return ""

    async def close(self):
        if self._rest and not self._rest.closed:
            await self._rest.close()
        if self._proxy_session and not self._proxy_session.closed:
            await self._proxy_session.close()
        if self.mcp:
            await self.mcp.close()

    # ── SERP / search ─────────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    async def serp_search(self, query: str, num_results: int = 10) -> list[dict]:
        """
        Search web. PRIMARY: MCP search_engine. FALLBACK: SERP REST API.
        Returns list of {title, url, snippet}.
        """
        if self.demo_mode:
            await asyncio.sleep(0.05)
            return _demo_serp(query)

        # PRIMARY: MCP search_engine (returns structured JSON)
        if self.mcp:
            try:
                await _emit("MCP Server", "search_engine", query)
                result = await self.mcp.call_tool("search_engine", {"query": query})
                parsed = self._parse_mcp_search_result(result)
                if parsed:
                    return parsed[:num_results]
                print(f"  [MCP search] empty result, falling back to REST for: {query}")
            except Exception as e:
                print(f"  [MCP search → REST fallback] {e}")

        # FALLBACK: SERP REST API
        await _emit("SERP API", "google_search", query)
        return await self._serp_rest(query, num_results)

    def _parse_mcp_search_result(self, result: Any) -> list[dict]:
        """Parse search_engine tool output (structured JSON or markdown)."""
        # MCP search_engine returns JSON: {"organic": [{link, title, description}, ...]}
        if isinstance(result, dict):
            organic = result.get("organic", result.get("results", []))
            return [
                {
                    "title":   r.get("title", ""),
                    "url":     r.get("link", r.get("url", "")),
                    "snippet": r.get("description", r.get("snippet", "")),
                    "date":    r.get("date", ""),
                }
                for r in organic if r.get("title")
            ]

        # Text / markdown fallback
        if isinstance(result, str) and result:
            results = []
            for match in re.finditer(r'\[([^\]]+)\]\(([^)]+)\)', result):
                results.append({"title": match.group(1), "url": match.group(2), "snippet": ""})
            return results

        return []

    async def _serp_rest(self, query: str, num_results: int) -> list[dict]:
        """SERP API via direct POST /request."""
        google_url = f"{GOOGLE_SEARCH_URL}?q={quote_plus(query)}&num={num_results}&hl=en&gl=us"
        payload    = {"zone": self.serp_zone, "url": google_url, "format": "raw"}
        rest       = await self._get_rest()
        try:
            async with rest.post(BD_REQUEST_URL, json=payload) as resp:
                resp.raise_for_status()
                html = await resp.text()
            return self._parse_google_html(html)
        except Exception as e:
            print(f"  [SERP REST error] {e}")
            return []

    def _parse_google_html(self, html: str) -> list[dict]:
        try:
            from bs4 import BeautifulSoup
            soup    = BeautifulSoup(html, "lxml")
            results = []
            for div in soup.select("div.g, div.tF2Cxc, div[jscontroller]")[:15]:
                h3  = div.select_one("h3")
                a   = div.select_one("a[href]")
                snip = div.select_one("div.VwiC3b, span.aCOpRe, div[data-sncf='1']")
                if h3 and a:
                    results.append({
                        "title":   h3.get_text(strip=True),
                        "url":     a["href"],
                        "snippet": snip.get_text(strip=True) if snip else "",
                    })
            return results
        except Exception:
            return []

    # ── LinkedIn Jobs ─────────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    async def scrape_linkedin_jobs(self, company: str) -> list[dict]:
        """
        Scrape LinkedIn jobs. PRIMARY: MCP scrape_as_markdown.
        FALLBACK: SERP-based job count search.
        """
        if self.demo_mode:
            await asyncio.sleep(0.1)
            return _demo_jobs(company)

        linkedin_url = f"https://www.linkedin.com/jobs/search/?keywords={quote_plus(company)}&location=Worldwide&f_TPR=r604800"

        # PRIMARY: MCP scrape_as_markdown
        if self.mcp:
            try:
                md   = await self.mcp.scrape_markdown(linkedin_url)
                jobs = self._parse_jobs_from_markdown(md, company)
                if jobs:
                    return jobs
            except Exception as e:
                print(f"  [MCP jobs → SERP fallback] {e}")

        # FALLBACK: count from search results
        results = await self.serp_search(f"{company} jobs hiring site:linkedin.com", 10)
        count   = max(len(results) * 12, 20)
        return [{"_total_count": count, "_source": "serp_estimate"}]

    def _parse_jobs_from_markdown(self, md: str, company: str) -> list[dict]:
        if not md or len(md) < 100:
            return []
        jobs  = []
        for line in md.splitlines():
            line = line.strip()
            if len(line) < 5 or len(line) > 120:
                continue
            if any(kw in line.lower() for kw in ["engineer", "scientist", "manager", "analyst", "developer", "director", "researcher", "designer"]):
                title = re.sub(r"[\*#\[\]()\-·•]", "", line).strip()
                if 5 < len(title) < 100:
                    jobs.append({
                        "title":      title, "company":    company,
                        "department": self._infer_dept(title),
                        "level":      self._infer_level(title),
                        "location":   "", "posted": datetime.utcnow().isoformat(),
                    })
        if jobs:
            jobs.append({"_total_count": max(len(jobs) * 8, 30)})
        return jobs

    def _infer_dept(self, t: str) -> str:
        t = t.lower()
        if any(w in t for w in ["engineer", "developer", "scientist", "ml", "ai", "data", "devops", "research"]): return "Engineering"
        if any(w in t for w in ["sales", "account", "revenue", "business dev"]): return "Sales"
        if any(w in t for w in ["product", "program", "project"]): return "Product"
        if any(w in t for w in ["operations", "supply", "manufacturing", "logistics"]): return "Operations"
        return "Other"

    def _infer_level(self, t: str) -> str:
        t = t.lower()
        if any(w in t for w in ["senior", "staff", "principal", "lead", "director", "vp", "head", "chief"]): return "Senior"
        if any(w in t for w in ["junior", "associate", "entry", "intern"]): return "Junior"
        return "Mid"

    # ── Pricing ───────────────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    async def scrape_pricing_page(self, url: str, company: str) -> dict:
        """
        Scrape pricing. PRIMARY: MCP extract (structured) → scrape_as_markdown.
        FALLBACK: Direct proxy REST.
        """
        if self.demo_mode or not url:
            return _demo_prices(company)

        if self.mcp:
            try:
                # scrape_as_markdown → parse prices from text
                md = await self.mcp.scrape_markdown(url)
                products = self._prices_from_markdown(md, company)
                if products:
                    return {"company": company, "url": url,
                            "products": products, "scraped_at": datetime.utcnow().isoformat()}
            except Exception as e:
                print(f"  [MCP pricing → REST fallback] {e}")

        # FALLBACK: direct proxy
        rest    = await self._get_rest()
        payload = {"zone": self.scraper_zone, "url": url, "format": "raw"}
        try:
            async with rest.post(BD_REQUEST_URL, json=payload) as resp:
                resp.raise_for_status()
                html = await resp.text()
            return self._prices_from_html(html, company, url)
        except Exception as e:
            print(f"  [Pricing REST error] {e}")
            return _demo_prices(company)

    def _prices_from_markdown(self, md: str, company: str) -> list[dict]:
        products = []
        for m in re.finditer(r"\$\s*([\d,]+(?:\.\d+)?)", md or ""):
            val = float(m.group(1).replace(",", ""))
            if 10 < val < 500_000:
                ctx  = md[max(0, m.start() - 60):m.start()].strip().splitlines()
                name = re.sub(r"[*#\[\]]", "", ctx[-1] if ctx else "").strip()[:50] or company
                products.append({"name": name, "price": val, "change_30d": 0})
        return products[:5]

    def _prices_from_html(self, html: str, company: str, url: str) -> dict:
        try:
            from bs4 import BeautifulSoup
            soup     = BeautifulSoup(html, "lxml")
            products = []
            for el in soup.select("[class*='price'],[itemprop='price'],.price,.cost"):
                text = el.get_text(strip=True)
                m    = re.search(r"[\$£€]?([\d,]+\.?\d*)", text.replace(",", ""))
                if m:
                    val = float(m.group(1))
                    if 1 < val < 1_000_000:
                        products.append({"name": company, "price": val, "change_30d": 0})
            return {"company": company, "url": url,
                    "products": products[:5] or _demo_prices(company)["products"],
                    "scraped_at": datetime.utcnow().isoformat()}
        except Exception:
            return _demo_prices(company)

    # ── Secured sites (SEC, G2, credit) — Web Unlocker ─────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    async def access_secured_site(self, url: str) -> str:
        """
        Web Unlocker — bypasses CAPTCHAs and bot protection.
        Used for: SEC EDGAR, G2.com, Moodys, Glassdoor, Yahoo Finance.
        PRIMARY: MCP scrape_as_html (Web Unlocker). FALLBACK: proxy REST.
        """
        if self.demo_mode:
            return "<p>Total Revenue: $25.17B (+9% YoY)</p><p>Operating Income: $3.89B</p><p>Cash: $18.2B</p>"

        if self.mcp:
            try:
                return await self.mcp.scrape_html_unlocker(url) or ""
            except Exception as e:
                print(f"  [MCP Web Unlocker → REST fallback] {e}")

        # FALLBACK: direct proxy
        await _emit("Web Unlocker", "proxy_request", url)
        rest    = await self._get_rest()
        payload = {"zone": self.scraper_zone, "url": url, "format": "raw"}
        try:
            async with rest.post(BD_REQUEST_URL, json=payload) as resp:
                resp.raise_for_status()
                return await resp.text()
        except Exception as e:
            print(f"  [Unlocker REST error] {e}")
            return ""

    # ── Web traffic ───────────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    async def scrape_traffic_data(self, company: str) -> dict:
        """SimilarWeb traffic. PRIMARY: MCP scrape_as_markdown. FALLBACK: proxy REST."""
        if self.demo_mode:
            return _demo_traffic(company)

        domain_map = {
            "Tesla": "tesla.com", "Apple": "apple.com",
            "Nvidia": "nvidia.com", "BYD": "bydusa.com", "Meta": "meta.com",
        }
        domain = domain_map.get(company, f"{company.lower().replace(' ', '')}.com")
        sw_url = f"https://www.similarweb.com/website/{domain}/"

        # Step 1: Bright Data Datasets API (SimilarWeb dataset)
        dataset_record = await self.dataset_traffic(domain)
        if dataset_record:
            visits = float(dataset_record.get("visits", 0) or 0) / 1_000_000
            if visits > 0:
                return {
                    "company": company, "domain": domain,
                    "monthly_visits_millions": visits,
                    "monthly_visits_prev_millions": visits,
                    "change_pct": float(dataset_record.get("mom_unique_visitors", 0) or 0),
                    "source": "Bright Data Datasets (SimilarWeb)",
                    "scraped_at": datetime.utcnow().isoformat(),
                }

        # Step 2: MCP scrape_as_markdown
        if self.mcp:
            try:
                md = await self.mcp.scrape_markdown(sw_url)
                t  = self._traffic_from_markdown(md, company, domain)
                if t.get("monthly_visits_millions", 0) > 0:
                    return t
            except Exception as e:
                print(f"  [MCP traffic → proxy fallback] {e}")

        # Step 3: Datacenter Proxy tunnel — SimilarWeb blocks cloud IPs
        html = await self.proxy_fetch(sw_url)
        if html:
            t = self._traffic_from_html(html, company, domain)
            if t.get("monthly_visits_millions", 0) > 0:
                t["source"] = "Datacenter Proxy (SimilarWeb)"
                return t

        # Step 4: REST API endpoint fallback
        rest    = await self._get_rest()
        payload = {"zone": self.scraper_zone, "url": sw_url, "format": "raw"}
        try:
            async with rest.post(BD_REQUEST_URL, json=payload) as resp:
                html = await resp.text()
            return self._traffic_from_html(html, company, domain)
        except Exception:
            return _demo_traffic(company)

    def _traffic_from_markdown(self, md: str, company: str, domain: str) -> dict:
        if not md:
            return _demo_traffic(company)
        visits = 0.0
        change = 0.0
        m = re.search(r"([\d.]+)\s*([MB])\s*(?:visits|monthly|total)", md, re.I)
        if m:
            visits = float(m.group(1)) * (1000 if m.group(2) == "B" else 1)
        c = re.search(r"([+-]?\d+\.?\d*)\s*%", md)
        if c:
            change = float(c.group(1))
        if visits > 0:
            prev = visits / (1 + change / 100) if change != -100 else visits
            return {"company": company, "domain": domain,
                    "monthly_visits_millions": visits,
                    "monthly_visits_prev_millions": prev,
                    "change_pct": change,
                    "source": "MCP (SimilarWeb)",
                    "scraped_at": datetime.utcnow().isoformat()}
        return _demo_traffic(company)

    def _traffic_from_html(self, html: str, company: str, domain: str) -> dict:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "lxml")
            el   = soup.select_one(".wa-overview__scorecard-value, .totalVisits, [data-test='visits']")
            if el:
                m = re.search(r"([\d.]+)\s*([MBK]?)", el.get_text(strip=True))
                if m:
                    mult   = {"M": 1, "B": 1000, "K": 0.001}.get(m.group(2), 1)
                    visits = float(m.group(1)) * mult
                    return {"company": company, "domain": domain,
                            "monthly_visits_millions": visits,
                            "monthly_visits_prev_millions": visits,
                            "change_pct": 0.0,
                            "source": "REST (SimilarWeb)",
                            "scraped_at": datetime.utcnow().isoformat()}
        except Exception:
            pass
        return _demo_traffic(company)

    # ── Bright Data Datasets API ──────────────────────────────────────────────
    #
    # Bright Data maintains pre-built, continuously refreshed datasets that are
    # queried via POST /datasets/v3/trigger → poll /datasets/v3/progress/<id>
    # → GET /datasets/v3/download/<id>
    #
    # This is faster and more reliable than live scraping because the data is
    # already collected and structured. We use it when available and fall back
    # to live scraping when the dataset doesn't cover the target.

    DATASETS_BASE = "https://api.brightdata.com/datasets/v3"

    DATASET_IDS = {
        # LinkedIn job postings — fields: company, title, location, posted_date, seniority
        "linkedin_jobs":   "gd_lpfll7v5hcqtkxl6l4",
        # Crunchbase organizations — fields: name, funding_total, last_funding_type, last_funding_date
        "crunchbase_orgs": "gd_l1viktl72bvl7bjuj0",
        # G2 product reviews — fields: product, rating, review_text, date, reviewer_title
        "g2_reviews":      "gd_m66ep1ittlt87kng1",
        # SimilarWeb traffic — fields: domain, visits, visit_duration, pages_per_visit, bounce_rate
        "similarweb":      "gd_lz11l67o2cb3r0lkj3",
    }

    async def dataset_query(
        self,
        dataset_key: str,
        filters: list[dict],
        limit: int = 100,
    ) -> list[dict]:
        """
        Query a Bright Data pre-built dataset.

        Steps:
          1. POST /trigger  → snapshot_id
          2. Poll  /progress/<id> until ready
          3. GET   /download/<id> → JSONL records

        Args:
            dataset_key: key in DATASET_IDS (e.g. "linkedin_jobs")
            filters:     list of filter dicts, e.g. [{"company": "Coda"}]
            limit:       max records to return
        """
        if self.demo_mode or not self.api_token:
            return []

        dataset_id = self.DATASET_IDS.get(dataset_key)
        if not dataset_id:
            return []

        await _emit("Datasets API", f"query:{dataset_key}", str(filters)[:60])

        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type":  "application/json",
        }
        rest = await self._get_rest()

        # Step 1 — trigger snapshot
        try:
            async with rest.post(
                f"{self.DATASETS_BASE}/trigger",
                headers=headers,
                json={"dataset_id": dataset_id, "include_errors": False, "filters": filters},
            ) as resp:
                if resp.status not in (200, 201):
                    body = await resp.text()
                    print(f"  [Datasets trigger error {resp.status}]: {body[:120]}")
                    return []
                data = await resp.json()
                snapshot_id = data.get("snapshot_id", "")
            if not snapshot_id:
                return []
        except Exception as e:
            print(f"  [Datasets trigger exception]: {e}")
            return []

        # Step 2 — poll until ready (max 60s)
        for _ in range(12):
            await asyncio.sleep(5)
            try:
                async with rest.get(
                    f"{self.DATASETS_BASE}/progress/{snapshot_id}",
                    headers=headers,
                ) as resp:
                    prog = await resp.json()
                    status = prog.get("status", "")
                    if status == "ready":
                        break
                    if status in ("failed", "error"):
                        print(f"  [Datasets snapshot failed]: {prog}")
                        return []
            except Exception:
                pass
        else:
            print(f"  [Datasets timeout] snapshot {snapshot_id} did not finish in 60s")
            return []

        # Step 3 — download JSONL
        try:
            async with rest.get(
                f"{self.DATASETS_BASE}/download/{snapshot_id}",
                headers={**headers, "Accept": "application/x-ndjson"},
            ) as resp:
                if resp.status != 200:
                    return []
                text = await resp.text()
            records = []
            for line in text.splitlines():
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            return records[:limit]
        except Exception as e:
            print(f"  [Datasets download exception]: {e}")
            return []

    async def dataset_linkedin_jobs(self, company: str, limit: int = 50) -> list[dict]:
        """Query LinkedIn Job Postings dataset for a company."""
        records = await self.dataset_query(
            "linkedin_jobs",
            filters=[{"company": company}],
            limit=limit,
        )
        if not records:
            return []
        await _emit("Datasets API", "linkedin_jobs", f"{company} → {len(records)} jobs")
        return records

    async def dataset_funding(self, company: str) -> dict:
        """Query Crunchbase Organizations dataset for funding data."""
        records = await self.dataset_query(
            "crunchbase_orgs",
            filters=[{"name": company}],
            limit=5,
        )
        if not records:
            return {}
        r = records[0]
        await _emit("Datasets API", "crunchbase_orgs", f"{company} → {r.get('last_funding_type','')}")
        return r

    async def dataset_g2_reviews(self, product: str, limit: int = 30) -> list[dict]:
        """Query G2 Reviews dataset for a product."""
        records = await self.dataset_query(
            "g2_reviews",
            filters=[{"product": product}],
            limit=limit,
        )
        if not records:
            return []
        await _emit("Datasets API", "g2_reviews", f"{product} → {len(records)} reviews")
        return records

    async def dataset_traffic(self, domain: str) -> dict:
        """Query SimilarWeb dataset for a domain."""
        records = await self.dataset_query(
            "similarweb",
            filters=[{"domain": domain}],
            limit=1,
        )
        if not records:
            return {}
        await _emit("Datasets API", "similarweb_traffic", domain)
        return records[0]

    # ── Direct MCP tool call ──────────────────────────────────────────────────

    async def mcp_query(self, tool: str, params: dict) -> Any:
        """Call any MCP tool directly by name."""
        if self.mcp:
            return await self.mcp.call_tool(tool, params)
        return {"error": "MCP not configured"}
