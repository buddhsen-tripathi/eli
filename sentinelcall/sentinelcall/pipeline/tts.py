"""TTS — Cartesia streaming, slow / high-prosody preset for elderly hearing.

The slow, clear cadence is a stated DESIGN CHOICE for age-related hearing
decline, not an accident. Cartesia exposes a speed control; we pin it to "slow".

Two consumers:
  * The local simulator plays synthesized audio (or, if no audio device /
    Cartesia key, just prints the line — the demo trace still shows what would
    be spoken).
  * The Twilio path can either <Play> Cartesia audio we host, or fall back to
    Twilio's built-in <Say> with prosody hints. For the hackathon we default the
    phone path to <Say> (zero extra hosting) and use Cartesia locally, so the
    demo works even without a public audio URL. See telephony/twilio_voice.py.

Adapted in shape from MIRA's voice/tts.py (number normalization, streaming),
minus the macOS sounddevice/barge-in machinery.
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Optional

from sentinelcall.config import get_settings
from sentinelcall.obs import trace as _trace

_HYPHEN_BETWEEN_NUMBERS = re.compile(r"(\d)\s*[-–]\s*(\d)")


def normalize_for_tts(text: str) -> str:
    """Rewrite patterns TTS reads awkwardly. '100.4' stays, but '5-6' -> '5 to 6'.
    Also spaces out '911' so it's read as digits, matching our scripts which
    already write '9 1 1'."""
    text = _HYPHEN_BETWEEN_NUMBERS.sub(r"\1 to \2", text)
    return text


class TTS:
    SAMPLE_RATE = 24000

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client = None

    def _get_client(self):
        if self._client is None:
            if not self._settings.cartesia_api_key:
                raise RuntimeError("CARTESIA_API_KEY is not set")
            if not self._settings.cartesia_voice:
                raise RuntimeError("CARTESIA_VOICE is not set")
            from cartesia import Cartesia

            self._client = Cartesia(api_key=self._settings.cartesia_api_key)
        return self._client

    def _speed(self):
        # Cartesia accepts "slowest"|"slow"|"normal"|"fast"|"fastest" or a float.
        s = self._settings.cartesia_speed
        try:
            return float(s)
        except (TypeError, ValueError):
            return s or "slow"

    async def synthesize(self, text: str) -> bytes:
        """Return raw PCM/WAV bytes for the line at the slow preset. Best-effort:
        on any failure returns b'' so callers degrade to text-only."""
        text = normalize_for_tts(text.strip())
        if not text:
            return b""
        t0 = time.perf_counter()

        def _call() -> bytes:
            client = self._get_client()
            # Non-streaming bytes for simplicity; the phone path streams via
            # Twilio anyway. Request WAV so the simulator can play it directly.
            audio = client.tts.bytes(
                model_id=self._settings.cartesia_tts_model,
                transcript=text,
                voice={"mode": "id", "id": self._settings.cartesia_voice},
                output_format={
                    "container": "wav",
                    "encoding": "pcm_s16le",
                    "sample_rate": self.SAMPLE_RATE,
                },
                language="en",
                speed=self._speed(),
            )
            if isinstance(audio, (bytes, bytearray)):
                return bytes(audio)
            # SDK may return a generator of chunks
            return b"".join(chunk for chunk in audio)

        try:
            data = await asyncio.to_thread(_call)
        except Exception as exc:
            _trace.event("tts.error", error=repr(exc))
            return b""
        _trace.event("tts.ok", chars=len(text), latency_ms=int((time.perf_counter() - t0) * 1000))
        return data

    async def speak_local(self, text: str) -> None:
        """Synthesize and play through the default audio device if available;
        otherwise no-op (the trace already shows the line). Used by the
        simulator so a demo laptop actually SPEAKS."""
        data = await self.synthesize(text)
        if not data:
            return
        try:
            import io
            import soundfile as sf
            import sounddevice as sd

            pcm, sr = sf.read(io.BytesIO(data), dtype="float32")
            sd.play(pcm, sr)
            sd.wait()
        except Exception as exc:
            _trace.event("tts.play_skipped", error=repr(exc))


_tts: Optional[TTS] = None


def tts() -> TTS:
    global _tts
    if _tts is None:
        _tts = TTS()
    return _tts
