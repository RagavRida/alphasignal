"""
Autonomous Monitoring Loop — The core engine that runs 24/7.

Each monitoring cycle:
  1. Runs all 7 detectors for all companies in parallel
  2. Feeds signals to the correlator
  3. If a thesis is detected, generates a full alert via Claude
  4. Saves alert to DB + JSONL file
  5. Pushes alert to dashboard via WebSocket
  6. Sleeps until next cycle
"""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from src.bright_data_client import BrightDataClient
from src.signal_detectors import (
    HiringVelocityDetector,
    PricingChangeDetector,
    FundingDetector,
    NewsDetector,
    FinancialHealthDetector,
    SupplierRiskDetector,
    WebTrafficDetector,
)
from src.signal_correlator import SignalCorrelator
from src.alert_generator import AlertGenerator
from src import state

console = Console()

# ─────────────────────────────────────────────────────────────────────────────
#  Alert subscribers (WebSocket push, Slack, etc.)
# ─────────────────────────────────────────────────────────────────────────────

_alert_subscribers: list[Callable] = []


def subscribe_to_alerts(callback: Callable):
    """Register a callback to receive alerts in real-time (e.g., WebSocket push)."""
    _alert_subscribers.append(callback)


async def _broadcast_alert(alert: dict):
    """Push alert to all subscribers."""
    for cb in _alert_subscribers:
        try:
            await cb(alert)
        except Exception as e:
            console.print(f"[yellow]Subscriber error: {e}[/yellow]")


# ─────────────────────────────────────────────────────────────────────────────
#  Main Monitor
# ─────────────────────────────────────────────────────────────────────────────

