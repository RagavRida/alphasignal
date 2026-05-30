"""
AlphaSignal Agent — ReAct-style autonomous agent loop.

The agent uses AI/ML API to DECIDE which Bright Data tools to call,
chains them based on intermediate results, and reasons before acting.

This is the difference from a scheduled pipeline:
  Pipeline: run all 7 detectors every hour (deterministic)
  Agent:    observe state → think → pick tools → act → observe → think again

Tool = a named Bright Data capability the agent can invoke by reasoning.
"""

import asyncio
import json
import os
from datetime import datetime
from typing import Any, Callable, Optional

from src.bright_data_client import BrightDataClient
from src.llm import OpenAI
from src import state


# ── Tool registry ────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "get_job_postings",
        "product": "Datasets API (LinkedIn Jobs)",
        "description": "Fetch structured LinkedIn job postings for a company. Returns count, role titles, departments, seniority levels. Use to detect hiring velocity or freeze.",
        "params": ["company"],
    },
    {
        "name": "get_funding_data",
        "product": "Datasets API (Crunchbase)",
        "description": "Fetch structured funding records for a company from Crunchbase dataset. Returns round size, stage, date, lead investors.",
        "params": ["company"],
    },
    {
        "name": "get_g2_reviews",
        "product": "Datasets API + Web Unlocker (G2)",
        "description": "Fetch recent G2 product reviews. Reveals switching intent, frustration signals, competitor mentions. High-confidence intent data.",
        "params": ["company"],
    },
    {
        "name": "get_traffic_data",
        "product": "Datasets API (SimilarWeb) + Datacenter Proxy",
        "description": "Fetch web traffic trends for a company's domain. Returns monthly visits, MoM change. Useful for growth or decline signals.",
        "params": ["company"],
    },
    {
        "name": "get_pricing_page",
        "product": "Web Scraper API",
        "description": "Scrape and diff a company's pricing page vs last cached baseline. Detects price changes as competitive signals.",
        "params": ["company", "pricing_url"],
    },
    {
        "name": "search_news",
        "product": "SERP API",
        "description": "Search recent news about a company via Google News. Finds acquisitions, launches, exec departures, regulatory actions.",
        "params": ["company", "query"],
    },
    {
        "name": "get_sec_filing",
        "product": "Web Unlocker (SEC EDGAR)",
        "description": "Fetch SEC 10-Q or 10-K filing for a public company. Returns revenue, cash burn, risk factors. Only valid for companies with a ticker.",
        "params": ["company", "ticker"],
    },
    {
        "name": "scrape_website",
        "product": "MCP Server (scrape_as_markdown)",
        "description": "Scrape any URL and return clean markdown. Use for company blog, job description pages, or press releases for personalization context.",
        "params": ["url"],
    },
    {
        "name": "enrich_tech_stack",
        "product": "Datacenter Proxy (BuiltWith) + MCP Server (homepage)",
        "description": "Detect what software a company uses: CRM, analytics, payments, frameworks, hosting. Use to score leads by tech fit (e.g. 'uses HubSpot = B2B SaaS buyer') and personalise outreach.",
        "params": ["domain"],
    },
    {
        "name": "find_github_leads",
        "product": "SERP API + MCP Server (GitHub orgs)",
        "description": "Find companies actively building on GitHub with a given tech stack. Returns org name, website, description. High buying intent: they are actively hiring engineers and shipping.",
        "params": ["tech_keywords"],
    },
    {
        "name": "find_producthunt_leads",
        "product": "SERP API + MCP Server (Product Hunt)",
        "description": "Find companies that recently launched on Product Hunt. Launch = growth mode = budget allocated and buying intent high.",
        "params": ["category_keywords"],
    },
    {
        "name": "trigger_outreach",
        "product": "internal + Resend",
        "description": "Trigger the full sales pipeline for a company and auto-send Step 1 email via Resend. Use when a company shows high buying intent (score >=70 or strong G2 switching signals). Sends immediately — no human click needed.",
        "params": ["company", "icp_hint"],
    },
    {
        "name": "record_finding",
        "product": "internal",
        "description": "Record a confirmed signal or thesis match into the findings log. Call this when you have enough evidence to make a claim.",
        "params": ["company", "thesis", "confidence", "evidence_summary", "direction"],
    },
    {
        "name": "stop",
        "product": "internal",
        "description": "Stop investigating this company for this cycle. Call when you have exhausted relevant signals or have already recorded a finding.",
        "params": ["reason"],
    },
]

