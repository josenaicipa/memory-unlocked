"""Okapi BM25 lexical ranking over an already-authorized candidate set.

Rare query terms outweigh common ones, term frequency saturates instead of
growing linearly, and long documents are length-normalised so a verbose memory
cannot outrank a precise one purely by repeating a word.

Scope safety
------------
BM25 needs corpus statistics (document frequency, average document length).
Those statistics are computed **only over the candidate list handed in**, which
the caller has already filtered by tenant/project/thread/status. Two
consequences, both deliberate:

- No cross-scope information — not even a term count — influences ranking.
- BM25 can only reorder candidates. It never adds one.

Determinism
-----------
Pure float arithmetic over :func:`memory_unlocked.ranking.tokenize`, with scores
rounded before they are returned so JSONL and SQLite produce identical orderings.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple

from .ranking import tokenize

BM25_K1 = 1.2
BM25_B = 0.75
TITLE_FIELD_WEIGHT = 2


@dataclass(frozen=True)
class BM25Document:
    """One scored unit: a stable id plus its pre-tokenized text."""

    doc_id: str
    tokens: Tuple[str, ...]

    @property
    def length(self) -> int:
        return len(self.tokens)


def build_document(
    doc_id: str,
    body: str,
    title: str = "",
    *,
    title_weight: int = TITLE_FIELD_WEIGHT,
) -> BM25Document:
    """Tokenize one memory into a :class:`BM25Document`.

    Title tokens are repeated ``title_weight`` times so a query term in the
    title outranks the same term buried in the body.
    """
    tokens = list(tokenize(body or ""))
    if title:
        tokens.extend(list(tokenize(title)) * max(1, int(title_weight)))
    return BM25Document(doc_id=doc_id, tokens=tuple(tokens))


class BM25Index:
    """In-memory BM25 index over one authorized candidate set.

    Built per query. Candidate sets are already bounded by the store, so
    building an index per search stays cheap and never observes other scopes.
    """

    def __init__(self, documents: Sequence[BM25Document]) -> None:
        self._docs = list(documents)
        self._n = max(1, len(self._docs))
        self._avg_len = (
            sum(doc.length for doc in self._docs) / float(len(self._docs))
            if self._docs
            else 0.0
        )
        df: Dict[str, int] = {}
        for doc in self._docs:
            for token in set(doc.tokens):
                df[token] = df.get(token, 0) + 1
        self._df = df

    def _idf(self, token: str) -> float:
        freq = self._df.get(token, 0)
        # Smoothed IDF that stays positive on tiny authorized sets (a student
        # store may have two memories). A term in every document still scores,
        # just less than a rare one.
        return math.log((self._n + 1) / (freq + 1)) + 1.0

    def score(self, query_tokens: Sequence[str], document: BM25Document) -> float:
        if not query_tokens or not document.tokens:
            return 0.0
        counts: Dict[str, int] = {}
        for token in document.tokens:
            counts[token] = counts.get(token, 0) + 1
        length = document.length or 1
        avg_len = self._avg_len or 1.0
        total = 0.0
        for term in query_tokens:
            tf = counts.get(term, 0)
            if not tf:
                continue
            idf = self._idf(term)
            denom = tf + BM25_K1 * (1.0 - BM25_B + BM25_B * (length / avg_len))
            total += idf * (tf * (BM25_K1 + 1.0)) / denom
        return round(total, 12)

    def rank(self, query_tokens: Sequence[str]) -> List[Tuple[str, float]]:
        """Return ``(doc_id, score)`` pairs, best-first, zeros omitted."""
        scored = [
            (doc.doc_id, self.score(query_tokens, doc))
            for doc in self._docs
        ]
        scored = [(doc_id, score) for doc_id, score in scored if score > 0.0]
        scored.sort(key=lambda item: (-item[1], item[0]))
        return scored


def rank_documents(
    documents: Iterable[BM25Document],
    query: str,
) -> List[Tuple[str, float]]:
    """Convenience wrapper: tokenize ``query`` and rank ``documents``."""
    index = BM25Index(list(documents))
    return index.rank(tokenize(query))
