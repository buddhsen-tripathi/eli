"""
Post-call analysis: turn a check-in transcript into a summary + triage.

`analyze_call(call_id)` reads the transcript, produces:
  - summary: a short, warm, plain-language recap a loved one can read
  - triage:  {"level": "ok|monitor|urgent", "flags": [...], "reason": "..."}
and persists both on the Call row.

Uses Anthropic (Claude Haiku) when ANTHROPIC_API_KEY is set; otherwise falls
back to a keyword heuristic so the pipeline always produces *something*. The key
is read lazily so the API boots without it.
"""

import json
import os

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.db_models import Call, TranscriptTurn

# Red-flag post-op symptoms for an elderly, recently-discharged patient. Presence
# of any of these in the patient's own words escalates triage toward "urgent".
URGENT_KEYWORDS = [
    "chest pain", "can't breathe", "cant breathe", "trouble breathing",
    "bleeding", "blood", "fell", "fallen", "a fall", "passed out", "fainted",
    "high fever", "confused", "dizzy", "swelling", "can't move", "worst pain",
    "not eating", "haven't eaten", "vomiting", "throwing up",
]
MONITOR_KEYWORDS = [
    "pain", "sore", "fever", "tired", "nauseous", "no appetite", "lonely",
    "missed", "forgot", "medication", "meds", "trouble sleeping",
]

TRIAGE_LEVELS = ("ok", "monitor", "urgent")


async def _load_transcript(call_id: str) -> str:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(TranscriptTurn)
            .where(TranscriptTurn.call_id == call_id)
            .order_by(TranscriptTurn.timestamp)
        )
        turns = result.scalars().all()
    return "\n".join(f"{t.role.upper()}: {t.text}" for t in turns)


def _heuristic(transcript: str) -> tuple[str, dict]:
    """Zero-dependency fallback: keyword scan for a triage level + flags."""
    lowered = transcript.lower()
    urgent = [k for k in URGENT_KEYWORDS if k in lowered]
    monitor = [k for k in MONITOR_KEYWORDS if k in lowered]

    if urgent:
        level, flags, reason = "urgent", urgent, "Concerning symptoms mentioned on the call."
    elif monitor:
        level, flags, reason = "monitor", monitor, "Minor symptoms worth keeping an eye on."
    else:
        level, flags, reason = "ok", [], "No concerning symptoms detected."

    summary = "Check-in completed. " + reason
    return summary, {"level": level, "flags": flags, "reason": reason}


def _llm(transcript: str) -> tuple[str, dict] | None:
    """Claude-based analysis. Returns None on any failure so callers fall back."""
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=(
                "You are a post-op nurse reviewing a phone check-in with an elderly, "
                "recently-discharged patient. Return ONLY a JSON object with keys: "
                '"summary" (2-3 warm plain-language sentences a family member can read), '
                '"level" (one of "ok", "monitor", "urgent"), '
                '"flags" (array of short symptom/issue strings), and '
                '"reason" (one sentence explaining the level). '
                "Escalate to \"urgent\" for chest pain, breathing trouble, heavy bleeding, "
                "falls, fainting, high fever, confusion, or signs of severe pain."
            ),
            messages=[{"role": "user", "content": transcript or "(no transcript captured)"}],
        )
        raw = msg.content[0].text.strip()
        # Strip code fences if the model wrapped the JSON.
        if raw.startswith("```"):
            raw = raw.split("```")[1].removeprefix("json").strip()
        data = json.loads(raw)
        level = data.get("level", "monitor")
        if level not in TRIAGE_LEVELS:
            level = "monitor"
        triage = {
            "level": level,
            "flags": data.get("flags", []),
            "reason": data.get("reason", ""),
        }
        return data.get("summary", "Check-in completed."), triage
    except Exception as e:
        print(f"[analysis] LLM analysis failed, using heuristic: {e}", flush=True)
        return None


async def analyze_call(call_id: str) -> dict | None:
    """Analyze a finished call and persist summary + triage. Returns the triage dict."""
    transcript = await _load_transcript(call_id)

    result = None
    if os.environ.get("ANTHROPIC_API_KEY"):
        result = _llm(transcript)
    if result is None:
        result = _heuristic(transcript)
    summary, triage = result

    async with AsyncSessionLocal() as session:
        call = await session.get(Call, call_id)
        if call:
            call.summary = summary
            call.triage = triage
            await session.commit()

    return triage
