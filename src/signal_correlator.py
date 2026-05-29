"""
Signal Correlator — Takes individual signals and identifies investment theses.

5 Correlation Rules:
  1. Growth Thesis        — hiring↑ + funding + positive_news + traffic↑
  2. Competitive Threat   — competitor hiring↑ + price cuts + news
  3. Financial Distress   — hiring_freeze + cash↓ + insider_sell + negative_news
  4. Supplier Risk        — supplier distress → customer supply chain disruption
  5. Market Disruption    — new competitor + funding + incumbent pricing↓

Each rule returns a match score (0–1). Score > threshold → generate alert.
"""

from datetime import datetime
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
#  Correlation rule helpers
# ─────────────────────────────────────────────────────────────────────────────

def _has_signal(signals: list[dict], signal_type: str, alert_only: bool = True) -> bool:
    """Check if a specific signal type fired."""
    for s in signals:
        if s.get("signal_type") == signal_type:
            return (not alert_only) or s.get("alert", False)
    return False


def _get_signal(signals: list[dict], signal_type: str) -> Optional[dict]:
    return next((s for s in signals if s.get("signal_type") == signal_type), None)


def _avg_confidence(signals: list[dict]) -> float:
    if not signals:
        return 0.0
    total = sum(s.get("confidence", 0) for s in signals)
    return round(total / len(signals), 1)


# ─────────────────────────────────────────────────────────────────────────────
#  Main Correlator
# ─────────────────────────────────────────────────────────────────────────────

