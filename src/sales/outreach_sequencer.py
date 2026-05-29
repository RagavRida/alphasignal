"""
Outreach Sequencer + Email Sender
===================================
Tool: Claude (AI/ML API) for email generation + Resend for sending

Generates per-lead:
  1. Subject lines (3 variants)
  2. Hyper-personalized email body (150 words, context-driven)
  3. LinkedIn DM variant (60 words)
  4. Full 3-touch follow-up sequence (day 0, 3, 7, 14)

Then sends via Resend API.
"""

import json
import os
import uuid
import asyncio
from datetime import datetime
from typing import Optional

from openai import OpenAI

from src.sales.models import Lead, PersonalizationContext, OutreachEmail, CRMEntry


SYSTEM_PROMPT = """You are an elite B2B sales copywriter. Write hyper-personalized cold outreach
that feels like it's from a founder, not a salesperson.

Rules:
- Reference SPECIFIC context (blog post title, funding round, job posting)
- Lead with THEIR world, not your product
- 150 words MAX for email body
- No buzzwords, no "I hope this finds you well"
- End with ONE clear, low-friction CTA
- LinkedIn DM: 60 words max, even more casual

Output ONLY valid JSON."""


GENERATE_PROMPT = """Write a personalized outreach sequence for this prospect.

SENDER INFO (the person sending this email):
  Sender: {sender_name}
  Product: {product_name}
  What we do: {product_description}
  Website: {product_website}

PROSPECT:
  Company: {company}
  Contact: {contact_name}, {contact_title}
  Funding: {funding}
  Industry: {industry}

TALKING POINTS (use 1-2 of these):
{talking_points}

PAIN POINTS DETECTED:
{pain_points}

Return JSON:
{{
  "subject_lines": ["3 subject line variants (no clickbait)"],
  "step1": {{
    "subject": "best subject from above",
    "body": "email body — 150 words max, hyper-personalized, references specific context. Pitch {product_name} as the solution.",
    "linkedin_dm": "casual DM — 60 words max"
  }},
  "step2": {{
    "subject": "Re: [step1 subject]",
    "body": "follow-up day 3 — different angle, adds value, mentions {product_name}",
    "delay_days": 3
  }},
  "step3": {{
    "subject": "quick question",
    "body": "follow-up day 7 — very short, one question only",
    "delay_days": 7
  }},
  "step4": {{
    "subject": "closing the loop",
    "body": "breakup email day 14 — gives them an out, keeps door open",
    "delay_days": 14
  }}
}}"""


