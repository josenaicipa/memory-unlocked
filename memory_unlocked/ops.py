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

from collections import defaultdict
from typing import Any, Dict, List, Optional

from .assembler import AssemblerConfig, ContextAssembler
from .graph import GRAPH_STATUSES, SEMANTIC_RELATIONS, Graph, extract_graph
from .models import DEFAULT_STATUS, Memory, Namespace, Source
from .policy import PolicyError, redact_if_secret, redact_pii
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


def _safe_text(text: str | None, limit: int = 160) -> str:
    """Redact PII/secret-shaped strings and cap output for public reports."""
    cleaned = redact_if_secret(redact_pii(text or ""))
    return cleaned[:limit]


def _handle_map(ids: List[str]) -> Dict[str, str]:
    """Map raw ids to stable local handles for one response."""
    return {raw: f"m{idx + 1}" for idx, raw in enumerate(dict.fromkeys(i for i in ids if i))}


def graph_temporal_report(store: MemoryStore, namespace: Namespace, query: str = "", current_only: bool = False) -> Dict[str, Any]:
    """Read-only temporal view of scoped semantic relations.

    Public stores do not persist relation rows separately, so relation validity is
    derived from the source memory ``created_at`` timestamp. Output intentionally
    avoids raw memory ids and source refs.
    """
    graph = _graph_for(store, namespace, query)
    grouped: Dict[tuple, List[Any]] = defaultdict(list)
    for rel in graph.relations:
        grouped[(rel.rel, rel.subject, rel.object)].append(rel)

    rows: List[Dict[str, Any]] = []
    for rels in grouped.values():
        ordered = sorted(rels, key=lambda r: (r.source_memory_id or "", r.source_title or ""))
        # With de-duplicated triples this is normally one row, but the shape is
        # temporal-safe if a future store preserves multiple observations.
        for idx, rel in enumerate(ordered):
            next_rel = ordered[idx + 1] if idx + 1 < len(ordered) else None
            current = next_rel is None
            if current_only and not current:
                continue
            rows.append({
                "handle": f"r{len(rows) + 1}",
                "relation": rel.rel,
                "subject": _safe_text(rel.subject),
                "object": _safe_text(rel.object),
                "valid_from": _created_at_for(store, namespace, rel.source_memory_id),
                "valid_until": _created_at_for(store, namespace, next_rel.source_memory_id) if next_rel else None,
                "current": current,
                "confidence": rel.confidence,
            })
    return {
        "command": "memory_graph_temporal_report",
        "namespace": namespace.as_key(),
        "query": query,
        "current_only": current_only,
        "relations": rows,
        "counts": {"relations": len(rows)},
        "dry_run": True,
        "writes_performed": 0,
    }


def graph_lineage_report(store: MemoryStore, namespace: Namespace, query: str = "") -> Dict[str, Any]:
    """Redacted relation evidence and source-memory lineage handles.

    Unlike ``graph_report``, this surface is designed for shared/public MCP
    consumers: no raw memory ids, source refs, URLs, or bodies are emitted.
    """
    graph = _graph_for(store, namespace, query)
    memory_ids = [rel.source_memory_id for rel in graph.relations if rel.source_memory_id]
    handles = _handle_map(memory_ids)
    memories = {m.id: m for m in store.query(namespace, statuses=GRAPH_STATUSES) if m.id in handles}

    relations = []
    for idx, rel in enumerate(graph.relations):
        relations.append({
            "handle": f"r{idx + 1}",
            "relation": rel.rel,
            "subject": _safe_text(rel.subject),
            "object": _safe_text(rel.object),
            "confidence": rel.confidence,
            "memory_handle": handles.get(rel.source_memory_id or ""),
            "extraction_rule": _safe_text(rel.extraction_rule, 80),
        })

    lineage = []
    for raw_id, handle in handles.items():
        mem = memories.get(raw_id)
        if mem is None:
            continue
        lineage.append({
            "handle": handle,
            "title": _safe_text(mem.title),
            "kind": mem.kind,
            "status": mem.status,
            "created_at": mem.created_at,
            "updated_at": mem.updated_at or mem.created_at,
            "link_counts": _link_counts(mem),
        })

    return {
        "command": "memory_graph_lineage",
        "namespace": namespace.as_key(),
        "query": query,
        "relation_evidence": relations,
        "memory_lineage": lineage,
        "counts": {"relations": len(relations), "memories": len(lineage)},
        "dry_run": True,
        "writes_performed": 0,
    }


def graph_effective_backend(store: MemoryStore, namespace: Namespace, query: str = "") -> Dict[str, Any]:
    """Public-safe effective backend read for MCP/agent consumers.

    Memory Unlocked is already the canonical local backend in the public package;
    this mirrors the private effective-backend contract without mentioning or
    depending on any private legacy graph infrastructure.
    """
    graph = _graph_for(store, namespace, query)
    graph_payload = {
        "nodes": [{"id": f"n{idx + 1}", "kind": e.kind, "name": _safe_text(e.name)} for idx, e in enumerate(graph.entities)],
        "edges": [
            {
                "id": f"e{idx + 1}",
                "source": _safe_text(rel.subject),
                "target": _safe_text(rel.object),
                "relation": rel.rel,
                "confidence": rel.confidence,
            }
            for idx, rel in enumerate(graph.relations)
        ],
    }
    return {
        "command": "memory_graph_effective_backend",
        "version": "public-1.0",
        "effective_backend": "memory_unlocked",
        "cutover_ready": True,
        "memory_unlocked_canonical": True,
        "legacy_backend_retained": False,
        "dry_run": True,
        "writes_performed": 0,
        "blockers": [],
        "warnings": _safe_graph_warnings(graph),
        "namespace": namespace.as_key(),
        "query": query,
        "node_count": len(graph_payload["nodes"]),
        "edge_count": len(graph_payload["edges"]),
        "graph": graph_payload,
    }


def _created_at_for(store: MemoryStore, namespace: Namespace, memory_id: str | None) -> str | None:
    if not memory_id:
        return None
    for mem in store.query(namespace, statuses=GRAPH_STATUSES):
        if mem.id == memory_id:
            return mem.created_at
    return None


def _link_counts(memory: Memory) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for link in memory.links:
        counts[link.rel] = counts.get(link.rel, 0) + 1
    return counts


def _safe_graph_warnings(graph: Graph) -> List[Dict[str, Any]]:
    """Warnings without raw memory ids or provenance for public agent reads."""
    raw = _graph_warnings(graph)
    safe: List[Dict[str, Any]] = []
    for warning in raw:
        kind = warning.get("kind")
        if kind == "noisy":
            safe.append({"kind": "noisy", "relations": int(warning.get("relations", 0) or 0)})
        elif kind == "duplicate":
            safe.append({
                "kind": "duplicate",
                "relation": _safe_text(str(warning.get("relation", "")), 80),
                "subject": _safe_text(str(warning.get("subject", "")), 80),
                "object": _safe_text(str(warning.get("object", "")), 80),
                "count": int(warning.get("count", 0) or 0),
            })
        else:
            safe.append({k: v for k, v in warning.items() if k != "source_memory_id"})
    return safe


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
