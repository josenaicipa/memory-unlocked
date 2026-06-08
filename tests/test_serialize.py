"""Serialization round-trip tests: model <-> plain dict (JSON-safe)."""

import json

from memory_unlocked import Memory, Namespace, Source
from memory_unlocked.models import Event, Link
from memory_unlocked.serialize import (
    event_from_dict,
    event_to_dict,
    memory_from_dict,
    memory_to_dict,
)


def _full_memory() -> Memory:
    mem = Memory(
        namespace=Namespace("acme", "billing"),
        title="Refunds run through the async queue",
        body="Refunds are enqueued and processed by a worker.",
        source=Source(kind="doc", ref="docs/refunds.md", note="design doc"),
        kind="decision",
        tags=["billing", "architecture"],
        links=[Link(rel="relates_to", target_id="mem_0002")],
        confidence=0.9,
    )
    mem.id = "mem_0001"
    mem.created_at = "2026-01-01T00:00:00Z"
    return mem


def test_memory_dict_is_json_serializable():
    d = memory_to_dict(_full_memory())
    # Must survive a JSON round-trip without custom encoders.
    assert json.loads(json.dumps(d)) == d


def test_memory_round_trip_preserves_fields():
    original = _full_memory()
    restored = memory_from_dict(memory_to_dict(original))

    assert restored.id == original.id
    assert restored.created_at == original.created_at
    assert restored.namespace == original.namespace
    assert restored.title == original.title
    assert restored.body == original.body
    assert restored.kind == original.kind
    assert restored.tags == original.tags
    assert restored.source.kind == original.source.kind
    assert restored.source.ref == original.source.ref
    assert restored.source.note == original.source.note
    assert restored.confidence == original.confidence
    assert restored.links[0].rel == "relates_to"
    assert restored.links[0].target_id == "mem_0002"


def test_event_round_trip():
    event = Event(
        type="memory.write",
        namespace=Namespace("acme", "billing"),
        at="2026-01-01T00:00:01Z",
        detail={"id": "mem_0001", "title": "x"},
    )
    restored = event_from_dict(event_to_dict(event))
    assert restored.type == event.type
    assert restored.namespace == event.namespace
    assert restored.at == event.at
    assert restored.detail == event.detail


def test_minimal_memory_round_trip():
    mem = Memory(
        namespace=Namespace("globex", "docs"),
        title="t",
        body="b",
        source=Source(kind="url", ref="https://example.com/x"),
    )
    restored = memory_from_dict(memory_to_dict(mem))
    assert restored.title == "t"
    assert restored.tags == []
    assert restored.links == []
    assert restored.id is None
