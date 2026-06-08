"""File-backed, dependency-free persistence for the memory fabric.

``JsonlStore`` is a drop-in :class:`~memory_unlocked.store.MemoryStore` that
durably persists to a local directory using two append-only JSON Lines logs:

    <path>/memories.jsonl   one accepted memory per line
    <path>/events.jsonl     one audit event per line (write / recall / reject)

Append-only logs are the simplest design that is also crash-resilient: a write
is a single ``append`` of one line, and a truncated or corrupt trailing line is
skipped on load rather than poisoning the whole store. Memory Unlocked stores
*durable facts*, not high-volume logs, so replaying the log on open is cheap.

The class only overrides the two persistence hooks on the base store, so every
scope/policy guarantee — the gate, the id assignment, the scope index — is
inherited unchanged.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import Event, Memory, Namespace
from .policy import PolicyConfig, PolicyError
from .serialize import (
    event_from_dict,
    event_to_dict,
    memory_from_dict,
    memory_to_dict,
)
from .store import MemoryStore

EXPORT_VERSION = 1


def atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically (temp file + ``os.replace``)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)  # atomic on POSIX and Windows


class JsonlStore(MemoryStore):
    """A ``MemoryStore`` that persists to append-only JSONL files."""

    def __init__(
        self,
        path,
        policy: Optional[PolicyConfig] = None,
        clock=None,
    ) -> None:
        super().__init__(policy=policy, clock=clock)
        self._path = Path(path)
        self._memories_file = self._path / "memories.jsonl"
        self._events_file = self._path / "events.jsonl"
        self._path.mkdir(parents=True, exist_ok=True)
        self._load()

    @property
    def path(self) -> Path:
        return self._path

    # --- Loading -------------------------------------------------------------

    def _load(self) -> None:
        """Replay the on-disk logs into the in-memory indices.

        Bypasses the persistence hooks so loading never re-writes to disk.
        Corrupt or partial lines are skipped, not fatal.
        """
        for record in self._read_jsonl(self._memories_file):
            try:
                memory = memory_from_dict(record)
            except (KeyError, ValueError, TypeError):
                continue
            if not memory.id:
                continue
            self._by_id[memory.id] = memory
            self._by_ns.setdefault(memory.namespace.as_key(), []).append(memory.id)

        for record in self._read_jsonl(self._events_file):
            try:
                self._events.append(event_from_dict(record))
            except (KeyError, ValueError, TypeError):
                continue

    @staticmethod
    def _read_jsonl(file: Path) -> List[Dict[str, Any]]:
        if not file.exists():
            return []
        records: List[Dict[str, Any]] = []
        with file.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    # Tolerate a corrupt/partial trailing line from a crash.
                    continue
        return records

    # --- Persistence hooks (override base no-ops) ----------------------------

    def _persist_memory(self, memory: Memory) -> None:
        self._append_jsonl(self._memories_file, memory_to_dict(memory))

    def _emit(self, event: Event) -> None:
        super()._emit(event)  # keep the in-memory log in sync
        self._append_jsonl(self._events_file, event_to_dict(event))

    @staticmethod
    def _append_jsonl(file: Path, record: Dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        with file.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())

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
        by this store, so imports merge rather than overwrite.
        """
        imported = 0
        rejected = 0
        for record in data.get("memories", []):
            try:
                candidate = memory_from_dict(record)
            except (KeyError, ValueError, TypeError):
                rejected += 1
                continue
            # Drop store-owned fields so this store assigns fresh ones.
            candidate.id = None
            candidate.created_at = None
            try:
                self.add(candidate)
                imported += 1
            except PolicyError:
                rejected += 1
        return {"imported": imported, "rejected": rejected}
