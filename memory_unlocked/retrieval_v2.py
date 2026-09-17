"""Explainable second-generation ranking over an already-authorized set."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .models import Memory
from .retrieval import rank_candidates


@dataclass(frozen=True)
class RankedMemory:
    memory: Memory
    rank: int
    score: float
    reasons: tuple[str, ...]


def rank_v2(memories: Sequence[Memory], query: str, mode: str = "hybrid") -> list[RankedMemory]:
    """Rank only supplied (therefore already scope-authorized) memories.

    Scores are ordinal and intended for explanation, not cross-query comparison.
    """
    ordered = rank_candidates(memories, query, mode=mode)
    total = max(len(ordered), 1)
    query_terms = {term.lower() for term in query.split() if term}
    result = []
    for rank, memory in enumerate(ordered, start=1):
        terms = set((memory.title + " " + memory.body + " " + " ".join(memory.tags)).lower().split())
        reasons = ["hybrid relevance"]
        if query_terms & terms:
            reasons.append("query-term match")
        if memory.confidence >= 0.8:
            reasons.append("high confidence")
        result.append(RankedMemory(memory, rank, round((total - rank + 1) / total, 6), tuple(reasons)))
    return result