class OutreachSequencer:

    def __init__(self, api_key: str = "", base_url: str = "https://api.aimlapi.com/v1",
                 model: str = "claude-sonnet-4-20250514",
                 resend_api_key: str = "", from_email: str = ""):
        self.model       = model
        self.resend_key  = resend_api_key
        self.from_email  = from_email or "outreach@alphasignal.ai"
        self.client: Optional[OpenAI] = None

        if api_key:
            self.client = OpenAI(api_key=api_key, base_url=base_url)

        # ── Load brand profile so emails pitch the right product ──────────────
        try:
            from src.company_profile import load_profile
            profile = load_profile()
            self.product_name        = profile.get("company_name", "Our Platform")
            self.product_description = profile.get("product_description",
                                                   "We help you grow your business.")
            self.product_website     = profile.get("website", "")
            self.sender_name         = profile.get("sender_name") or profile.get("company_name", "[Your Name]")
        except Exception:
            self.product_name        = "Our Platform"
            self.product_description = "We help you grow your business."
            self.product_website     = ""
            self.sender_name         = "[Your Name]"

    async def generate_sequence(self, lead: Lead,
                                ctx: PersonalizationContext) -> list[OutreachEmail]:
        """Generate full 4-touch email sequence for a lead."""
        contact     = lead.contacts[0] if lead.contacts else None
        contact_name  = contact.name if contact else lead.company_name
        contact_title = contact.title if contact else "Founder"

        talking_str = "\n".join(f"  • {p}" for p in ctx.talking_points) or "  • Recent company growth"
        pain_str    = "\n".join(f"  • {p}" for p in ctx.pain_points) or "  • Scaling efficiently"

        if self.client:
            emails = await self._llm_generate(lead, contact_name, contact_title,
                                              talking_str, pain_str)
        else:
            emails = self._template_generate(lead, contact_name, contact_title, ctx)

        return emails

    async def _llm_generate(self, lead: Lead, contact_name: str, contact_title: str,
                            talking_str: str, pain_str: str) -> list[OutreachEmail]:
        prompt = GENERATE_PROMPT.format(
            company=lead.company_name,
            contact_name=contact_name,
            contact_title=contact_title,
            funding=lead.funding_amount or "N/A",
            industry=lead.industry or "B2B SaaS",
            talking_points=talking_str,
            pain_points=pain_str,
            # Inject brand profile so Claude pitches the right product
            product_name=self.product_name,
            product_description=self.product_description,
            product_website=self.product_website,
            sender_name=self.sender_name,
        )

        def _call():
            resp = self.client.chat.completions.create(
                model=self.model,
                max_tokens=1500,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
            )
            raw = resp.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            return json.loads(raw)

        loop = asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(None, _call)
            return self._data_to_emails(lead.id, data)
        except Exception as e:
            print(f"  [Sequencer] LLM error: {e} — using templates")
            return self._template_generate(lead, contact_name, contact_title, None)

    def _data_to_emails(self, lead_id: str, data: dict) -> list[OutreachEmail]:
        emails  = []
        steps   = ["step1", "step2", "step3", "step4"]
        delays  = [0, 3, 7, 14]
        for i, (step_key, delay) in enumerate(zip(steps, delays), start=1):
            step = data.get(step_key, {})
            emails.append(OutreachEmail(
                id=str(uuid.uuid4())[:8],
                lead_id=lead_id,
                sequence_step=i,
                delay_days=delay,
                subject=step.get("subject", f"Follow-up {i}"),
                body=step.get("body", ""),
                linkedin_dm=step.get("linkedin_dm", "") if i == 1 else "",
                personalization_tokens={"subject_variants": data.get("subject_lines", [])},
            ))
        return emails

    def _template_generate(self, lead: Lead, contact_name: str, contact_title: str,
                           ctx: Optional[PersonalizationContext]) -> list[OutreachEmail]:
        """Fallback templates — uses brand profile for product pitch."""
        company   = lead.company_name
        funding   = lead.funding_amount or "your recent round"
        first     = contact_name.split()[0] if contact_name else "there"
        industry  = lead.industry or "B2B"
        product   = self.product_name
        what_we_do = self.product_description
        website   = self.product_website
        sender    = self.sender_name

        return [
            OutreachEmail(
                id=str(uuid.uuid4())[:8], lead_id=lead.id, sequence_step=1, delay_days=0,
                subject=f"Congrats on {funding}, {first}",
                body=(
                    f"Hi {first},\n\n"
                    f"Congrats on the {funding} — great milestone.\n\n"
                    f"We built {product} for {industry} teams exactly like yours. "
                    f"{what_we_do}\n\n"
                    f"Worth a 15-minute chat to see if it fits?\n\n"
                    f"Best,\n{sender}"
                    + (f"\n{website}" if website else "")
                ),
                linkedin_dm=(
                    f"Hey {first} — saw the {funding} news, congrats! "
                    f"Built {product} that {industry} founders are using right now. "
                    f"Happy to share — open to a quick chat?"
                ),
            ),
            OutreachEmail(
                id=str(uuid.uuid4())[:8], lead_id=lead.id, sequence_step=2, delay_days=3,
                subject=f"One thing working really well for {industry} teams right now",
                body=(
                    f"Hi {first},\n\n"
                    f"Wanted to follow up — companies like {company} "
                    f"are getting a lot out of {product}. {what_we_do}\n\n"
                    f"Happy to show you a quick demo.\n\n"
                    f"Worth 15 mins?\n\n"
                    f"Best,\n{sender}"
                ),
            ),
            OutreachEmail(
                id=str(uuid.uuid4())[:8], lead_id=lead.id, sequence_step=3, delay_days=7,
                subject="Quick question",
                body=(
                    f"Hi {first},\n\n"
                    f"Is {product} something that could help {company} right now?\n\n"
                    f"{sender}"
                ),
            ),
            OutreachEmail(
                id=str(uuid.uuid4())[:8], lead_id=lead.id, sequence_step=4, delay_days=14,
                subject="Closing the loop",
                body=(
                    f"Hi {first},\n\n"
                    f"I'll stop following up after this — I know timing isn't always right.\n\n"
                    f"If {product} ever becomes relevant at {company}, feel free to reach out.\n\n"
                    f"Best of luck with the {funding} deployment!\n\n"
                    f"{sender}"
                    + (f"\n{website}" if website else "")
                ),
            ),
        ]

    # ── Email Sending via Resend ───────────────────────────────────────────────

    async def send_email(self, email: OutreachEmail, to_email: str,
                         to_name: str = "") -> bool:
        """
        Send an email via Resend API.
        Returns True on success.
        """
        if not self.resend_key:
            print(f"  [Sequencer] No Resend key — email not sent (draft only)")
            return False

        if not to_email or "@" not in to_email:
            print(f"  [Sequencer] Invalid email address: {to_email}")
            return False

        def _call():
            import resend
            resend.api_key = self.resend_key
            params = {
                "from":    self.from_email,
                "to":      [to_email],
                "subject": email.subject,
                "text":    email.body,
                "html":    self._body_to_html(email.body),
            }
            return resend.Emails.send(params)

        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(None, _call)
            print(f"  [Resend] ✓ Sent to {to_email} — ID: {result.get('id', 'N/A')}")
            return True
        except Exception as e:
            print(f"  [Resend] ✗ Send failed to {to_email}: {e}")
            return False

    def _body_to_html(self, text: str) -> str:
        """Convert plain text email to basic HTML."""
        paragraphs = text.split("\n\n")
        html_parts = ["<!DOCTYPE html><html><body style='font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px;color:#1a1a1a;line-height:1.6'>"]
        for p in paragraphs:
            lines = p.replace("\n", "<br>")
            html_parts.append(f"<p>{lines}</p>")
        html_parts.append("</body></html>")
        return "".join(html_parts)

    # ── CRM Logging ───────────────────────────────────────────────────────────

    def build_crm_entry(self, lead: Lead, emails: list[OutreachEmail]) -> CRMEntry:
        """Build a CRM entry from a lead and its email sequence."""
        contact = lead.contacts[0] if lead.contacts else None
        return CRMEntry(
            lead_id=lead.id,
            company_name=lead.company_name,
            contact_name=contact.name if contact else "",
            contact_title=contact.title if contact else "",
            emails=emails,
            status="sequence_ready",
            notes=(
                f"Score: {lead.score}/100 | "
                f"Funding: {lead.funding_amount or 'N/A'} | "
                f"Stage: {lead.funding_stage or 'N/A'} | "
                f"Signals: {', '.join(lead.hiring_signals[:2]) or 'none'}"
            ),
        )
