"""The policy gate: the security-critical write filter.

Every write passes through ``review`` before it is stored. The gate has two
hard-fail checks (secrets, missing source) and an optional soft-redaction pass.

The patterns here are a sensible floor, not a complete DLP solution. Extend
``SECRET_PATTERNS`` for your domain. The goal is to make the *common, dangerous*
mistakes impossible by default.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Iterable, List, Pattern, Tuple

from .models import Memory, Source


class PolicyError(Exception):
    """Raised when a proposed write violates policy and must not be stored."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        # A machine-readable reason code, e.g. "secret_detected".
        # Never carries the offending value.
        self.reason = reason


# Credential-shaped patterns. Each entry is (reason_code, compiled_regex).
SECRET_PATTERNS: List[tuple[str, Pattern[str]]] = [
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("aws_secret_var", re.compile(r"AWS_SECRET_ACCESS_KEY\s*[=:]\s*\S+")),
    ("private_key_block", re.compile(r"-----BEGIN[ A-Z]*PRIVATE KEY-----")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9\-._~+/]{20,}=*", re.IGNORECASE)),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("generic_secret_assignment", re.compile(
        r"\b(password|passwd|secret|api[_-]?key|access[_-]?token|client[_-]?secret)\b"
        r"\s*[=:]\s*[\"']?\S{6,}",
        re.IGNORECASE,
    )),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
]


# Personal-data-shaped patterns. These are *soft* by default: depending on
# ``pii_mode`` they either reject the write or are scrubbed from the stored copy.
# Kept conservative to limit false positives on legitimate source refs.
PII_PATTERNS: List[Tuple[str, Pattern[str]]] = [
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("phone", re.compile(r"(?<!\d)(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}(?!\d)")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("credit_card", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
]

PII_PLACEHOLDER = "[REDACTED_PII]"


@dataclass
class PolicyConfig:
    """Tunables for the gate. Defaults are strict.

    ``pii_mode`` controls personal-data handling:

    * ``"reject"`` (default) — hard-fail any write containing PII-shaped content,
      matching the privacy doc's "PII must never be stored" rule;
    * ``"redact"`` — scrub matches to a placeholder and store the cleaned copy;
    * ``"off"`` — do not scan for PII.

    Size limits cap how much a single write can carry, so one oversized write
    cannot bloat the store or a rendered context block. ``0`` disables a limit.
    """

    require_source: bool = True
    scan_secrets: bool = True
    pii_mode: str = "reject"
    max_title_chars: int = 500
    max_body_chars: int = 20_000
    max_tags: int = 32
    max_tag_chars: int = 64

    def __post_init__(self) -> None:
        if self.pii_mode not in ("reject", "redact", "off"):
            raise ValueError("pii_mode must be 'reject', 'redact', or 'off'")


def _scan_for_secret(text: str) -> str | None:
    """Return the reason code of the first matching secret pattern, or None."""
    for reason, pattern in SECRET_PATTERNS:
        if pattern.search(text):
            return reason
    return None


def secret_reason(text: str) -> str | None:
    """Public helper for transports/audit logs that must avoid persisting secrets."""
    return _scan_for_secret(text or "")


def redact_if_secret(text: str) -> str:
    """Return a safe placeholder if ``text`` looks like a credential."""
    return "[REDACTED_SECRET]" if secret_reason(text) else (text or "")


def pii_reason(text: str) -> str | None:
    """Return the reason code of the first matching PII pattern, or None."""
    for reason, pattern in PII_PATTERNS:
        if pattern.search(text or ""):
            return reason
    return None


def redact_pii(text: str) -> str:
    """Scrub any PII-shaped substrings to a placeholder."""
    cleaned = text or ""
    for _reason, pattern in PII_PATTERNS:
        cleaned = pattern.sub(PII_PLACEHOLDER, cleaned)
    return cleaned


def _model_controlled_text(memory: Memory) -> Iterable[str]:
    """All text fields a model/user can supply through CLI or MCP."""
    yield memory.title
    yield memory.body
    yield memory.source.ref if memory.source else ""
    yield memory.source.note if memory.source and memory.source.note else ""
    yield " ".join(memory.tags)


def review(memory: Memory, config: PolicyConfig | None = None) -> Memory:
    """Validate a proposed memory. Returns the (possibly redacted) memory or raises.

    Hard fails raise ``PolicyError`` and the memory is never stored.
    """
    cfg = config or PolicyConfig()

    # 1. Source check. Provenance is mandatory.
    if cfg.require_source:
        if memory.source is None or not memory.source.is_usable:
            raise PolicyError(
                "missing_source",
                "memory rejected: a usable source reference is required",
            )

    # 2. Size limits. Reject oversized writes before scanning so a pathological
    #    input cannot drive the regex engine over a huge string.
    _enforce_size_limits(memory, cfg)

    # 3. Secret scan over every model-controlled field. Hard fail on any match.
    if cfg.scan_secrets:
        for text in _model_controlled_text(memory):
            reason = _scan_for_secret(text)
            if reason is not None:
                raise PolicyError(
                    "secret_detected",
                    f"memory rejected: content matched a secret pattern ({reason})",
                )

    # 4. PII handling — reject, redact, or ignore per config. Redaction always
    #    works on a copy so the caller's object is never mutated in place.
    if cfg.pii_mode == "reject":
        for text in _model_controlled_text(memory):
            reason = pii_reason(text)
            if reason is not None:
                raise PolicyError(
                    "pii_detected",
                    f"memory rejected: content matched a personal-data pattern ({reason})",
                )
    elif cfg.pii_mode == "redact":
        return _redact_pii_copy(memory)

    return memory


def _enforce_size_limits(memory: Memory, cfg: PolicyConfig) -> None:
    if cfg.max_title_chars and len(memory.title) > cfg.max_title_chars:
        raise PolicyError("title_too_long",
                          f"memory rejected: title exceeds {cfg.max_title_chars} chars")
    if cfg.max_body_chars and len(memory.body) > cfg.max_body_chars:
        raise PolicyError("body_too_long",
                          f"memory rejected: body exceeds {cfg.max_body_chars} chars")
    if cfg.max_tags and len(memory.tags) > cfg.max_tags:
        raise PolicyError("too_many_tags",
                          f"memory rejected: more than {cfg.max_tags} tags")
    if cfg.max_tag_chars:
        for tag in memory.tags:
            if len(tag) > cfg.max_tag_chars:
                raise PolicyError("tag_too_long",
                                  f"memory rejected: a tag exceeds {cfg.max_tag_chars} chars")


def _redact_pii_copy(memory: Memory) -> Memory:
    """Return a copy of ``memory`` with PII scrubbed from every text field."""
    note = memory.source.note
    cleaned_source = Source(
        kind=memory.source.kind,
        ref=redact_pii(memory.source.ref),
        note=redact_pii(note) if note else note,
    )
    return replace(
        memory,
        title=redact_pii(memory.title),
        body=redact_pii(memory.body),
        source=cleaned_source,
        tags=[redact_pii(t) for t in memory.tags],
    )
