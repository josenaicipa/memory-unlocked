"""Reciprocal Rank Fusion for the retrieval pipeline.

RRF combines several rankings without needing their scores on a common scale::

    score(d) = Σ  weight_i / (k + rank_i(d))

with ``rank`` 1-based and ``k`` damping the influence of the very top ranks.

Authorization
-------------
RRF is a **ranker, not a gate**. Every id it emits must already be authorized by
the store's scope filter. :func:`reciprocal_rank_fusion` therefore takes an
explicit ``authorized_ids`` set and raises :class:`UnauthorizedCandidateError`
if any input ranking contains an id outside it. A bug in an upstream ranker
fails loudly here instead of quietly leaking a sibling thread's memory.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence

RRF_K = 60


class UnauthorizedCandidateError(RuntimeError):
    """A ranking contained an id outside the authorized candidate set."""

    def __init__(self, offending: Iterable[str]) -> None:
        ids = sorted(set(offending))
        super().__init__(
            f"fusion received {len(ids)} candidate id(s) outside the authorized "
            f"scope set: {ids[:5]}{'...' if len(ids) > 5 else ''}"
        )
        self.offending_ids = tuple(ids)


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]],
    *,
    authorized_ids: FrozenSet[str],
    weights: Optional[Sequence[float]] = None,
    k: int = RRF_K,
) -> Dict[str, float]:
    """Fuse ranked id lists into ``id -> score``. Higher is better.

    A document missing from a ranking contributes nothing from that ranking,
    which is the standard RRF treatment of partial lists.
    """
    if weights is None:
        used_weights: Sequence[float] = [1.0] * len(rankings)
    else:
        used_weights = weights
    if len(used_weights) != len(rankings):
        raise ValueError("weights and rankings must be the same length")

    offending = {
        doc_id
        for ranking in rankings
        for doc_id in ranking
        if doc_id not in authorized_ids
    }
    if offending:
        raise UnauthorizedCandidateError(offending)

    fused: Dict[str, float] = {}
    for ranking, weight in zip(rankings, used_weights):
        for position, doc_id in enumerate(ranking, start=1):
            fused[doc_id] = fused.get(doc_id, 0.0) + float(weight) / (k + position)
    return fused


def ranking_ids(scored: Sequence[tuple]) -> List[str]:
    """Best-first ids from ``(id, score)`` pairs, dropping non-positive scores."""
    ordered = [
        doc_id
        for doc_id, score in sorted(scored, key=lambda pair: (-float(pair[1]), pair[0]))
        if float(score) > 0.0
    ]
    return ordered
