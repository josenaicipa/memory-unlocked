"""JSON-safe (de)serialization for the core models.

These helpers convert the dataclasses in :mod:`memory_unlocked.models` to and
from plain ``dict`` values that survive ``json.dumps``/``json.loads`` without any
custom encoder. They are the single source of truth for the on-disk JSONL format,
CLI ``--json`` output, exports, and MCP structured content, so every surface
agrees on the wire shape.
"""

from __future__ import annotations

from typing import Any, Dict

from .models import Event, Link, Memory, Namespace, Source


def namespace_to_dict(ns: Namespace) -> Dict[str, str]:
    return {"tenant": ns.tenant, "project": ns.project}


def namespace_from_dict(d: Dict[str, Any]) -> Namespace:
    return Namespace(tenant=d["tenant"], project=d["project"])


def source_to_dict(source: Source) -> Dict[str, Any]:
    return {"kind": source.kind, "ref": source.ref, "note": source.note}


def source_from_dict(d: Dict[str, Any]) -> Source:
    return Source(kind=d["kind"], ref=d["ref"], note=d.get("note"))


def memory_to_dict(memory: Memory) -> Dict[str, Any]:
    """Render a memory as a JSON-safe dict (stable key order, no objects)."""
    return {
        "id": memory.id,
        "namespace": namespace_to_dict(memory.namespace),
        "title": memory.title,
        "body": memory.body,
        "kind": memory.kind,
        "tags": list(memory.tags),
        "source": source_to_dict(memory.source),
        "links": [{"rel": link.rel, "target_id": link.target_id} for link in memory.links],
        "confidence": memory.confidence,
        "created_at": memory.created_at,
    }


def memory_from_dict(d: Dict[str, Any]) -> Memory:
    """Rebuild a memory from a dict. Re-runs model validation (not policy)."""
    memory = Memory(
        namespace=namespace_from_dict(d["namespace"]),
        title=d["title"],
        body=d["body"],
        source=source_from_dict(d["source"]),
        kind=d.get("kind", "fact"),
        tags=list(d.get("tags", [])),
        links=[Link(rel=link["rel"], target_id=link["target_id"]) for link in d.get("links", [])],
        confidence=d.get("confidence", 1.0),
    )
    # id / created_at are assigned post-construction (they are store-owned).
    memory.id = d.get("id")
    memory.created_at = d.get("created_at")
    return memory


def event_to_dict(event: Event) -> Dict[str, Any]:
    return {
        "type": event.type,
        "namespace": namespace_to_dict(event.namespace),
        "at": event.at,
        "detail": dict(event.detail),
    }


def event_from_dict(d: Dict[str, Any]) -> Event:
    return Event(
        type=d["type"],
        namespace=namespace_from_dict(d["namespace"]),
        at=d["at"],
        detail=dict(d.get("detail", {})),
    )
