"""SQLite-backed store — a single local file, no external database required.

``SqliteStore`` is a drop-in :class:`~memory_unlocked.store.MemoryStore` backed
by one SQLite file (``<path>/memory.db`` by default). It uses only the standard
library ``sqlite3`` module, so there is no server to run and no dependency to
install.

Like :class:`~memory_unlocked.persistence.JsonlStore`, it mirrors state in
memory on open and uses the database purely for durability, overriding only the
persistence hooks. This keeps the scope/policy/lifecycle control flow — and
therefore every safety invariant — in the base class, identical across backends.
Namespace isolation, export/import parity, the policy gate, and the audit log
all behave exactly the same as the JSONL backend.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

from .models import Event, Link, Memory, Namespace, Source
from .policy import PolicyConfig
from .store import MemoryStore

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id          TEXT PRIMARY KEY,
    tenant      TEXT NOT NULL,
    project     TEXT NOT NULL,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    kind        TEXT NOT NULL,
    tags        TEXT NOT NULL,        -- JSON array
    source      TEXT NOT NULL,        -- JSON object
    links       TEXT NOT NULL,        -- JSON array
    confidence  REAL NOT NULL,
    status      TEXT NOT NULL,
    created_at  TEXT,
    updated_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories (tenant, project);
CREATE TABLE IF NOT EXISTS events (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT NOT NULL,
    tenant      TEXT NOT NULL,
    project     TEXT NOT NULL,
    at          TEXT NOT NULL,
    detail      TEXT NOT NULL         -- JSON object
);
"""


class SqliteStore(MemoryStore):
    """A ``MemoryStore`` that persists to a local SQLite file."""

    def __init__(self, path, policy: Optional[PolicyConfig] = None, clock=None) -> None:
        super().__init__(policy=policy, clock=clock)
        self._path = Path(path)
        # Accept either a directory (use memory.db inside it) or a .db file path.
        if self._path.suffix == ".db":
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._db_file = self._path
        else:
            self._path.mkdir(parents=True, exist_ok=True)
            self._db_file = self._path / "memory.db"
        self._conn = sqlite3.connect(str(self._db_file))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._load()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def db_file(self) -> Path:
        return self._db_file

    def close(self) -> None:
        self._conn.close()

    # --- Loading -------------------------------------------------------------

    def _load(self) -> None:
        for row in self._conn.execute(
            "SELECT * FROM memories ORDER BY rowid ASC"
        ):
            try:
                memory = self._row_to_memory(row)
            except (KeyError, ValueError, TypeError):
                continue
            self._index(memory)
        for row in self._conn.execute("SELECT * FROM events ORDER BY seq ASC"):
            self._events.append(Event(
                type=row["type"],
                namespace=Namespace(tenant=row["tenant"], project=row["project"]),
                at=row["at"],
                detail=json.loads(row["detail"]),
            ))

    @staticmethod
    def _row_to_memory(row: sqlite3.Row) -> Memory:
        source = json.loads(row["source"])
        memory = Memory(
            namespace=Namespace(tenant=row["tenant"], project=row["project"]),
            title=row["title"],
            body=row["body"],
            source=Source(kind=source["kind"], ref=source["ref"], note=source.get("note")),
            kind=row["kind"],
            tags=list(json.loads(row["tags"])),
            links=[
                Link(rel=link["rel"], target_id=link["target_id"])
                for link in json.loads(row["links"])
            ],
            confidence=row["confidence"],
            status=row["status"],
        )
        memory.id = row["id"]
        memory.created_at = row["created_at"]
        memory.updated_at = row["updated_at"] or row["created_at"]
        return memory

    # --- Persistence hooks (override base no-ops) ----------------------------

    def _persist_memory(self, memory: Memory) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO memories "
            "(id, tenant, project, title, body, kind, tags, source, links, "
            " confidence, status, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                memory.id,
                memory.namespace.tenant,
                memory.namespace.project,
                memory.title,
                memory.body,
                memory.kind,
                json.dumps(list(memory.tags)),
                json.dumps({
                    "kind": memory.source.kind,
                    "ref": memory.source.ref,
                    "note": memory.source.note,
                }),
                json.dumps(
                    [{"rel": link.rel, "target_id": link.target_id} for link in memory.links]
                ),
                memory.confidence,
                memory.status,
                memory.created_at,
                memory.updated_at,
            ),
        )
        self._conn.commit()

    def _persist_update(self, memory: Memory) -> None:
        self._conn.execute(
            "UPDATE memories SET status = ?, confidence = ?, updated_at = ? WHERE id = ?",
            (memory.status, memory.confidence, memory.updated_at, memory.id),
        )
        self._conn.commit()

    def _persist_forget(self, memory: Memory) -> None:
        self._conn.execute("DELETE FROM memories WHERE id = ?", (memory.id,))
        self._conn.commit()

    def _emit(self, event: Event) -> None:
        super()._emit(event)  # keep the in-memory log in sync
        self._conn.execute(
            "INSERT INTO events (type, tenant, project, at, detail) VALUES (?,?,?,?,?)",
            (
                event.type,
                event.namespace.tenant,
                event.namespace.project,
                event.at,
                json.dumps(event.detail, sort_keys=True),
            ),
        )
        self._conn.commit()
