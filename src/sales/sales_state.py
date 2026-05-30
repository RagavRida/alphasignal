"""
Sales State — SQLite persistence for leads, emails, signals, CRM entries.
Separate DB from the hedge fund monitor (data/sales.db).
"""

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from datetime import datetime
from typing import Optional

from src.sales.models import Lead, IntentSignal, OutreachEmail, CRMEntry

DB_PATH = Path("data/sales.db")


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS leads (
            id TEXT PRIMARY KEY,
            company_name TEXT,
            domain TEXT,
            industry TEXT,
            geo TEXT,
            headcount TEXT,
            funding_stage TEXT,
            funding_amount TEXT,
            funding_date TEXT,
            score REAL,
            status TEXT DEFAULT 'new',
            data_json TEXT,
            discovered_at TEXT
        );

        CREATE TABLE IF NOT EXISTS intent_signals (
            id TEXT PRIMARY KEY,
            intent_type TEXT,
            source TEXT,
            source_url TEXT,
            quote TEXT,
            company_mentioned TEXT,
            lead_match TEXT,
            confidence REAL,
            detected_at TEXT
        );

        CREATE TABLE IF NOT EXISTS outreach_emails (
            id TEXT PRIMARY KEY,
            lead_id TEXT,
            sequence_step INTEGER,
            delay_days INTEGER,
            subject TEXT,
            body TEXT,
            linkedin_dm TEXT,
            status TEXT DEFAULT 'draft',
            generated_at TEXT,
            sent_at TEXT,
            FOREIGN KEY (lead_id) REFERENCES leads(id)
        );

        CREATE TABLE IF NOT EXISTS crm_entries (
            lead_id TEXT PRIMARY KEY,
            company_name TEXT,
            contact_name TEXT,
            contact_title TEXT,
            status TEXT,
            notes TEXT,
            logged_at TEXT
        );

        CREATE TABLE IF NOT EXISTS followup_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id TEXT,
            step_sent INTEGER,
            contact_email TEXT,
            sent_at TEXT
        );
        """)


def clear_run_data():
    """Wipe all leads, emails, signals and CRM from the previous run.
    Called at the start of each new pipeline run so the UI shows only fresh results."""
    with _conn() as c:
        c.executescript("""
        DELETE FROM leads;
        DELETE FROM outreach_emails;
        DELETE FROM intent_signals;
        DELETE FROM crm_entries;
        """)


def save_lead(lead: Lead):
    with _conn() as c:
        c.execute("""
        INSERT OR REPLACE INTO leads
          (id, company_name, domain, industry, geo, headcount,
           funding_stage, funding_amount, funding_date, score, status, data_json, discovered_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            lead.id, lead.company_name, lead.domain,
            lead.industry, lead.geo, lead.headcount,
            lead.funding_stage, lead.funding_amount, lead.funding_date,
            lead.score, lead.status,
            json.dumps({
                "description":   lead.description,
                "linkedin_url":  lead.linkedin_url,
                "tech_stack":    lead.tech_stack,
                "hiring_signals": lead.hiring_signals,
                "contacts":      [vars(co) for co in lead.contacts],
                "score_reasons": lead.score_reasons,
                "source_urls":   lead.source_urls,
            }),
            lead.discovered_at,
        ))


