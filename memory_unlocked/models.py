"""Canonical data models for Memory Unlocked.

These mirror docs/schema.md. They are plain dataclasses with no external
dependencies so they are trivial to read, test, and port.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


# Allowed enumerations. Kept as simple tuples to avoid importing Enum machinery
# and to keep validation explicit and easy to extend.
MEMORY_KINDS = ("fact", "decision", "convention", "reference")
SOURCE_KINDS = ("doc", "url", "ticket", "commit", "run", "message")
LINK_RELATIONS = ("relates_to", "supersedes", "contradicts", "derived_from")
EVENT_TYPES = (
    "memory.write",
    "memory.recall",
    "memory.reject",
    "memory.update",
    "memory.forget",
)

# Lifecycle states. A memory starts life as either a reviewed ``active`` fact or
# an unreviewed ``candidate``, and can later be ``archived`` (kept for audit but
# excluded from recall) or ``rejected`` (kept as a tombstone of a bad write).
MEMORY_STATUSES = ("candidate", "active", "archived", "rejected")
DEFAULT_STATUS = "active"
# Statuses that the recall/context path surfaces to a model by default.
RECALL_STATUSES = ("active",)


@dataclass(frozen=True)
class Namespace:
    """A `(tenant, project)` scope attached to every memory.

    Frozen so it is hashable and safe to use as a dict key / set member.
    """

    tenant: str
    project: str

    def __post_init__(self) -> None:
        if not self.tenant or not self.tenant.strip():
            raise ValueError("namespace.tenant must be non-empty")
        if not self.project or not self.project.strip():
            raise ValueError("namespace.project must be non-empty")

    def as_key(self) -> str:
        """Serialized form used for scope matching and event logs."""
        return f"{self.tenant}/{self.project}"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.as_key()


@dataclass(frozen=True)
class Source:
    """Provenance for a memory. Mandatory; a memory with no source is rejected."""

    kind: str
    ref: str
    note: Optional[str] = None

    def __post_init__(self) -> None:
        if self.kind not in SOURCE_KINDS:
            raise ValueError(f"source.kind must be one of {SOURCE_KINDS}")
        if not self.ref or not self.ref.strip():
            raise ValueError("source.ref must be non-empty")

    @property
    def is_usable(self) -> bool:
        return bool(self.ref and self.ref.strip())


@dataclass(frozen=True)
class Link:
    """A typed relation between two memories within a namespace."""

    rel: str
    target_id: str

    def __post_init__(self) -> None:
        if self.rel not in LINK_RELATIONS:
            raise ValueError(f"link.rel must be one of {LINK_RELATIONS}")
        if not self.target_id:
            raise ValueError("link.target_id must be non-empty")


@dataclass
class Memory:
    """One atomic, durable fact with provenance and scope."""

    namespace: Namespace
    title: str
    body: str
    source: Source
    kind: str = "fact"
    tags: List[str] = field(default_factory=list)
    links: List[Link] = field(default_factory=list)
    confidence: float = 1.0
    status: str = DEFAULT_STATUS
    # Assigned by the store on write; None until then.
    id: Optional[str] = None
    created_at: Optional[str] = None
    # Updated by the store on any lifecycle change (status/confidence). None
    # until the first mutation; serializers default it to ``created_at``.
    updated_at: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.title or not self.title.strip():
            raise ValueError("memory.title must be non-empty")
        if not self.body or not self.body.strip():
            raise ValueError("memory.body must be non-empty")
        if self.kind not in MEMORY_KINDS:
            raise ValueError(f"memory.kind must be one of {MEMORY_KINDS}")
        if self.status not in MEMORY_STATUSES:
            raise ValueError(f"memory.status must be one of {MEMORY_STATUSES}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("memory.confidence must be in [0, 1]")
        # Normalize tags to lowercase, de-duplicated, order-preserving.
        seen: set = set()
        normalized: List[str] = []
        for tag in self.tags:
            key = tag.strip().lower()
            if key and key not in seen:
                seen.add(key)
                normalized.append(key)
        self.tags = normalized


@dataclass
class Event:
    """Append-only audit record. Never contains secret values."""

    type: str
    namespace: Namespace
    at: str
    detail: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.type not in EVENT_TYPES:
            raise ValueError(f"event.type must be one of {EVENT_TYPES}")
