"""Local simulator — drive the FULL pipeline from the keyboard (or real audio),
no phone required. Same ordering as the phone path, so the GER hero and the
escalation are visible on screen for the demo even if carrier audio is flaky.

  sentinel sim P001              # type patient turns; pipeline runs on each
  sentinel sim P001 --audio      # your typed line is spoken (Cartesia) then
                                 # transcribed (Deepgram N-best) -> real GER
  sentinel sim P001 --inbound    # inbound Q&A mode
"""
from __future__ import annotations

import asyncio

from sentinelcall.data.record import load_patient_by_id
from sentinelcall.obs import trace as _trace
from sentinelcall.pipeline.loop import ConversationEngine


def _audio_hypotheses(text: str):
    """Speak `text` via Cartesia, transcribe via Deepgram N-best. Returns the
    real N-best list — so GER operates on genuine ASR output."""
    from sentinelcall.pipeline.tts import tts
    from sentinelcall.pipeline.stt import stt

    async def _run():
        wav = await tts().synthesize(text)
        if not wav:
            return [text]
        res = await stt().transcribe(wav)
        return res.hypotheses or [text]

    return asyncio.run(_run())


def run_simulator(patient_id: str, *, use_audio: bool = False, inbound: bool = False) -> int:
    patient = load_patient_by_id(patient_id)
    if not patient:
        print(f"Unknown patient_id {patient_id!r}. Try `sentinel patients`.")
        return 1

    direction = "inbound" if inbound else "outbound"
    engine = ConversationEngine(patient, direction=direction)

    _trace.banner(f"SIMULATOR — {patient.name} ({direction})", _trace.CYAN)
    print(f"{_trace.BOLD}AGENT:{_trace.RESET} {engine.opening_line()}\n")
    print(f"{_trace.DIM}(type what the patient says; Ctrl-C or empty line + 'quit' to end)"
          f"{'  [AUDIO MODE: your line is spoken + re-transcribed]' if use_audio else ''}{_trace.RESET}\n")

    while not engine.ended:
        try:
            said = input(f"{_trace.BOLD}PATIENT> {_trace.RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if said.lower() in ("quit", "exit", "q"):
            break
        if not said:
            continue

        with _trace.turn("turn", engine.supervisor.state.value if engine.supervisor else "inbound"):
            if use_audio:
                hyps = _audio_hypotheses(said)
                outcome = engine.process_hypotheses(hyps)
            else:
                # Text mode: the typed line is the single hypothesis; GER still
                # runs and repairs it. To showcase GER without a mic, prefix a
                # line with 'ASR:' and separate alt hypotheses with ' || '.
                if said.startswith("ASR:"):
                    hyps = [h.strip() for h in said[4:].split("||") if h.strip()]
                    outcome = engine.process_hypotheses(hyps)
                else:
                    outcome = engine.process_text(said)

            print(f"\n{_trace.BOLD}{_trace.GREEN}AGENT:{_trace.RESET} {outcome.reply}\n")
            if outcome.emergency:
                print(f"{_trace.RED}{_trace.BOLD}*** EMERGENCY PATH — call ended ***{_trace.RESET}\n")

    if engine.direction == "outbound" and engine.supervisor:
        _trace.banner("CALL SUMMARY (Layer-3 structured extract)", _trace.GREEN)
        ex = engine.supervisor.extract.to_dict()
        for k, v in ex.items():
            if v not in (None, [], "", False):
                print(f"  {k}: {v}")
    return 0
