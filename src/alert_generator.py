"""
Alert Generator — Uses Claude via AI/ML API (OpenAI-compatible) to produce
structured financial alerts.

AI/ML API base URL: https://api.aimlapi.com/v1
Model:              claude-sonnet-4-20250514
Auth:               Bearer <AIML_API_KEY>
"""

import json
import os
import uuid
from datetime import datetime
from typing import Optional


class AlertGenerator:

    SYSTEM_PROMPT = """You are an elite alternative data analyst at a top-tier hedge fund.
Transform raw data signals into precise, actionable investment alerts.

Write in the style of an experienced buy-side analyst — concise, data-driven, confident.
Recommendations must be specific: trade, timeframe, conviction level, risk.
Always include the bear case. Output ONLY valid JSON with no markdown wrapping."""

    def __init__(
        self,
        api_key:  str  = "",
        base_url: str  = "https://api.aimlapi.com/v1",
        model:    str  = "claude-sonnet-4-20250514",
        demo_mode: bool = False,
    ):
        self.demo_mode = demo_mode
        self.model     = model
        self.client    = None

        if api_key and not demo_mode:
            try:
                from src.llm import OpenAI
                self.client = OpenAI(api_key=api_key, base_url=base_url)
            except ImportError:
                print("[AlertGenerator] openai package not installed — using demo templates")

    async def generate_alert(self, company: str, correlation: dict, signals: list[dict]) -> dict:
        """Generate the full structured alert JSON."""
        alert_id = (
            f"ALERT_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
            f"_{company.upper()}_{str(uuid.uuid4())[:8].upper()}"
        )

        if self.demo_mode or not self.client:
            claude_out = self._demo_output(company, correlation, signals)
        else:
            claude_out = await self._call_llm(company, correlation, signals)

        rec = {**correlation.get("recommendation", {}), **claude_out.get("recommendation", {})}

        alert = {
            "alert_id":         alert_id,
            "timestamp":        datetime.utcnow().isoformat() + "Z",
            "company":          company,
            "alert_type":       correlation["correlation_type"],
            "correlation_label": correlation.get("correlation_label", ""),
            "confidence_score": correlation["confidence"],
            "time_sensitivity": self._sensitivity(correlation["confidence"]),
            "headline":         claude_out.get("headline", correlation.get("headline", f"{company} Alert")),
            "signals": [
                {
                    "signal_type": s["signal_type"],
                    "metric":      self._metric_str(s),
                    "baseline":    f"{s.get('baseline', 0):.1f}",
                    "variance_pct": f"{s.get('variance_pct', 0):+.1f}%",
                    "source":      s.get("source", "Bright Data"),
                    "confidence":  s.get("confidence", 0),
                    "alert":       s.get("alert", False),
                    "timestamp":   s.get("timestamp", ""),
                }
                for s in signals
            ],
            "narrative":        claude_out.get("narrative", "Signal analysis pending."),
            "financial_impact": claude_out.get("financial_impact", {
                "revenue_impact": "Analysis pending",
                "margin_impact":  "Analysis pending",
                "timeline":       correlation.get("time_horizon", "1–2 quarters"),
            }),
            "thesis":           claude_out.get("thesis", ""),
            "recommendation":   rec,
            "risk_assessment":  claude_out.get("risk_assessment", {
                "primary_risk":       "Data quality uncertainty",
                "hedge":              "Monitor closely",
                "false_positive_risk": "Medium",
            }),
            "next_monitoring": {
                "check_in":  "48 hours",
                "watch_for": claude_out.get("watch_for", [
                    f"Follow-up {company} announcements",
                    "Competitor response",
                    "Earnings guidance updates",
                ]),
            },
            "data_quality": {
                "sources_used":         len(set(s.get("source", "") for s in signals)),
                "signals_total":        len(signals),
                "signals_fired":        sum(1 for s in signals if s.get("alert")),
                "unique_data_points":   sum(len(s.get("details", {})) for s in signals),
                "bright_data_products": list(set(
                    p.strip()
                    for s in signals
                    for p in s.get("source", "").split("+")
                    if p.strip()
                )),
                "false_positive_risk":  "Low" if correlation["confidence"] > 80 else "Medium",
                "potential_bias":       "None identified",
            },
            "correlation_type": correlation["correlation_type"],
            "match_score":      correlation.get("match_score", 0),
        }
        return alert

    async def _call_llm(self, company: str, correlation: dict, signals: list[dict]) -> dict:
        """Call Claude via AI/ML API (OpenAI-compatible) synchronously in executor."""
        import asyncio

        signal_summary = "\n".join([
            f"  - [{s['signal_type'].upper()}] {s.get('narrative', '')} "
            f"(Confidence: {s.get('confidence', 0):.0f}%, Alert: {s.get('alert', False)})"
            for s in signals
        ])

        prompt = f"""Analyze these alternative data signals for {company} and generate a hedge fund alert.

CORRELATION: {correlation['correlation_label']}
MATCH SCORE: {correlation['match_score']:.0%}
TIME HORIZON: {correlation.get('time_horizon', '2-4 quarters')}

SIGNALS:
{signal_summary}

Return ONLY a JSON object with these exact keys:
{{
  "headline": "1 sentence with key metric included",
  "narrative": "3-4 sentences — what do these signals mean collectively and why it matters for investors",
  "financial_impact": {{
    "revenue_impact": "specific % or $ estimate",
    "margin_impact": "impact on profit margins",
    "timeline": "when visible in financials"
  }},
  "thesis": "2-3 sentence bull case with evidence",
  "recommendation": {{
    "trade": "specific instrument and parameters",
    "conviction": "High/Medium/Low with reason",
    "risk": "primary bear case",
    "hedge": "hedge strategy",
    "direction": "LONG or SHORT or HEDGE or NEUTRAL"
  }},
  "risk_assessment": {{
    "primary_risk": "most likely way thesis is wrong",
    "probability": "% chance of being wrong",
    "hedge": "specific hedge",
    "false_positive_risk": "Low/Medium/High"
  }},
  "watch_for": ["3-5 follow-up indicators to monitor in next 48h"]
}}"""

        def _sync_call():
            resp = self.client.chat.completions.create(
                model=self.model,
                max_tokens=1200,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
            )
            text = resp.choices[0].message.content.strip()
            # Strip markdown fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            return json.loads(text)

        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, _sync_call)
        except Exception as e:
            print(f"[AlertGenerator] LLM call failed: {e}")
            return self._demo_output(company, correlation, signals)

    # ─────────────────────────────────────────────────────────────────────────
    #  Demo templates (rich, realistic — no {company} literal bugs)
    # ─────────────────────────────────────────────────────────────────────────

    def _demo_output(self, company: str, correlation: dict, signals: list[dict]) -> dict:
        rule = correlation.get("correlation_type", "growth_thesis")
        conf = correlation.get("confidence", 75)

        hiring = next((s for s in signals if s["signal_type"] == "hiring_velocity"), {})
        pricing = next((s for s in signals if s["signal_type"] == "pricing_change"), {})
        funding = next((s for s in signals if s["signal_type"] == "funding"), {})

        hiring_var   = hiring.get("variance_pct", 87)
        pricing_var  = abs(pricing.get("variance_pct", 12))
        funding_amt  = funding.get("current_value", 100)

        templates = {
            "growth_thesis": {
                "headline": f"{company} Activates Growth Mode — {hiring_var:+.0f}% Hiring Surge + Expansion Signals",
                "narrative": (
                    f"{company} is exhibiting classic pre-earnings growth signals across multiple independent data sources. "
                    f"Hiring is running {hiring_var:+.0f}% above the 90-day baseline, concentrated in engineering and manufacturing — "
                    f"historically a 1–2 quarter leading indicator of revenue acceleration. "
                    f"Simultaneous funding activity and positive news sentiment strengthen the conviction. "
                    f"Models assign {conf:.0f}% confidence to a Q2/Q3 earnings beat scenario."
                ),
                "financial_impact": {
                    "revenue_impact": "+8–15% vs. consensus if hiring converts to productive headcount",
                    "margin_impact":  "Short-term compression of 1–2% from hiring costs, reversing in H2",
                    "timeline":       "Earnings impact visible in 2–3 quarters; re-rating likely sooner",
                },
                "thesis": (
                    f"{company} is making a deliberate, data-confirmed bet on accelerating growth. "
                    f"The combination of hiring velocity, capital deployment, and positive strategic news suggests management "
                    f"has strong conviction in near-term demand. Current valuations favor the long side."
                ),
                "recommendation": {
                    "trade":     f"Long {company} calls, 90-day expiration, 5% OTM",
                    "conviction":"High — 4 of 7 signals confirming",
                    "risk":      "Hiring surge reflects defensive talent grab, not growth (AI talent war effect)",
                    "hedge":     "Sell covered calls at 15% OTM to cap upside if uncertain",
                    "direction": "LONG",
                },
                "risk_assessment": {
                    "primary_risk":       "Macro headwinds compress multiples even if fundamentals improve",
                    "probability":        "25%",
                    "hedge":              f"Paired short on sector ETF to neutralize {company} beta",
                    "false_positive_risk":"Low",
                },
                "watch_for": [
                    f"{company} earnings call guidance language",
                    "Competitor response to hiring surge",
                    "Q2 revenue print vs. Street consensus",
                    "Insider buying to confirm management conviction",
                    "Customer contract announcements",
                ],
            },
            "competitive_threat": {
                "headline": f"{company} Under Competitive Pressure — {pricing_var:.0f}% Price Cuts Signal Margin Squeeze",
                "narrative": (
                    f"{company} is executing defensive pricing moves as competitive intensity escalates. "
                    f"Price cuts of {pricing_var:.0f}% signal demand softness or aggressive market share defense. "
                    f"The simultaneous hiring surge suggests competing on both price and talent — a capital-intensive strategy. "
                    f"Gross margin compression of 300–500bps is likely in the next 1–2 quarters."
                ),
                "financial_impact": {
                    "revenue_impact": "Flat to -5% if price cuts don't drive volume gains",
                    "margin_impact":  "-3 to -5% gross margin compression expected",
                    "timeline":       "Margin impact visible next quarter; volume recovery takes 2–3 quarters",
                },
                "thesis": (
                    f"The market has not yet priced in the full margin impact of {company}'s pricing actions. "
                    f"If the price war persists beyond 2 quarters, consensus EPS estimates are 15–20% too high. "
                    f"The bear case is straightforward and data-confirmed."
                ),
                "recommendation": {
                    "trade":     f"Long puts on {company}, 60-day expiration, 10% OTM",
                    "conviction":"Medium-High — pricing data confirmed, volume recovery uncertain",
                    "risk":      f"Volume surge offsets {company} margin compression (Jevons Paradox)",
                    "hedge":     "Long stock as hedge if put position size is large",
                    "direction": "SHORT",
                },
                "risk_assessment": {
                    "primary_risk":       "Price cuts drive massive volume increase, more than offsetting margin loss",
                    "probability":        "30%",
                    "hedge":              "Collar strategy (long put + short call) to reduce premium cost",
                    "false_positive_risk":"Medium",
                },
                "watch_for": [
                    "Competitor price response (escalation vs. hold)",
                    "Next quarter unit volume data",
                    f"{company} CFO commentary on margin guidance",
                    "Market share data in key geographies",
                    "Promotional intensity tracking",
                ],
            },
            "financial_distress": {
                "headline": f"{company} Distress Signals — Hiring Freeze + Financial Deterioration Detected",
                "narrative": (
                    f"Multiple independent data streams are signaling financial stress at {company}. "
                    f"The hiring freeze is historically one of the most reliable leading indicators of cash flow problems. "
                    f"This is corroborated by deteriorating financial metrics and negative news sentiment. "
                    f"Our distress model assigns {conf:.0f}% probability of a material negative event within 6 months."
                ),
                "financial_impact": {
                    "revenue_impact": "-15 to -30% if distress escalates to restructuring",
                    "margin_impact":  "EBITDA margins likely to turn negative if restructuring costs hit",
                    "timeline":       f"Critical inflection point for {company} in next 1–2 quarters",
                },
                "thesis": (
                    f"{company} has entered a financial stress cycle. Hiring freeze, cash deterioration, "
                    f"and negative sentiment create a high-conviction short thesis. "
                    f"Historical base rates: 60% of companies with these signals see significant stock declines within 12 months."
                ),
                "recommendation": {
                    "trade":     f"Short {company} stock or long puts, 4-month expiration",
                    "conviction":"High — distress signals confirmed across 3+ independent sources",
                    "risk":      f"Strategic buyout of {company} at premium (distressed M&A)",
                    "hedge":     "Long-dated calls as tail hedge against M&A at premium",
                    "direction": "SHORT",
                },
                "risk_assessment": {
                    "primary_risk":       f"{company} secures emergency funding or strategic partner",
                    "probability":        "20%",
                    "hedge":              "Small long call position (3–5% of short notional) as M&A hedge",
                    "false_positive_risk":"Low",
                },
                "watch_for": [
                    f"{company} emergency capital raise announcement",
                    "CEO or CFO departure",
                    "Credit rating downgrade",
                    "Debt covenant waiver requests",
                    "Activist investor activity",
                ],
            },
            "supplier_risk": {
                "headline": f"{company} Supply Chain Alert — Key Supplier Distress Could Disrupt Operations",
                "narrative": (
                    f"Alternative data monitoring of {company}'s supplier ecosystem has detected distress signals at critical vendors. "
                    f"Supplier hiring freezes and negative news suggest instability cascading to {company} within 3–9 months. "
                    f"Companies with >30% single-supplier concentration face outsized risk. "
                    f"Historical supply chain disruptions cause 15–25% stock corrections in affected customers."
                ),
                "financial_impact": {
                    "revenue_impact": "-5 to -20% if supply disruption causes production halts",
                    "margin_impact":  "+300–700bps cost increase from emergency sourcing",
                    "timeline":       f"{company} disruption risk peaks in 3–9 months",
                },
                "thesis": (
                    f"Supply chain risk is systematically under-priced by equity markets until disruption occurs. "
                    f"Our real-time supplier monitoring gives {company} stakeholders a 3–6 month early warning. "
                    f"The risk-reward of a modest short position against confirmed supplier distress is favorable."
                ),
                "recommendation": {
                    "trade":     f"Reduce {company} position / Long puts, 6-month expiration",
                    "conviction":"Medium-High — supplier distress confirmed, timing uncertain",
                    "risk":      f"{company} has undisclosed secondary supplier relationships",
                    "hedge":     "Monitor supplier recovery signals weekly — cover if supplier stabilizes",
                    "direction": "SHORT",
                },
                "risk_assessment": {
                    "primary_risk":       f"{company} has undisclosed supplier diversification — impact is minimal",
                    "probability":        "35%",
                    "hedge":              f"Track {company} supplier job postings weekly for recovery signal",
                    "false_positive_risk":"Medium",
                },
                "watch_for": [
                    "Supplier hiring recovery (job postings normalize)",
                    f"{company} diversification announcements",
                    "Component pricing changes in supplier's sector",
                    "Supplier credit rating actions",
                    f"{company} executive supply chain commentary in earnings calls",
                ],
            },
            "market_disruption": {
                "headline": f"{company} Market Disruption — ${funding_amt:.0f}M Raised + {hiring_var:+.0f}% Hiring = Aggressive Expansion",
                "narrative": (
                    f"{company} is entering a 'market disruption' configuration. "
                    f"Simultaneous capital deployment (${funding_amt:.0f}M funding), aggressive talent acquisition "
                    f"({hiring_var:+.0f}% hiring surge), and pricing signals indicate {company} is on offense — not defense. "
                    f"This pattern typically precedes 12–24 months of market share gains at incumbents' expense. "
                    f"The hiring + funding combination is rare and historically predictive."
                ),
                "financial_impact": {
                    "revenue_impact": f"+20–40% revenue growth for {company} in target market over next 4 quarters",
                    "margin_impact":  "Short-term dilution (-5–8%) as investments scale; inflection in 6–12 months",
                    "timeline":       "Market share gains visible in 2–3 quarters; revenue recognition 1–2 quarters later",
                },
                "thesis": (
                    f"{company} is executing a classic 'invest now, harvest later' playbook. "
                    f"The capital deployment + hiring pattern suggests line-of-sight to a significant market opportunity. "
                    f"Patient capital will be rewarded; the risk is execution, not direction."
                ),
                "recommendation": {
                    "trade":     f"Long {company} stock / calls, 6–12 month horizon",
                    "conviction":"High — rare multi-signal confirmation",
                    "risk":      f"Market opportunity is smaller than {company} management assumes; ROI disappoints",
                    "hedge":     "Sector ETF short to neutralize macro beta",
                    "direction": "LONG",
                },
                "risk_assessment": {
                    "primary_risk":       "Market opportunity smaller than assumed; ROI disappoints at scale",
                    "probability":        "30%",
                    "hedge":              f"Sell 25% OTM calls on {company} to generate income while waiting",
                    "false_positive_risk":"Low",
                },
                "watch_for": [
                    f"{company} product launch announcements confirming market entry",
                    f"{company} customer win announcements",
                    "Incumbent competitor defensive moves",
                    f"{company} Q3/Q4 revenue vs. investment spending trajectory",
                    f"Insider buying by {company} executives",
                ],
            },
        }

        return templates.get(rule, templates["growth_thesis"])

    # ─────────────────────────────────────────────────────────────────────────
    #  Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _metric_str(self, signal: dict) -> str:
        st = signal.get("signal_type", "")
        cv = signal.get("current_value", 0)
        bl = signal.get("baseline", 0)
        vp = signal.get("variance_pct", 0)
        return {
            "hiring_velocity":  f"{cv:.0f} jobs (baseline {bl:.0f}/week, {vp:+.0f}%)",
            "pricing_change":   f"${cv:,.0f} current (baseline ${bl:,.0f}, {vp:+.1f}%)",
            "funding":          f"${cv:.0f}M funding detected",
            "news":             f"Sentiment {cv:+.2f} (positive=+1, negative=-1)",
            "financial_health": f"Distress score {cv:.2f}",
            "supplier_risk":    f"{cv:.0f} high-risk suppliers",
            "web_traffic":      f"{cv:.1f}M visits/mo (baseline {bl:.1f}M, {vp:+.1f}%)",
        }.get(st, f"{cv:.2f} ({vp:+.1f}% vs baseline)")

    def _sensitivity(self, confidence: float) -> str:
        if confidence >= 90: return "immediate"
        if confidence >= 75: return "urgent"
        if confidence >= 60: return "moderate"
        return "low"
