"""Deterministic, propose-only consolidation planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .models import Memory, Namespace
from .ranking import find_duplicate_groups


@dataclass(frozen=True)
class ConsolidationProposal:
    namespace: Namespace
    source_ids: tuple[str, ...]
    action: str
    reason: str
    requires_approval: bool = True


def plan_consolidation(memories: Sequence[Memory], namespace: Namespace, threshold: float = 0.92) -> list[ConsolidationProposal]:
    """Suggest duplicate merges within exactly one scope; never writes or deletes."""
    scoped = [m for m in memories if m.namespace == namespace and m.status in ("active", "candidate")]
    proposals = []
    for group in find_duplicate_groups(scoped, threshold):
        ids = tuple(sorted(m.id for m in group if m.id))
        if len(ids) > 1:
            proposals.append(ConsolidationProposal(namespace, ids, "merge", "near-duplicate memories"))
    return proposals
