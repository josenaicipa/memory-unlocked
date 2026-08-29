"""Retrieval modes over an already-authorized candidate set.

Pipeline order is the whole point of this module:

    1. **Hard scope filter (the store).** Tenant/project/thread/status/expiry
       are applied before anything here runs. Everything below can only reorder
       or drop rows.
    2. **BM25** over the authorized set (:mod:`memory_unlocked.bm25`).
    3. **Local hash vector** over the authorized set (:mod:`memory_unlocked.vector`).
    4. **RRF fusion** of those rankings (:mod:`memory_unlocked.fusion`), guarded
       by an explicit authorized-id set.
    5. **Post-scope re-rank** — confidence, recency, and status as bounded
       boosts *after* authorization, so they can promote a canonical memory
       but can never rescue an out-of-scope one.

``classic`` keeps the v1.0 blended scorer so existing recall stays stable.
``lexical``, ``vector``, and ``hybrid`` are the v1.1 opt-in path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .bm25 import BM25Index, build_document
from .fusion import ranking_ids, reciprocal_rank_fusion
from .models import Memory
from .ranking import rank as classic_rank, tokenize
from .vector import cosine_similarity, embed

BM25_FUSION_WEIGHT = 1.0
VECTOR_FUSION_WEIGHT = 0.8
RETRIEVAL_MODES = ("classic", "lexical", "vector", "hybrid")
DEFAULT_RETRIEVAL_MODE = "classic"
VECTOR_GATE = 0.05


class RetrievalError(ValueError):
    """Invalid retrieval mode or empty authorized set handling."""


@dataclass(frozen=True)
class RankedCandidate:
    """One ranked memory plus the per-signal breakdown behind its score."""

    memory: Memory
    score: float
    components: Dict[str, float]


def normalize_mode(mode: Optional[str]) -> str:
    value = (mode or DEFAULT_RETRIEVAL_MODE).strip().lower()
    if value not in RETRIEVAL_MODES:
        raise RetrievalError(
            f"retrieval mode must be one of {RETRIEVAL_MODES}, not {mode!r}"
        )
    return value


def _authorized(memories: Sequence[Memory]) -> Tuple[List[Memory], frozenset]:
    usable = [m for m in memories if m.id]
    return usable, frozenset(m.id for m in usable)


def _bm25_ranking(memories: Sequence[Memory], query: str) -> List[Tuple[str, float]]:
    docs = [
        build_document(m.id or "", m.body, m.title)
        for m in memories
        if m.id
    ]
    index = BM25Index(docs)
    return index.rank(tokenize(query))


def _vector_ranking(memories: Sequence[Memory], query: str) -> List[Tuple[str, float]]:
    query_vec = embed(query)
    scored: List[Tuple[str, float]] = []
    for memory in memories:
        if not memory.id:
            continue
        score = cosine_similarity(query_vec, embed(f"{memory.title} {memory.body}"))
        if score > VECTOR_GATE:
            scored.append((memory.id, round(score, 12)))
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored


def _post_scope_boost(memory: Memory, recency_fraction: float) -> float:
    status = 0.20 if memory.status == "active" else 0.0
    confidence = 0.08 * memory.confidence
    recency = 0.12 * recency_fraction
    return status + confidence + recency


def _recency_map(memories: Sequence[Memory]) -> Dict[str, float]:
    ordered = sorted(
        [m for m in memories if m.id],
        key=lambda m: (m.created_at or "", m.id or ""),
    )
    n = len(ordered)
    if n <= 1:
        return {m.id: 1.0 for m in ordered if m.id}
    return {m.id: i / (n - 1) for i, m in enumerate(ordered) if m.id}


def rank_candidates(
    memories: Sequence[Memory],
    query: str = "",
    mode: str = DEFAULT_RETRIEVAL_MODE,
) -> List[Memory]:
    """Return authorized ``memories`` sorted best-first for ``query``."""
    resolved = normalize_mode(mode)
    if resolved == "classic" or not (query or "").strip():
        return classic_rank(memories, query)

    usable, authorized = _authorized(memories)
    if not usable:
        return []

    bm25 = _bm25_ranking(usable, query) if resolved in ("lexical", "hybrid") else []
    vector = _vector_ranking(usable, query) if resolved in ("vector", "hybrid") else []

    if resolved == "lexical":
        fused_ids = ranking_ids(bm25)
        scores = {doc_id: score for doc_id, score in bm25}
    elif resolved == "vector":
        fused_ids = ranking_ids(vector)
        scores = {doc_id: score for doc_id, score in vector}
    else:
        scores = reciprocal_rank_fusion(
            [ranking_ids(bm25), ranking_ids(vector)],
            authorized_ids=authorized,
            weights=(BM25_FUSION_WEIGHT, VECTOR_FUSION_WEIGHT),
        )
        fused_ids = ranking_ids(list(scores.items()))

    by_id = {m.id: m for m in usable}
    recency = _recency_map(usable)
    ranked: List[Tuple[float, str, Memory]] = []
    bm25_map = dict(bm25)
    vector_map = dict(vector)
    for doc_id in fused_ids:
        memory = by_id.get(doc_id)
        if memory is None:
            continue
        if bm25_map.get(doc_id, 0.0) <= 0.0 and vector_map.get(doc_id, 0.0) <= 0.0:
            continue
        relevance = float(scores.get(doc_id, 0.0))
        boost = _post_scope_boost(memory, recency.get(doc_id, 0.0))
        ranked.append((relevance + boost, doc_id, memory))
    ranked.sort(key=lambda item: (-item[0], item[2].created_at or "", item[1]))
    return [item[2] for item in ranked]


# Keep a documented alias so tests/callers can name the gate without importing
# an undefined vector module constant.
VECTOR_MATCH_GATE = VECTOR_GATE
