"""In-memory reference store with scope enforcement and an event log.

This is intentionally simple and dependency-free. For production, implement the
same surface (``add``, ``query``, ``all``, ``events``) against a real backend and
keep the scope-filter-inside-the-query invariant.
"""

from __future__ import annotations

import uuid
from typing import Dict, Iterable, List, Optional

from .models import Event, Memory, Namespace
from .policy import PolicyConfig, PolicyError, redact_if_secret, review


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
        self._policy = policy or PolicyConfig()
        # Injectable clock so tests are deterministic and we avoid wall-clock
        # calls inside the library. Returns an ISO-8601 string.
        self._clock = clock or (lambda: "1970-01-01T00:00:00Z")

    @classmethod
    def open(cls, path: str, **kwargs) -> "MemoryStore":
        """Open a durable, file-backed store at ``path``.

        Returns a :class:`~memory_unlocked.persistence.JsonlStore`, which shares
        this class's surface (``add``, ``query``, ``all``, ``events``) and the
        same scope/policy guarantees, but persists to disk. Imported lazily to
        keep this module free of a persistence dependency.
        """
        from .persistence import JsonlStore

        return JsonlStore(path, **kwargs)

    def add(self, memory: Memory) -> Memory:
        """Run the policy gate, assign an id, store, and emit an event.

        Raises ``PolicyError`` (and stores nothing) if the write is rejected.
        """
        try:
            reviewed = review(memory, self._policy)
        except PolicyError as exc:
            # Audit the rejection without ever recording the offending content.
            self._emit(Event(
                type="memory.reject",
                namespace=memory.namespace,
                at=self._clock(),
                detail={"reason": exc.reason},
            ))
            raise

        reviewed.id = f"mem_{uuid.uuid4().hex}"
        reviewed.created_at = self._clock()

        self._by_id[reviewed.id] = reviewed
        self._by_ns.setdefault(reviewed.namespace.as_key(), []).append(reviewed.id)
        self._persist_memory(reviewed)

        self._emit(Event(
            type="memory.write",
            namespace=reviewed.namespace,
            at=reviewed.created_at,
            detail={"id": reviewed.id, "title": reviewed.title},
        ))
        return reviewed

    # --- Persistence hooks ---------------------------------------------------
    # No-ops in the in-memory store. A durable backend overrides these to write
    # to its storage. Keeping them here means the add/query control flow — and
    # therefore the scope/policy invariants — lives in exactly one place.

    def _emit(self, event: Event) -> None:
        """Record an event. Override to also persist it."""
        self._events.append(event)

    def _persist_memory(self, memory: Memory) -> None:
        """Called after a memory is accepted and indexed. Override to persist."""

    def query(self, namespace: Namespace, text: Optional[str] = None) -> List[Memory]:
        """Return memories in ``namespace`` only, optionally text-filtered.

        Scope is enforced first and unconditionally. Text matching is a simple
        case-insensitive substring/tag check on the in-scope set.
        """
        ids = self._by_ns.get(namespace.as_key(), [])
        # Defense in depth: even if a malformed/colliding persisted index ever
        # points at the wrong object, query re-checks the object's namespace.
        in_scope = [self._by_id[i] for i in ids if self._by_id[i].namespace == namespace]

        self._emit(Event(
            type="memory.recall",
            namespace=namespace,
            at=self._clock(),
            detail={"query": redact_if_secret(text or ""), "scope_size": len(in_scope)},
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
