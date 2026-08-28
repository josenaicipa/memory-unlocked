"""Episodic session summaries. Transcripts are evidence, not durable memory.

This module produces a redacted episodic summary and optional durable-fact
*proposals* that still need the normal policy gate before any write. It never
stores a transcript, never writes a memory, and never returns secret values.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from .policy import redact_pii, secret_reason

_DURABLE_HINTS = (
    "remember",
    "recuerda",
    "prefers",
    "prefiere",
    "decided",
    "decidimos",
    "decided to",
    "uses ",
    "usa ",
    "source of truth",
    "fuente de verdad",
    "convention",
    "always",
)


@dataclass(frozen=True)
class SessionSummary:
    session_id: Optional[str]
    kind: str
    event_count: int
    redacted_summary: str
    episodic_only: bool
    durable_proposals: List[Dict[str, Any]]
    write_policy: str
    secret_like_content: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _event_text(event: Dict[str, Any]) -> str:
    for key in ("content", "text", "message", "body"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _compact_summary(lines: List[str], limit: int = 800) -> str:
    joined = " | ".join(line for line in lines if line)
    if len(joined) <= limit:
        return joined
    return joined[: limit - 3].rstrip() + "..."


def _durable_proposals(lines: List[str], session_id: Optional[str]) -> List[Dict[str, Any]]:
    proposals: List[Dict[str, Any]] = []
    for index, line in enumerate(lines):
        lower = line.lower()
        if not any(hint in lower for hint in _DURABLE_HINTS):
            continue
        proposals.append(
            {
                "index": index,
                "title": line[:80],
                "body": line[:500],
                "source": f"session:{session_id or 'local'}",
                "status": "candidate",
                "requires_human_review": True,
                "applied": False,
            }
        )
    return proposals[:8]


def summarize_session_events(
    events: List[Dict[str, Any]],
    *,
    session_id: Optional[str] = None,
    max_events: int = 40,
) -> SessionSummary:
    """Build a redacted episodic summary from chat/event dictionaries.

    Expected event shape is loose: ``role`` plus ``content``/``text``/``message``.
    The function never returns raw secret material and never writes durable memory.
    """
    bounded = list(events or [])[: max(1, min(max_events, 200))]
    texts = [_event_text(event) for event in bounded]
    blob = "\n".join(text for text in texts if text)
    kind = secret_reason(blob)
    if kind:
        return SessionSummary(
            session_id=session_id,
            kind="episodic_session_summary",
            event_count=len(bounded),
            redacted_summary="[redacted: secret-like session content]",
            episodic_only=True,
            durable_proposals=[],
            write_policy="blocked: session contains secret-like content; do not store",
            secret_like_content=True,
        )

    redacted_lines = [redact_pii(text).strip() for text in texts if text.strip()]
    summary = _compact_summary(redacted_lines)
    proposals = _durable_proposals(redacted_lines, session_id=session_id)
    return SessionSummary(
        session_id=session_id,
        kind="episodic_session_summary",
        event_count=len(bounded),
        redacted_summary=summary or "(empty session)",
        episodic_only=True,
        durable_proposals=proposals,
        write_policy="propose-only: durable facts still need a source and the policy gate",
        secret_like_content=False,
    )
