"""
Slack Alert Integration
========================
Sends rich, formatted alerts to Slack via Incoming Webhooks.

Two alert types:
  1. Market Intelligence alerts (hedge-fund-grade analysis)
  2. Sales Pipeline summaries (new leads discovered)

Setup:
  1. Create a Slack app → Incoming Webhooks → Activate
  2. Add webhook to a channel → Copy URL
  3. Set SLACK_WEBHOOK_URL in .env
"""

import os
import json
from datetime import datetime
from typing import Optional

import httpx


SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")


def _get_url() -> str:
    """Re-read env var in case it was set after import."""
    return os.getenv("SLACK_WEBHOOK_URL", "") or SLACK_WEBHOOK_URL


# ── Emoji / color maps ────────────────────────────────────────────────────────

ALERT_COLORS = {
    "growth_thesis":      "#22c55e",   # green
    "competitive_threat": "#f59e0b",   # amber
    "financial_distress": "#ef4444",   # red
    "supplier_risk":      "#8b5cf6",   # purple
    "market_disruption":  "#3b82f6",   # blue
}

ALERT_EMOJI = {
    "growth_thesis":      "📈",
    "competitive_threat": "⚔️",
    "financial_distress": "🚨",
    "supplier_risk":      "⛓️",
    "market_disruption":  "💥",
}

DIRECTION_EMOJI = {
    "LONG":    "🟢 LONG",
    "SHORT":   "🔴 SHORT",
    "HEDGE":   "🟡 HEDGE",
    "NEUTRAL": "⚪ NEUTRAL",
}

SIGNAL_EMOJI = {
    "hiring_velocity":  "👥",
    "pricing_change":   "💰",
    "funding":          "🏦",
    "news":             "📰",
    "financial_health": "📊",
    "supplier_risk":    "🏭",
    "web_traffic":      "🌐",
}


# ── Market Intelligence Alert ─────────────────────────────────────────────────

async def send_market_alert(alert: dict) -> bool:
    """
    Send a hedge-fund-grade market intelligence alert to Slack.

    Example output in Slack:
    ┌──────────────────────────────────────────┐
    │ 📈 GROWTH THESIS — Tesla — 89%           │
    │                                          │
    │ Tesla Activates Growth Mode — +87% Hiring│
    │ Surge + Expansion Signals                │
    │                                          │
    │ 👥 Hiring +87% | 💰 Pricing -12% |      │
    │ 🏦 Funding $100M | 📰 News +0.8         │
    │                                          │
    │ 📝 Thesis: Tesla is making a deliberate..│
    │ 🟢 LONG · High conviction                │
    │ ⚠️ Risk: Hiring surge reflects defensive │
    └──────────────────────────────────────────┘
    """
    url = _get_url()
    if not url:
        return False

    alert_type = alert.get("alert_type", alert.get("correlation_type", "growth_thesis"))
    company    = alert.get("company", "Unknown")
    confidence = alert.get("confidence_score", 0)
    headline   = alert.get("headline", "")
    narrative  = alert.get("narrative", "")
    thesis     = alert.get("thesis", "")
    rec        = alert.get("recommendation", {})
    risk       = alert.get("risk_assessment", {})
    signals    = alert.get("signals", [])
    sensitivity = alert.get("time_sensitivity", "moderate")

    emoji = ALERT_EMOJI.get(alert_type, "🔔")
    color = ALERT_COLORS.get(alert_type, "#3b82f6")
    direction = DIRECTION_EMOJI.get(rec.get("direction", "NEUTRAL"), "⚪ NEUTRAL")

    # Build signal summary line
    signal_parts = []
    for s in signals[:7]:
        sig_emoji = SIGNAL_EMOJI.get(s.get("signal_type", ""), "📊")
        sig_name  = s.get("signal_type", "").replace("_", " ").title()
        variance  = s.get("variance_pct", "")
        fired     = "🔥" if s.get("alert") else ""
        signal_parts.append(f"{sig_emoji} {sig_name} {variance} {fired}")

    signal_line = " │ ".join(signal_parts) if signal_parts else "No signals"

    # Build Slack Block Kit message
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} {alert_type.replace('_', ' ').upper()} — {company} — {confidence:.0f}%",
                "emoji": True,
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{headline}*\n\n{narrative}"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Signals:*\n{signal_line}"
            }
        },
        {"type": "divider"},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Direction:*\n{direction}"},
                {"type": "mrkdwn", "text": f"*Conviction:*\n{rec.get('conviction', 'N/A')}"},
                {"type": "mrkdwn", "text": f"*Trade:*\n{rec.get('trade', 'N/A')}"},
                {"type": "mrkdwn", "text": f"*Sensitivity:*\n{sensitivity.upper()}"},
            ]
        },
    ]

    # Add thesis if available
    if thesis:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"📝 *Thesis:* {thesis[:500]}"}
        })

    # Add risk
    if risk.get("primary_risk"):
        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"⚠️ *Risk:* {risk['primary_risk']} — False positive: {risk.get('false_positive_risk', 'Medium')}"}
            ]
        })

    # Add footer with timestamp and data quality
    dq = alert.get("data_quality", {})
    blocks.append({
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": f"🟠 *Bright Data:* {', '.join(dq.get('bright_data_products', []))} │ Signals: {dq.get('signals_fired', 0)}/{dq.get('signals_total', 0)} fired │ _AlphaSignal {datetime.utcnow().strftime('%H:%M UTC')}_"}
        ]
    })

    payload = {"blocks": blocks}

    return await _post(url, payload)


