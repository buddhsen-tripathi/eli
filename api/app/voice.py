"""
Twilio voice webhook + ElevenLabs Conversational AI bridge.

Flow:
  1. Twilio calls POST /call/incoming  → returns TwiML <Connect><Stream>
  2. Twilio opens a WebSocket to GET /call/stream
  3. This server opens a *second* WebSocket to ElevenLabs Conversational AI and
     bridges the two with two concurrent asyncio tasks. Audio is transcoded with
     the stdlib ``audioop`` module: Twilio mu-law 8kHz <-> ElevenLabs PCM16 16kHz.

Note: ``audioop`` was removed from the stdlib in Python 3.13, so ``audioop-lts``
is pinned for 3.13+ — do not remove that dependency.

Credentials are read lazily (``os.environ.get``) so the API boots without call
credentials; they are only required when an actual call is bridged.
"""

import asyncio
import audioop
import base64
import json
import os
from datetime import datetime, timezone

import websockets
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse

from app.database import AsyncSessionLocal
from app.db_models import Call, TranscriptTurn

router = APIRouter(prefix="/call", tags=["voice"])


async def _run_post_call(call_id: str) -> None:
    """After hangup: pull the authoritative transcript, analyze, notify loved ones."""
    try:
        from app.analysis import analyze_call
        from app.elevenlabs import sync_transcript
        from app.notify import notify_caregivers

        # Pull the finalized transcript from ElevenLabs (more reliable than the
        # real-time capture), then run analysis over whatever turns we have.
        async with AsyncSessionLocal() as session:
            call = await session.get(Call, call_id)
            conv_id = call.el_conversation_id if call else None
        if conv_id:
            await sync_transcript(call_id, conv_id)

        await analyze_call(call_id)
        await notify_caregivers(call_id)
    except Exception as e:
        print(f"[voice] post-call pipeline error for {call_id}: {e}", flush=True)


ELEVENLABS_AGENT_ID = os.environ.get("ELEVENLABS_AGENT_ID")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")


def _elevenlabs_ws_url() -> str:
    return (
        "wss://api.elevenlabs.io/v1/convai/conversation"
        f"?agent_id={ELEVENLABS_AGENT_ID}"
    )


def _twiml_stream(public_ws_url: str, patient_id: str | None = None) -> str:
    param = f'<Parameter name="patient_id" value="{patient_id}"/>' if patient_id else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        "<Connect>"
        f'<Stream url="{public_ws_url}/call/stream">'
        f"{param}"
        "</Stream>"
        "</Connect>"
        "</Response>"
    )


async def _send_audio(ws: WebSocket, stream_sid: str, audio_b64: str) -> None:
    """Convert ElevenLabs PCM16 16kHz -> mu-law 8kHz and send to Twilio."""
    pcm16 = base64.b64decode(audio_b64)
    pcm8k, _ = audioop.ratecv(pcm16, 2, 1, 16000, 8000, None)
    ulaw = audioop.lin2ulaw(pcm8k, 2)
    payload = base64.b64encode(ulaw).decode()
    await ws.send_text(json.dumps({
        "event": "media",
        "streamSid": stream_sid,
        "media": {"payload": payload},
    }))


async def _save_turn(call_id: str, role: str, text: str) -> None:
    async with AsyncSessionLocal() as session:
        session.add(TranscriptTurn(call_id=call_id, role=role, text=text))
        await session.commit()