TOOL_NAMES = {t["name"] for t in TOOLS}


# ── Thought broadcaster ──────────────────────────────────────────────────────

_thought_callbacks: list[Callable] = []

def subscribe_to_thoughts(cb: Callable):
    _thought_callbacks.append(cb)

async def _emit_thought(thought: dict):
    for cb in _thought_callbacks:
        try:
            await cb(thought)
        except Exception:
            pass


# ── Agent ────────────────────────────────────────────────────────────────────

class AlphaSignalAgent:
    """
    ReAct agent that investigates companies using Bright Data tools.

    Loop per company per cycle:
      OBSERVE  →  state snapshot (signals in DB, recent alerts, watch list context)
      THINK    →  AI/ML API decides: which tool to call next?
      ACT      →  call the tool (Bright Data product)
      OBSERVE  →  append result to context
      THINK    →  continue or stop?
    """

    MAX_STEPS = 6  # max tool calls per company per cycle

    def __init__(self, bd: BrightDataClient, demo_mode: bool = False):
        self.bd = bd
        self.demo_mode = demo_mode
        api_key  = os.getenv("AIML_API_KEY", "")
        base_url = os.getenv("AIML_BASE_URL", "https://api.aimlapi.com/v1")
        self.llm = OpenAI(api_key=api_key, base_url=base_url) if api_key else None
        self.model = os.getenv("AIML_MODEL", "claude-sonnet-4-20250514")

    # ── Main entry ────────────────────────────────────────────────────────────

    async def investigate(self, company: str, company_cfg: dict) -> list[dict]:
        """
        Run the full agent loop for one company. Returns list of findings.
        """
        findings = []
        context  = self._build_initial_context(company, company_cfg)

        await _emit_thought({
            "type":    "agent_start",
            "company": company,
            "ts":      _ts(),
            "message": f"Starting investigation of {company}",
        })

        for step in range(self.MAX_STEPS):
            # THINK
            decision = await self._think(company, context, step)

            await _emit_thought({
                "type":     "agent_thought",
                "company":  company,
                "step":     step + 1,
                "ts":       _ts(),
                "thought":  decision.get("reasoning", ""),
                "tool":     decision.get("tool", ""),
                "params":   decision.get("params", {}),
            })

            tool_name = decision.get("tool", "stop")
            params    = decision.get("params", {})

            if tool_name not in TOOL_NAMES:
                tool_name = "stop"
                params = {"reason": f"Unknown tool: {tool_name}"}

            if tool_name == "stop":
                await _emit_thought({
                    "type":    "agent_stop",
                    "company": company,
                    "ts":      _ts(),
                    "reason":  params.get("reason", "investigation complete"),
                })
                break

            if tool_name == "record_finding":
                finding = self._build_finding(company, params, context)
                findings.append(finding)
                state.save_alert(finding)
                await _emit_thought({
                    "type":      "agent_finding",
                    "company":   company,
                    "ts":        _ts(),
                    "thesis":    params.get("thesis", ""),
                    "confidence": params.get("confidence", 0),
                    "direction": params.get("direction", "WATCH"),
                })
                # Don't stop — agent may want to investigate further
                context["findings"].append(finding)
                continue

            # ACT — call the Bright Data tool
            result = await self._act(tool_name, params, company_cfg)

            await _emit_thought({
                "type":    "agent_observation",
                "company": company,
                "step":    step + 1,
                "ts":      _ts(),
                "tool":    tool_name,
                "product": next((t["product"] for t in TOOLS if t["name"] == tool_name), ""),
                "summary": _summarize_result(tool_name, result),
            })

            # OBSERVE — append result to context
            context["observations"].append({
                "step":   step + 1,
                "tool":   tool_name,
                "result": result,
            })

        return findings

    # ── Think ─────────────────────────────────────────────────────────────────

    async def _think(self, company: str, context: dict, step: int) -> dict:
        if not self.llm:
            return self._heuristic_decision(context, step)

        tools_desc = "\n".join(
            f'  - {t["name"]}({", ".join(t["params"])}): [{t["product"]}] {t["description"]}'
            for t in TOOLS
        )
        obs_text = "\n".join(
            f'  Step {o["step"]}: called {o["tool"]} → {_summarize_result(o["tool"], o["result"])}'
            for o in context["observations"]
        )
        findings_text = f'{len(context["findings"])} findings recorded so far'

        prompt = f"""You are an autonomous market intelligence agent investigating {company}.

Your goal: detect investment-grade signals — hiring surges, funding events, pricing changes,
competitor switching intent — and record confirmed thesis matches.

Available tools:
{tools_desc}

Current context:
- Company: {company}
- Category: {context.get("category", "unknown")}
- Prior signals in DB: {context.get("prior_signals", [])}
- Investigation step: {step + 1} of {self.MAX_STEPS}
- {findings_text}

Observations so far:
{obs_text if obs_text else "  None yet — this is the first step."}

Based on this, decide:
1. What is your reasoning about what to investigate next?
2. Which tool should you call?
3. What parameters?

If you have gathered enough evidence OR the step limit is close, call "record_finding" or "stop".

Respond ONLY with valid JSON, no markdown:
{{
  "reasoning": "one sentence explaining why you are choosing this tool",
  "tool": "tool_name",
  "params": {{...}}
}}"""

        try:
            resp = self.llm.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=400,
            )
            text = resp.choices[0].message.content.strip()
            # Strip markdown fences if present
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text)
        except Exception as e:
            print(f"  [Agent think error] {e}")
            return self._heuristic_decision(context, step)

    def _heuristic_decision(self, context: dict, step: int) -> dict:
        """Fallback when AI/ML API is unavailable — rule-based tool selection."""
        already_called = {o["tool"] for o in context["observations"]}
        priority = ["get_job_postings", "get_funding_data", "get_g2_reviews",
                    "get_traffic_data", "search_news"]
        for tool in priority:
            if tool not in already_called:
                return {
                    "reasoning": f"Heuristic: checking {tool} as part of standard investigation",
                    "tool": tool,
                    "params": {"company": context.get("company", "")},
                }
        return {"reasoning": "All standard tools called", "tool": "stop",
                "params": {"reason": "standard investigation complete"}}

    # ── Act ───────────────────────────────────────────────────────────────────

    async def _act(self, tool_name: str, params: dict, company_cfg: dict) -> Any:  # noqa: C901
        company = params.get("company", company_cfg.get("name", ""))
        try:
            if tool_name == "get_job_postings":
                result = await self.bd.dataset_linkedin_jobs(company)
                if not result:
                    result = await self.bd.scrape_linkedin_jobs(company)
                return result

            if tool_name == "get_funding_data":
                result = await self.bd.dataset_funding(company)
                if not result:
                    result = await self.bd.serp_search(f"{company} funding raised series")
                return result

            if tool_name == "get_g2_reviews":
                result = await self.bd.dataset_g2_reviews(company)
                if not result:
                    url = f"https://www.g2.com/products/{company.lower()}/reviews"
                    html = await self.bd.access_secured_site(url)
                    result = {"html_length": len(html), "source": "web_unlocker"}
                return result

            if tool_name == "get_traffic_data":
                return await self.bd.scrape_traffic_data(company)

            if tool_name == "get_pricing_page":
                url = params.get("pricing_url") or company_cfg.get("pricing_url", "")
                if url:
                    return await self.bd.scrape_pricing_page(url, company)
                return {"error": "no pricing_url configured"}

            if tool_name == "search_news":
                query = params.get("query", f"{company} news funding product launch")
                return await self.bd.serp_search(query)

            if tool_name == "get_sec_filing":
                ticker = params.get("ticker") or company_cfg.get("ticker", "")
                if ticker:
                    url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={ticker}&type=10-Q"
                    return await self.bd.access_secured_site(url)
                return {"error": "no ticker configured"}

            if tool_name == "scrape_website":
                url = params.get("url", "")
                if url:
                    return await self.bd.mcp.scrape_markdown(url) if self.bd.mcp else {}
                return {"error": "no url provided"}

            if tool_name == "enrich_tech_stack":
                from src.sales.tech_enricher import TechEnricher
                enricher = TechEnricher(self.bd)
                return await enricher.enrich(params.get("domain", ""))

            if tool_name == "find_github_leads":
                from src.sales.alt_sources import GitHubSourcer
                sourcer = GitHubSourcer(self.bd)
                keywords = params.get("tech_keywords", [])
                if isinstance(keywords, str):
                    keywords = [keywords]
                return await sourcer.find_companies(keywords)

            if tool_name == "find_producthunt_leads":
                from src.sales.alt_sources import ProductHuntSourcer
                sourcer = ProductHuntSourcer(self.bd)
                keywords = params.get("category_keywords", [])
                if isinstance(keywords, str):
                    keywords = [keywords]
                return await sourcer.find_recent_launches(keywords)

            if tool_name == "trigger_outreach":
                # Run the sales pipeline with auto_send=True — no human click needed
                try:
                    from src.sales.pipeline import SalesPipeline
                    icp_hint = params.get("icp_hint", f"companies similar to {company}")
                    pipeline  = SalesPipeline(demo_mode=self.demo_mode)
                    summary   = await pipeline.run(
                        icp_text=icp_hint,
                        max_leads=5,
                        auto_send=True,   # ← emails fire automatically via Resend
                    )
                    return {
                        "leads_found":  summary.get("leads_found", 0),
                        "emails_sent":  summary.get("emails_ready", 0),
                        "auto_send":    True,
                    }
                except Exception as e:
                    return {"error": str(e)}

        except Exception as e:
            return {"error": str(e)}

        return {"error": f"unknown tool: {tool_name}"}

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_initial_context(self, company: str, company_cfg: dict) -> dict:
        recent_signals = state.get_signal_history(company, "hiring_velocity", days=7)
        return {
            "company":       company,
            "category":      company_cfg.get("category", ""),
            "prior_signals": [s.get("signal_type") for s in recent_signals[:3]],
            "observations":  [],
            "findings":      [],
        }

    def _build_finding(self, company: str, params: dict, context: dict) -> dict:
        # Convert agent observations into proper signal objects
        tool_to_signal = {
            "get_job_postings":   "hiring_velocity",
            "get_funding_data":   "funding",
            "get_g2_reviews":     "news",
            "get_traffic_data":   "web_traffic",
            "get_pricing_page":   "pricing_change",
            "search_news":        "news",
            "get_sec_filing":     "financial_health",
            "scrape_website":     "news",
            "enrich_tech_stack":  "web_traffic",
        }
        signals = []
        for o in context["observations"]:
            tool = o.get("tool", "")
            sig_type = tool_to_signal.get(tool, "")
            if sig_type and sig_type not in [s.get("signal_type") for s in signals]:
                signals.append({
                    "signal_type":  sig_type,
                    "variance_pct": "",
                    "alert":        True,
                    "source":       next((t["product"] for t in TOOLS if t["name"] == tool), "Agent"),
                })

        return {
            "alert_id":        f"agent-{company}-{_ts_id()}",
            "company":         company,
            "alert_type":      params.get("thesis", "agent_finding"),
            "confidence_score": float(params.get("confidence", 70)),
            "recommendation":  {"direction": params.get("direction", "WATCH")},
            "narrative":       params.get("evidence_summary", "Agent-recorded finding"),
            "signals":         signals,
            "source":          "AlphaSignal Agent (ReAct loop)",
            "timestamp":       datetime.utcnow().isoformat() + "Z",
        }


