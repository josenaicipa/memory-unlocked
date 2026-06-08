"""File-backed, dependency-free persistence for the memory fabric.

``JsonlStore`` is a drop-in :class:`~memory_unlocked.store.MemoryStore` that
durably persists to a local directory using two append-only JSON Lines logs:

    <path>/memories.jsonl   one record per write or lifecycle change
    <path>/events.jsonl     one audit event per line (write / recall / update / …)

Append-only logs are the simplest design that is also crash-resilient: a write
is a single ``append`` of one line, and a truncated or corrupt trailing line is
skipped on load rather than poisoning the whole store. Lifecycle changes are not
in-place edits — they are *new* records for the same id, and load applies
last-write-wins. A removal is a tombstone record. Memory Unlocked stores durable
facts, not high-volume logs, so replaying the log on open is cheap.

The class only overrides the persistence hooks on the base store, so every
scope/policy/lifecycle guarantee is inherited unchanged.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import Event, Memory
from .policy import PolicyConfig
from .serialize import event_from_dict, event_to_dict, memory_from_dict, memory_to_dict
from .store import MemoryStore

# Sentinel key marking a tombstone line: ``{"_forget": "<id>"}``.
FORGET_KEY = "_forget"


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

    def __init__(self, path, policy: Optional[PolicyConfig] = None, clock=None) -> None:
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

        Memory records are applied last-write-wins per id; a ``_forget``
        tombstone drops the id. Bypasses the persistence hooks so loading never
        re-writes to disk. Corrupt or partial lines are skipped, not fatal.
        """
        latest: Dict[str, Memory] = {}
        order: List[str] = []
        for record in self._read_jsonl(self._memories_file):
            forget_id = record.get(FORGET_KEY)
            if forget_id is not None:
                latest.pop(forget_id, None)
                continue
            try:
                memory = memory_from_dict(record)
            except (KeyError, ValueError, TypeError):
                continue
            if not memory.id:
                continue
            if memory.id not in latest:
                order.append(memory.id)
            latest[memory.id] = memory

        for memory_id in order:
            memory = latest.get(memory_id)
            if memory is not None:
                self._index(memory)

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

    def _persist_update(self, memory: Memory) -> None:
        # A lifecycle change is a new record for the same id; load resolves it
        # last-write-wins. Append-only keeps the full history for audit.
        self._append_jsonl(self._memories_file, memory_to_dict(memory))

    def _persist_forget(self, memory: Memory) -> None:
        self._append_jsonl(self._memories_file, {FORGET_KEY: memory.id})

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
