"""
Sales Pipeline Orchestrator
============================
Runs all 5 modules in sequence for a given ICP.

Flow:
  1. Parse ICP text → structured ICP
  2. Discover leads (SERP + Web Scraper)
  3. Monitor intent signals (Reddit, G2, HN, Glassdoor)
  4. Scan competitive radar
  5. Fetch personalization context per lead
  6. Generate outreach sequences (AI/ML API)
  7. Save everything to SQLite + JSONL
  8. Optionally send Step 1 email via Resend
"""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from src.llm import OpenAI
from src.bright_data_client import _emit

from src.bright_data_client import BrightDataClient
from src.sales.icp_parser import ICPParser
from src.sales.lead_discovery import LeadDiscoveryEngine
from src.sales.intent_monitor import IntentMonitor
from src.sales.context_fetcher import ContextFetcher
from src.sales.competitive_radar import CompetitiveRadar
from src.sales.outreach_sequencer import OutreachSequencer
from src.sales.models import ICP, Lead, IntentSignal
from src.sales import sales_state
from src.company_profile import load_profile

load_dotenv()
console = Console()

_pipeline_subscribers: list[Callable] = []


def subscribe_to_leads(callback: Callable):
    """Register a callback for real-time lead updates (WebSocket push)."""
    _pipeline_subscribers.append(callback)


async def _broadcast(event: dict):
    for cb in _pipeline_subscribers:
        try:
            await cb(event)
        except Exception:
            pass


