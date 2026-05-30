"""
Follow-up Scheduler
====================
Autonomously sends Step 2, 3, and 4 emails based on elapsed time since Step 1.

No inbox access needed — purely state-based:
  - Step 1 sent → wait 3 days  → send Step 2
  - Step 2 sent → wait 7 days  → send Step 3
  - Step 3 sent → wait 14 days → send Step 4

Runs as a background asyncio task. Checks every hour.
"""

import asyncio
import os
from datetime import datetime, timedelta
from pathlib import Path

from src.sales import sales_state


# Days to wait between each step
STEP_DELAYS = {1: 3, 2: 7, 3: 14}   # step_sent → days until next step


class FollowUpScheduler:
    """
    Polls SQLite every `check_interval` seconds.
    For each lead in "emailed" state, checks whether the next step is due
    and sends it via Resend if so.
    """

    def __init__(self, check_interval: int = 3600):
        self.check_interval = check_interval
        self._running = False

    async def run(self):
        """Blocking loop — meant to run as an asyncio background task."""
        self._running = True
        print("[FollowUpScheduler] started — checking every "
              f"{self.check_interval}s", flush=True)
        while self._running:
            try:
                await self._tick()
            except Exception as e:
                print(f"[FollowUpScheduler] tick error: {e}", flush=True)
            await asyncio.sleep(self.check_interval)

    def stop(self):
        self._running = False

    async def _tick(self):
        resend_key = os.getenv("RESEND_API_KEY", "")
        from_email = os.getenv("RESEND_FROM_EMAIL",
                                "outreach@alphasignal.ai")
        if not resend_key:
            return

        from src.sales.outreach_sequencer import OutreachSequencer
        sequencer = OutreachSequencer(
            resend_api_key=resend_key,
            from_email=from_email,
        )

        due = sales_state.get_followup_due_leads()
        if not due:
            return

        print(f"[FollowUpScheduler] {len(due)} leads due for follow-up",
              flush=True)

        for entry in due:
            lead_id       = entry["lead_id"]
            next_step     = entry["next_step"]         # 2, 3, or 4
            contact_email = entry.get("contact_email", "")
            contact_name  = entry.get("contact_name", "")

            if not contact_email or "@" not in contact_email:
                continue

            # Fetch the right email object from SQLite
            emails = sales_state.get_emails_for_lead(lead_id)
            target = next(
                (e for e in emails if e.get("step") == next_step), None
            )
            if not target:
                continue

            from src.sales.models import OutreachEmail
            email_obj = OutreachEmail(
                id            = target.get("id", ""),
                lead_id       = lead_id,
                sequence_step = next_step,
                subject       = target.get("subject", ""),
                body          = target.get("body", ""),
                channel       = "email",
            )

            sent = await sequencer.send_email(
                email_obj, contact_email, contact_name
            )
            if sent:
                sales_state.update_email_status(email_obj.id, "sent")
                sales_state.record_followup_sent(lead_id, next_step)
                print(f"[FollowUpScheduler] Step {next_step} sent to "
                      f"{contact_email} for lead {lead_id}", flush=True)
