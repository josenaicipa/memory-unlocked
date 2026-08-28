"""Local deterministic token-hash embeddings.

The public package stays dependency-free and never calls a paid embedding API.
This module ships a hashing-trick vector: every token is mapped into a fixed
dimension with a signed bucket, term frequencies accumulate, and the vector is
L2-normalised. It is a portable, offline stand-in so hybrid ranking is
testable on every machine — not a semantic encoder.

Nothing here can widen scope: callers pass already-authorized texts and receive
scores for those texts only.
"""

from __future__ import annotations

import hashlib
import math
from functools import lru_cache
from typing import Sequence, Tuple

from .ranking import tokenize

EMBEDDING_DIM = 256
Vector = Tuple[float, ...]


def _bucket_and_sign(token: str, dim: int) -> Tuple[int, float]:
    """Map a token to a (bucket, sign) pair deterministically.

    Uses MD5 (stable across processes/platforms, unlike the salted builtin
    ``hash``) so embeddings are reproducible run-to-run. The digest is not used
    as a security control.
    """
    digest = hashlib.md5(token.encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:4], "big") % dim
    sign = 1.0 if (digest[4] & 1) else -1.0
    return bucket, sign


@lru_cache(maxsize=4096)
def embed(text: str, dim: int = EMBEDDING_DIM) -> Vector:
    """Return an L2-normalised token-hash embedding for ``text``.

    Empty or token-free text yields the zero vector (no signal).
    """
    vec = [0.0] * dim
    for token in tokenize(text):
        bucket, sign = _bucket_and_sign(token, dim)
        vec[bucket] += sign
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return tuple(vec)
    return tuple(x / norm for x in vec)


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity in [-1, 1]; 0.0 if either vector is all-zero."""
    if len(a) != len(b):
        raise ValueError("vectors must share dimensionality")
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)
