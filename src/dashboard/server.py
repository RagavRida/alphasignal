"""
FastAPI dashboard server with WebSocket real-time alert streaming.

Endpoints:
  GET  /              → Live dashboard HTML
  GET  /sales         → Sales intelligence dashboard
  GET  /api/alerts    → All recent alerts (JSON)
  GET  /api/signals/{company} → Latest signals
  GET  /api/status    → Monitor health / stats
  GET  /api/companies → Watch list
  POST /api/trigger-cycle → Trigger one monitor cycle
  WS   /ws            → Real-time alert stream (with heartbeat)
  WS   /ws/sales      → Real-time sales pipeline stream
  POST /api/sales/run → Start sales pipeline
  GET  /api/sales/leads → Discovered leads
  GET  /api/sales/emails/{lead_id} → Generated emails
  GET  /api/sales/signals → Intent signals
  POST /api/sales/send → Send email via Resend
"""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Set

import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from src import state
from src.company_profile import (
    load_profile, save_profile, needs_setup,
    generate_watchlist, update_config_watchlist,
    refresh_watchlist_if_needed, analyze_brand,
)

app = FastAPI(title="AlphaSignal — Alternative Data Monitor", version="2.0.0")

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── SSE queue registries ──────────────────────────────────────────────────────
_sse_monitor_queues: Set[asyncio.Queue] = set()
_sse_sales_queues:   Set[asyncio.Queue] = set()

# Keep WebSocket sets alive so broadcast_alert signature stays compatible
_ws_clients:       Set[WebSocket] = set()
_ws_sales_clients: Set[WebSocket] = set()

# Config cache
_config       = None
_monitor_ref  = None


@app.on_event("startup")
async def start_background_monitor():
    """Launch the autonomous monitor as a background task in the same process."""
    demo_mode = os.getenv("DEMO_MODE", "false").lower() == "true"
    if demo_mode:
        return
    config_path = Path("config.yaml")
    if not config_path.exists():
        return
    try:
        from src.monitor import AutonomousMonitor, subscribe_to_alerts
        monitor = AutonomousMonitor(config_path=str(config_path), demo_mode=False)
        monitor.check_interval = int(os.getenv("CHECK_INTERVAL", "3600"))
        subscribe_to_alerts(broadcast_alert)
        asyncio.create_task(monitor.run())
    except Exception as e:
        print(f"[monitor] Failed to start background monitor: {e}", flush=True)


def _get_config():
    global _config
    if _config is None:
        config_path = Path("config.yaml")
        if config_path.exists():
            with open(config_path) as f:
                _config = yaml.safe_load(f)
    return _config or {}


# ── Broadcast helpers ─────────────────────────────────────────────────────────

def _enqueue(queues: Set[asyncio.Queue], message: str):
    dead = set()
    for q in list(queues):
        try:
            q.put_nowait(message)
        except asyncio.QueueFull:
            dead.add(q)
    queues -= dead


async def broadcast_alert(alert: dict):
    _enqueue(_sse_monitor_queues, json.dumps({"type": "alert", "data": alert}))


async def broadcast_sales_event(event: dict):
    _enqueue(_sse_sales_queues, json.dumps(event))


async def _on_bd_activity(event: dict):
    _enqueue(_sse_sales_queues, json.dumps({"type": "bd_activity", **event}))

try:
    from src.bright_data_client import set_activity_callback
    set_activity_callback(_on_bd_activity)
except Exception:
    pass


# ── WebSocket — Hedge Fund Monitor ────────────────────────────────────────────

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