class AutonomousMonitor:

    def __init__(self, config_path: str = "config.yaml", demo_mode: bool = False):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        self.demo_mode = demo_mode
        self.check_interval = self.config["monitoring"]["check_interval_seconds"]
        self.min_confidence = self.config["thresholds"]["minimum_confidence"]
        self.cycle_count = 0

        # Bright Data client
        self.bd = BrightDataClient.from_env()

        # Agent (ReAct loop — wraps detectors as tools with AI reasoning)
        from src.agent import AlphaSignalAgent
        self.agent = AlphaSignalAgent(self.bd, demo_mode=demo_mode)

        # Signal detectors
        self.hiring    = HiringVelocityDetector(self.bd, self.config["thresholds"]["hiring_velocity_alert"])
        self.pricing   = PricingChangeDetector(self.bd, self.config["thresholds"]["pricing_change_alert"])
        self.funding   = FundingDetector(self.bd)
        self.news      = NewsDetector(self.bd)
        self.financial = FinancialHealthDetector(self.bd)
        self.supplier  = SupplierRiskDetector(self.bd)
        self.traffic   = WebTrafficDetector(self.bd, self.config["thresholds"]["traffic_growth_alert"])

        # Correlator + alert generator
        self.correlator = SignalCorrelator(self.config["thresholds"]["correlation_match_score"])
        # Alert generator (AI/ML API)
        self.alert_gen  = AlertGenerator(
            api_key=os.getenv("AIML_API_KEY", ""),
            base_url=os.getenv("AIML_BASE_URL", "https://api.aimlapi.com/v1"),
            model=os.getenv("AIML_MODEL", "claude-sonnet-4-20250514"),
            demo_mode=demo_mode,
        )

        # Output
        self.alerts_path = Path(self.config["alerts"]["jsonl_path"])
        self.alerts_path.parent.mkdir(parents=True, exist_ok=True)

        # State DB
        state.init_db()

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self):
        """Start the 24/7 monitoring loop."""
        mode_label = "[bold yellow]DEMO MODE[/bold yellow]" if self.demo_mode else "[bold green]LIVE MODE[/bold green]"
        companies = [c["name"] for c in self.config["watch_list"]["companies"]]

        console.print(Panel(
            f"[bold cyan]🚀 Autonomous Alternative Data Monitor[/bold cyan]\n\n"
            f"Mode: {mode_label}\n"
            f"Companies: {', '.join(companies)}\n"
            f"Check interval: {self.check_interval}s\n"
            f"Min confidence: {self.min_confidence}%\n"
            f"Dashboard: http://localhost:{self.config['dashboard']['port']}",
            title="Starting Monitor",
            border_style="cyan",
        ))

        while True:
            try:
                self.cycle_count += 1
                await self.run_cycle()
            except Exception as e:
                console.print(f"[red bold]Cycle error: {e}[/red bold]")
                import traceback
                traceback.print_exc()

            console.print(f"\n[dim]Next cycle in {self.check_interval}s (Ctrl+C to stop)[/dim]\n")
            await asyncio.sleep(self.check_interval)

    async def run_cycle(self):
        """Run one complete monitoring cycle for all companies."""
        console.print(f"\n[bold cyan]═══ Monitoring Cycle #{self.cycle_count} — {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC ═══[/bold cyan]")

        company_configs = self.config["watch_list"]["companies"]
        max_concurrent = self.config["monitoring"]["max_concurrent_companies"]

        # Run companies in parallel batches
        for i in range(0, len(company_configs), max_concurrent):
            batch = company_configs[i : i + max_concurrent]
            tasks = [self._monitor_company(c) for c in batch]
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _monitor_company(self, company_cfg: dict):
        """Run all signal detectors for one company and generate alert if warranted."""
        company  = company_cfg["name"]
        ticker   = company_cfg.get("ticker", company)
        pricing_url = company_cfg.get("pricing_url", "")
        suppliers = company_cfg.get("suppliers", [])

        console.print(f"\n[bold]📊 {company}[/bold] ({ticker})")

        try:
            # ── Agent investigation (ReAct loop, runs concurrently) ────────
            agent_task = asyncio.create_task(
                self.agent.investigate(company, company_cfg)
            )

            # ── Run all detectors in parallel ──────────────────────────────
            detector_tasks = {
                "hiring":    self.hiring.detect(company),
                "pricing":   self.pricing.detect(company, pricing_url),
                "funding":   self.funding.detect(company),
                "news":      self.news.detect(company),
                "financial": self.financial.detect(company, ticker),
                "supplier":  self.supplier.detect(company, suppliers),
                "traffic":   self.traffic.detect(company),
            }

            results = await asyncio.gather(*detector_tasks.values(), return_exceptions=True)
            signals = []
            for key, result in zip(detector_tasks.keys(), results):
                if isinstance(result, Exception):
                    console.print(f"  [yellow]⚠ {key} detector error: {result}[/yellow]")
                else:
                    signals.append(result)

            # ── Print signal summary ───────────────────────────────────────
            self._print_signal_table(company, signals)

            # ── Save signals to history ────────────────────────────────────
            for s in signals:
                state.save_signal(company, s["signal_type"], s.get("current_value", 0))

            # ── Correlation ────────────────────────────────────────────────
            correlation = await self.correlator.correlate(company, signals)
            if not correlation:
                console.print(f"  [dim]No strong correlation detected for {company}[/dim]")
                return

            console.print(
                f"  [bold yellow]🔗 Correlation: {correlation['correlation_label']} "
                f"(score: {correlation['match_score']:.0%}, "
                f"confidence: {correlation['confidence']:.0f}%)[/bold yellow]"
            )

            # ── Generate alert if confidence meets threshold ───────────────
            if correlation["confidence"] < self.min_confidence:
                console.print(f"  [dim]Confidence {correlation['confidence']:.0f}% below threshold {self.min_confidence}% — skipping alert[/dim]")
                return

            alert = await self.alert_gen.generate_alert(company, correlation, signals)
            await self._deliver_alert(alert)

            # ── Await agent findings (non-blocking — already running) ──────
            try:
                agent_findings = await asyncio.wait_for(agent_task, timeout=60)
                for finding in agent_findings:
                    console.print(f"  [bold cyan]🤖 Agent finding: {finding.get('alert_type')} ({finding.get('confidence_score', 0):.0f}%)[/bold cyan]")
                    await self._deliver_alert(finding)
            except asyncio.TimeoutError:
                console.print(f"  [dim]Agent timed out for {company}[/dim]")

        except Exception as e:
            console.print(f"  [red]Error monitoring {company}: {e}[/red]")
            import traceback
            traceback.print_exc()

    async def _deliver_alert(self, alert: dict):
        """Save alert, log it, and push to all subscribers."""
        # 1. Save to SQLite
        state.save_alert(alert)

        # 2. Append to JSONL
        with open(self.alerts_path, "a") as f:
            f.write(json.dumps(alert) + "\n")

        # 3. Print to console
        conf = alert.get("confidence_score", 0)
        sensitivity = alert.get("time_sensitivity", "moderate")
        color = {"immediate": "red", "urgent": "yellow", "moderate": "cyan", "low": "dim"}.get(sensitivity, "cyan")

        console.print(Panel(
            f"[bold]{alert.get('headline', 'Alert')}[/bold]\n\n"
            f"{alert.get('narrative', '')}\n\n"
            f"[bold]Recommendation:[/bold] {alert.get('recommendation', {}).get('trade', 'N/A')}\n"
            f"[bold]Conviction:[/bold] {alert.get('recommendation', {}).get('conviction', 'N/A')}\n"
            f"[bold]Risk:[/bold] {alert.get('recommendation', {}).get('risk', 'N/A')}",
            title=f"🚨 ALERT [{sensitivity.upper()}] — {alert['company']} — {conf:.0f}% confidence",
            border_style=color,
        ))

        # 4. Push to WebSocket subscribers (dashboard)
        await _broadcast_alert(alert)

        # 5. Push to Slack (if configured)
        try:
            from src.slack_alerts import send_market_alert
            sent = await send_market_alert(alert)
            if sent:
                console.print(f"  [green]✓ Slack alert sent[/green]")
        except Exception as e:
            console.print(f"  [dim]Slack: {e}[/dim]")

        console.print(f"  [green]✓ Alert saved: {alert['alert_id']}[/green]")

    def _print_signal_table(self, company: str, signals: list[dict]):
        """Print a rich table summarizing all signals for a company."""
        table = Table(box=box.SIMPLE, show_header=True, header_style="bold dim")
        table.add_column("Signal", style="bold")
        table.add_column("Current", justify="right")
        table.add_column("Baseline", justify="right")
        table.add_column("Variance", justify="right")
        table.add_column("Alert", justify="center")
        table.add_column("Confidence", justify="right")

        for s in signals:
            fired = s.get("alert", False)
            var = s.get("variance_pct", 0)
            var_str = f"[red]{var:+.1f}%[/red]" if abs(var) > 20 else f"{var:+.1f}%"
            alert_str = "[red bold]🔴 YES[/red bold]" if fired else "[green]🟢 no[/green]"
            conf = s.get("confidence", 0)
            conf_str = f"[yellow]{conf:.0f}%[/yellow]" if conf >= 70 else f"[dim]{conf:.0f}%[/dim]"

            table.add_row(
                s.get("signal_type", "").replace("_", " ").title(),
                f"{s.get('current_value', 0):.1f}",
                f"{s.get('baseline', 0):.1f}",
                var_str,
                alert_str,
                conf_str,
            )

        console.print(table)

    async def run_once(self):
        """Run exactly one monitoring cycle and exit cleanly."""
        self.cycle_count = 1
        try:
            await self.run_cycle()
        finally:
            await self.bd.close()
