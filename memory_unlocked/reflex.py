"""Read-first task reflexes; both helpers are side-effect free."""

from __future__ import annotations

from typing import Any

from .assembler import AssemblerConfig, ContextAssembler
from .models import Memory, Namespace, Source
from .ranking import jaccard
from .store import MemoryStore


def reflex_pre_task(store: MemoryStore, namespace: Namespace, query: str, token_budget: int = 600) -> dict[str, Any]:
    """Build scoped context before a task; it never performs a write."""
    context = ContextAssembler(store, AssemblerConfig(max_tokens=token_budget)).assemble(namespace, query)
    return {"action": "context", "namespace": namespace.as_key(), "context": context}


def reflex_post_task(
    store: MemoryStore, namespace: Namespace, title: str, body: str, source_ref: str,
    confidence: float = 0.5,
) -> dict[str, Any]:
    """Create a candidate proposal and duplicate signal without persisting it."""
    candidate = Memory(
        namespace=namespace, title=title, body=body, source=Source("run", source_ref),
        confidence=confidence, status="candidate",
    )
    similar = [m.id for m in store.query(namespace, match=False) if jaccard(candidate, m) >= 0.92]
    return {
        "action": "propose", "namespace": namespace.as_key(), "candidate": candidate,
        "duplicate_ids": similar, "requires_review": True,
    }
