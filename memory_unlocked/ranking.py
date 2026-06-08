"""Deterministic, dependency-free ranking and token-budget helpers.

The reference recall path ranks scope-filtered memories with a transparent,
fully local scoring function — no paid APIs, no external embeddings, no network.
Everything here is pure and deterministic so ranking is testable and a ranking
bug can never widen scope (scope is already enforced by the store before any of
this runs).

Scoring blends four signals:

* **Lexical relevance** — token overlap between the query and a memory, weighted
  by a local inverse-document-frequency so common words count for less. This is
  a tiny BM25-style lexical score, not a vector embedding, but it is stable and
  needs nothing beyond the standard library.
* **Confidence** — the writer's stated confidence in the fact.
* **Recency** — newer memories rank slightly higher, by ``created_at`` order.
* **Status** — ``active`` memories outrank ``candidate`` ones when both are in
  the candidate set.

It also provides a token estimator and a near-duplicate detector used by the
context assembler and the governance audit.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Sequence

from .models import Memory

# A word is a run of alphanumerics; everything else is a separator. Lowercased.
_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Rough chars-per-token heuristic for budgeting context windows without pulling
# in a tokenizer dependency. English prose averages ~4 characters per token.
CHARS_PER_TOKEN = 4


def tokenize(text: str) -> List[str]:
    """Split text into lowercased alphanumeric tokens."""
    return _TOKEN_RE.findall((text or "").lower())


def estimate_tokens(text: str) -> int:
    """Estimate the token count of ``text`` (deterministic, no tokenizer dep)."""
    if not text:
        return 0
    return max(1, math.ceil(len(text) / CHARS_PER_TOKEN))


@dataclass
class RankingConfig:
    """Weights for the blended score. Defaults are deliberately conservative.

    The lexical term dominates when a query is present; ``confidence`` provides
    the ordering when a query is absent, matching the original behaviour.
    """

    lexical_weight: float = 1.0
    confidence_weight: float = 1.0
    recency_weight: float = 0.25
    tag_weight: float = 0.5
    status_weight: float = 0.5
    # Jaccard similarity at/above which two memories are treated as duplicates.
    dedupe_threshold: float = 0.92


def _token_set(memory: Memory) -> set:
    return set(tokenize(f"{memory.title} {memory.body}"))


def _document_frequencies(memories: Sequence[Memory]) -> Dict[str, int]:
    """How many memories each token appears in (for the IDF weighting)."""
    df: Dict[str, int] = {}
    for memory in memories:
        for token in _token_set(memory):
            df[token] = df.get(token, 0) + 1
    return df


def _idf(token: str, df: Dict[str, int], n_docs: int) -> float:
    """Smoothed inverse document frequency in [~0, ln(N)+1]."""
    freq = df.get(token, 0)
    return math.log((n_docs + 1) / (freq + 1)) + 1.0


@dataclass
class Scorer:
    """Stateful scorer bound to a candidate set (so IDF is corpus-relative)."""

    memories: Sequence[Memory]
    config: RankingConfig = field(default_factory=RankingConfig)

    def __post_init__(self) -> None:
        self._n = max(1, len(self.memories))
        self._df = _document_frequencies(self.memories)
        # Stable recency ranking: position of each id in created_at order. We use
        # (created_at, id) so the order is total and deterministic even when two
        # memories share a timestamp (the injected clocks in tests can collide).
        ordered = sorted(
            [m for m in self.memories if m.id],
            key=lambda m: (m.created_at or "", m.id or ""),
        )
        self._recency_rank = {m.id: i for i, m in enumerate(ordered)}

    def score(self, memory: Memory, query_terms: Sequence[str]) -> float:
        cfg = self.config
        score = cfg.confidence_weight * memory.confidence
        score += cfg.status_weight * (1.0 if memory.status == "active" else 0.0)
        score += cfg.recency_weight * self._recency_fraction(memory)

        if query_terms:
            score += cfg.lexical_weight * self._lexical(memory, query_terms)
            score += cfg.tag_weight * self._tag_overlap(memory, query_terms)
        return score

    def _recency_fraction(self, memory: Memory) -> float:
        if self._n <= 1:
            return 1.0
        rank = self._recency_rank.get(memory.id, 0)
        return rank / (self._n - 1)

    def _lexical(self, memory: Memory, query_terms: Sequence[str]) -> float:
        tokens = tokenize(f"{memory.title} {memory.body}")
        if not tokens:
            return 0.0
        counts: Dict[str, int] = {}
        for tok in tokens:
            counts[tok] = counts.get(tok, 0) + 1
        total = 0.0
        for term in query_terms:
            tf = counts.get(term, 0)
            if tf:
                # Saturating term frequency keeps one spammy word from dominating.
                tf_component = tf / (tf + 1.0)
                total += tf_component * _idf(term, self._df, self._n)
        return total

    @staticmethod
    def _tag_overlap(memory: Memory, query_terms: Sequence[str]) -> float:
        return float(sum(1 for t in query_terms if any(t in tag for tag in memory.tags)))


def rank(
    memories: Sequence[Memory],
    query: str = "",
    config: RankingConfig | None = None,
) -> List[Memory]:
    """Return ``memories`` sorted best-first for ``query`` (stable, deterministic)."""
    cfg = config or RankingConfig()
    scorer = Scorer(memories, cfg)
    terms = tokenize(query)
    # Sort by (-score, created_at, id) so ties break deterministically.
    return sorted(
        memories,
        key=lambda m: (-scorer.score(m, terms), m.created_at or "", m.id or ""),
    )


def jaccard(a: Memory, b: Memory) -> float:
    """Token-set Jaccard similarity of two memories' title+body."""
    sa, sb = _token_set(a), _token_set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def dedupe(memories: Sequence[Memory], threshold: float = 0.92) -> List[Memory]:
    """Drop near-duplicate memories, keeping the first occurrence.

    Order-preserving: the earlier memory in the input wins, so a caller that has
    already ranked best-first keeps the best representative of each cluster.
    """
    kept: List[Memory] = []
    for memory in memories:
        if any(jaccard(memory, k) >= threshold for k in kept):
            continue
        kept.append(memory)
    return kept


def find_duplicate_groups(
    memories: Sequence[Memory],
    threshold: float = 0.92,
) -> List[List[Memory]]:
    """Cluster near-duplicate memories. Returns only groups with 2+ members."""
    groups: List[List[Memory]] = []
    assigned: set = set()
    for i, memory in enumerate(memories):
        if id(memory) in assigned:
            continue
        group = [memory]
        assigned.add(id(memory))
        for other in memories[i + 1:]:
            if id(other) in assigned:
                continue
            if jaccard(memory, other) >= threshold:
                group.append(other)
                assigned.add(id(other))
        if len(group) > 1:
            groups.append(group)
    return groups
