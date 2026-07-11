"""Per-turn tracing + cost metering, with a demo-grade console renderer.

Two jobs:
  1. Structured JSONL log to `.sentinel/trace.jsonl` for clinician credibility.
  2. A colorized, on-screen console view that makes the GER recovery and the
     escalation VISIBLE during the live demo — this is what wins the room.

Forked in shape from MIRA's obs/logging + runtime/tracing, collapsed into one
module and given a human-facing renderer.
"""
from __future__ import annotations

import contextvars
import json
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from sentinelcall.config import TRACE_DIR

# ---- ANSI (fall back to no-color if not a tty) ------------------------------

_TTY = sys.stdout.isatty()


def _c(code: str) -> str:
    return code if _TTY else ""


DIM = _c("\033[2m")
BOLD = _c("\033[1m")
RED = _c("\033[91m")
GREEN = _c("\033[92m")
YELLOW = _c("\033[93m")
BLUE = _c("\033[94m")
MAGENTA = _c("\033[95m")
CYAN = _c("\033[96m")
GREY = _c("\033[90m")
RESET = _c("\033[0m")

# ---- trace context ----------------------------------------------------------

_current_turn: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "sc_turn", default=None
)
_lock = threading.Lock()

# Per-turn cost accumulator, keyed by turn id.
_turn_cost: Dict[str, float] = {}
_turn_tokens: Dict[str, Dict[str, int]] = {}
_session_cost = 0.0


def _short() -> str:
    return uuid.uuid4().hex[:8]


def _trace_path() -> Path:
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    return TRACE_DIR / "trace.jsonl"


def _write_jsonl(record: Dict[str, Any]) -> None:
    try:
        with _lock:
            with open(_trace_path(), "a") as f:
                f.write(json.dumps(record, default=str) + "\n")
    except Exception:
        pass  # never let tracing crash the caller


def _now() -> float:
    # time.time() is fine here — traces are wall-clock stamped for the demo log.
    return time.time()


def event(event_name: str, **fields: Any) -> None:
    """Emit a structured event to the JSONL trace (auto-tagged with turn id)."""
    tid = _current_turn.get()
    rec = {"ts": _now(), "event": event_name, "turn": tid, **fields}
    _write_jsonl(rec)


def record_cost(
    *, cost_usd: float, prompt_tokens: int, completion_tokens: int
) -> None:
    """Accumulate LLM cost/tokens into the current turn + session totals."""
    global _session_cost
    tid = _current_turn.get() or "_"
    with _lock:
        _turn_cost[tid] = _turn_cost.get(tid, 0.0) + cost_usd
        tok = _turn_tokens.setdefault(tid, {"prompt": 0, "completion": 0})
        tok["prompt"] += prompt_tokens
        tok["completion"] += completion_tokens
        _session_cost += cost_usd


def session_cost() -> float:
    return _session_cost


# ---- console renderer (the demo view) ---------------------------------------


def banner(text: str, color: str = CYAN) -> None:
    line = "═" * (len(text) + 2)
    print(f"\n{color}{BOLD}╔{line}╗{RESET}")
    print(f"{color}{BOLD}║ {text} ║{RESET}")
    print(f"{color}{BOLD}╚{line}╝{RESET}\n")


def line(tag: str, msg: str, color: str = "") -> None:
    """One-line labeled console trace, also mirrored to JSONL."""
    label = f"{color}{BOLD}{tag:>10}{RESET}" if color else f"{BOLD}{tag:>10}{RESET}"
    print(f"  {label} {DIM}│{RESET} {msg}")
    event("trace", tag=tag, msg=msg)


def show_ger(
    hypotheses: List[str],
    repaired: str,
    confidence: float,
    *,
    changed: bool,
    action: str,
) -> None:
    """The hero panel. Renders raw ASR hypotheses next to the recovered text
    so the recovery is unmistakable on screen."""
    print(f"\n{MAGENTA}{BOLD}  ┌─ GENERATIVE ERROR CORRECTION (GER) ─────────────────────{RESET}")
    print(f"{MAGENTA}  │{RESET} {DIM}raw ASR hypotheses (Deepgram N-best):{RESET}")
    for i, h in enumerate(hypotheses):
        marker = f"{RED}✗{RESET}"
        print(f"{MAGENTA}  │{RESET}   {marker} {GREY}\"{h}\"{RESET}")
    print(f"{MAGENTA}  │{RESET}")
    conf_color = GREEN if confidence >= 0.75 else YELLOW if confidence >= 0.5 else RED
    arrow = f"{GREEN}✓ RECOVERED{RESET}" if changed else f"{DIM}(unchanged){RESET}"
    print(f"{MAGENTA}  │{RESET} {arrow} {BOLD}\"{repaired}\"{RESET}")
    print(f"{MAGENTA}  │{RESET}   confidence: {conf_color}{confidence:.2f}{RESET}   action: {BOLD}{action}{RESET}")
    print(f"{MAGENTA}  └──────────────────────────────────────────────────────────{RESET}\n")
    event(
        "ger",
        hypotheses=hypotheses,
        repaired=repaired,
        confidence=confidence,
        changed=changed,
        action=action,
    )


def show_escalation(channel: str, to: str, body: str, *, clinical: bool) -> None:
    color = RED if clinical else BLUE
    kind = "CLINICAL → NURSE" if clinical else "PRESENCE → VOLUNTEER"
    print(f"\n{color}{BOLD}  ╭─ 📲 ESCALATION SMS  [{kind}] ───────────────────────{RESET}")
    print(f"{color}  │{RESET}  to: {BOLD}{to}{RESET}  via {channel}")
    for ln in body.splitlines():
        print(f"{color}  │{RESET}  {ln}")
    print(f"{color}  ╰──────────────────────────────────────────────────────────{RESET}\n")
    event("escalation.sms", channel=channel, to=to, clinical=clinical, body=body)


def cost_report(turn_id: Optional[str] = None) -> None:
    tid = turn_id or _current_turn.get() or "_"
    cost = _turn_cost.get(tid, 0.0)
    tok = _turn_tokens.get(tid, {"prompt": 0, "completion": 0})
    print(
        f"  {GREY}{DIM}⏱  turn {tid}  ·  ${cost:.5f}  ·  "
        f"{tok['prompt']}→{tok['completion']} tok  ·  session ${_session_cost:.4f}{RESET}"
    )


@contextmanager
def turn(name: str = "turn", state: str = "") -> Iterator[str]:
    """Open a per-turn trace context. Everything logged inside is tagged with
    this turn id; cost is rolled up and printed on close."""
    tid = _short()
    token = _current_turn.set(tid)
    t0 = time.perf_counter()
    label = f"{state}" if state else name
    print(f"{DIM}{GREY}─── turn {tid} · {label} ─────────────────────────────{RESET}")
    event("turn.start", name=name, state=state)
    status = "ok"
    try:
        yield tid
    except BaseException as exc:  # noqa: BLE001 - we re-raise
        status = "error"
        event("turn.error", error=repr(exc))
        raise
    finally:
        dt = round((time.perf_counter() - t0) * 1000, 1)
        event("turn.end", status=status, latency_ms=dt)
        cost_report(tid)
        _current_turn.reset(token)
