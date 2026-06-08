"""In-memory reference store with scope enforcement and an event log.

This is intentionally simple and dependency-free. For production, implement the
same surface (``add``, ``query``, ``all``, ``events``) against a real backend and
keep the scope-filter-inside-the-query invariant.
"""

from __future__ import annotations

import itertools
from typing import Dict, Iterable, List, Optional

from .models import Event, Memory, Namespace
from .policy import PolicyConfig, PolicyError, review


class MemoryStore:
    """Scope-isolated memory store.

    Invariant: ``query`` returns only memories whose namespace matches exactly.
    Scope filtering happens here, before any ranking, so a ranking bug can never
    widen scope.
    """

    def __init__(self, policy: Optional[PolicyConfig] = None, clock=None) -> None:
        self._by_id: Dict[str, Memory] = {}
        # namespace key -> list of memory ids, preserving insertion order.
        self._by_ns: Dict[str, List[str]] = {}
        self._events: List[Event] = []
        self._ids = itertools.count(1)
        self._policy = policy or PolicyConfig()
        # Injectable clock so tests are deterministic and we avoid wall-clock
        # calls inside the library. Returns an ISO-8601 string.
        self._clock = clock or (lambda: "1970-01-01T00:00:00Z")

    @classmethod
    def open(cls, path: str, **kwargs) -> "MemoryStore":  # pragma: no cover
        """Placeholder for a persistent backend.

        The reference implementation is in-memory only; ``path`` is accepted so
        downstream code can switch to a durable store without changing call
        sites. Adapt this to load/save from ``path`` in your own backend.
        """
        return cls(**kwargs)

    def add(self, memory: Memory) -> Memory:
        """Run the policy gate, assign an id, store, and emit an event.

        Raises ``PolicyError`` (and stores nothing) if the write is rejected.
        """
        try:
            reviewed = review(memory, self._policy)
        except PolicyError as exc:
            # Audit the rejection without ever recording the offending content.
            self._events.append(Event(
                type="memory.reject",
                namespace=memory.namespace,
                at=self._clock(),
                detail={"reason": exc.reason},
            ))
            raise

        reviewed.id = f"mem_{next(self._ids):04d}"
        reviewed.created_at = self._clock()

        self._by_id[reviewed.id] = reviewed
        self._by_ns.setdefault(reviewed.namespace.as_key(), []).append(reviewed.id)

        self._events.append(Event(
            type="memory.write",
            namespace=reviewed.namespace,
            at=reviewed.created_at,
            detail={"id": reviewed.id, "title": reviewed.title},
        ))
        return reviewed

    def query(self, namespace: Namespace, text: Optional[str] = None) -> List[Memory]:
        """Return memories in ``namespace`` only, optionally text-filtered.

        Scope is enforced first and unconditionally. Text matching is a simple
        case-insensitive substring/tag check on the in-scope set.
        """
        ids = self._by_ns.get(namespace.as_key(), [])
        in_scope = [self._by_id[i] for i in ids]

        self._events.append(Event(
            type="memory.recall",
            namespace=namespace,
            at=self._clock(),
            detail={"query": text or "", "scope_size": len(in_scope)},
        ))

        if not text:
            return list(in_scope)

        needle = text.lower()
        return [m for m in in_scope if self._matches(m, needle)]

    @staticmethod
    def _matches(memory: Memory, needle: str) -> bool:
        if needle in memory.title.lower():
            return True
        if needle in memory.body.lower():
            return True
        return any(needle in tag for tag in memory.tags)

    def all(self) -> Iterable[Memory]:
        """Every memory, across all scopes. For admin/audit/export use only."""
        return list(self._by_id.values())

    def events(self) -> List[Event]:
        """The append-only event log."""
        return list(self._events)
