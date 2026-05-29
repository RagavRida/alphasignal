"""
State persistence layer using SQLite.

Stores:
  - Historical signal baselines (per company, per signal type)
  - Signal snapshots (for trend analysis)
  - All generated alerts
  - Check timestamps (throttling)
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional


DB_PATH = Path("data/state.db")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """Initialize all tables."""
    conn = _connect()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS signal_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            company     TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            value       REAL,
            value_json  TEXT,
            timestamp   TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_sig_company_type
            ON signal_history (company, signal_type, timestamp);

        CREATE TABLE IF NOT EXISTS baselines (
            company     TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            baseline    REAL NOT NULL,
            updated_at  TEXT NOT NULL,
            PRIMARY KEY (company, signal_type)
        );

        CREATE TABLE IF NOT EXISTS alerts (
            alert_id    TEXT PRIMARY KEY,
            company     TEXT NOT NULL,
            alert_type  TEXT NOT NULL,
            confidence  REAL NOT NULL,
            headline    TEXT,
            payload_json TEXT NOT NULL,
            timestamp   TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS check_log (
            company     TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            checked_at  TEXT NOT NULL,
            PRIMARY KEY (company, signal_type)
        );
    """)
    conn.commit()
    conn.close()


# ── Baselines ─────────────────────────────────────────────────────────────────

def get_baseline(company: str, signal_type: str) -> Optional[float]:
    conn = _connect()
    row = conn.execute(
        "SELECT baseline FROM baselines WHERE company=? AND signal_type=?",
        (company, signal_type),
    ).fetchone()
    conn.close()
    return row["baseline"] if row else None


def set_baseline(company: str, signal_type: str, value: float):
    conn = _connect()
    conn.execute(
        """INSERT INTO baselines (company, signal_type, baseline, updated_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(company, signal_type) DO UPDATE SET
               baseline   = excluded.baseline,
               updated_at = excluded.updated_at""",
        (company, signal_type, value, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def update_baseline_rolling(company: str, signal_type: str, new_value: float, alpha: float = 0.3):
    """Exponential moving average for baseline — adapts slowly to normal changes."""
    existing = get_baseline(company, signal_type)
    if existing is None:
        set_baseline(company, signal_type, new_value)
    else:
        updated = (1 - alpha) * existing + alpha * new_value
        set_baseline(company, signal_type, updated)


# ── Signal History ────────────────────────────────────────────────────────────

def save_signal(company: str, signal_type: str, value: float, value_json: dict = None):
    conn = _connect()
    conn.execute(
        "INSERT INTO signal_history (company, signal_type, value, value_json, timestamp) VALUES (?, ?, ?, ?, ?)",
        (company, signal_type, value, json.dumps(value_json or {}), datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def get_signal_history(company: str, signal_type: str, days: int = 30) -> list[dict]:
    conn = _connect()
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT * FROM signal_history WHERE company=? AND signal_type=? AND timestamp >= ? ORDER BY timestamp DESC",
        (company, signal_type, since),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Alerts ────────────────────────────────────────────────────────────────────

def save_alert(alert: dict):
    conn = _connect()
    conn.execute(
        """INSERT OR REPLACE INTO alerts
           (alert_id, company, alert_type, confidence, headline, payload_json, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            alert["alert_id"],
            alert["company"],
            alert.get("alert_type", alert.get("correlation_type", "unknown")),
            alert.get("confidence_score", 0),
            alert.get("headline", ""),
            json.dumps(alert),
            alert.get("timestamp", datetime.utcnow().isoformat()),
        ),
    )
    conn.commit()
    conn.close()


def get_recent_alerts(limit: int = 50) -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT payload_json FROM alerts ORDER BY timestamp DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [json.loads(r["payload_json"]) for r in rows]


def get_company_alerts(company: str, limit: int = 20) -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT payload_json FROM alerts WHERE company=? ORDER BY timestamp DESC LIMIT ?",
        (company, limit),
    ).fetchall()
    conn.close()
    return [json.loads(r["payload_json"]) for r in rows]


def get_alert_stats() -> dict:
    conn = _connect()
    total = conn.execute("SELECT COUNT(*) AS c FROM alerts").fetchone()["c"]
    by_type = conn.execute(
        "SELECT alert_type, COUNT(*) AS c FROM alerts GROUP BY alert_type"
    ).fetchall()
    by_company = conn.execute(
        "SELECT company, COUNT(*) AS c FROM alerts GROUP BY company ORDER BY c DESC LIMIT 10"
    ).fetchall()
    avg_conf = conn.execute("SELECT AVG(confidence) AS a FROM alerts").fetchone()["a"] or 0
    conn.close()
    return {
        "total_alerts": total,
        "avg_confidence": round(avg_conf, 1),
        "by_type": {r["alert_type"]: r["c"] for r in by_type},
        "by_company": {r["company"]: r["c"] for r in by_company},
    }


# ── Check throttling ──────────────────────────────────────────────────────────

def should_check(company: str, signal_type: str, min_interval_seconds: int = 3600) -> bool:
    """Returns True if enough time has passed since the last check."""
    conn = _connect()
    row = conn.execute(
        "SELECT checked_at FROM check_log WHERE company=? AND signal_type=?",
        (company, signal_type),
    ).fetchone()
    conn.close()
    if not row:
        return True
    last = datetime.fromisoformat(row["checked_at"])
    return (datetime.utcnow() - last).total_seconds() >= min_interval_seconds


def record_check(company: str, signal_type: str):
    conn = _connect()
    conn.execute(
        """INSERT INTO check_log (company, signal_type, checked_at)
           VALUES (?, ?, ?)
           ON CONFLICT(company, signal_type) DO UPDATE SET checked_at=excluded.checked_at""",
        (company, signal_type, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()
