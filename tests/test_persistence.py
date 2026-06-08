"""Persistence tests for the file-backed JsonlStore."""

import itertools

import pytest

from memory_unlocked import Memory, Namespace, PolicyError, Source
from memory_unlocked.persistence import JsonlStore

NS = Namespace("acme", "billing")
OTHER = Namespace("globex", "docs")


def _clock():
    counter = itertools.count(0)
    return lambda: f"2026-01-01T00:00:{next(counter):02d}Z"


def _mem(ns: Namespace, title: str, body: str) -> Memory:
    return Memory(namespace=ns, title=title, body=body,
                  source=Source(kind="doc", ref="docs/x.md"))


def test_write_then_reload_from_disk(tmp_path):
    store = JsonlStore(tmp_path, clock=_clock())
    store.add(_mem(NS, "first fact", "bodies are durable"))
    store.add(_mem(NS, "second fact", "and they persist"))

    # A brand new store instance pointed at the same path sees the data.
    reopened = JsonlStore(tmp_path)
    titles = sorted(m.title for m in reopened.query(NS))
    assert titles == ["first fact", "second fact"]


def test_reload_preserves_unique_ids(tmp_path):
    store = JsonlStore(tmp_path, clock=_clock())
    first = store.add(_mem(NS, "a", "one"))
    assert first.id.startswith("mem_")

    reopened = JsonlStore(tmp_path, clock=_clock())
    # New writes must not collide with restored ids.
    third = reopened.add(_mem(NS, "b", "two"))
    assert third.id != first.id
    assert len(reopened.all()) == 2


def test_scope_isolation_survives_reload(tmp_path):
    store = JsonlStore(tmp_path, clock=_clock())
    store.add(_mem(NS, "acme fact", "acme only"))
    store.add(_mem(OTHER, "globex fact", "globex only"))

    reopened = JsonlStore(tmp_path)
    assert [m.title for m in reopened.query(NS)] == ["acme fact"]
    assert [m.title for m in reopened.query(OTHER)] == ["globex fact"]



def test_parallel_store_id_collision_cannot_leak_across_namespace_after_reload(tmp_path):
    """Two MCP servers can share one HOME without ID collision causing scope bleed."""
    a = JsonlStore(tmp_path, clock=_clock())
    b = JsonlStore(tmp_path, clock=_clock())
    acme = a.add(_mem(NS, "acme fact", "acme only content"))
    globex = b.add(_mem(OTHER, "globex fact", "globex only content"))
    assert acme.id != globex.id

    reopened = JsonlStore(tmp_path)
    assert [m.title for m in reopened.query(NS)] == ["acme fact"]
    assert [m.title for m in reopened.query(OTHER)] == ["globex fact"]
    assert "globex only content" not in [m.body for m in reopened.query(NS)]


def test_recall_event_redacts_secret_shaped_query(tmp_path):
    store = JsonlStore(tmp_path, clock=_clock())
    store.add(_mem(NS, "safe", "content"))
    store.query(NS, text="password=supersecretvalue")
    log = (tmp_path / "events.jsonl").read_text()
    assert "supersecretvalue" not in log
    assert "[REDACTED_SECRET]" in log


def test_events_are_persisted(tmp_path):
    store = JsonlStore(tmp_path, clock=_clock())
    store.add(_mem(NS, "a", "one"))
    store.query(NS)  # emits a recall event

    reopened = JsonlStore(tmp_path)
    types = [e.type for e in reopened.events()]
    assert "memory.write" in types
    assert "memory.recall" in types


def test_policy_gate_still_enforced(tmp_path):
    store = JsonlStore(tmp_path, clock=_clock())
    bad = Memory(namespace=NS, title="leak",
                 body="password = supersecretvalue",
                 source=Source(kind="doc", ref="x"))
    with pytest.raises(PolicyError):
        store.add(bad)

    # Nothing leaked to disk, and the reject was audited without the secret.
    reopened = JsonlStore(tmp_path)
    assert reopened.all() == []
    reject = [e for e in reopened.events() if e.type == "memory.reject"]
    assert reject and reject[0].detail == {"reason": "secret_detected"}
    assert "supersecretvalue" not in (tmp_path / "events.jsonl").read_text()


def test_corrupt_line_is_skipped_not_fatal(tmp_path):
    store = JsonlStore(tmp_path, clock=_clock())
    store.add(_mem(NS, "good", "valid memory"))
    # Append a junk line to the memories log.
    with (tmp_path / "memories.jsonl").open("a") as fh:
        fh.write("{ this is not valid json\n")

    reopened = JsonlStore(tmp_path)  # must not raise
    assert [m.title for m in reopened.query(NS)] == ["good"]


def test_export_then_import_into_fresh_store(tmp_path):
    src = JsonlStore(tmp_path / "a", clock=_clock())
    src.add(_mem(NS, "exported fact", "round trip me"))
    export = src.export()
    assert export["memories"][0]["title"] == "exported fact"

    dst = JsonlStore(tmp_path / "b", clock=_clock())
    result = dst.import_memories(export)
    assert result["imported"] == 1
    assert [m.title for m in dst.query(NS)] == ["exported fact"]


def test_import_re_enforces_policy(tmp_path):
    dst = JsonlStore(tmp_path, clock=_clock())
    payload = {
        "version": 1,
        "memories": [
            {
                "namespace": {"tenant": "acme", "project": "billing"},
                "title": "ok fact",
                "body": "totally fine",
                "source": {"kind": "doc", "ref": "x"},
            },
            {
                "namespace": {"tenant": "acme", "project": "billing"},
                "title": "leak",
                "body": "AWS_SECRET_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE",
                "source": {"kind": "doc", "ref": "x"},
            },
        ],
    }
    result = dst.import_memories(payload)
    assert result["imported"] == 1
    assert result["rejected"] == 1
    assert [m.title for m in dst.query(NS)] == ["ok fact"]
