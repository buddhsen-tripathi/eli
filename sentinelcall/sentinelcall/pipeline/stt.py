"""STT — Deepgram Nova with N-best / multiple hypotheses ON, Whisper fallback.

The N-best requirement is load-bearing: GER needs MULTIPLE hypotheses, not one
transcript. We request `alternatives=N` from Deepgram and hand the whole list
downstream. Whisper (OpenAI) is the fallback; it returns a single transcript,
which GER still repairs but with less to disambiguate against.

Adapted in shape from MIRA's voice/stt.py, changed to:
  * request + return N-best alternatives (MIRA returned only the top),
  * accept either a WAV byte buffer OR a file path (Twilio recordings arrive
    as URLs we download to bytes; the local simulator passes a wav path).
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import List, Optional

from sentinelcall.config import get_settings
from sentinelcall.obs import trace as _trace


@dataclass
class STTResult:
    hypotheses: List[str]           # N-best, best first
    provider: str
    latency_ms: int
    top_confidence: Optional[float] = None
    raw: dict = field(default_factory=dict)

    @property
    def top(self) -> str:
        return self.hypotheses[0] if self.hypotheses else ""


class STT:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._deepgram = None
        self._openai = None

    # ---- clients (lazy) ----

    def _deepgram_client(self):
        if self._deepgram is None:
            if not self._settings.deepgram_api_key:
                raise RuntimeError("DEEPGRAM_API_KEY is not set")
            from deepgram import DeepgramClient

            self._deepgram = DeepgramClient(self._settings.deepgram_api_key)
        return self._deepgram

    def _openai_client(self):
        if self._openai is None:
            if not self._settings.openai_api_key:
                raise RuntimeError("OPENAI_API_KEY is not set")
            from openai import OpenAI

            self._openai = OpenAI(api_key=self._settings.openai_api_key)
        return self._openai

    # ---- Deepgram N-best ----

    async def transcribe_deepgram(self, wav_bytes: bytes) -> STTResult:
        from deepgram import PrerecordedOptions

        t0 = time.perf_counter()
        client = self._deepgram_client()
        model = self._settings.deepgram_model
        n_alt = self._settings.stt_alternatives

        # Not every Deepgram tier supports multiple alternatives: nova-2 / nova-3
        # reject `alternatives>1` with a 400. N-best is load-bearing for GER, so
        # when a non-N-best model is configured we auto-substitute an N-best-
        # capable tier ("enhanced") rather than silently dropping to 1 hypothesis.
        _NBEST_CAPABLE = {"nova", "enhanced", "base"}
        effective_model = model
        if n_alt > 1 and model not in _NBEST_CAPABLE:
            effective_model = "enhanced"

        def _build(m: str, alts: int) -> "PrerecordedOptions":
            return PrerecordedOptions(
                model=m, smart_format=True, punctuate=True,
                language="en-US", alternatives=alts,
            )

        def _call() -> dict:
            try:
                return client.listen.rest.v("1").transcribe_file(
                    {"buffer": wav_bytes}, _build(effective_model, n_alt)
                )
            except Exception as exc:
                # Last-ditch: if even the substitute rejects N-best, fall back to
                # the configured model with a single alternative so STT still works.
                if "alternative" in str(exc).lower():
                    _trace.event("stt.deepgram.nbest_unsupported", model=effective_model)
                    return client.listen.rest.v("1").transcribe_file(
                        {"buffer": wav_bytes}, _build(model, 1)
                    )
                raise

        resp = await asyncio.to_thread(_call)
        latency_ms = int((time.perf_counter() - t0) * 1000)

        hyps: List[str] = []
        conf: Optional[float] = None
        try:
            alts = resp.results.channels[0].alternatives
            for a in alts:
                txt = (getattr(a, "transcript", "") or "").strip()
                if txt:
                    hyps.append(txt)
            if alts:
                conf = float(getattr(alts[0], "confidence", 0.0) or 0.0)
        except Exception as exc:
            _trace.event("stt.deepgram.parse_error", error=repr(exc))

        return STTResult(hypotheses=hyps, provider="deepgram", latency_ms=latency_ms,
                         top_confidence=conf)

    # ---- Whisper fallback (single hypothesis) ----

    async def transcribe_whisper(self, wav_bytes: bytes) -> STTResult:
        t0 = time.perf_counter()
        client = self._openai_client()

        def _call() -> str:
            import io

            buf = io.BytesIO(wav_bytes)
            buf.name = "audio.wav"
            r = client.audio.transcriptions.create(
                model=self._settings.whisper_model, file=buf, language="en"
            )
            return (getattr(r, "text", "") or "").strip()

        text = await asyncio.to_thread(_call)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return STTResult(hypotheses=[text] if text else [], provider="whisper",
                         latency_ms=latency_ms)

    async def transcribe(self, wav_bytes: bytes) -> STTResult:
        """Deepgram N-best primary; Whisper fallback on hard failure."""
        if self._settings.deepgram_api_key:
            try:
                res = await self.transcribe_deepgram(wav_bytes)
                if res.hypotheses:
                    _trace.event("stt.ok", provider="deepgram",
                                 n_hyps=len(res.hypotheses), latency_ms=res.latency_ms)
                    return res
            except Exception as exc:
                _trace.event("stt.deepgram.failed", error=repr(exc))
        if self._settings.openai_api_key:
            return await self.transcribe_whisper(wav_bytes)
        return STTResult(hypotheses=[], provider="none", latency_ms=0)


_stt: Optional[STT] = None


def stt() -> STT:
    global _stt
    if _stt is None:
        _stt = STT()
    return _stt