@router.post("/incoming")
async def incoming_call(request: Request) -> PlainTextResponse:
    # patient_id is present for outbound check-ins (see app/outbound.py). For an
    # inbound call, identify the patient by the caller's phone number so the agent
    # still gets their EHR context (and can answer "which is my red pill?").
    patient_id = request.query_params.get("patient_id")
    if not patient_id:
        form = await request.form()
        from_number = form.get("From")
        if from_number:
            from sqlalchemy import select

            from app.db_models import Patient

            async with AsyncSessionLocal() as session:
                res = await session.execute(select(Patient).where(Patient.phone == from_number))
                patient = res.scalar_one_or_none()
            if patient:
                patient_id = patient.id
                print(f"[voice] inbound caller {from_number} matched patient {patient_id}", flush=True)
            else:
                print(f"[voice] inbound caller {from_number} not recognized", flush=True)

    base_url = os.environ["PUBLIC_BASE_URL"].rstrip("/")
    ws_base = base_url.replace("https://", "wss://").replace("http://", "ws://")
    return PlainTextResponse(
        content=_twiml_stream(ws_base, patient_id), media_type="application/xml"
    )


@router.websocket("/stream")
async def call_stream(twilio_ws: WebSocket):
    await twilio_ws.accept()

    stream_sid: str | None = None
    call_sid: str | None = None
    call_id: str | None = None
    patient_id: str | None = None
    direction: str = "inbound"
    el_conversation_id: str | None = None
    pre_start_media: list[str] = []  # Twilio media (mu-law b64) arriving before 'start'

    print("[voice] Twilio WS accepted", flush=True)

    # Phase 1: wait for Twilio's 'start' so we know which patient this is BEFORE
    # opening ElevenLabs — the agent needs the EHR as dynamic variables at init.
    try:
        async for raw in twilio_ws.iter_text():
            msg = json.loads(raw)
            event = msg.get("event")
            if event == "start":
                stream_sid = msg["start"]["streamSid"]
                call_sid = msg["start"].get("callSid", stream_sid)
                params = msg["start"].get("customParameters", {})
                patient_id = params.get("patient_id")
                direction = "outbound" if patient_id else "inbound"
                break
            elif event == "media":
                pre_start_media.append(msg["media"]["payload"])
            elif event == "stop":
                print("[voice] Twilio stopped before start — nothing to bridge", flush=True)
                return
    except WebSocketDisconnect:
        print("[voice] Twilio disconnected before start", flush=True)
        return

    # Create the Call row, then build the agent's dynamic variables from the EHR.
    async with AsyncSessionLocal() as session:
        call = Call(
            call_sid=call_sid,
            patient_id=patient_id,
            direction=direction,
            status="in_progress",
        )
        session.add(call)
        await session.commit()
        await session.refresh(call)
        call_id = call.id

    from app.ehr_context import build_dynamic_variables

    dynamic_variables = await build_dynamic_variables(patient_id)
    print(
        f"[twilio] start: call_id={call_id} sid={call_sid} patient_id={patient_id} "
        f"direction={direction} agent_name={dynamic_variables['patient_name']!r} "
        f"recovery_day={dynamic_variables['recovery_day']!r}",
        flush=True,
    )

    el_headers = {"xi-api-key": ELEVENLABS_API_KEY}

    try:
        async with websockets.connect(_elevenlabs_ws_url(), additional_headers=el_headers) as el_ws:
            # Inject the EHR as dynamic variables so the agent greets the patient by
            # name and can reason over their meds / recovery day. No config override —
            # that field isn't enabled on the agent and would fail init.
            await el_ws.send(json.dumps({
                "type": "conversation_initiation_client_data",
                "dynamic_variables": dynamic_variables,
            }))
            print("[voice] sent conversation_initiation with EHR dynamic variables", flush=True)

            # Forward any media that arrived before 'start'.
            for payload in pre_start_media:
                pcm8k = audioop.ulaw2lin(base64.b64decode(payload), 2)
                pcm16k, _ = audioop.ratecv(pcm8k, 2, 1, 8000, 16000, None)
                await el_ws.send(json.dumps({"user_audio_chunk": base64.b64encode(pcm16k).decode()}))

            async def twilio_to_el():
                async for raw in twilio_ws.iter_text():
                    msg = json.loads(raw)
                    event = msg.get("event")

                    if event == "media":
                        ulaw = base64.b64decode(msg["media"]["payload"])
                        pcm8k = audioop.ulaw2lin(ulaw, 2)
                        pcm16k, _ = audioop.ratecv(pcm8k, 2, 1, 8000, 16000, None)
                        await el_ws.send(json.dumps({
                            "user_audio_chunk": base64.b64encode(pcm16k).decode()
                        }))

                    elif event == "stop":
                        print(f"[twilio] stop: call_id={call_id}", flush=True)
                        break

            async def el_to_twilio():
                nonlocal el_conversation_id
                audio_chunks = 0

                async for raw in el_ws:
                    msg = json.loads(raw)
                    msg_type = msg.get("type")

                    if msg_type == "conversation_initiation_metadata":
                        meta = msg.get("conversation_initiation_metadata_event", {})
                        el_conversation_id = meta.get("conversation_id")
                        print(
                            f"[el] init OK — conversation_id={el_conversation_id} "
                            f"audio_format={meta.get('agent_output_audio_format')}",
                            flush=True,
                        )

                    elif msg_type == "ping":
                        event_id = msg.get("ping_event", {}).get("event_id")
                        await el_ws.send(json.dumps({"type": "pong", "event_id": event_id}))

                    elif msg_type == "audio":
                        audio_b64 = msg.get("audio_event", {}).get("audio_base_64")
                        if not audio_b64:
                            continue
                        audio_chunks += 1
                        if audio_chunks == 1:
                            print("[el] first audio chunk received — agent is speaking", flush=True)
                        await _send_audio(twilio_ws, stream_sid, audio_b64)

                    elif msg_type == "agent_response":
                        text = msg.get("agent_response_event", {}).get("agent_response", "").strip()
                        print(f"[el] agent: {text[:120]}", flush=True)
                        if text and call_id:
                            await _save_turn(call_id, "agent", text)

                    elif msg_type == "user_transcript":
                        text = msg.get("user_transcription_event", {}).get("user_transcript", "").strip()
                        print(f"[el] patient: {text[:120]}", flush=True)
                        if text and call_id:
                            await _save_turn(call_id, "patient", text)

                    elif msg_type == "interruption" and stream_sid:
                        await twilio_ws.send_text(json.dumps({
                            "event": "clear",
                            "streamSid": stream_sid,
                        }))

                    elif msg_type in ("agent_response_correction", "vad_score", "internal_tentative_agent_response"):
                        pass  # high-frequency / internal — ignore quietly

                    else:
                        # Surface anything unexpected (errors, unknown events) verbatim.
                        print(f"[el] event: {msg_type} :: {json.dumps(msg)[:200]}", flush=True)

            tasks = [
                asyncio.create_task(twilio_to_el()),
                asyncio.create_task(el_to_twilio()),
            ]
            # When either side closes, cancel the other.
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            # Gather ALL tasks (not just pending) so the finished task's exception —
            # e.g. a benign ConnectionClosedOK from a last send on hangup — is
            # retrieved rather than logged as "Task exception was never retrieved".
            await asyncio.gather(*tasks, return_exceptions=True)

    except WebSocketDisconnect:
        print("[voice] Twilio WebSocket disconnected", flush=True)
    except websockets.exceptions.ConnectionClosed as e:
        print(f"[el] ElevenLabs closed: code={e.code} reason={e.reason!r}", flush=True)
    except Exception as e:
        print(f"[call_stream] ERROR: {type(e).__name__}: {e}", flush=True)
    finally:
        print(
            f"[voice] call ended: call_id={call_id} el_conversation_id={el_conversation_id}",
            flush=True,
        )
        if call_id:
            async with AsyncSessionLocal() as session:
                call = await session.get(Call, call_id)
                if call:
                    call.status = "completed"
                    call.ended_at = datetime.now(timezone.utc)
                    call.el_conversation_id = el_conversation_id
                    await session.commit()
            # Pull transcript, analyze, notify — off the request path.
            asyncio.create_task(_run_post_call(call_id))
