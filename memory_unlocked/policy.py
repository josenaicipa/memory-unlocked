"""The policy gate: the security-critical write filter.

Every write passes through ``review`` before it is stored. The gate has two
hard-fail checks (secrets, missing source) and an optional soft-redaction pass.

The patterns here are a sensible floor, not a complete DLP solution. Extend
``SECRET_PATTERNS`` for your domain. The goal is to make the *common, dangerous*
mistakes impossible by default.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Pattern

from .models import Memory


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


@dataclass
class PolicyConfig:
    """Tunables for the gate. Defaults are strict."""

    require_source: bool = True
    scan_secrets: bool = True


def _scan_for_secret(text: str) -> str | None:
    """Return the reason code of the first matching secret pattern, or None."""
    for reason, pattern in SECRET_PATTERNS:
        if pattern.search(text):
            return reason
    return None


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

    # 2. Secret scan over title + body. Hard fail on any match.
    if cfg.scan_secrets:
        haystacks = (memory.title, memory.body)
        for text in haystacks:
            reason = _scan_for_secret(text)
            if reason is not None:
                raise PolicyError(
                    "secret_detected",
                    f"memory rejected: content matched a secret pattern ({reason})",
                )

    # 3. (Soft redaction hook) — by default nothing is scrubbed because hard
    #    fails already removed the dangerous cases. Implementations that prefer
    #    redaction over rejection for borderline content can do it here, working
    #    on a copy so the caller's object is never mutated in place.

    return memory