@app.get("/sse")
async def sse_monitor():
    queue: asyncio.Queue = asyncio.Queue(maxsize=200)
    _sse_monitor_queues.add(queue)

    async def generate():
        try:
            recent = state.get_recent_alerts(20)
            for alert in reversed(recent):
                yield f"data: {json.dumps({'type': 'alert', 'data': alert})}\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except (GeneratorExit, Exception):
            pass
        finally:
            _sse_monitor_queues.discard(queue)

    return StreamingResponse(generate(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.get("/sse/sales")
async def sse_sales():
    queue: asyncio.Queue = asyncio.Queue(maxsize=200)
    _sse_sales_queues.add(queue)

    async def generate():
        try:
            try:
                from src.sales import sales_state
                leads   = sales_state.get_leads(limit=50)
                signals = sales_state.get_signals(limit=20)
                if leads:
                    yield f"data: {json.dumps({'type': 'initial_data', 'leads': leads, 'signals': signals})}\n\n"
            except Exception:
                pass
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except (GeneratorExit, Exception):
            pass
        finally:
            _sse_sales_queues.discard(queue)

    return StreamingResponse(generate(), media_type="text/event-stream", headers=SSE_HEADERS)


# ── REST — Hedge Fund Monitor ─────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def landing():
    return HTMLResponse(content=(STATIC_DIR / "landing.html").read_text())


@app.get("/app", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(content=(STATIC_DIR / "index.html").read_text())


@app.get("/api/alerts")
async def get_alerts(limit: int = 50):
    return {"alerts": state.get_recent_alerts(limit)}


@app.get("/api/alerts/{company}")
async def get_company_alerts(company: str, limit: int = 20):
    return {"company": company, "alerts": state.get_company_alerts(company, limit)}


@app.get("/api/signals/{company}")
async def get_company_signals(company: str):
    signal_types = ["hiring_velocity", "pricing_change", "funding", "news",
                    "financial_health", "supplier_risk", "web_traffic"]
    signals = {}
    for st in signal_types:
        history = state.get_signal_history(company, st, days=7)
        signals[st] = history[:5] if history else []
    return {"company": company, "signals": signals}


@app.get("/api/status")
async def get_status():
    stats  = state.get_alert_stats()
    config = _get_config()
    companies = [c["name"] for c in config.get("watch_list", {}).get("companies", [])]
    return {
        "status":               "running",
        "timestamp":            datetime.utcnow().isoformat() + "Z",
        "companies_monitored":  companies,
        "connected_clients":    len(_ws_clients),
        "sales_clients":        len(_ws_sales_clients),
        "alert_stats":          stats,
        "bright_data_products": ["SERP API", "Web Scraper API",
                                  "Scraping Browser", "Web Unlocker", "MCP Server"],
        "demo_mode":            os.getenv("DEMO_MODE", "false").lower() == "true",
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/companies")
async def get_companies():
    """
    Return the watch list companies.
    Prefers the AI-generated list from the company profile (updated daily)
    over the static config.yaml fallback.
    """
    # First: try the AI-generated list from the saved profile
    profile = load_profile()
    watchlist = profile.get("watchlist_companies", [])
    if watchlist:
        # Normalize to config.yaml-compatible shape
        companies = [
            {
                "name":        c.get("name", ""),
                "ticker":      c.get("ticker", ""),
                "pricing_url": c.get("pricing_url", ""),
                "category":    c.get("category", ""),
                "reason":      c.get("reason", ""),
                "suppliers":   c.get("suppliers", []),
            }
            for c in watchlist
        ]
        return {
            "companies": companies,
            "source":    "ai_generated",
            "generated_at": profile.get("updated_at", ""),
        }

    # Fallback: static config.yaml
    config = _get_config()
    return {
        "companies": config.get("watch_list", {}).get("companies", []),
        "source": "config_yaml",
    }


@app.post("/api/trigger-cycle")
async def trigger_cycle(background_tasks: BackgroundTasks):
    """Trigger one monitor cycle in the background and stream alerts via WebSocket."""
    global _monitor_ref
    if _monitor_ref is None:
        # Lazy-init monitor if not already running
        try:
            from src.monitor import AutonomousMonitor
            _monitor_ref = AutonomousMonitor(demo_mode=False)
            _monitor_ref.cycle_count = 0
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def _run():
        _monitor_ref.cycle_count += 1
        await _monitor_ref.run_cycle()
        # Refresh clients with new alerts
        recent = state.get_recent_alerts(5)
        for alert in recent:
            await broadcast_alert(alert)

    background_tasks.add_task(_run)
    return {"status": "started", "message": "Monitoring cycle triggered"}


# ── REST — Sales Pipeline ─────────────────────────────────────────────────────

@app.get("/sales", response_class=HTMLResponse)
async def sales_dashboard():
    return HTMLResponse(content=(STATIC_DIR / "sales.html").read_text())


@app.post("/api/sales/run")
async def run_sales_pipeline(body: dict, background_tasks: BackgroundTasks):
    """Start sales pipeline asynchronously. Results stream via /ws/sales."""
    icp_text   = body.get("icp_text", "")
    max_leads  = int(body.get("max_leads", 20))
    competitor = body.get("competitor", "")
    auto_send  = bool(body.get("auto_send", False))

    if not icp_text:
        return {"status": "error", "message": "icp_text is required"}

    async def _run():
        try:
            from src.sales.pipeline import SalesPipeline, subscribe_to_leads

            pipeline = SalesPipeline(demo_mode=False)

            # Wire real-time WebSocket push
            async def _push_lead(event: dict):
                await broadcast_sales_event(event)

            subscribe_to_leads(_push_lead)

            competitors = [competitor] if competitor else []
            summary = await pipeline.run(
                icp_text=icp_text,
                max_leads=max_leads,
                competitors=competitors,
                auto_send=auto_send,
            )

            # Final summary push
            await broadcast_sales_event({
                "type":    "pipeline_done",
                "leads":   summary["leads_found"],
                "emails":  summary["emails_ready"],
                "signals": summary["signals"],
            })
        except Exception as e:
            await broadcast_sales_event({"type": "error", "message": str(e)})
            import traceback; traceback.print_exc()

    background_tasks.add_task(_run)
    return {"status": "started", "icp": icp_text}


@app.get("/api/sales/leads")
async def get_sales_leads(limit: int = 100):
    try:
        from src.sales import sales_state
        return {"leads": sales_state.get_leads(limit=limit)}
    except Exception as e:
        return {"leads": [], "error": str(e)}


@app.get("/api/sales/emails/{lead_id}")
async def get_lead_emails(lead_id: str):
    try:
        from src.sales import sales_state
        return {"emails": sales_state.get_emails(lead_id)}
    except Exception as e:
        return {"emails": [], "error": str(e)}


@app.get("/api/sales/signals")
async def get_sales_signals(limit: int = 50):
    try:
        from src.sales import sales_state
        return {"signals": sales_state.get_signals(limit=limit)}
    except Exception as e:
        return {"signals": [], "error": str(e)}


@app.post("/api/sales/send")
async def send_sales_email(body: dict):
    """Send a specific email via Resend.
    Body: { lead_id, email_id, to_email? }
    If to_email is provided it overrides the contact email from the DB.
    """
    lead_id  = body.get("lead_id", "")
    email_id = body.get("email_id", "")
    to_email_override = (body.get("to_email") or "").strip()

    try:
        from src.sales import sales_state
        from src.sales.outreach_sequencer import OutreachSequencer

        emails = sales_state.get_emails(lead_id)
        email  = next((e for e in emails if e["id"] == email_id), None)
        if not email:
            return {"success": False, "error": "Email not found"}

        # Determine recipient: manual override > contact from DB
        to_email = to_email_override
        if not to_email:
            leads = sales_state.get_leads()
            lead  = next((l for l in leads if l["id"] == lead_id), None)
            if lead and lead.get("contacts"):
                contacts = lead["contacts"]
                if isinstance(contacts, str):
                    import json as _json
                    contacts = _json.loads(contacts)
                if contacts:
                    to_email = contacts[0].get("email", "")

        if not to_email or "@" not in to_email:
            return {"success": False, "error": "No email address — enter one in the drawer and try again"}

        seq = OutreachSequencer(
            resend_api_key=os.getenv("RESEND_API_KEY", ""),
            from_email=os.getenv("RESEND_FROM_EMAIL", ""),
        )

        from src.sales.models import OutreachEmail
        email_obj = OutreachEmail(
            id=email["id"], lead_id=lead_id,
            subject=email["subject"], body=email["body"],
        )
        success = await seq.send_email(email_obj, to_email)
        if success:
            sales_state.update_email_status(email_id, "sent")
            sales_state.update_lead_status(lead_id, "emailed")

        return {"success": success, "to": to_email}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/sales/demo")
async def load_demo_data(background_tasks: BackgroundTasks):
    """Load pre-curated Natively AI demo data instantly — no API calls needed.
    Clears previous data then populates DB + pushes via WebSocket.
    """
    async def _load():
        from src.sales import sales_state
        from src.sales.demo_data import DEMO_LEADS, DEMO_EMAILS, DEMO_SIGNALS

        # Clear old data first
        sales_state.clear_run_data()

        # Load profile to personalize the "Pitching as" label
        try:
            profile = load_profile()
            brand   = profile.get("company_name", "Natively AI")
        except Exception:
            brand = "Natively AI"

        # Push pipeline start event
        await broadcast_sales_event({"type": "pipeline_step", "step": "discover", "status": "active"})

        # Insert each demo lead into DB and broadcast
        for lead_dict in DEMO_LEADS:
            d = dict(lead_dict)  # copy
            import json as _json
            from src.sales import sales_state as ss

            # Save via raw SQL to match the schema
            with ss._conn() as c:
                c.execute("""
                INSERT OR REPLACE INTO leads
                  (id, company_name, domain, industry, geo, headcount,
                   funding_stage, funding_amount, funding_date, score, status, data_json, discovered_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    d["id"], d["company_name"], d["domain"], d.get("industry",""),
                    d.get("geo",""), d.get("headcount",""), d.get("funding_stage",""),
                    d.get("funding_amount",""), d.get("funding_date",""),
                    d["score"], d["status"],
                    _json.dumps({
                        "description":   d.get("description",""),
                        "linkedin_url":  d.get("linkedin_url",""),
                        "tech_stack":    d.get("tech_stack",[]),
                        "hiring_signals": d.get("hiring_signals",[]),
                        "contacts":      d.get("contacts",[]),
                        "score_reasons": d.get("score_reasons",[]),
                        "source_urls":   d.get("source_urls",[]),
                    }),
                    d["discovered_at"],
                ))

            # Insert emails for this lead
            emails_for_lead = DEMO_EMAILS.get(d["id"], [])
            if not emails_for_lead and DEMO_EMAILS:
                # Use the first available email set as template for remaining leads
                first_key = next(iter(DEMO_EMAILS))
                emails_for_lead = [
                    {**e, "id": f"{d['id']}-step-{e['sequence_step']}", "lead_id": d["id"]}
                    for e in DEMO_EMAILS[first_key]
                ]

            with ss._conn() as c:
                for e in emails_for_lead:
                    c.execute("""
                    INSERT OR REPLACE INTO outreach_emails
                      (id, lead_id, sequence_step, delay_days, subject, body, linkedin_dm, status, generated_at)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    """, (
                        e["id"], e["lead_id"], e.get("sequence_step",1), e.get("delay_days",0),
                        e["subject"], e["body"], e.get("linkedin_dm",""), e.get("status","draft"),
                        e.get("generated_at", ""),
                    ))

            # Broadcast new_lead event to WebSocket
            await broadcast_sales_event({
                "type": "new_lead",
                "lead": {
                    "id":             d["id"],
                    "company_name":   d["company_name"],
                    "domain":         d["domain"],
                    "score":          d["score"],
                    "funding_amount": d.get("funding_amount",""),
                    "funding_stage":  d.get("funding_stage",""),
                    "geo":            d.get("geo",""),
                    "hiring_signals": d.get("hiring_signals",[]),
                    "status":         d["status"],
                    "emails":         len(emails_for_lead),
                },
            })
            await asyncio.sleep(0.15)  # small delay so leads appear one-by-one (visual effect)

        # Insert signals
        for sig in DEMO_SIGNALS:
            with ss._conn() as c:
                c.execute("""
                INSERT OR REPLACE INTO intent_signals
                  (id, intent_type, source, source_url, quote, company_mentioned, lead_match, confidence, detected_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                """, (
                    sig["id"], sig["intent_type"], sig["source"], sig["source_url"],
                    sig["quote"], sig["company_mentioned"], sig.get("lead_match",""),
                    sig["confidence"], sig["detected_at"],
                ))
            await broadcast_sales_event({"type": "new_signal", "signal": sig})
            await asyncio.sleep(0.1)

        # Done
        await broadcast_sales_event({
            "type":    "pipeline_done",
            "leads":   len(DEMO_LEADS),
            "emails":  sum(len(v) for v in DEMO_EMAILS.values()),
            "signals": len(DEMO_SIGNALS),
            "brand":   brand,
            "demo":    True,
        })

    background_tasks.add_task(_load)
    return {"status": "loading", "leads": 8, "mode": "demo"}



@app.post("/api/profile/analyze")
async def analyze_brand_endpoint(body: dict):
    """
    One-shot brand intelligence: given just a brand name,
    use Bright Data SERP + Claude to auto-generate the full profile.
    Returns profile preview for user to review (NOT saved yet).
    Body: { brand_name: "Hubspot" }
    """
    brand_name  = (body.get("brand_name")  or "").strip()
    website_url = (body.get("website_url") or "").strip()
    if not brand_name:
        return {"success": False, "error": "brand_name is required"}

    # Spin up a Bright Data client for SERP lookups + website scraping
    try:
        from src.bright_data_client import BrightDataClient
        import os
        bd = BrightDataClient(
            api_token=os.getenv("BRIGHT_DATA_API_TOKEN", ""),
            serp_zone=os.getenv("BRIGHT_DATA_SERP_ZONE", "serp_api1"),
            mcp_url=os.getenv("BRIGHT_DATA_MCP_URL", ""),
            demo_mode=not os.getenv("BRIGHT_DATA_API_TOKEN"),
        )
        profile = await analyze_brand(brand_name, bd, website_url=website_url)
        await bd.close()
    except Exception as e:
        # Fallback: AI/ML API only, no SERP
        profile = await analyze_brand(brand_name, bd=None, website_url=website_url)

    return {
        "success":       True,
        "profile":       profile,
        "serp_snippets": profile.pop("serp_snippet_count", 0),
    }


@app.get("/api/profile")
async def get_profile():
    """Return the stored company profile."""
    profile = load_profile()
    return {
        "profile":     profile,
        "needs_setup": needs_setup(),
    }


@app.post("/api/profile")
async def save_company_profile(body: dict, background_tasks: BackgroundTasks):
    """
    Save company profile and regenerate the watch list.
    Body: { company_name, product_description, industry, icp_description,
            known_competitors: [], sender_name, sender_title }
    """
    required = ["company_name", "product_description"]
    for field in required:
        if not body.get(field):
            return {"success": False, "error": f"'{field}' is required"}

    profile = load_profile()
    profile.update({
        "company_name":          body.get("company_name", ""),
        "product_description":   body.get("product_description", ""),
        "industry":              body.get("industry", ""),
        "icp_description":       body.get("icp_description", ""),
        "known_competitors":     body.get("known_competitors", []),
        "sender_name":           body.get("sender_name", ""),
        "sender_title":          body.get("sender_title", ""),
        "watchlist_generated_date": "",  # force refresh
    })
    save_profile(profile)

    # Regenerate watch list in background
    async def _refresh():
        try:
            companies = await generate_watchlist(profile)
            update_config_watchlist(companies)
            profile["watchlist_generated_date"] = str(__import__("datetime").date.today())
            profile["watchlist_companies"] = companies
            save_profile(profile)
            # Reset config cache so next /api/companies picks up new list
            global _config
            _config = None
        except Exception as e:
            print(f"  [Profile] Watch list refresh error: {e}")

    background_tasks.add_task(_refresh)

    return {
        "success":  True,
        "message":  f"Profile saved for {body['company_name']}. Watch list generating…",
        "profile":  profile,
    }


@app.get("/api/profile/watchlist")
async def get_watchlist():
    """Return the current auto-generated watch list."""
    profile = load_profile()
    return {
        "companies":     profile.get("watchlist_companies", []),
        "generated_at":  profile.get("updated_at", ""),
        "needs_refresh": not profile.get("watchlist_generated_date"),
    }


@app.post("/api/profile/refresh-watchlist")
async def refresh_watchlist_now(background_tasks: BackgroundTasks):
    """Force regenerate the watch list now."""
    profile = load_profile()
    if not profile.get("company_name"):
        return {"success": False, "error": "Complete your company profile first"}

    async def _refresh():
        global _config
        companies = await generate_watchlist(profile)
        update_config_watchlist(companies)
        profile["watchlist_generated_date"] = str(__import__("datetime").date.today())
        profile["watchlist_companies"] = companies
        save_profile(profile)
        _config = None  # clear cache

    background_tasks.add_task(_refresh)
    return {"success": True, "message": "Watch list refresh started"}
