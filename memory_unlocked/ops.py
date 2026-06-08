"""Service layer shared by the CLI and the MCP server.

These functions translate primitive arguments (strings, lists) into model
objects, run them through the store, and return JSON-safe result dicts. Putting
the logic here means the CLI and the MCP server expose the *same* behavior and
the *same* result shapes — there is one place where a write is built and one
place where a rejection is shaped, so the two transports can never drift.

Every function returns plain data. None of them print, read argv, or touch
stdio; the transports own I/O.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .assembler import AssemblerConfig, ContextAssembler
from .graph import GRAPH_STATUSES, SEMANTIC_RELATIONS, Graph, extract_graph
from .models import DEFAULT_STATUS, Memory, Namespace, Source
from .policy import PolicyError
from .ranking import estimate_tokens, find_duplicate_groups
from .serialize import event_to_dict, memory_to_dict
from .store import MemoryStore

# A single memory emitting more relations than this is flagged as noisy.
GRAPH_NOISY_THRESHOLD = 8
# Relations below this confidence are flagged as weak.
GRAPH_WEAK_CONFIDENCE = 0.4


def _split_tags(tags: Optional[Any]) -> List[str]:
    """Accept a comma string or a list; return a clean list of tags."""
    if tags is None:
        return []
    if isinstance(tags, str):
        return [t.strip() for t in tags.split(",") if t.strip()]
    return [str(t).strip() for t in tags if str(t).strip()]


def write_memory(
    store: MemoryStore,
    *,
    namespace: Namespace,
    title: str,
    body: str,
    source: str,
    source_kind: str = "doc",
    source_note: Optional[str] = None,
    kind: str = "fact",
    tags: Optional[Any] = None,
    confidence: float = 1.0,
    status: str = DEFAULT_STATUS,
) -> Dict[str, Any]:
    """Build and store a memory.

    Returns ``{"ok": True, "id": ..., "status": ...}`` on success, or
    ``{"ok": False, "rejected": <reason>}`` if the gate or model validation
    refuses it. The offending content is never included in the result.
    """
    try:
        memory = Memory(
            namespace=namespace,
            title=title,
            body=body,
            source=Source(kind=source_kind, ref=source, note=source_note),
            kind=kind,
            tags=_split_tags(tags),
            confidence=confidence,
            status=status,
        )
    except ValueError as exc:
        return {"ok": False, "rejected": "invalid_input", "detail": str(exc)}

    try:
        stored = store.add(memory)
    except PolicyError as exc:
        return {"ok": False, "rejected": exc.reason}

    return {"ok": True, "id": stored.id, "status": stored.status}


def recall(
    store: MemoryStore,
    namespace: Namespace,
    query: str = "",
    max_memories: Optional[int] = None,
) -> Dict[str, Any]:
    """Assemble a scope-filtered context block plus the structured matches."""
    config = AssemblerConfig(max_memories=max_memories) if max_memories else AssemblerConfig()
    assembler = ContextAssembler(store, config)
    selected = assembler.select(namespace, query=query)
    context = assembler.assemble(namespace, query=query, selected=selected)
    return {
        "context": context,
        "matches": [memory_to_dict(m) for m in selected],
    }


def build_context(
    store: MemoryStore,
    namespace: Namespace,
    query: str = "",
    token_budget: Optional[int] = None,
    max_memories: Optional[int] = None,
) -> Dict[str, Any]:
    """Assemble a token-budgeted context block (the ``memory_context`` surface).

    Distinct from :func:`recall`: this returns a single rendered block bounded by
    an estimated ``token_budget`` plus accounting (estimated tokens used and which
    memory ids were included), for callers that need to fit context into a model
    window. ``recall`` returns the structured matches for programmatic use.
    """
    config = AssemblerConfig()
    if max_memories:
        config.max_memories = max_memories
    if token_budget:
        config.max_tokens = token_budget
    assembler = ContextAssembler(store, config)
    selected = assembler.select(namespace, query=query)
    context = assembler.assemble(namespace, query=query, selected=selected)
    return {
        "context": context,
        "estimated_tokens": estimate_tokens(context),
        "token_budget": token_budget,
        "memory_ids": [m.id for m in selected],
        "matches": [memory_to_dict(m) for m in selected],
    }


def _graph_for(store: MemoryStore, namespace: Namespace, query: str) -> Graph:
    """Extract the semantic graph for a scope, optionally narrowed by ``query``.

    Scope is enforced by ``store.query`` (active memories only); the graph layer
    re-checks each memory's namespace as defense in depth. A substring ``query``
    narrows which memories feed the graph, the same way recall does.
    """
    memories = store.query(
        namespace,
        text=query or None,
        statuses=GRAPH_STATUSES,
        match=bool(query),
    )
    return extract_graph(memories, namespace)


def _relation_view(rel) -> Dict[str, Any]:
    """JSON-safe view of one relation. Carries ids/titles/refs, never a body."""
    return {
        "subject": rel.subject,
        "subject_kind": rel.subject_kind,
        "object": rel.object,
        "object_kind": rel.object_kind,
        "confidence": rel.confidence,
        "source_memory_id": rel.source_memory_id,
        "source_title": rel.source_title,
        "source_ref": rel.source_ref,
        "extraction_rule": rel.extraction_rule,
    }


def graph_report(
    store: MemoryStore,
    namespace: Namespace,
    query: str = "",
) -> Dict[str, Any]:
    """Structured semantic-graph report for a scope.

    Returns entities, semantic relations grouped by type, co-occurrences kept
    separately, and warnings (noisy memories, weak edges, duplicate triples).
    Like :func:`audit`, it carries only ids/titles/refs — never memory bodies —
    so the report is safe to print or ship. Secret/PII-shaped names are dropped
    at extraction time, so they can never appear here.
    """
    graph = _graph_for(store, namespace, query)

    grouped: Dict[str, List[Dict[str, Any]]] = {rel: [] for rel in SEMANTIC_RELATIONS}
    for rel in graph.relations:
        grouped.setdefault(rel.rel, []).append(_relation_view(rel))
    # Drop empty buckets so the report only lists relations that occur.
    semantic_relations = {rel: views for rel, views in grouped.items() if views}

    co_occurs = [
        {"a": rel.subject, "b": rel.object,
         "source_memory_id": rel.source_memory_id, "source_title": rel.source_title}
        for rel in graph.co_occurs
    ]

    entities = [
        {"kind": e.kind, "name": e.name, "confidence": e.confidence,
         "source_memory_id": e.source_memory_id, "source_title": e.source_title}
        for e in graph.entities
    ]

    return {
        "namespace": namespace.as_key(),
        "query": query,
        "entities": entities,
        "semantic_relations": semantic_relations,
        "co_occurs": co_occurs,
        "warnings": _graph_warnings(graph),
        "counts": {
            "entities": len(graph.entities),
            "relations": len(graph.relations),
            "co_occurs": len(graph.co_occurs),
        },
    }


def _graph_warnings(graph: Graph) -> List[Dict[str, Any]]:
    """Deterministic governance warnings over an extracted graph."""
    warnings: List[Dict[str, Any]] = []

    # Noisy: a single memory contributing an unusually large number of relations.
    per_memory: Dict[str, int] = {}
    for rel in graph.relations:
        key = rel.source_memory_id or ""
        per_memory[key] = per_memory.get(key, 0) + 1
    for memory_id, count in sorted(per_memory.items()):
        if count > GRAPH_NOISY_THRESHOLD:
            warnings.append({"kind": "noisy", "source_memory_id": memory_id, "relations": count})

    # Weak: low-confidence semantic edges.
    weak = sum(1 for rel in graph.relations if rel.confidence < GRAPH_WEAK_CONFIDENCE)
    if weak:
        warnings.append({"kind": "weak", "count": weak})

    # Duplicates: the same (rel, subject, object) asserted by more than one memory.
    seen: Dict[tuple, int] = {}
    for rel in graph.relations:
        triple = (rel.rel, rel.subject, rel.object)
        seen[triple] = seen.get(triple, 0) + 1
    # Note: extract_graph de-dupes within a namespace, so duplicates surface only
    # when the same triple is independently asserted; report any that repeat.
    duplicates = {t: c for t, c in seen.items() if c > 1}
    for (rel, subject, obj), count in sorted(duplicates.items()):
        warnings.append({"kind": "duplicate", "relation": rel,
                         "subject": subject, "object": obj, "count": count})

    return warnings


def graph_context(
    store: MemoryStore,
    namespace: Namespace,
    query: str = "",
    token_budget: Optional[int] = None,
) -> Dict[str, Any]:
    """Render a compact, token-budgeted semantic-graph context block.

    Semantic relations are rendered first (in vocabulary priority order), then
    co-occurrences as a low-priority tail. The block is bounded by an estimated
    ``token_budget`` and carries no bodies, secrets, or PII — only the typed
    edges and the entities they connect.
    """
    graph = _graph_for(store, namespace, query)
    header = f"# Memory graph — {namespace.as_key()}"
    lines: List[str] = [header]
    used = estimate_tokens(header)

    def _emit(text: str) -> bool:
        nonlocal used
        tokens = estimate_tokens(text)
        if token_budget is not None and used + tokens > token_budget:
            return False
        lines.append(text)
        used += tokens
        return True

    rendered = 0
    by_rel: Dict[str, List] = {rel: [] for rel in SEMANTIC_RELATIONS}
    for rel in graph.relations:
        by_rel.setdefault(rel.rel, []).append(rel)

    stop = False
    for rel_name in SEMANTIC_RELATIONS:
        for rel in by_rel.get(rel_name, []):
            if not _emit(f"- {rel.subject} --{rel_name}--> {rel.object}"):
                stop = True
                break
            rendered += 1
        if stop:
            break

    if not stop:
        for rel in graph.co_occurs:
            if not _emit(f"- {rel.subject} ~ {rel.object} (co_occurs)"):
                break
            rendered += 1

    context = "\n".join(lines).strip() if rendered else ""
    return {
        "context": context,
        "estimated_tokens": estimate_tokens(context),
        "token_budget": token_budget,
        "relations_rendered": rendered,
        "relation_count": len(graph.relations),
        "entity_count": len(graph.entities),
    }


def list_memories(
    store: MemoryStore,
    namespace: Namespace,
    statuses: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """All memories in one scope, optionally filtered by lifecycle status.

    This uses ``store.query`` so the listing is audited as a scope-local recall.
    """
    memories = store.query(namespace, statuses=statuses)
    return {"memories": [memory_to_dict(m) for m in memories]}


def set_memory_status(store: MemoryStore, memory_id: str, status: str) -> Dict[str, Any]:
    """Transition a memory's lifecycle status (promote/archive/reject)."""
    try:
        memory = store.set_status(memory_id, status)
    except KeyError:
        return {"ok": False, "error": "not_found", "id": memory_id}
    except ValueError as exc:
        return {"ok": False, "error": "invalid_status", "detail": str(exc)}
    return {"ok": True, "id": memory.id, "status": memory.status}


