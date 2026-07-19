"""Layer 2 (Reference, general) — the ONLY RAG layer.

A small clinician-style markdown doc per surgery type, chunked by heading and
retrieved by keyword overlap (no external vector DB — deliberately not
over-engineered for a hackathon demo; the interface is the same if we swap in
embeddings later).

Selection is by surgery type: `protocol_<type>.md` if one matches the patient's
`surgery` field, else `protocol_generic.md`. This is what keeps SentinelCall a
GENERAL post-op agent — knee is just the first protocol pack, not a hardcoded
assumption.

This layer informs the agent's questions and escalation. It is NEVER read to the
patient as a recommendation, and it NEVER overrides the patient's prescribed
record (Layer 1).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sentinelcall.config import DATA_DIR

_STOP = set(
    "the a an of to and or is are was be it my your you i we for on in at with as "
    "that this these those any some do does not no yes if then so but from about "
    "have has had will would can could should".split()
)


@dataclass
class Chunk:
    heading: str
    text: str
    source: str


def _tokenize(s: str) -> List[str]:
    return [w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in _STOP and len(w) > 2]


def _surgery_to_protocol(surgery: str) -> str:
    """Map a free-text surgery description to a protocol filename stem.

    'Total knee replacement (right knee)' -> 'knee'
    'Total hip replacement (left hip)'    -> 'hip' (falls back to generic if no file)
    """
    s = surgery.lower()
    for key in ("knee", "hip", "shoulder", "cardiac", "spine", "abdominal", "cataract"):
        if key in s:
            return key
    return "generic"


class ReferenceRAG:
    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        self._data_dir = data_dir
        self._cache: Dict[str, List[Chunk]] = {}

    def _protocol_path(self, surgery: str) -> Tuple[Path, str]:
        stem = _surgery_to_protocol(surgery)
        specific = self._data_dir / f"protocol_{stem}.md"
        if specific.exists():
            return specific, stem
        return self._data_dir / "protocol_generic.md", "generic"

    def _load_chunks(self, path: Path) -> List[Chunk]:
        key = str(path)
        if key in self._cache:
            return self._cache[key]
        chunks: List[Chunk] = []
        if path.exists():
            raw = path.read_text()
            # split on ## / ### headings, keep the heading with its body
            parts = re.split(r"(?m)^(#{2,3}\s+.*)$", raw)
            # parts alternates: [pre, heading, body, heading, body, ...]
            heading = "overview"
            buf = parts[0]
            pending: List[Tuple[str, str]] = []
            if buf.strip():
                pending.append((heading, buf))
            i = 1
            while i < len(parts):
                h = parts[i].lstrip("#").strip()
                body = parts[i + 1] if i + 1 < len(parts) else ""
                pending.append((h, body))
                i += 2
            for h, body in pending:
                body = body.strip()
                if body:
                    chunks.append(Chunk(heading=h, text=body, source=path.name))
        self._cache[key] = chunks
        return chunks

    def retrieve(self, query: str, surgery: str, *, k: int = 2) -> List[Chunk]:
        """Return the top-k reference chunks for a query, scoped to the surgery's
        protocol pack (specific if present, else generic)."""
        path, _ = self._protocol_path(surgery)
        chunks = self._load_chunks(path)
        if not chunks:
            return []
        q = set(_tokenize(query))
        scored: List[Tuple[float, Chunk]] = []
        for c in chunks:
            ctoks = _tokenize(c.heading + " " + c.text)
            if not ctoks:
                continue
            overlap = sum(1 for t in ctoks if t in q)
            # normalize a little by chunk length so long chunks don't always win
            score = overlap / (1 + 0.01 * len(ctoks))
            if overlap:
                scored.append((score, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:k]]

    def protocol_name(self, surgery: str) -> str:
        _, stem = self._protocol_path(surgery)
        return stem


_rag: Optional[ReferenceRAG] = None


def reference_rag() -> ReferenceRAG:
    global _rag
    if _rag is None:
        _rag = ReferenceRAG()
    return _rag
