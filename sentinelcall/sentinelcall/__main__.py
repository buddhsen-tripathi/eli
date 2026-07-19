"""SentinelCall CLI.

    sentinel call <patient_id>     place an OUTBOUND Twilio call (needs Twilio + ngrok)
    sentinel serve                 run the INBOUND/outbound webhook server (FastAPI)
    sentinel sim <patient_id>      LOCAL text simulator of the full pipeline (no phone)
    sentinel sim <patient_id> --audio   simulator that speaks/round-trips real audio
    sentinel demo                  run the scripted end-to-end demo path
    sentinel patients              list seeded demo patients
    sentinel check                 report which API keys / config are present

Run as `python -m sentinelcall <cmd>` or via the `sentinel` console script.
"""
from __future__ import annotations

import argparse
import sys

from sentinelcall.config import get_settings
from sentinelcall.data.record import all_patients, load_patient_by_id, set_patient_phone
from sentinelcall.obs import trace as _trace


def _cmd_patients(_args) -> int:
    print("Seeded demo patients:")
    for p in all_patients():
        print(f"  {p.patient_id}  {p.name:20} {p.phone:16} — {p.summary_line()}")
    return 0


def _cmd_check(_args) -> int:
    s = get_settings()
    def mark(v):
        return "\033[92m✓\033[0m" if v else "\033[91m✗\033[0m"
    print("Config / key presence:")
    print(f"  {mark(s.anthropic_api_key)} ANTHROPIC_API_KEY   (LLM: supervisor + GER)")
    print(f"  {mark(s.deepgram_api_key)} DEEPGRAM_API_KEY    (STT N-best)")
    print(f"  {mark(s.cartesia_api_key)} CARTESIA_API_KEY    (TTS)")
    print(f"  {mark(s.cartesia_voice)} CARTESIA_VOICE")
    print(f"  {mark(s.openai_api_key)} OPENAI_API_KEY      (optional Whisper fallback)")
    print("  --- telephony (needed for real calls) ---")
    print(f"  {mark(s.twilio_account_sid)} TWILIO_ACCOUNT_SID")
    print(f"  {mark(s.twilio_auth_token)} TWILIO_AUTH_TOKEN")
    print(f"  {mark(s.twilio_from_number)} TWILIO_FROM_NUMBER")
    print(f"  {mark(s.public_base_url)} PUBLIC_BASE_URL     (ngrok URL for webhooks)")
    print(f"  {mark(s.nurse_sms_number)} NURSE_SMS_NUMBER    (clinical escalation)")
    print(f"  {mark(s.volunteer_sms_number)} VOLUNTEER_SMS_NUMBER (presence escalation)")
    return 0


def _cmd_setup_phone(args) -> int:
    p = load_patient_by_id(args.patient_id)
    if not p:
        print(f"Unknown patient_id {args.patient_id!r}. Try `sentinel patients`.")
        return 1
    phone = args.phone.strip()
    if not phone.startswith("+"):
        print(f"\033[93mNote:\033[0m phone should be E.164 format, e.g. +12125550123")
    ok = set_patient_phone(args.patient_id, phone)
    if ok:
        print(f"✓ {args.patient_id} ({p.name}) phone set to {phone}.")
        print(f"  Now `sentinel call {args.patient_id}` will dial that number,")
        print(f"  and an inbound call FROM it is recognized as {p.preferred_name}.")
        return 0
    print("Failed to update patient record.")
    return 1


def _cmd_call(args) -> int:
    from sentinelcall.telephony.twilio_voice import place_outbound_call

    try:
        sid = place_outbound_call(args.patient_id)
    except Exception as exc:
        print(f"\033[91mCould not place call:\033[0m {exc}", file=sys.stderr)
        return 1
    print(f"Outbound call placed. CallSid={sid}")
    print("Twilio will hit your /voice/outbound webhook when the patient answers.")
    print("Make sure `sentinel serve` is running and PUBLIC_BASE_URL points to it.")
    return 0


def _cmd_serve(args) -> int:
    from sentinelcall.telephony.twilio_voice import build_app

    try:
        import uvicorn
    except Exception:
        print("uvicorn is required for `serve` (pip install 'uvicorn[standard]' fastapi).",
              file=sys.stderr)
        return 1
    s = get_settings()
    app = build_app()
    print(f"SentinelCall webhook on http://{s.host}:{args.port or s.port}")
    print("  inbound  -> POST /voice/inbound   (point your Twilio number here)")
    print("  outbound -> POST /voice/outbound  (used by `sentinel call`)")
    uvicorn.run(app, host=s.host, port=args.port or s.port, log_level="warning")
    return 0


def _cmd_sim(args) -> int:
    from sentinelcall.sim import run_simulator

    return run_simulator(args.patient_id, use_audio=args.audio, inbound=args.inbound)


def _cmd_demo(args) -> int:
    from sentinelcall.demo import run_demo

    return run_demo(pause=not args.no_pause)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="sentinel", description="SentinelCall CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_call = sub.add_parser("call", help="place an outbound Twilio call")
    p_call.add_argument("patient_id")
    p_call.set_defaults(func=_cmd_call)

    p_phone = sub.add_parser("setup-phone", help="point a demo patient at a real number (e.g. your cell)")
    p_phone.add_argument("patient_id")
    p_phone.add_argument("phone", help="E.164 number, e.g. +12125550123")
    p_phone.set_defaults(func=_cmd_setup_phone)

    p_serve = sub.add_parser("serve", help="run the inbound/outbound webhook server")
    p_serve.add_argument("--port", type=int, default=None)
    p_serve.set_defaults(func=_cmd_serve)

    p_sim = sub.add_parser("sim", help="local simulator of the full pipeline")
    p_sim.add_argument("patient_id")
    p_sim.add_argument("--audio", action="store_true", help="use real TTS/STT audio round-trip")
    p_sim.add_argument("--inbound", action="store_true", help="simulate an inbound Q&A call")
    p_sim.set_defaults(func=_cmd_sim)

    p_demo = sub.add_parser("demo", help="run the scripted end-to-end demo path")
    p_demo.add_argument("--no-pause", action="store_true", help="don't pause between beats")
    p_demo.set_defaults(func=_cmd_demo)

    sub.add_parser("patients", help="list seeded demo patients").set_defaults(func=_cmd_patients)
    sub.add_parser("check", help="report key/config presence").set_defaults(func=_cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