class SalesPipeline:

    def __init__(self, demo_mode: bool = False):
        self.demo_mode = demo_mode

        # Shared Bright Data client (proxy creds auto-loaded from env)
        self.bd = BrightDataClient.from_env()
        self.bd.demo_mode = demo_mode

        # LLM client (AI/ML API — OpenAI-compatible)
        aiml_key  = os.getenv("AIML_API_KEY", "")
        aiml_url  = os.getenv("AIML_BASE_URL", "https://api.aimlapi.com/v1")
        aiml_model = os.getenv("AIML_MODEL", "claude-sonnet-4-20250514")
        llm = OpenAI(api_key=aiml_key, base_url=aiml_url) if aiml_key else None

        # 5 pipeline modules
        self.icp_parser   = ICPParser(aiml_key, aiml_url, aiml_model)
        self.discovery    = LeadDiscoveryEngine(self.bd, llm, aiml_model)
        self.intent_mon   = IntentMonitor(self.bd)
        self.ctx_fetcher  = ContextFetcher(self.bd)
        self.radar        = CompetitiveRadar(self.bd)
        self.sequencer    = OutreachSequencer(
            api_key=aiml_key, base_url=aiml_url, model=aiml_model,
            resend_api_key=os.getenv("RESEND_API_KEY", ""),
            from_email=os.getenv("RESEND_FROM_EMAIL", ""),
        )

        # Output paths
        self.leads_path   = Path("data/leads.jsonl")
        self.emails_path  = Path("data/emails.jsonl")
        self.signals_path = Path("data/signals.jsonl")
        for p in [self.leads_path, self.emails_path, self.signals_path]:
            p.parent.mkdir(parents=True, exist_ok=True)

        sales_state.init_db()

    async def run(self, icp_text: str, max_leads: int = 20,
                  competitors: list[str] = None,
                  auto_send: bool = False) -> dict:
        """
        Run the complete sales pipeline for a given ICP description.

        Args:
            icp_text:    Free-text ICP description or company name
            max_leads:   Max leads to discover (default 20)
            competitors: Additional competitors to track
            auto_send:   If True, send Step 1 email via Resend

        Returns:
            Summary dict with leads, signals, emails counts
        """
        console.print(Panel(
            f"[bold cyan]🎯 Sales Intelligence Pipeline[/bold cyan]\n"
            f"[dim]ICP: {icp_text[:80]}{'...' if len(icp_text) > 80 else ''}[/dim]",
            border_style="cyan",
        ))

        # ── Clear previous run data ────────────────────────────────────────────
        console.print("  [dim]Clearing previous run data…[/dim]")
        sales_state.clear_run_data()
        # Also truncate JSONL files so exports only contain current run
        self.leads_path.write_text("")
        self.emails_path.write_text("")
        self.signals_path.write_text("")

        # ── Reload brand profile NOW (profile may have been set after server start) ──
        try:
            profile = load_profile()
            self.sequencer.product_name        = profile.get("company_name", "Our Platform")
            self.sequencer.product_description = profile.get("product_description", "We help you grow.")
            self.sequencer.product_website     = profile.get("website", "")
            self.sequencer.sender_name         = (
                profile.get("sender_name") or profile.get("company_name", "[Your Name]")
            )
            console.print(f"  [dim]Pitching as: {self.sequencer.product_name}[/dim]")
        except Exception as e:
            console.print(f"  [yellow]Profile load warning: {e}[/yellow]")

        # ── Step 1: Parse ICP ──────────────────────────────────────────────────
        console.print("\n[bold]Step 1/5:[/bold] Parsing ICP...")
        await _emit("AI/ML API", "icp_parse", icp_text[:60])
        icp = self.icp_parser.parse(icp_text)
        console.print(f"  Mode: {icp.mode} | Industry: {icp.industry} | "
                      f"Stage: {icp.stage} | Geo: {icp.geo}")
        console.print(f"  Generated {len(icp.search_queries)} search queries")

        all_competitors = list(set((competitors or []) + ([icp.competitor] if icp.competitor else [])))

        # ── Step 2: Discover leads + Step 3: Intent + Step 4: Radar (parallel) ─
        console.print("\n[bold]Steps 2-4:[/bold] Discovering leads + monitoring signals...")
        leads_task   = self.discovery.discover(icp, max_leads=max_leads)
        intent_task  = self.intent_mon.monitor(icp, all_competitors)
        radar_task   = self.radar.scan(all_competitors) if all_competitors else asyncio.sleep(0)

        leads, intent_signals, radar_signals = await asyncio.gather(
            leads_task, intent_task, radar_task, return_exceptions=True,
        )

        leads         = leads if isinstance(leads, list) else []
        intent_signals = intent_signals if isinstance(intent_signals, list) else []
        radar_signals  = radar_signals if isinstance(radar_signals, list) else []
        all_signals    = intent_signals + radar_signals

        console.print(f"  ✓ {len(leads)} leads discovered")
        console.print(f"  ✓ {len(intent_signals)} intent signals detected")
        console.print(f"  ✓ {len(radar_signals)} competitive signals found")

        # Save signals
        for s in all_signals:
            sales_state.save_signal(s)
            with open(self.signals_path, "a") as f:
                f.write(json.dumps({
                    "id": s.id, "type": s.intent_type, "source": s.source,
                    "quote": s.quote[:150], "confidence": s.confidence,
                    "detected_at": s.detected_at,
                }) + "\n")

        # ── Step 5: Context + Email generation (parallel, max 5 concurrent) ───
        console.print(f"\n[bold]Step 5/5:[/bold] Generating emails for {len(leads)} leads in parallel...")
        self._print_lead_table(leads)

        sem = asyncio.Semaphore(5)  # max 5 concurrent context fetches

        async def _process_lead(i: int, lead: Lead):
            async with sem:
                console.print(f"  [{i+1}/{len(leads)}] {lead.company_name} (score: {lead.score:.0f})...")
                ctx    = await self.ctx_fetcher.fetch(lead)
                await _emit("AI/ML API", "email_generate", lead.company_name)
                emails = await self.sequencer.generate_sequence(lead, ctx)

                lead.intent_signals = [
                    s for s in all_signals
                    if lead.company_name.lower() in s.company_mentioned.lower()
                    or s.company_mentioned.lower() in lead.company_name.lower()
                ]

                sales_state.save_lead(lead)
                sales_state.save_emails(emails)
                crm = self.sequencer.build_crm_entry(lead, emails)
                sales_state.save_crm(crm)

                with open(self.leads_path, "a") as f:
                    f.write(json.dumps({
                        "id": lead.id, "company": lead.company_name, "domain": lead.domain,
                        "score": lead.score, "funding": lead.funding_amount,
                        "stage": lead.funding_stage, "geo": lead.geo,
                        "signals": lead.hiring_signals, "discovered_at": lead.discovered_at,
                    }) + "\n")

                with open(self.emails_path, "a") as f:
                    for e in emails:
                        f.write(json.dumps({
                            "lead_id": e.lead_id, "step": e.sequence_step,
                            "subject": e.subject, "body": e.body[:200] + "...",
                        }) + "\n")

                if auto_send:
                    sent = await self._auto_send_step1(lead, emails[0])
                    if sent:
                        sales_state.update_email_status(emails[0].id, "sent")
                        sales_state.update_lead_status(lead.id, "emailed")

                # Broadcast to WebSocket — use 'company_name' to match frontend
                await _broadcast({
                    "type": "new_lead",
                    "lead": {
                        "id":           lead.id,
                        "company_name": lead.company_name,   # ← was 'company' (BUG)
                        "domain":       lead.domain,
                        "score":        lead.score,
                        "funding_amount": lead.funding_amount,
                        "funding_stage":  lead.funding_stage,
                        "geo":          lead.geo,
                        "hiring_signals": lead.hiring_signals,
                        "status":       lead.status,
                        "emails":       len(emails),
                    },
                })
                return len(emails)

        results = await asyncio.gather(
            *[_process_lead(i, lead) for i, lead in enumerate(leads)],
            return_exceptions=True,
        )
        total_emails = sum(r for r in results if isinstance(r, int))

        # ── Summary ───────────────────────────────────────────────────────────
        summary = {
            "icp":          icp_text,
            "leads_found":  len(leads),
            "signals":      len(all_signals),
            "emails_ready": total_emails,
            "run_at":       datetime.utcnow().isoformat() + "Z",
        }

        console.print(Panel(
            f"[green bold]✓ Pipeline Complete[/green bold]\n\n"
            f"  Leads discovered:  {len(leads)}\n"
            f"  Intent signals:    {len(all_signals)}\n"
            f"  Emails generated:  {total_emails}\n\n"
            f"  📁 data/leads.jsonl\n"
            f"  📁 data/emails.jsonl\n"
            f"  📁 data/signals.jsonl\n"
            f"  🌐 Dashboard: http://localhost:8080/sales",
            title="🎯 AlphaSignal Sales Pipeline",
            border_style="green",
        ))

        # ── Slack notification ─────────────────────────────────────────────
        try:
            from src.slack_alerts import send_sales_summary
            brand_name = self.sequencer.product_name or "AlphaSignal"
            lead_dicts = [
                {"company_name": l.company_name, "score": l.score,
                 "domain": l.domain, "funding_stage": l.funding_stage,
                 "funding_amount": l.funding_amount, "geo": l.geo,
                 "hiring_signals": l.hiring_signals}
                for l in leads
            ]
            sent = await send_sales_summary(
                brand_name=brand_name,
                icp_text=icp_text,
                leads=lead_dicts,
                total_emails=total_emails,
                total_signals=len(all_signals),
            )
            if sent:
                console.print("  [green]✓ Slack summary sent[/green]")
        except Exception as e:
            console.print(f"  [dim]Slack: {e}[/dim]")

        await self.bd.close()
        return summary

    async def _auto_send_step1(self, lead: Lead, email) -> bool:
        """
        Automatically send Step 1 email via Resend.
        In demo mode (or Resend free tier), sends to DEMO_EMAIL / own address.
        In production, sends to real contact emails.
        """
        import re

        # Demo mode: send to own email so judges can see it arrive
        demo_email = os.getenv("DEMO_SEND_TO", "")
        if demo_email and "@" in demo_email:
            sent = await self.sequencer.send_email(email, demo_email, "Demo Recipient")
            if sent:
                console.print(f"  [green]✉ Demo auto-sent to {demo_email}[/green]")
                return True

        # Try known contacts first
        for contact in (lead.contacts or []):
            if contact.email and "@" in contact.email:
                sent = await self.sequencer.send_email(email, contact.email, contact.name)
                if sent:
                    console.print(f"  [green]✉ Auto-sent to {contact.email}[/green]")
                    return True

        # Guess email from domain if no contact found
        if lead.domain:
            domain = lead.domain.lstrip("www.").strip("/")
            first_name = "founder"
            company_slug = re.sub(r"[^a-z]", "", lead.company_name.lower().split()[0])
            guesses = [
                f"hello@{domain}",
                f"contact@{domain}",
                f"{first_name}@{domain}",
                f"{company_slug}@{domain}",
            ]
            for addr in guesses:
                sent = await self.sequencer.send_email(email, addr, "")
                if sent:
                    console.print(f"  [green]✉ Auto-sent to guessed address {addr}[/green]")
                    return True

        console.print(f"  [yellow]⚠ No valid email found for {lead.company_name} — skipping auto-send[/yellow]")
        return False

    def _print_lead_table(self, leads: list[Lead]):
        table = Table(box=box.SIMPLE, show_header=True, header_style="bold dim")
        table.add_column("Company", style="bold")
        table.add_column("Score", justify="right")
        table.add_column("Stage")
        table.add_column("Funding")
        table.add_column("Geo")
        table.add_column("Signals")

        for lead in leads[:15]:
            score_color = "green" if lead.score >= 70 else "yellow" if lead.score >= 50 else "red"
            table.add_row(
                lead.company_name[:30],
                f"[{score_color}]{lead.score:.0f}[/{score_color}]",
                lead.funding_stage or "–",
                lead.funding_amount or "–",
                lead.geo or "–",
                ", ".join(lead.hiring_signals[:2]) or "–",
            )
        console.print(table)