# ── Sales Pipeline Summary ────────────────────────────────────────────────────

async def send_sales_summary(
    brand_name: str,
    icp_text: str,
    leads: list[dict],
    total_emails: int,
    total_signals: int,
) -> bool:
    """
    Send a sales pipeline completion summary to Slack.

    Shows top 5 leads with scores, ICP used, and action stats.
    """
    url = _get_url()
    if not url:
        return False

    # Top 5 leads formatted
    top_leads = sorted(leads, key=lambda l: l.get("score", 0), reverse=True)[:5]
    lead_lines = []
    for i, lead in enumerate(top_leads, 1):
        score = lead.get("score", 0)
        emoji = "🟢" if score >= 70 else "🟡" if score >= 50 else "🔴"
        name  = lead.get("company_name", lead.get("company", "Unknown"))
        stage = lead.get("funding_stage", "")
        geo   = lead.get("geo", "")
        lead_lines.append(f"{emoji} *{i}. {name}* — Score: {score:.0f}/100 │ {stage} │ {geo}")

    leads_text = "\n".join(lead_lines) if lead_lines else "No leads found"

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🎯 Sales Pipeline Complete — {brand_name}",
                "emoji": True,
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*ICP:* {icp_text[:200]}"
            }
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Leads Found:*\n{len(leads)}"},
                {"type": "mrkdwn", "text": f"*Emails Generated:*\n{total_emails}"},
                {"type": "mrkdwn", "text": f"*Intent Signals:*\n{total_signals}"},
                {"type": "mrkdwn", "text": f"*Avg Score:*\n{sum(l.get('score',0) for l in leads)/max(len(leads),1):.0f}/100"},
            ]
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Top Leads:*\n{leads_text}"
            }
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"🟠 Powered by Bright Data + AI/ML API │ _AlphaSignal {datetime.utcnow().strftime('%H:%M UTC')}_"}
            ]
        },
    ]

    payload = {"blocks": blocks}
    return await _post(url, payload)


# ── New Lead Alert (individual) ───────────────────────────────────────────────

async def send_new_lead(lead: dict, brand_name: str = "AlphaSignal") -> bool:
    """Send a single high-score lead notification to Slack."""
    url = _get_url()
    if not url:
        return False

    score = lead.get("score", 0)
    if score < 70:  # Only alert on high-quality leads
        return False

    name    = lead.get("company_name", "Unknown")
    domain  = lead.get("domain", "")
    stage   = lead.get("funding_stage", "")
    funding = lead.get("funding_amount", "")
    geo     = lead.get("geo", "")
    hiring  = ", ".join(lead.get("hiring_signals", [])[:3])

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"🎯 *New High-Score Lead for {brand_name}*\n\n"
                    f"*{name}* — `{score:.0f}/100`\n"
                    f"🌐 {domain} │ 💰 {stage} {funding} │ 📍 {geo}\n"
                    f"{'👥 Hiring: ' + hiring if hiring else ''}"
                )
            }
        },
    ]

    payload = {"blocks": blocks}
    return await _post(url, payload)


# ── Internal ──────────────────────────────────────────────────────────────────

async def _post(url: str, payload: dict) -> bool:
    """Post payload to Slack webhook URL."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                return True
            else:
                print(f"[Slack] Error {resp.status_code}: {resp.text}")
                return False
    except Exception as e:
        print(f"[Slack] Send failed: {e}")
        return False
