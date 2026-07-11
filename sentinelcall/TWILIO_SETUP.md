# Twilio setup — get to a live call in ~10 minutes

Everything in SentinelCall is built and tested. This is the only thing left:
wiring Twilio so a real phone rings. Written for an **upgraded (paid) Twilio
account**, dialing **your own phone** as the demo patient.

## 1. Put your Twilio creds in `.env`

From <https://console.twilio.com> (Account Dashboard):

```
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_FROM_NUMBER=+1XXXXXXXXXX      # a Voice+SMS-capable Twilio number you own
```

Escalation targets (real phones so the SMS actually buzzes on stage):

```
NURSE_SMS_NUMBER=+1XXXXXXXXXX        # e.g. a teammate's phone playing "the nurse"
VOLUNTEER_SMS_NUMBER=+1XXXXXXXXXX    # e.g. another phone playing "the volunteer"
```

Check it:

```bash
sentinel check      # every telephony row should be green ✓
```

## 2. Point the demo patient at your cell

So `sentinel call P001` rings **you** (you'll play Eleanor):

```bash
sentinel setup-phone P001 +1XXXXXXXXXX     # your mobile, E.164 format
```

This also makes an **inbound** call *from* your phone get recognized as Eleanor,
so the inbound beat (Beat 5) works from the same handset.

## 3. Expose the webhook server to Twilio

Twilio needs a public URL to reach your laptop.

```bash
# Terminal 1
sentinel serve                      # FastAPI on :8080

# Terminal 2
ngrok http 8080                     # copy the https://....ngrok-free.app URL
```

Put that URL in `.env` (no trailing slash) and **restart `sentinel serve`**:

```
PUBLIC_BASE_URL=https://xxxx-xx-xx.ngrok-free.app
```

## 4. Point your Twilio number at the inbound webhook (for Beat 5)

Twilio console → **Phone Numbers → Manage → Active numbers → (your number) →
Voice Configuration**:

- **A call comes in** → Webhook →
  `https://xxxx.ngrok-free.app/voice/inbound` → HTTP **POST** → Save.

(Outbound doesn't need this — `sentinel call` passes its webhook URL directly.)

## 5. Run the live demo

```bash
# OUTBOUND — SentinelCall dials your phone; you answer and play Eleanor.
sentinel call P001
#   -> greets "Eleanor, day 5 from your knee surgery..."
#   -> speak a slurred/quiet symptom; watch the `serve` console show GER recover it
#   -> say "the redness around my incision is spreading and I feel warm"
#   -> agent routes to a nurse (no diagnosis); NURSE phone buzzes with the SMS

# INBOUND — call your Twilio number FROM your phone.
#   -> "is it normal that my incision itches?" -> grounded reassurance
#   -> or say an emergency phrase ("I can't breathe") -> "hang up and call 911" + alert

# GREEN SIGNAL — volunteer routing (no phone needed, but SMS is real):
sentinel demo --no-pause      # Beat 6 fires the volunteer SMS
```

Keep the `sentinel serve` terminal visible on the projector — the **GER recovery
panel and the escalation SMS render there live** as the call happens. That's the
moment that wins the room.

## Tips for the stage

- **Two terminals visible:** the call happens on your phone; the *trace* (raw ASR
  → GER recovered → escalation SMS) prints in the `serve` window. Show both.
- **ngrok URL changes** each restart (on the free tier) — re-paste it into `.env`
  *and* the Twilio number config if you restart ngrok.
- **If carrier audio is flaky on stage**, fall back instantly to
  `sentinel demo` or `sentinel sim P001 --audio` — the identical pipeline,
  identical trace, no carrier dependency. The hero still lands.
- **Latency:** patient turns are recorded (~8s max) then transcribed, so expect a
  short pause after the patient speaks. Tell the audience "it's running Deepgram
  N-best + Claude GER on that clip" — the pause *is* the safety work.
