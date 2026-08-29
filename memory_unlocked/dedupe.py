"""Duplicate and contradiction detection over already-authorized memories.

Pure, deterministic helpers. Duplicate detection uses token-set Jaccard
similarity. Exact duplicates (same normalised text) are reported with
``kind="exact"``. Contradiction detection is conservative: it only fires when
two texts share enough *subject* tokens AND differ in polarity (a negation cue
or an opposite state word). Output is advisory — links are suggested, never
applied.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from .models import Memory

_WORD_RE = re.compile(r"[a-z0-9]+")

DEFAULT_DUPLICATE_THRESHOLD = 0.85
DEFAULT_NEAR_THRESHOLD = 0.92
DEFAULT_SUBJECT_OVERLAP = 0.5

NEGATION_CUES = frozenset(
    {
        "no", "not", "never", "neither", "without",
        "nunca", "jamas", "tampoco", "ningun", "ninguna", "ninguno", "sin",
    }
)
OBLIGATION_CUES = frozenset(
    {"must", "should", "cannot", "can't", "debe", "deben", "deberia", "deberian"}
)
OPPOSITE_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("on", "off"),
    ("enabled", "disabled"),
    ("active", "inactive"),
    ("allow", "deny"),
    ("allowed", "denied"),
    ("true", "false"),
    ("yes", "no"),
    ("activo", "inactivo"),
    ("habilitado", "deshabilitado"),
)
_TOGGLE_TOKENS = frozenset(token for pair in OPPOSITE_PAIRS for token in pair)
_STOPWORDS = frozenset(
    {
        "the", "of", "to", "in", "on", "and", "or", "a", "an", "for", "with",
        "is", "are", "be", "by", "as", "at", "from",
        "el", "la", "los", "las", "un", "una", "de", "del", "al", "y", "o",
        "que", "en", "a", "es", "por", "para", "con", "su", "sus", "se", "lo",
    }
)


def normalize_text(text: Optional[str]) -> str:
    """Accent-stripped, lowercased, whitespace-collapsed text."""
    if not text:
        return ""
    norm = unicodedata.normalize("NFKD", text)
    ascii_text = norm.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"\s+", " ", ascii_text).strip()


def _tokens(text: Optional[str]) -> List[str]:
    return _WORD_RE.findall(normalize_text(text))


def _token_set(memory: Memory) -> set:
    return set(_tokens(f"{memory.title} {memory.body}"))


def jaccard_texts(a: str, b: str) -> float:
    sa, sb = set(_tokens(a)), set(_tokens(b))
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / float(len(sa | sb))


def jaccard(a: Memory, b: Memory) -> float:
    sa, sb = _token_set(a), _token_set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / float(len(sa | sb))


@dataclass(frozen=True)
class DuplicatePair:
    left_id: str
    right_id: str
    similarity: float
    kind: str  # exact | near


def find_duplicate_pairs(
    memories: Sequence[Memory],
    threshold: float = DEFAULT_DUPLICATE_THRESHOLD,
) -> List[DuplicatePair]:
    """Return unique pairs of near/exact duplicates, ids sorted per pair."""
    usable = [m for m in memories if m.id]
    pairs: List[DuplicatePair] = []
    for i, left in enumerate(usable):
        left_text = normalize_text(f"{left.title} {left.body}")
        for right in usable[i + 1:]:
            similarity = jaccard(left, right)
            if similarity < threshold:
                continue
            right_text = normalize_text(f"{right.title} {right.body}")
            kind = "exact" if left_text == right_text or similarity >= 0.999 else "near"
            a, b = sorted((left.id or "", right.id or ""))
            pairs.append(DuplicatePair(left_id=a, right_id=b, similarity=round(similarity, 4), kind=kind))
    pairs.sort(key=lambda p: (-p.similarity, p.left_id, p.right_id))
    return pairs


def _subject_tokens(text: str) -> set:
    return {
        token
        for token in _tokens(text)
        if token not in _STOPWORDS
        and token not in NEGATION_CUES
        and token not in OBLIGATION_CUES
        and token not in _TOGGLE_TOKENS
    }


def _polarity(text: str) -> Tuple[bool, frozenset]:
    tokens = set(_tokens(text))
    negated = bool(tokens & NEGATION_CUES)
    toggles = frozenset(tokens & _TOGGLE_TOKENS)
    return negated, toggles


def _opposes(left_toggles: frozenset, right_toggles: frozenset) -> bool:
    for a, b in OPPOSITE_PAIRS:
        if (a in left_toggles and b in right_toggles) or (b in left_toggles and a in right_toggles):
            return True
    return False


@dataclass(frozen=True)
class ContradictionPair:
    left_id: str
    right_id: str
    subject_overlap: float
    reason: str


def find_contradiction_pairs(
    memories: Sequence[Memory],
    subject_overlap: float = DEFAULT_SUBJECT_OVERLAP,
) -> List[ContradictionPair]:
    """Advisory contradiction pairs. Never mutates memories or links."""
    usable = [m for m in memories if m.id]
    pairs: List[ContradictionPair] = []
    for i, left in enumerate(usable):
        left_text = f"{left.title} {left.body}"
        left_subject = _subject_tokens(left_text)
        left_neg, left_toggles = _polarity(left_text)
        if not left_subject:
            continue
        for right in usable[i + 1:]:
            right_text = f"{right.title} {right.body}"
            right_subject = _subject_tokens(right_text)
            if not right_subject:
                continue
            overlap = len(left_subject & right_subject) / float(len(left_subject | right_subject))
            if overlap < subject_overlap:
                continue
            right_neg, right_toggles = _polarity(right_text)
            reason = None
            if left_neg != right_neg:
                reason = "negation"
            elif _opposes(left_toggles, right_toggles):
                reason = "toggle"
            if reason is None:
                continue
            a, b = sorted((left.id or "", right.id or ""))
            pairs.append(
                ContradictionPair(
                    left_id=a,
                    right_id=b,
                    subject_overlap=round(overlap, 4),
                    reason=reason,
                )
            )
    pairs.sort(key=lambda p: (-p.subject_overlap, p.left_id, p.right_id, p.reason))
    return pairs