def forget_memory(store: MemoryStore, memory_id: str) -> Dict[str, Any]:
    """Permanently remove a memory by id."""
    removed = store.forget(memory_id)
    return {"ok": removed, "id": memory_id, "forgotten": removed}


def audit(
    store: MemoryStore,
    namespace: Optional[Namespace] = None,
    min_confidence: float = 0.5,
    stale_before: Optional[str] = None,
    dupe_threshold: float = 0.92,
) -> Dict[str, Any]:
    """Governance scan: stale, low-confidence, and duplicate memories.

    Returns plain data with ids and titles only — never bodies — so an audit
    report is safe to print or ship. ``stale_before`` is an ISO-8601 string;
    any active/candidate memory created at or before it is flagged stale (the
    caller computes the cutoff from a wall clock so this stays deterministic).
    """
    memories = [
        m for m in store.all()
        if namespace is None or m.namespace == namespace
    ]

    def _ref(m: Memory) -> Dict[str, Any]:
        return {"id": m.id, "title": m.title, "namespace": m.namespace.as_key(),
                "status": m.status, "confidence": m.confidence, "created_at": m.created_at}

    low_confidence = [_ref(m) for m in memories if m.confidence < min_confidence]
    stale = []
    if stale_before is not None:
        stale = [
            _ref(m) for m in memories
            if m.status in ("active", "candidate")
            and (m.created_at or "") <= stale_before
        ]
    candidates = [_ref(m) for m in memories if m.status == "candidate"]

    groups = find_duplicate_groups(memories, dupe_threshold)
    duplicates = [[_ref(m) for m in group] for group in groups]

    return {
        "total": len(memories),
        "low_confidence": low_confidence,
        "stale": stale,
        "candidates": candidates,
        "duplicates": duplicates,
    }


