from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv

    load_dotenv(".env", override=True)
except Exception:  # dotenv is optional; env vars still work without it
    pass

try:
    from pydantic import Field
    from pydantic_settings import BaseSettings, SettingsConfigDict

    _HAVE_PYDANTIC = True
except Exception:  # pragma: no cover - lets the repo import without deps
    _HAVE_PYDANTIC = False


REPO_ROOT = Path(__file__).resolve().parent
DATA_DIR = REPO_ROOT / "data"
TRACE_DIR = REPO_ROOT.parent / ".sentinel"


if _HAVE_PYDANTIC:

    class Settings(BaseSettings):
        """Runtime config. Every field is optional so the repo always imports;
        the layers that need a key raise a clear error when it's missing.

        Precedence: process env > cwd .env (loaded above).
        """

        model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

        # --- LLM (Claude via the gateway) ---
        anthropic_api_key: Optional[str] = None
        # Sonnet-class supervisor + GER model. Prefix `claude-` routes to the
        # Anthropic adapter in gateway/llm.py.
        supervisor_model: str = "claude-sonnet-4-6"
        # GER can run on the same model; kept separate so it can be pinned.
        ger_model: str = "claude-sonnet-4-6"
        # temp 0.25 per spec — deterministic, grounded.
        llm_temperature: float = 0.25

        # OpenAI (Whisper STT fallback + optional embeddings for L2 RAG)
        openai_api_key: Optional[str] = None
        whisper_model: str = "whisper-1"

        # --- STT (Deepgram primary, N-best on) ---
        deepgram_api_key: Optional[str] = None
        # `enhanced` supports N-best alternatives (nova-2/nova-3 reject
        # alternatives>1). N-best is required by GER, so we default to a
        # capable tier; stt.py auto-substitutes if a non-capable model is set.
        deepgram_model: str = "enhanced"
        # Number of alternative hypotheses to request. GER needs > 1.
        stt_alternatives: int = 4

        # --- TTS (Cartesia, slow/high-prosody preset for elderly hearing) ---
        cartesia_api_key: Optional[str] = None
        cartesia_voice: Optional[str] = None
        cartesia_tts_model: str = "sonic-2"
        # Slow speaking rate for age-related hearing decline. Cartesia accepts
        # a speed control; "slow" is the named preset, or a float in [-1, 1].
        cartesia_speed: str = "slow"

        # --- Twilio (telephony transport — MANDATORY sponsor req) ---
        twilio_account_sid: Optional[str] = None
        twilio_auth_token: Optional[str] = None
        # The Twilio number SentinelCall calls FROM / receives inbound ON.
        twilio_from_number: Optional[str] = None
        # Publicly reachable base URL for webhooks (ngrok during dev), e.g.
        # https://abcd-1234.ngrok-free.app  — no trailing slash.
        public_base_url: Optional[str] = None

        # --- Escalation targets ---
        # Nurse receives CLINICAL escalations. Volunteer receives PRESENCE-only
        # (never clinical content — enforced in code, see telephony/twilio_sms).
        nurse_sms_number: Optional[str] = None
        volunteer_sms_number: Optional[str] = None

        # --- Server ---
        host: str = "0.0.0.0"
        port: int = 8080

        # --- Behaviour tuning ---
        # Below this GER confidence on a safety-critical field, the agent must
        # read back to confirm rather than accept the transcript.
        ger_confirm_threshold: float = 0.75
        # Emergency screen + safety gate are always on; this only toggles very
        # verbose per-turn console tracing for the demo screen.
        demo_trace: bool = True

        def require(self, *keys: str) -> None:
            missing = [k for k in keys if not getattr(self, k, None)]
            if missing:
                raise RuntimeError(
                    "Missing required config: "
                    + ", ".join(k.upper() for k in missing)
                    + ". Set them in .env (see .env.example)."
                )

    @lru_cache(maxsize=1)
    def get_settings() -> "Settings":
        return Settings()

else:  # pragma: no cover — minimal fallback if pydantic isn't installed yet

    class Settings:  # type: ignore
        def __init__(self) -> None:
            g = os.environ.get
            self.anthropic_api_key = g("ANTHROPIC_API_KEY")
            self.supervisor_model = g("SUPERVISOR_MODEL", "claude-sonnet-4-6")
            self.ger_model = g("GER_MODEL", "claude-sonnet-4-6")
            self.llm_temperature = float(g("LLM_TEMPERATURE", "0.25"))
            self.openai_api_key = g("OPENAI_API_KEY")
            self.whisper_model = g("WHISPER_MODEL", "whisper-1")
            self.deepgram_api_key = g("DEEPGRAM_API_KEY")
            self.deepgram_model = g("DEEPGRAM_MODEL", "nova-2")
            self.stt_alternatives = int(g("STT_ALTERNATIVES", "4"))
            self.cartesia_api_key = g("CARTESIA_API_KEY")
            self.cartesia_voice = g("CARTESIA_VOICE")
            self.cartesia_tts_model = g("CARTESIA_TTS_MODEL", "sonic-2")
            self.cartesia_speed = g("CARTESIA_SPEED", "slow")
            self.twilio_account_sid = g("TWILIO_ACCOUNT_SID")
            self.twilio_auth_token = g("TWILIO_AUTH_TOKEN")
            self.twilio_from_number = g("TWILIO_FROM_NUMBER")
            self.public_base_url = g("PUBLIC_BASE_URL")
            self.nurse_sms_number = g("NURSE_SMS_NUMBER")
            self.volunteer_sms_number = g("VOLUNTEER_SMS_NUMBER")
            self.host = g("HOST", "0.0.0.0")
            self.port = int(g("PORT", "8080"))
            self.ger_confirm_threshold = float(g("GER_CONFIRM_THRESHOLD", "0.75"))
            self.demo_trace = g("DEMO_TRACE", "true").lower() != "false"

        def require(self, *keys: str) -> None:
            missing = [k for k in keys if not getattr(self, k, None)]
            if missing:
                raise RuntimeError(
                    "Missing required config: "
                    + ", ".join(k.upper() for k in missing)
                )

    @lru_cache(maxsize=1)
    def get_settings() -> "Settings":  # type: ignore
        return Settings()