# ── Utilities ─────────────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.utcnow().strftime("%H:%M:%S")

def _ts_id() -> str:
    return datetime.utcnow().strftime("%Y%m%d%H%M%S")

def _summarize_result(tool: str, result: Any) -> str:
    if isinstance(result, dict) and "error" in result:
        return f"error: {result['error']}"
    if tool == "get_job_postings" and isinstance(result, list):
        return f"{len(result)} job records"
    if tool == "get_funding_data" and isinstance(result, dict):
        return f"funding: {result.get('last_funding_type', '?')} {result.get('funding_total', '')}"
    if tool == "get_g2_reviews" and isinstance(result, list):
        return f"{len(result)} reviews"
    if tool == "get_traffic_data" and isinstance(result, dict):
        return f"traffic: {result.get('monthly_visits_millions', '?')}M/mo ({result.get('change_pct', 0):+.1f}%)"
    if tool == "search_news" and isinstance(result, list):
        return f"{len(result)} news results"
    if tool == "trigger_outreach" and isinstance(result, dict):
        sent = result.get("emails_sent", 0)
        leads = result.get("leads_found", 0)
        return f"pipeline ran — {leads} leads, {sent} emails auto-sent via Resend"
    if isinstance(result, str):
        return f"{len(result)} chars scraped"
    return "ok"
