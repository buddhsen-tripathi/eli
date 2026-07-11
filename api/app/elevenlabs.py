"""
ElevenLabs Conversational AI management/data API client.

Used post-call to pull the *authoritative* transcript for a conversation (more
reliable than our real-time WebSocket capture) and extract useful info — the
summary ElevenLabs generates, plus the turn-by-turn transcript.

The transcript is finalized a few seconds after the call ends, so `fetch_conversation`
polls until the conversation is `done` with a non-empty transcript (or gives up).
"""

import asyncio
import os

import httpx

from sqlalchemy import delete, select

from app.database import AsyncSessionLocal
from app.db_models import Call, TranscriptTurn

BASE = "https://api.elevenlabs.io/v1/convai/conversations"


async def fetch_conversation(
    conversation_id: str, *, retries: int = 6, delay: float = 3.0
) -> dict | None:
    """GET a conversation, polling until its transcript is finalized."""
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        print("[elevenlabs] no API key — cannot fetch conversation", flush=True)
        return None

    url = f"{BASE}/{conversation_id}"
    headers = {"xi-api-key": api_key}
    data: dict | None = None
    async with httpx.AsyncClient(timeout=20.0) as client:
        for attempt in range(retries):
            resp = await client.get(url, headers=headers)
            if resp.status_code == 404:
                print(f"[elevenlabs] {conversation_id} not found yet (try {attempt + 1})", flush=True)
                await asyncio.sleep(delay)
                continue
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status")
            transcript = data.get("transcript") or []
            print(
                f"[elevenlabs] {conversation_id} status={status} turns={len(transcript)} "
                f"(try {attempt + 1}/{retries})",
                flush=True,
            )
            if status == "done":
                return data  # done — transcript is as complete as it will get
            await asyncio.sleep(delay)
    return data


def extract_turns(data: dict) -> list[tuple[str, str]]:
    """Flatten an ElevenLabs transcript into (role, text) pairs.

    ElevenLabs uses roles "user"/"agent"; we store "patient"/"agent".
    """
    turns: list[tuple[str, str]] = []
    for t in data.get("transcript") or []:
        raw_role = t.get("role")
        role = "agent" if raw_role == "agent" else "patient"
        text = (t.get("message") or "").strip()
        if text:
            turns.append((role, text))
    return turns


def extract_summary(data: dict) -> str | None:
    return (data.get("analysis") or {}).get("transcript_summary")


async def sync_transcript(call_id: str, conversation_id: str) -> int:
    """Pull the ElevenLabs transcript and store it as the call's turns.

    Replaces any real-time-captured turns with the authoritative ones. Returns
    the number of turns written (0 if the conversation had no transcript).
    """
    data = await fetch_conversation(conversation_id)
    if not data:
        print(f"[elevenlabs] no data for {conversation_id}", flush=True)
        return 0

    turns = extract_turns(data)
    if not turns:
        term = (data.get("metadata") or {}).get("termination_reason")
        print(f"[elevenlabs] empty transcript for {conversation_id} (termination: {term})", flush=True)
        return 0

    async with AsyncSessionLocal() as session:
        # Drop any partial real-time turns, then insert the authoritative set.
        existing = await session.execute(
            select(TranscriptTurn.id).where(TranscriptTurn.call_id == call_id)
        )
        if existing.first():
            await session.execute(delete(TranscriptTurn).where(TranscriptTurn.call_id == call_id))
        for role, text in turns:
            session.add(TranscriptTurn(call_id=call_id, role=role, text=text))

        # Stash ElevenLabs' own summary if it produced one.
        summary = extract_summary(data)
        if summary:
            call = await session.get(Call, call_id)
            if call and not call.summary:
                call.summary = summary
        await session.commit()

    print(f"[elevenlabs] synced {len(turns)} turns for call {call_id}", flush=True)
    return len(turns)