def save_signal(signal: IntentSignal):
    with _conn() as c:
        c.execute("""
        INSERT OR REPLACE INTO intent_signals
          (id, intent_type, source, source_url, quote, company_mentioned, lead_match, confidence, detected_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            signal.id, signal.intent_type, signal.source, signal.source_url,
            signal.quote, signal.company_mentioned, signal.lead_match,
            signal.confidence, signal.detected_at,
        ))


def save_emails(emails: list[OutreachEmail]):
    with _conn() as c:
        for e in emails:
            c.execute("""
            INSERT OR REPLACE INTO outreach_emails
              (id, lead_id, sequence_step, delay_days, subject, body, linkedin_dm, status, generated_at, sent_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (
                e.id, e.lead_id, e.sequence_step, e.delay_days,
                e.subject, e.body, e.linkedin_dm, e.status,
                e.generated_at, e.sent_at,
            ))


def save_crm(entry: CRMEntry):
    with _conn() as c:
        c.execute("""
        INSERT OR REPLACE INTO crm_entries
          (lead_id, company_name, contact_name, contact_title, status, notes, logged_at)
        VALUES (?,?,?,?,?,?,?)
        """, (
            entry.lead_id, entry.company_name, entry.contact_name,
            entry.contact_title, entry.status, entry.notes, entry.logged_at,
        ))


def get_leads(limit: int = 100, status: str = None) -> list[dict]:
    with _conn() as c:
        if status:
            rows = c.execute("SELECT * FROM leads WHERE status=? ORDER BY score DESC LIMIT ?",
                             (status, limit)).fetchall()
        else:
            rows = c.execute("SELECT * FROM leads ORDER BY score DESC LIMIT ?",
                             (limit,)).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        extra = json.loads(d.pop("data_json", "{}"))
        d.update(extra)
        result.append(d)
    return result


def get_emails(lead_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM outreach_emails WHERE lead_id=? ORDER BY sequence_step",
            (lead_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_signals(limit: int = 50) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM intent_signals ORDER BY confidence DESC, detected_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def update_email_status(email_id: str, status: str, sent_at: str = ""):
    with _conn() as c:
        c.execute(
            "UPDATE outreach_emails SET status=?, sent_at=? WHERE id=?",
            (status, sent_at or datetime.utcnow().isoformat() + "Z", email_id),
        )


def update_lead_status(lead_id: str, status: str):
    with _conn() as c:
        c.execute("UPDATE leads SET status=? WHERE id=?", (status, lead_id))


def get_emails_for_lead(lead_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM outreach_emails WHERE lead_id=? ORDER BY sequence_step",
            (lead_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_followup_due_leads() -> list[dict]:
    """
    Returns leads where the next follow-up step is due based on elapsed days.
    Step delays: Step1→Step2: 3 days, Step2→Step3: 7 days, Step3→Step4: 14 days.
    """
    step_delays = {1: 3, 2: 7, 3: 14}
    due = []
    with _conn() as c:
        # Get leads that have at least one sent email
        rows = c.execute("""
            SELECT l.id as lead_id, l.status,
                   MAX(e.sequence_step) as last_step,
                   e.sent_at, e.id as last_email_id,
                   cr.contact_name, cr.contact_title
            FROM leads l
            JOIN outreach_emails e ON l.id = e.lead_id
            LEFT JOIN crm_entries cr ON l.id = cr.lead_id
            WHERE e.status = 'sent'
            GROUP BY l.id
        """).fetchall()

    for row in rows:
        r = dict(row)
        last_step = r.get("last_step", 0)
        if last_step >= 4:
            continue  # sequence complete
        sent_at_str = r.get("sent_at", "")
        if not sent_at_str:
            continue
        try:
            sent_at = datetime.fromisoformat(sent_at_str.replace("Z", ""))
        except ValueError:
            continue
        delay = step_delays.get(last_step, 999)
        if datetime.utcnow() >= sent_at + timedelta(days=delay):
            # Look up contact email from CRM or lead data
            contact_email = ""
            with _conn() as c:
                lead_row = c.execute(
                    "SELECT data_json FROM leads WHERE id=?", (r["lead_id"],)
                ).fetchone()
                if lead_row and lead_row["data_json"]:
                    import json
                    data = json.loads(lead_row["data_json"])
                    contacts = data.get("contacts", [])
                    if contacts:
                        contact_email = contacts[0].get("email", "")
            due.append({
                "lead_id":       r["lead_id"],
                "next_step":     last_step + 1,
                "contact_email": contact_email,
                "contact_name":  r.get("contact_name", ""),
            })
    return due


def record_followup_sent(lead_id: str, step: int, contact_email: str = ""):
    with _conn() as c:
        c.execute(
            "INSERT INTO followup_log (lead_id, step_sent, contact_email, sent_at) VALUES (?,?,?,?)",
            (lead_id, step, contact_email, datetime.utcnow().isoformat() + "Z"),
        )
