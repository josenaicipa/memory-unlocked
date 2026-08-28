"""Propose-only governance curator.

The curator is a deliberate, deterministic pass over what is already stored. It
reads memories, applies explicit rules, and emits a **reviewable plan**. It
never writes, never promotes, and never archives. Applying a proposal is a
separate, explicit human action through ``status`` / ``forget``.

Every proposal carries ``applied=False`` and ``requires_human_review=True``.
Evidence is titles and ids only — never bodies, secrets, or PII-shaped values.
``now`` is a required input so the same store + config + timestamp produce a
byte-stable plan.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from .dedupe import find_contradiction_pairs, find_duplicate_pairs
from .models import Memory, Namespace
from .policy import redact_if_secret, redact_pii, secret_reason
from .thread_scope import admits_thread, normalize_thread

CURATOR_SCHEMA_VERSION = "1.1"
CURATOR_VERSION = "1.1.0"

ACTIONS = (
    "quarantine_suspected_secret",
    "archive_duplicate",
    "merge_near_duplicates",
    "review_contradiction",
    "mark_expired",
    "review_low_confidence",
    "promote_candidate",
)

_SEVERITY = {
    "quarantine_suspected_secret": "critical",
    "archive_duplicate": "high",
    "review_contradiction": "high",
    "mark_expired": "medium",
    "merge_near_duplicates": "medium",
    "review_low_confidence": "low",
    "promote_candidate": "low",
}
_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}

DEFAULT_LOW_CONFIDENCE = 0.3
DEFAULT_PROMOTE_MIN_CONFIDENCE = 0.7
DEFAULT_MAX_PROPOSALS = 200


def _safe_title(title: str) -> str:
    return redact_if_secret(redact_pii(title or ""))[:160]


def _proposal_id(action: str, memory_ids: Sequence[str], scope: str) -> str:
    payload = "|".join((action, scope, ",".join(sorted(memory_ids))))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"cur_{digest}"


def _ref(memory: Memory) -> Dict[str, Any]:
    return {
        "id": memory.id,
        "title": _safe_title(memory.title),
        "status": memory.status,
        "confidence": memory.confidence,
        "thread": memory.thread,
    }


@dataclass(frozen=True)
class CuratorConfig:
    low_confidence: float = DEFAULT_LOW_CONFIDENCE
    promote_min_confidence: float = DEFAULT_PROMOTE_MIN_CONFIDENCE
    max_proposals: int = DEFAULT_MAX_PROPOSALS


def curate(
    memories: Sequence[Memory],
    *,
    namespace: Optional[Namespace] = None,
    thread: Optional[str] = None,
    now: str,
    config: Optional[CuratorConfig] = None,
) -> Dict[str, Any]:
    """Return a propose-only plan. Does not mutate ``memories`` or any store."""
    cfg = config or CuratorConfig()
    requested_thread = normalize_thread(thread)
    scoped = [
        m for m in memories
        if (namespace is None or m.namespace == namespace)
        and admits_thread(m.thread, requested_thread)
    ]
    by_id = {m.id: m for m in scoped if m.id}
    proposals: List[Dict[str, Any]] = []

    def emit(action: str, ids: Sequence[str], reasons: List[str], extra: Optional[Dict[str, Any]] = None) -> None:
        scope_key = namespace.as_key() if namespace else "*"
        if requested_thread:
            scope_key = f"{scope_key}#{requested_thread}"
        proposal = {
            "proposal_id": _proposal_id(action, ids, scope_key),
            "action": action,
            "severity": _SEVERITY[action],
            "memory_ids": list(ids),
            "evidence": [_ref(by_id[i]) for i in ids if i in by_id],
            "reasons": reasons,
            "applied": False,
            "requires_human_review": True,
        }
        if extra:
            proposal.update(extra)
        proposals.append(proposal)

    for memory in scoped:
        if not memory.id:
            continue
        blob = f"{memory.title}\n{memory.body}\n{memory.source.ref}"
        reason = secret_reason(blob)
        if reason:
            emit(
                "quarantine_suspected_secret",
                [memory.id],
                ["stored content matched a secret pattern"],
                {"secret_kind": reason},
            )
        if memory.expires_at and memory.expires_at <= now and memory.status in ("active", "candidate"):
            emit("mark_expired", [memory.id], ["ttl elapsed; exclude from recall or archive"])
        if memory.confidence < cfg.low_confidence:
            emit("review_low_confidence", [memory.id], ["confidence below review floor"])
        if memory.status == "candidate" and memory.confidence >= cfg.promote_min_confidence:
            emit("promote_candidate", [memory.id], ["candidate meets the promotion confidence floor"])

    for pair in find_duplicate_pairs(scoped):
        action = "archive_duplicate" if pair.kind == "exact" else "merge_near_duplicates"
        emit(
            action,
            [pair.left_id, pair.right_id],
            [f"{pair.kind} duplicate similarity={pair.similarity}"],
            {"similarity": pair.similarity, "kind": pair.kind},
        )

    for pair in find_contradiction_pairs(scoped):
        emit(
            "review_contradiction",
            [pair.left_id, pair.right_id],
            [f"possible contradiction ({pair.reason})"],
            {"reason": pair.reason, "subject_overlap": pair.subject_overlap},
        )

    # A suspected secret on a memory suppresses every other proposal about it.
    secret_ids = {
        item["memory_ids"][0]
        for item in proposals
        if item["action"] == "quarantine_suspected_secret" and item["memory_ids"]
    }
    if secret_ids:
        proposals = [
            item for item in proposals
            if item["action"] == "quarantine_suspected_secret"
            or not secret_ids.intersection(item["memory_ids"])
        ]

    proposals.sort(
        key=lambda item: (
            _SEVERITY_RANK[item["severity"]],
            item["action"],
            item["proposal_id"],
        )
    )
    truncated = len(proposals) > cfg.max_proposals
    proposals = proposals[: cfg.max_proposals]
    plan = {
        "schema_version": CURATOR_SCHEMA_VERSION,
        "curator_version": CURATOR_VERSION,
        "generated_at": now,
        "namespace": namespace.as_key() if namespace else None,
        "thread": requested_thread,
        "applied": False,
        "requires_human_review": True,
        "writes_performed": 0,
        "truncated": truncated,
        "counts": {
            "memories": len(scoped),
            "proposals": len(proposals),
        },
        "proposals": proposals,
    }
    # Stable JSON form for determinism checks (callers may dump this).
    plan["plan_id"] = hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return plan
