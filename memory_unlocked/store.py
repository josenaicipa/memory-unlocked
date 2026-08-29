"""In-memory reference store with scope enforcement and an event log.

This is intentionally simple and dependency-free. Durable backends
(:class:`~memory_unlocked.persistence.JsonlStore`,
:class:`~memory_unlocked.sqlite_store.SqliteStore`) subclass this and override
only the persistence hooks, so the scope/policy/lifecycle control flow lives in
exactly one place and a storage bug can never widen scope.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .models import Event, Memory, Namespace
from .policy import PolicyConfig, PolicyError, redact_if_secret, review
from .serialize import event_to_dict, memory_from_dict, memory_to_dict
from .thread_scope import admits_thread, normalize_thread

EXPORT_VERSION = 1


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
    def open(cls, path: str, backend: str = "jsonl", **kwargs) -> "MemoryStore":
        """Open a durable, file-backed store at ``path``.

        ``backend`` selects the on-disk format: ``"jsonl"`` (default,
        append-only JSON Lines) or ``"sqlite"`` (a single local SQLite file).
        Both share this class's surface and the same scope/policy guarantees.
        Imported lazily to keep this module free of a persistence dependency.
        """
        if backend == "sqlite":
            from .sqlite_store import SqliteStore

            return SqliteStore(path, **kwargs)
        if backend == "jsonl":
            from .persistence import JsonlStore

            return JsonlStore(path, **kwargs)
        raise ValueError(f"unknown backend: {backend!r} (use 'jsonl' or 'sqlite')")

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
        reviewed.updated_at = reviewed.created_at

        self._index(reviewed)
        self._persist_memory(reviewed)

        self._emit(Event(
            type="memory.write",
            namespace=reviewed.namespace,
            at=reviewed.created_at,
            detail={"id": reviewed.id, "title": reviewed.title, "status": reviewed.status},
        ))
        return reviewed

    def _index(self, memory: Memory) -> None:
        """Insert/refresh a memory in the in-memory indices (no double-add)."""
        self._by_id[memory.id] = memory
        ids = self._by_ns.setdefault(memory.namespace.as_key(), [])
        if memory.id not in ids:
            ids.append(memory.id)

    # --- Persistence hooks ---------------------------------------------------
    # No-ops in the in-memory store. Durable backends override these. Keeping the
    # add/query/lifecycle control flow here means the scope/policy invariants
    # live in exactly one place.

    def _emit(self, event: Event) -> None:
        """Record an event. Override to also persist it."""
        self._events.append(event)

    def _persist_memory(self, memory: Memory) -> None:
        """Called after a memory is accepted and indexed. Override to persist."""

    def _persist_update(self, memory: Memory) -> None:
        """Called after an in-place lifecycle change. Override to persist."""

    def _persist_forget(self, memory: Memory) -> None:
        """Called after a memory is removed. Override to persist the removal."""

    # --- Read ----------------------------------------------------------------

    def query(
        self,
        namespace: Namespace,
        text: Optional[str] = None,
        statuses: Optional[Sequence[str]] = None,
        match: bool = True,
        thread: Optional[str] = None,
        thread_mode: Optional[str] = None,
        include_expired: bool = False,
        now: Optional[str] = None,
    ) -> List[Memory]:
        """Return memories in ``namespace`` only.

        Scope is enforced first and unconditionally: tenant/project exact match,
        then the thread predicate, then expiry. Ranking never sees a row these
        filters excluded. ``statuses`` optionally restricts to a set of
        lifecycle states (``None`` = every status). ``match`` toggles the
        simple case-insensitive substring filter: callers that do their own
        ranking (the assembler) pass ``match=False`` to get the full in-scope
        set while still recording the recall in the audit log.
        """
        ids = self._by_ns.get(namespace.as_key(), [])
        # Defense in depth: re-check each object's namespace even though the
        # index is keyed by it, so a corrupt index can never leak scope.
        in_scope = [self._by_id[i] for i in ids if self._by_id[i].namespace == namespace]
        requested_thread = normalize_thread(thread)
        in_scope = [
            m for m in in_scope
            if admits_thread(m.thread, requested_thread, thread_mode)
        ]
        if statuses is not None:
            allowed = set(statuses)
            in_scope = [m for m in in_scope if m.status in allowed]
        if not include_expired:
            cutoff = now or self._clock()
            in_scope = [
                m for m in in_scope
                if not m.expires_at or m.expires_at > cutoff
            ]

        self._emit(Event(
            type="memory.recall",
            namespace=namespace,
            at=self._clock(),
            detail={
                "query": redact_if_secret(text or ""),
                "scope_size": len(in_scope),
                "thread": requested_thread,
            },
        ))

        if not text or not match:
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

    def get(self, memory_id: str) -> Optional[Memory]:
        """Return a memory by id, or None. Not scope-filtered (admin/lifecycle)."""
        return self._by_id.get(memory_id)

    def all(self) -> Iterable[Memory]:
        """Every memory, across all scopes. For admin/audit/export use only."""
        return list(self._by_id.values())

    def events(self) -> List[Event]:
        """The append-only event log."""
        return list(self._events)

    # --- Lifecycle / governance ----------------------------------------------

    def set_status(self, memory_id: str, status: str) -> Memory:
        """Transition a memory to a new lifecycle ``status`` and audit it."""
        from .models import MEMORY_STATUSES

        if status not in MEMORY_STATUSES:
            raise ValueError(f"status must be one of {MEMORY_STATUSES}")
        memory = self._require(memory_id)
        previous = memory.status
        memory.status = status
        memory.updated_at = self._clock()
        self._persist_update(memory)
        self._emit(Event(
            type="memory.update",
            namespace=memory.namespace,
            at=memory.updated_at,
            detail={"id": memory.id, "from": previous, "to": status, "field": "status"},
        ))
        return memory

    def promote(self, memory_id: str) -> Memory:
        """Mark a memory ``active`` (the recall-visible state)."""
        return self.set_status(memory_id, "active")

    def archive(self, memory_id: str) -> Memory:
        """Mark a memory ``archived`` (kept for audit, excluded from recall)."""
        return self.set_status(memory_id, "archived")

    def reject(self, memory_id: str) -> Memory:
        """Mark a memory ``rejected`` (kept as a tombstone of a bad write)."""
        return self.set_status(memory_id, "rejected")

    def set_confidence(self, memory_id: str, confidence: float) -> Memory:
        """Update the confidence of a memory and audit it."""
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        memory = self._require(memory_id)
        previous = memory.confidence
        memory.confidence = confidence
        memory.updated_at = self._clock()
        self._persist_update(memory)
        self._emit(Event(
            type="memory.update",
            namespace=memory.namespace,
            at=memory.updated_at,
            detail={"id": memory.id, "from": previous, "to": confidence, "field": "confidence"},
        ))
        return memory

    def forget(self, memory_id: str) -> bool:
        """Permanently remove a memory. Returns False if it did not exist."""
        memory = self._by_id.get(memory_id)
        if memory is None:
            return False
        del self._by_id[memory_id]
        ids = self._by_ns.get(memory.namespace.as_key(), [])
        if memory_id in ids:
            ids.remove(memory_id)
        self._persist_forget(memory)
        self._emit(Event(
            type="memory.forget",
            namespace=memory.namespace,
            at=self._clock(),
            detail={"id": memory_id},
        ))
        return True

    def _require(self, memory_id: str) -> Memory:
        memory = self._by_id.get(memory_id)
        if memory is None:
            raise KeyError(f"no such memory: {memory_id}")
        return memory

    # --- Export / import -----------------------------------------------------

    def export(self, namespace: Optional[Namespace] = None) -> Dict[str, Any]:
        """Return a JSON-safe export document for all scopes or one namespace."""
        memories = [
            m for m in self.all()
            if namespace is None or m.namespace == namespace
        ]
        events = [
            e for e in self.events()
            if namespace is None or e.namespace == namespace
        ]
        return {
            "version": EXPORT_VERSION,
            "memories": [memory_to_dict(m) for m in memories],
            "events": [event_to_dict(e) for e in events],
        }

    def import_memories(self, data: Dict[str, Any]) -> Dict[str, int]:
        """Import memories from an export document, re-running the policy gate.

        Importing never bypasses the gate: a secret-bearing record in an
        untrusted export is rejected just like a live write. Ids are reassigned
        by this store, so imports merge rather than overwrite. The original
        ``status`` is preserved so an exported ``archived``/``candidate`` memory
        keeps its lifecycle state.
        """
        imported = 0
        rejected = 0
        for record in data.get("memories", []):
            try:
                candidate = memory_from_dict(record)
            except (KeyError, ValueError, TypeError):
                rejected += 1
                continue
            status = candidate.status
            # Drop store-owned fields so this store assigns fresh ones.
            candidate.id = None
            candidate.created_at = None
            candidate.updated_at = None
            try:
                stored = self.add(candidate)
                if status != stored.status:
                    self.set_status(stored.id, status)
                imported += 1
            except PolicyError:
                rejected += 1
        return {"imported": imported, "rejected": rejected}
