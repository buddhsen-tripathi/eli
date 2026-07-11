"""
Notify loved ones after a check-in call — by email.

`notify_caregivers(call_id)` loads the patient's caregivers and the call's summary
+ triage, then emails each caregiver (with an email on file) whose `notify_when`
preference matches this call's triage level. Uses Resend's REST API; the key is
read lazily so missing config degrades to a logged no-op rather than crashing.

Env:
  RESEND_API_KEY     — Resend API key (re_...)
  NOTIFY_FROM_EMAIL  — sender, e.g. "Eli Care <care@yourdomain.com>"
                       (defaults to Resend's test sender, which only delivers to
                       your own Resend account email)
"""

import asyncio
import os
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal
from app.db_models import Call, Caregiver, Patient

DEFAULT_FROM = "Eli Care <onboarding@resend.dev>"

_LEVEL = {
    "urgent": ("⚠️ Please check on {name}", "#dc2626", "Their post-op check-in raised a concern."),
    "monitor": ("Update on {name}'s recovery", "#d97706", "A few things worth keeping an eye on."),
    "ok": ("{name} is doing well", "#059669", "Their post-op check-in went smoothly."),
}


def _should_notify(notify_when: str, level: str) -> bool:
    if notify_when == "never":
        return False
    if notify_when == "urgent":
        return level == "urgent"
    return True  # "always"


def _compose_email(patient_name: str, level: str, summary: str, flags: list[str]) -> tuple[str, str]:
    subject_tpl, color, tagline = _LEVEL.get(level, _LEVEL["monitor"])
    subject = subject_tpl.format(name=patient_name)
    flag_html = ""
    if flags:
        items = "".join(
            f'<li style="margin:4px 0;color:#374151;">{f}</li>' for f in flags
        )
        flag_html = (
            '<p style="margin:20px 0 6px;font-size:13px;font-weight:600;'
            'text-transform:uppercase;letter-spacing:.05em;color:#6b7280;">Things noted</p>'
            f'<ul style="margin:0;padding-left:18px;">{items}</ul>'
        )
    html = f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:520px;margin:0 auto;padding:24px;">
  <div style="border-left:4px solid {color};padding:4px 0 4px 16px;">
    <p style="margin:0;font-size:13px;letter-spacing:.05em;text-transform:uppercase;color:#6b7280;">Eli · post-op care</p>
    <h1 style="margin:6px 0 2px;font-size:22px;color:#111827;">{subject}</h1>
    <p style="margin:0;color:#6b7280;font-size:14px;">{tagline}</p>
  </div>
  <p style="margin:22px 0 0;font-size:16px;line-height:1.6;color:#111827;">{summary}</p>
  {flag_html}
  <p style="margin:28px 0 0;font-size:12px;color:#9ca3af;">
    You're receiving this because you're listed as a contact for {patient_name}.
    This is an automated recovery update, not medical advice — in an emergency call 911.
  </p>
</div>"""
    return subject, html


def _send_email_sync(to: str, from_email: str, subject: str, html: str) -> None:
    api_key = os.environ["RESEND_API_KEY"]
    resp = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"from": from_email, "to": [to], "subject": subject, "html": html},
        timeout=15.0,
    )
    resp.raise_for_status()


async def notify_caregivers(call_id: str) -> None:
    async with AsyncSessionLocal() as session:
        call = await session.get(Call, call_id)
        if not call or not call.patient_id:
            print(f"[notify] call {call_id} has no patient — skipping", flush=True)
            return

        result = await session.execute(
            select(Patient)
            .where(Patient.id == call.patient_id)
            .options(selectinload(Patient.caregivers))
        )
        patient = result.scalar_one_or_none()
        if not patient:
            return

        triage = call.triage or {"level": "ok"}
        level = triage.get("level", "ok")
        summary = call.summary or "Check-in completed."
        flags = triage.get("flags", []) or []
        caregivers = list(patient.caregivers)

    if not os.environ.get("RESEND_API_KEY"):
        print("[notify] RESEND_API_KEY not set — skipping caregiver email", flush=True)
        return

    from_email = os.environ.get("NOTIFY_FROM_EMAIL", DEFAULT_FROM)
    subject, html = _compose_email(patient.name, level, summary, flags)

    sent = 0
    for cg in caregivers:
        if not cg.email or not _should_notify(cg.notify_when, level):
            continue
        try:
            await asyncio.to_thread(_send_email_sync, cg.email, from_email, subject, html)
            sent += 1
        except Exception as e:
            print(f"[notify] failed to email {cg.name}: {e}", flush=True)

    async with AsyncSessionLocal() as session:
        call = await session.get(Call, call_id)
        if call:
            call.notified_at = datetime.now(timezone.utc)
            await session.commit()

    print(f"[notify] call {call_id}: emailed {sent}/{len(caregivers)} caregivers (level={level})", flush=True)
