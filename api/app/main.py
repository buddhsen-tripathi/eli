from dotenv import load_dotenv

load_dotenv()

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.calls import router as calls_router
from app.caregivers import router as caregivers_router
from app.outbound import router as outbound_router
from app.patients import router as patients_router
from app.voice import router as voice_router

app = FastAPI(
    title="arya API",
    description="Backend for a post-op voice agent (Twilio + ElevenLabs).",
    version="0.1.0",
)

# Allow the Next.js dashboard (default localhost:3000) to call the API in dev.
_origins = os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(voice_router)
app.include_router(outbound_router)
app.include_router(calls_router)
app.include_router(patients_router)
app.include_router(caregivers_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
