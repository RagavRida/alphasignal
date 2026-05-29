"""
AlphaSignal — Autonomous Alternative Data Pipeline
Entry point for the complete monitoring system.

Usage:
  python main.py                         # Start monitor + dashboard (live mode)
  python main.py --demo                  # Demo mode (no credentials needed)
  python main.py --run-once              # Run one monitoring cycle and exit
  python main.py --dashboard-only        # Just the dashboard server
  python main.py --test-credentials      # Verify Bright Data API credentials
  python main.py --company Tesla         # Monitor a single company
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

# Load environment variables
load_dotenv()

console = Console()


def parse_args():
    parser = argparse.ArgumentParser(
        description="AlphaSignal — Autonomous Alternative Data Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--demo",           action="store_true", help="Run in demo mode (no credentials needed)")
    parser.add_argument("--run-once",       action="store_true", help="Run one monitoring cycle and exit")
    parser.add_argument("--dashboard-only", action="store_true", help="Start only the dashboard server")
    parser.add_argument("--test-credentials", action="store_true", help="Test Bright Data API credentials")
    parser.add_argument("--company",        type=str, help="Monitor a single company by name")
    parser.add_argument("--config",         type=str, default="config.yaml", help="Path to config file")
    parser.add_argument("--interval",       type=int, help="Override check interval (seconds)")
    return parser.parse_args()


async def test_credentials():
    """Test each Bright Data API connection."""
    from src.bright_data_client import BrightDataClient

    token = os.getenv("BRIGHT_DATA_API_TOKEN", "")
    if not token:
        console.print("[red]❌ BRIGHT_DATA_API_TOKEN not set in .env[/red]")
        return False

    client = BrightDataClient(
        api_token=token,
        serp_zone=os.getenv("BRIGHT_DATA_SERP_ZONE", "serp_api1"),
        scraper_zone=os.getenv("BRIGHT_DATA_SCRAPER_ZONE", "datacenter_proxy1"),
        mcp_url=os.getenv("BRIGHT_DATA_MCP_URL", ""),
        demo_mode=False,
    )

    tests = [
        ("SERP API",        lambda: client.serp_search("Tesla quarterly earnings")),
        ("Web Scraper API", lambda: client.scrape_linkedin_jobs("Tesla")),
        ("Scraping Browser",lambda: client.scrape_pricing_page("https://www.tesla.com/model3", "Tesla")),
        ("Web Unlocker",    lambda: client.access_secured_site("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=TSLA&type=10-Q")),
    ]

    all_ok = True
    for name, test_fn in tests:
        try:
            result = await test_fn()
            status = "✅" if result else "⚠️"
            console.print(f"{status} {name}: OK")
        except Exception as e:
            console.print(f"❌ {name}: {e}")
            all_ok = False

    await client.close()
    return all_ok


async def run_dashboard_server(host: str, port: int):
    """Start the FastAPI dashboard server."""
    import uvicorn
    from src.dashboard.server import app

    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    console.print(f"[bold cyan]🌐 Dashboard: http://{host}:{port}[/bold cyan]")
    await server.serve()


async def main():
    args = parse_args()

    # Seed demo mode from env or flag
    demo_mode = args.demo or os.getenv("DEMO_MODE", "false").lower() == "true"

    console.print(Panel(
        "[bold cyan]AlphaSignal[/bold cyan] — Autonomous Alternative Data Pipeline\n"
        "[dim]Bright Data Hackathon 2024[/dim]",
        border_style="cyan",
    ))

    # ── Test credentials ──────────────────────────────────────────────────────
    if args.test_credentials:
        ok = await test_credentials()
        sys.exit(0 if ok else 1)

    # ── Ensure config exists ──────────────────────────────────────────────────
    if not Path(args.config).exists():
        console.print(f"[red]Config file not found: {args.config}[/red]")
        sys.exit(1)

    # ── Load config for dashboard settings ────────────────────────────────────
    import yaml
    with open(args.config) as f:
        config = yaml.safe_load(f)
    dashboard_host = os.getenv("DASHBOARD_HOST", config["dashboard"]["host"])
    dashboard_port = int(os.getenv("DASHBOARD_PORT", config["dashboard"]["port"]))

    # ── Dashboard only ────────────────────────────────────────────────────────
    if args.dashboard_only:
        await run_dashboard_server(dashboard_host, dashboard_port)
        return

    # ── Build monitor ─────────────────────────────────────────────────────────
    from src.monitor import AutonomousMonitor, subscribe_to_alerts
    from src.dashboard.server import app, broadcast_alert

    # Override check interval if provided
    monitor = AutonomousMonitor(config_path=args.config, demo_mode=demo_mode)
    if args.interval:
        monitor.check_interval = args.interval

    # Override for single company
    if args.company:
        companies = monitor.config["watch_list"]["companies"]
        match = [c for c in companies if c["name"].lower() == args.company.lower()]
        if not match:
            console.print(f"[yellow]Company '{args.company}' not found in watch list. Using all companies.[/yellow]")
        else:
            monitor.config["watch_list"]["companies"] = match

    # Wire up WebSocket broadcast
    subscribe_to_alerts(broadcast_alert)

    # ── Run once ──────────────────────────────────────────────────────────────
    if args.run_once:
        console.print("[bold]Running one monitoring cycle…[/bold]")
        await monitor.run_once()
        console.print("[green]✓ Cycle complete. Check data/alerts.jsonl for results.[/green]")
        return

    # ── Full mode: monitor + dashboard together ───────────────────────────────
    import uvicorn
    uvicorn_config = uvicorn.Config(app, host=dashboard_host, port=dashboard_port, log_level="warning")
    server = uvicorn.Server(uvicorn_config)

    console.print(f"[bold cyan]🌐 Dashboard: http://{dashboard_host}:{dashboard_port}[/bold cyan]")

    await asyncio.gather(
        server.serve(),
        monitor.run(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Monitor stopped.[/yellow]")
