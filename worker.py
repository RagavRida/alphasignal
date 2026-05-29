"""
worker.py — Render background worker entry point.

Runs the AutonomousMonitor loop continuously.
The dashboard (FastAPI) runs as a separate Render web service.
Alerts are broadcast via the shared state / JSONL file.
"""

import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


async def main():
    config_path = os.getenv("CONFIG_PATH", "config.yaml")

    if not Path(config_path).exists():
        print(f"[worker] Config file not found: {config_path}", flush=True)
        sys.exit(1)

    demo_mode = os.getenv("DEMO_MODE", "false").lower() == "true"
    check_interval = int(os.getenv("CHECK_INTERVAL", "3600"))

    print(f"[worker] Starting AutonomousMonitor | demo={demo_mode} | interval={check_interval}s", flush=True)

    from src.monitor import AutonomousMonitor

    monitor = AutonomousMonitor(config_path=config_path, demo_mode=demo_mode)
    monitor.check_interval = check_interval

    await monitor.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[worker] Monitor stopped.", flush=True)