class SignalCorrelator:

    def __init__(self, min_match_score: float = 0.6):
        self.min_match_score = min_match_score

        self.rules = [
            ("growth_thesis",       self._rule_growth_thesis,       "📈 Growth Thesis"),
            ("competitive_threat",  self._rule_competitive_threat,  "⚔️  Competitive Threat"),
            ("financial_distress",  self._rule_financial_distress,  "🚨 Financial Distress"),
            ("supplier_risk",       self._rule_supplier_risk,       "⛓️  Supplier Risk"),
            ("market_disruption",   self._rule_market_disruption,   "💥 Market Disruption"),
        ]

    async def correlate(self, company: str, signals: list[dict]) -> Optional[dict]:
        """
        Evaluate all correlation rules. Return the best-matching thesis, or None.
        """
        firing = [s for s in signals if s.get("alert")]

        if not firing:
            return None

        best_match = None
        best_score = 0.0

        for rule_key, rule_fn, rule_label in self.rules:
            match_score, matched_signals = rule_fn(signals)
            if match_score > best_score and match_score >= self.min_match_score:
                best_score = match_score
                best_match = (rule_key, rule_label, match_score, matched_signals)

        if not best_match:
            return None

        rule_key, rule_label, match_score, matched_signals = best_match
        confidence = min(98.0, round(match_score * 100 * 0.6 + _avg_confidence(matched_signals) * 0.4, 1))

        return {
            "correlation_type": rule_key,
            "correlation_label": rule_label,
            "headline": self._generate_headline(rule_key, company, matched_signals),
            "match_score": match_score,
            "confidence": confidence,
            "signals_fired": len(firing),
            "signals_matched": matched_signals,
            "recommendation": self._get_recommendation(rule_key),
            "time_horizon": self._get_time_horizon(rule_key),
            "timestamp": datetime.utcnow().isoformat(),
        }

    # ── Correlation Rules ─────────────────────────────────────────────────────

    def _rule_growth_thesis(self, signals: list[dict]) -> tuple[float, list[dict]]:
        """
        Growth signals: hiring surge + funding + positive news + traffic spike.
        """
        components = []
        weights = []

        hiring = _get_signal(signals, "hiring_velocity")
        if hiring and hiring.get("alert") and hiring.get("variance_pct", 0) > 0:
            components.append(hiring)
            weights.append(0.35)

        funding = _get_signal(signals, "funding")
        if funding and funding.get("alert"):
            components.append(funding)
            weights.append(0.30)

        news = _get_signal(signals, "news")
        if news and news.get("alert") and news.get("details", {}).get("sentiment") == "positive":
            components.append(news)
            weights.append(0.20)

        traffic = _get_signal(signals, "web_traffic")
        if traffic and traffic.get("alert") and traffic.get("variance_pct", 0) > 0:
            components.append(traffic)
            weights.append(0.15)

        score = sum(weights) / 1.0  # Max possible weight is 1.0
        return round(score, 2), components

    def _rule_competitive_threat(self, signals: list[dict]) -> tuple[float, list[dict]]:
        """
        Competitive pressure: pricing cuts + hiring surge (racing to compete).
        """
        components = []
        weights = []

        pricing = _get_signal(signals, "pricing_change")
        if pricing and pricing.get("alert") and pricing.get("variance_pct", 0) < 0:
            components.append(pricing)
            weights.append(0.40)

        hiring = _get_signal(signals, "hiring_velocity")
        if hiring and hiring.get("alert"):
            components.append(hiring)
            weights.append(0.30)

        news = _get_signal(signals, "news")
        if news and news.get("alert"):
            components.append(news)
            weights.append(0.30)

        score = sum(weights) / 1.0
        return round(score, 2), components

    def _rule_financial_distress(self, signals: list[dict]) -> tuple[float, list[dict]]:
        """
        Distress signals: hiring freeze + cash burn + negative news.
        """
        components = []
        weights = []

        hiring = _get_signal(signals, "hiring_velocity")
        if hiring and hiring.get("alert") and hiring.get("variance_pct", 0) < -50:
            components.append(hiring)
            weights.append(0.35)  # Freeze = strong distress signal

        financial = _get_signal(signals, "financial_health")
        if financial and financial.get("alert"):
            components.append(financial)
            weights.append(0.35)

        news = _get_signal(signals, "news")
        if news and news.get("alert") and news.get("details", {}).get("sentiment") == "negative":
            components.append(news)
            weights.append(0.30)

        score = sum(weights) / 1.0
        return round(score, 2), components

    def _rule_supplier_risk(self, signals: list[dict]) -> tuple[float, list[dict]]:
        """
        Supply chain risk: supplier distress signals.
        """
        components = []
        weights = []

        supplier = _get_signal(signals, "supplier_risk")
        if supplier and supplier.get("alert"):
            components.append(supplier)
            weights.append(0.70)

        news = _get_signal(signals, "news")
        if news and news.get("alert"):
            components.append(news)
            weights.append(0.30)

        score = sum(weights) / 1.0
        return round(score, 2), components

    def _rule_market_disruption(self, signals: list[dict]) -> tuple[float, list[dict]]:
        """
        Market disruption: funding + aggressive hiring + pricing pressure together.
        """
        components = []
        weights = []

        funding = _get_signal(signals, "funding")
        if funding and funding.get("alert"):
            components.append(funding)
            weights.append(0.35)

        hiring = _get_signal(signals, "hiring_velocity")
        if hiring and hiring.get("alert") and hiring.get("variance_pct", 0) > 80:  # Very aggressive
            components.append(hiring)
            weights.append(0.35)

        pricing = _get_signal(signals, "pricing_change")
        if pricing and pricing.get("alert"):
            components.append(pricing)
            weights.append(0.30)

        score = sum(weights) / 1.0
        return round(score, 2), components

    # ── Supporting methods ────────────────────────────────────────────────────

    def _generate_headline(self, rule: str, company: str, signals: list[dict]) -> str:
        hiring = _get_signal(signals, "hiring_velocity")
        pricing = _get_signal(signals, "pricing_change")
        funding = _get_signal(signals, "funding")

        headlines = {
            "growth_thesis": (
                f"{company} Aggressive Expansion — Earnings Upside Signal "
                f"({hiring.get('variance_pct', 0):+.0f}% hiring surge)" if hiring else f"{company} Growth Thesis Activated"
            ),
            "competitive_threat": (
                f"{company} Under Competitive Pressure — Margin Compression Risk "
                f"({abs(pricing.get('variance_pct', 0)):.0f}% price cut)" if pricing else f"{company} Competitive Threat Detected"
            ),
            "financial_distress": f"{company} Financial Distress Signals — Risk Alert",
            "supplier_risk": f"{company} Supply Chain Disruption Risk — Operational Alert",
            "market_disruption": (
                f"{company} Market Disruption — {funding.get('current_value', 0):.0f}M Raised + Aggressive Hiring"
                if funding else f"{company} Market Disruption Detected"
            ),
        }
        return headlines.get(rule, f"{company} Signal Alert")

    def _get_recommendation(self, rule: str) -> dict:
        recs = {
            "growth_thesis": {
                "trade": "Long calls",
                "conviction": "High — multiple confirming signals",
                "expiration": "3-month",
                "direction": "LONG",
            },
            "competitive_threat": {
                "trade": "Neutral — consider protective puts or collar strategy",
                "conviction": "Medium — pricing war may compress margins",
                "expiration": "1-2 month",
                "direction": "HEDGE",
            },
            "financial_distress": {
                "trade": "Short stock / long puts",
                "conviction": "High — distress signals confirmed",
                "expiration": "2-4 month",
                "direction": "SHORT",
            },
            "supplier_risk": {
                "trade": "Short stock / reduce position",
                "conviction": "Medium-High — supply chain disruption likely",
                "expiration": "6-12 month",
                "direction": "SHORT",
            },
            "market_disruption": {
                "trade": "Long disruptor / Short incumbent",
                "conviction": "High — aggressive capital deployment signals conviction",
                "expiration": "2-4 quarter",
                "direction": "LONG",
            },
        }
        return recs.get(rule, {"trade": "Monitor", "conviction": "Low", "direction": "NEUTRAL"})

    def _get_time_horizon(self, rule: str) -> str:
        horizons = {
            "growth_thesis": "2–4 quarters",
            "competitive_threat": "1–2 quarters",
            "financial_distress": "2–4 quarters",
            "supplier_risk": "6–12 months",
            "market_disruption": "2–4 quarters",
        }
        return horizons.get(rule, "1–2 quarters")
