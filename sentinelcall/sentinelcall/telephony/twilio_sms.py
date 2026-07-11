"""Twilio SMS — escalation to nurse (clinical) or volunteer (presence-only).

THE HARD BARRIER (company-ending if violated): volunteers handle PRESENCE, never
medicine. The clinical-vs-wellness split is enforced HERE, in code — the system
literally cannot send clinical content down the volunteer channel. A red-flag
result marked `clinical=True` routes ONLY to the nurse number; the volunteer
body is generated from a separate, sanitized template that carries no symptoms,
diagnoses, meds, or wound detail.

If Twilio isn't configured, we still render the exact SMS to the console/trace
(so the demo shows the escalation) and return a simulated result — the whole
pipeline works without a live carrier, and the finale swaps in the real send.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from sentinelcall.agent.redflags import RedFlagResult, Route
from sentinelcall.config import get_settings
from sentinelcall.data.record import Patient
from sentinelcall.obs import trace as _trace


@dataclass
class SMSResult:
    sent: bool
    channel: str          # nurse | volunteer
    to: Optional[str]
    body: str
    sid: Optional[str] = None
    simulated: bool = False


def _nurse_body(patient: Patient, flags: RedFlagResult, *, extra: str = "") -> str:
    """Structured clinical escalation for the NURSE. This is the ONLY body that
    may contain clinical detail (symptoms, meds, wound status)."""
    lines = [
        "🏥 SENTINELCALL — CLINICAL ESCALATION",
        f"Patient: {patient.name} ({patient.patient_id})",
        f"Surgery: {patient.surgery}, post-op day {patient.post_op_day}",
        f"Surgeon: {patient.surgeon}",
        f"Phone: {patient.phone}",
        "",
        "Signals (agreement-based, agent did NOT diagnose):",
    ]
    for f in flags.flags:
        if f.clinical:
            lines.append(f"  • {f.label}: {f.detail}")
    if extra:
        lines.append("")
        lines.append(f"Patient words: “{extra.strip()}”")
    lines.append("")
    lines.append("Recommended: nurse call-back for assessment. Not an agent diagnosis.")
    return "\n".join(lines)


def _volunteer_body(patient: Patient, flags: RedFlagResult) -> str:
    """PRESENCE-ONLY task for a VOLUNTEER. Carries NO clinical content — no
    symptoms, no meds, no wound/diagnosis. Only a bounded wellness action."""
    # Map presence signals to bounded, non-clinical asks.
    action = "Please do a friendly wellbeing check-in."
    for f in flags.flags:
        if f.label == "no_food":
            action = "Please help with food/groceries and confirm they've eaten."
        elif f.label == "isolation":
            action = "Please pay a friendly visit for company."
        elif f.label == "missed_calls":
            action = "Please knock, confirm they're safe, and report back."
    return "\n".join([
        "🤝 SENTINELCALL — VOLUNTEER CHECK-IN",
        f"Community member: {patient.preferred_name}",
        f"Area contact via care team.",
        "",
        action,
        "",
        "You are NOT a caregiver: presence and company only. Do NOT assess any "
        "medical issue, wound, or medication. If they seem unwell, call the "
        "nurse line or 9 1 1 — do not handle it yourself.",
    ])


def _send(to: str, body: str) -> SMSResult:
    settings = get_settings()
    channel = "nurse"  # caller sets the real label; overwritten below
    if not (settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_from_number):
        # No Twilio configured — simulate (still fully visible in the trace).
        return SMSResult(sent=False, channel=channel, to=to, body=body, simulated=True)
    try:
        from twilio.rest import Client

        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        msg = client.messages.create(body=body, from_=settings.twilio_from_number, to=to)
        return SMSResult(sent=True, channel=channel, to=to, body=body, sid=msg.sid)
    except Exception as exc:
        _trace.event("sms.error", error=repr(exc))
        return SMSResult(sent=False, channel=channel, to=to, body=body, simulated=True)


def escalate(
    patient: Patient,
    flags: RedFlagResult,
    *,
    patient_words: str = "",
) -> List[SMSResult]:
    """Route an escalation to the correct party/parties.

    CLINICAL flags -> nurse ONLY (never volunteer).
    PRESENCE-only flags -> volunteer.
    Both can fire (e.g. confusion: nurse first + volunteer presence), but the
    volunteer body is always the sanitized, non-clinical template.
    """
    settings = get_settings()
    results: List[SMSResult] = []

    if flags.has_clinical:
        nurse_to = settings.nurse_sms_number or "+1XXXXXXXXXX (nurse — set NURSE_SMS_NUMBER)"
        body = _nurse_body(patient, flags, extra=patient_words)
        res = _send(nurse_to, body)
        res.channel = "nurse"
        _trace.show_escalation("SMS", nurse_to, body, clinical=True)
        results.append(res)

    # Presence-only volunteer routing — ONLY for non-clinical signals, and NEVER
    # with clinical content. If a clinical flag exists we may still add a
    # volunteer *presence* task, but its body is sanitized.
    has_presence = any(f.route == Route.VOLUNTEER for f in flags.flags)
    if has_presence:
        vol_to = settings.volunteer_sms_number or "+1XXXXXXXXXX (volunteer — set VOLUNTEER_SMS_NUMBER)"
        body = _volunteer_body(patient, flags)
        res = _send(vol_to, body)
        res.channel = "volunteer"
        _trace.show_escalation("SMS", vol_to, body, clinical=False)
        results.append(res)

    return results


def missed_calls_to_volunteer(patient: Patient) -> SMSResult:
    """Green-signal path: missed check-in calls -> a VOLUNTEER (never nurse,
    never clinical). Demonstrates ecosystem routing where the volunteer channel
    receives only a presence task."""
    from sentinelcall.agent.redflags import RedFlag

    settings = get_settings()
    flags = RedFlagResult(flags=[
        RedFlag("missed_calls", "Patient missed check-in calls.", Route.VOLUNTEER, clinical=False)
    ])
    vol_to = settings.volunteer_sms_number or "+1XXXXXXXXXX (volunteer — set VOLUNTEER_SMS_NUMBER)"
    body = _volunteer_body(patient, flags)
    res = _send(vol_to, body)
    res.channel = "volunteer"
    _trace.show_escalation("SMS", vol_to, body, clinical=False)
    return res