def compute_stats(
    store: MemoryStore,
    namespace: Optional[Namespace] = None,
) -> Dict[str, Any]:
    """Counts of memories per namespace and events per type."""
    memories = [
        m for m in store.all()
        if namespace is None or m.namespace == namespace
    ]
    events = [
        e for e in store.events()
        if namespace is None or e.namespace == namespace
    ]

    ns_counts: Dict[str, int] = {}
    for memory in memories:
        ns_counts[memory.namespace.as_key()] = ns_counts.get(memory.namespace.as_key(), 0) + 1

    event_counts: Dict[str, int] = {}
    for event in events:
        event_counts[event.type] = event_counts.get(event.type, 0) + 1

    return {
        "total": len(memories),
        "namespaces": ns_counts,
        "events": event_counts,
    }


def export_store(
    store: MemoryStore,
    namespace: Optional[Namespace] = None,
) -> Dict[str, Any]:
    """Export the store (delegates to a durable backend's exporter if present)."""
    exporter = getattr(store, "export", None)
    if callable(exporter):
        return exporter(namespace)

    memories = [
        m for m in store.all()
        if namespace is None or m.namespace == namespace
    ]
    events = [
        e for e in store.events()
        if namespace is None or e.namespace == namespace
    ]
    return {
        "version": 1,
        "memories": [memory_to_dict(m) for m in memories],
        "events": [event_to_dict(e) for e in events],
    }


def import_into(store: MemoryStore, data: Dict[str, Any]) -> Dict[str, int]:
    """Import an export document, re-running the policy gate on each memory."""
    importer = getattr(store, "import_memories", None)
    if callable(importer):
        return importer(data)

    imported = 0
    rejected = 0
    for record in data.get("memories", []):
        result = write_memory(
            store,
            namespace=Namespace(record["namespace"]["tenant"], record["namespace"]["project"]),
            title=record["title"],
            body=record["body"],
            source=record["source"]["ref"],
            source_kind=record["source"]["kind"],
            source_note=record["source"].get("note"),
            kind=record.get("kind", "fact"),
            tags=record.get("tags", []),
            confidence=record.get("confidence", 1.0),
        )
        if result["ok"]:
            imported += 1
        else:
            rejected += 1
    return {"imported": imported, "rejected": rejected}
