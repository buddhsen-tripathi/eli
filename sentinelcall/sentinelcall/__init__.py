"""SentinelCall — accessibility-first post-op voice agent.

A cascaded, guardrailed Twilio voice agent that phones elderly post-op
patients and is engineered so slurred / quiet / accented speech degrades
gracefully instead of failing silently.

The agent is a structured-intake + routing instrument, NOT a medical advisor.
It collects, grounds in the patient's own discharge record, and routes to a
human. It never diagnoses, never recommends treatment, never renders clinical
judgment to the patient.
"""

__version__ = "0.1.0"
