"""A public-safe, deterministic semantic graph layer over stored memories.

Memory Unlocked stores atomic facts. This module reads those facts and extracts
a small, *typed* graph of entities and relations from their text — entirely with
local, deterministic regex rules. No model calls, no network, no embeddings.

The point is to turn prose like "the billing service owns refunds" or
"el landing usa Gemini, fallback a local_ollama" into structured edges
(``owns``, ``uses_provider``, ``fallback_provider``) that a context block can
present compactly. It is the public, generic counterpart of the richer graph
semantics used in private Memory Fabric plans — with **no** private domains,
channels, providers, or routing baked in.

Design guarantees, mirroring the rest of the package:

* **Deterministic.** Same input → same graph. Pure regex + table lookups.
* **Scope-safe.** Extraction never crosses a namespace; callers pass an already
  scope-filtered set and we re-check every memory's namespace anyway.
* **Privacy-safe.** Every emitted entity/relation name passes the same secret/PII
  gate as a write (:mod:`memory_unlocked.policy`); a credential- or PII-shaped
  fragment is dropped, never surfaced. Bodies are never carried into a relation —
  only ids, titles, and source refs travel with an edge.
* **Generic only.** The alias map and provider lexicon contain widely-known
  public tech names, never anything private or deployment-specific.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .models import RECALL_STATUSES, Memory, Namespace
from .policy import pii_reason, secret_reason

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

# The semantic relation vocabulary, in descending presentation priority. These
# are the meaningful edges we try to extract. ``co_occurs`` (below) is the
# low-priority fallback used only when no semantic relation could be found.
SEMANTIC_RELATIONS: Tuple[str, ...] = (
    "owns",
    "routes_to",
    "separate_from",
    "uses_provider",
    "fallback_provider",
    "deploys_to",
    "source_of_truth_for",
    "sensitive_write",
    "depends_on",
    "supersedes",
)

# Low-priority fallback edge: two entities appeared together in one memory but no
# semantic relation was extracted between them.
CO_OCCURS = "co_occurs"

ALL_RELATIONS: Tuple[str, ...] = SEMANTIC_RELATIONS + (CO_OCCURS,)

# The kinds an extracted entity can take. Inferred heuristically from the entity
# name and its role in a relation.
ENTITY_KINDS: Tuple[str, ...] = (
    "project",
    "channel",
    "repo",
    "url",
    "provider",
    "service",
    "workflow",
    "decision",
    "source_of_truth",
    "module",
    "topic",
)

# Confidence multipliers applied to the source memory's own confidence.
SEMANTIC_CONFIDENCE = 0.85
CO_OCCURS_CONFIDENCE = 0.3

# Hard caps so one pathological memory cannot flood the graph or carry a huge
# string into an entity name. An entity name is a short noun phrase, not a
# sentence — the word cap keeps trailing prose (and therefore body text) out of
# the graph when a regex captures more than the intended noun.
MAX_NAME_CHARS = 80
MAX_NAME_WORDS = 4
MAX_RELATIONS_PER_MEMORY = 24


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GraphEntity:
    """A node in the semantic graph, traceable back to its source memory."""

    kind: str
    name: str
    namespace: Namespace
    source_memory_id: Optional[str] = None
    source_title: Optional[str] = None
    source_ref: Optional[str] = None
    confidence: float = SEMANTIC_CONFIDENCE
    extraction_rule: str = ""

    def key(self) -> Tuple[str, str, str]:
        return (self.namespace.as_key(), self.kind, self.name)


@dataclass(frozen=True)
class GraphRelation:
    """A typed, directed edge ``subject --rel--> object`` within a namespace."""

    rel: str
    subject: str
    object: str
    namespace: Namespace
    subject_kind: str = "topic"
    object_kind: str = "topic"
    source_memory_id: Optional[str] = None
    source_title: Optional[str] = None
    source_ref: Optional[str] = None
    confidence: float = SEMANTIC_CONFIDENCE
    extraction_rule: str = ""

    def triple(self) -> Tuple[str, str, str, str]:
        return (self.namespace.as_key(), self.rel, self.subject, self.object)


# ---------------------------------------------------------------------------
# Canonicalization (generic only — no private domains)
# ---------------------------------------------------------------------------

# Generic alias map. Keys are lowercased surface forms; values are the canonical
# name. Deliberately limited to widely-known public tech names — extend in your
# own deployment, but keep the public package free of private identifiers.
ALIAS_MAP: Dict[str, str] = {
    "open ai": "openai",
    "openai api": "openai",
    "chatgpt": "openai",
    "gpt": "openai",
    "gpt-4": "openai",
    "gpt-4o": "openai",
    "google gemini": "gemini",
    "gemini api": "gemini",
    "anthropic claude": "claude",
    "claude api": "claude",
    "postgresql": "postgres",
    "postgre": "postgres",
    "ollama local": "local_ollama",
    "local ollama": "local_ollama",
}

# Generic provider/infrastructure lexicon used for entity-kind inference. Public
# names only.
PROVIDER_LEXICON = frozenset({
    "openai",
    "gemini",
    "claude",
    "anthropic",
    "ollama",
    "local_ollama",
    "llama",
    "mistral",
    "cohere",
    "huggingface",
    "postgres",
    "redis",
    "sqlite",
    "s3",
    "stripe",
})

# Subjects/objects that carry no useful meaning as graph nodes.
_STOPWORDS = frozenset({
    "it", "this", "that", "they", "we", "you", "i", "he", "she",
    "the system", "the service", "the app", "everything", "nothing",
    "esto", "eso", "esa", "ese", "ellos", "nosotros", "el sistema",
    "la app", "el servicio", "todo", "nada",
})

# Leading articles/determiners stripped from a captured noun phrase.
_LEADING_ARTICLES = re.compile(
    r"^(?:the|a|an|el|la|los|las|un|una|unos|unas)\s+",
    re.IGNORECASE,
)

_URL_RE = re.compile(r"^(?:[a-z][a-z0-9+.\-]*://)?[a-z0-9.\-]+\.[a-z]{2,}(?:/\S*)?$", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")


def canonical_name(raw: str) -> str:
    """Normalize an entity surface form to a generic canonical name.

    Lowercase, collapse whitespace, strip surrounding punctuation, normalize URLs
    (drop scheme / ``www.`` / trailing slash) and channel markers, then apply the
    generic alias map. Returns ``""`` for an empty/garbage fragment.
    """
    if not raw:
        return ""
    name = _WS_RE.sub(" ", raw).strip()
    name = name.strip("\"'`.,;:!?()[]{}<>")
    name = _LEADING_ARTICLES.sub("", name).strip()
    low = name.lower()
    if not low:
        return ""

    # URL: keep host (+ path), drop scheme / www. / trailing slash.
    if "://" in low or _URL_RE.match(low):
        low = re.sub(r"^[a-z][a-z0-9+.\-]*://", "", low)
        low = re.sub(r"^www\.", "", low)
        low = low.rstrip("/")

    # Channel: collapse to a single leading '#'.
    if low.startswith("#"):
        low = "#" + low.lstrip("#").strip()

    return ALIAS_MAP.get(low, low)


def _is_url(name: str) -> bool:
    return bool(_URL_RE.match(name)) and "." in name


def infer_entity_kind(name: str, role: str, rel: str) -> str:
    """Best-effort, deterministic entity-kind inference.

    Uses surface shape first (channel/url/known provider), then the entity's role
    in its relation. This is a heuristic, not a classifier — it stays inside the
    fixed :data:`ENTITY_KINDS` set and never guesses anything private.
    """
    if name.startswith("#"):
        return "channel"
    if _is_url(name):
        return "url"
    if name in PROVIDER_LEXICON:
        return "provider"
    if name.endswith(".git") or name.endswith("-repo") or name.endswith(" repo"):
        return "repo"

    if rel in ("uses_provider", "fallback_provider") and role == "object":
        return "provider"
    if rel == "deploys_to" and role == "object":
        return "service"
    if rel == "routes_to" and role == "object":
        return "service"
    if rel == "source_of_truth_for":
        return "source_of_truth" if role == "subject" else "topic"
    if rel == "sensitive_write":
        return "service" if role == "object" else "project"
    if rel == "owns" and role == "subject":
        return "project"
    if role == "subject":
        return "project"
    return "topic"


# ---------------------------------------------------------------------------
# Extraction rules (English + Spanish / Spanglish), deterministic regex only.
# ---------------------------------------------------------------------------

# Each rule: (relation, rule_label, compiled_regex). A regex has an ``obj`` group
# and an optional ``subj`` group. A rule without a ``subj`` group binds to the
# nearest preceding subject (see :func:`_extract_relations`). Rules are tried in
# list order; the first match for a clause wins.
_RULES: List[Tuple[str, str, "re.Pattern[str]"]] = [
    # supersedes — try before uses_provider so "ya no usar X usar Y" is caught.
    ("supersedes", "supersedes:es-replace",
     re.compile(r"^ya no usar\s+(?P<obj>.+?)[,;]?\s+usar\s+(?P<subj>.+)$", re.IGNORECASE)),
    ("supersedes", "supersedes:en",
     re.compile(r"^(?P<subj>.+?)\s+(?:replaces|supersedes)\s+(?P<obj>.+)$", re.IGNORECASE)),
    ("supersedes", "supersedes:es",
     re.compile(r"^(?P<subj>.+?)\s+(?:reemplaza|sustituye)(?:\s+a)?\s+(?P<obj>.+)$", re.IGNORECASE)),

    # source_of_truth_for
    ("source_of_truth_for", "source_of_truth:en",
     re.compile(r"^(?P<subj>.+?)\s+(?:is\s+(?:the\s+)?)?source of truth (?:for|of)\s+(?P<obj>.+)$", re.IGNORECASE)),
    ("source_of_truth_for", "source_of_truth:es",
     re.compile(r"^(?P<subj>.+?)\s+es\s+(?:la\s+)?fuente de verdad (?:de|para)\s+(?P<obj>.+)$", re.IGNORECASE)),
    ("source_of_truth_for", "source_of_truth:es-bare",
     re.compile(r"^fuente de verdad (?:de|para)\s+(?P<obj>.+)$", re.IGNORECASE)),

    # separate_from (symmetric; one direction emitted)
    ("separate_from", "separate_from:en-mix",
     re.compile(r"^(?:do not mix|don'?t mix)\s+(?P<subj>.+?)\s+(?:with|and)\s+(?P<obj>.+)$", re.IGNORECASE)),
    ("separate_from", "separate_from:es-mix",
     re.compile(r"^no mezclar\s+(?P<subj>.+?)\s+(?:con|y)\s+(?P<obj>.+)$", re.IGNORECASE)),
    ("separate_from", "separate_from:generic",
     re.compile(r"^(?P<subj>.+?)\s+(?:is\s+)?(?:separate from|separado de|aparte de|kept separate from)\s+(?P<obj>.+)$", re.IGNORECASE)),

    # sensitive_write (flag-like; object is the protected resource)
    ("sensitive_write", "sensitive_write:en",
     re.compile(r"^(?:no writes? (?:to|on|in)|sensitive[_\s]?writes?\s+(?:to|on|in))\s+(?P<obj>.+)$", re.IGNORECASE)),
    ("sensitive_write", "sensitive_write:es",
     re.compile(r"^(?:no hacer writes (?:en|a)|no escribir (?:en|a)|escritura sensible (?:en|a))\s+(?P<obj>.+)$", re.IGNORECASE)),

    # deploys_to (incl. the "live at/on/en" idiom)
    ("deploys_to", "deploys_to:en",
     re.compile(r"^(?P<subj>.+?)\s+(?:deploys? to|is deployed to|despliega en|se despliega en)\s+(?P<obj>.+)$", re.IGNORECASE)),
    ("deploys_to", "deploys_to:live",
     re.compile(r"^(?P<subj>.+?)\s+(?:is\s+)?live (?:at|on|en)\s+(?P<obj>.+)$", re.IGNORECASE)),
    ("deploys_to", "deploys_to:es-live",
     re.compile(r"^(?P<subj>.+?)\s+(?:está\s+)?(?:en vivo|en produccion|en producción) en\s+(?P<obj>.+)$", re.IGNORECASE)),

    # fallback_provider — explicit-subject form first, then nearest-subject form.
    ("fallback_provider", "fallback_provider:en-subj",
     re.compile(r"^(?P<subj>.+?)\s+fallbacks?\s+(?:to|a)\s+(?P<obj>.+)$", re.IGNORECASE)),
    ("fallback_provider", "fallback_provider:nearest",
     re.compile(r"^(?:fallback|respaldo)(?:\s+provider)?\s*(?:to|a|de|=|:)?\s*(?P<obj>.+)$", re.IGNORECASE)),

    # routes_to
    ("routes_to", "routes_to",
     re.compile(r"^(?P<subj>.+?)\s+(?:routes? to|is routed to|enruta a|redirige a)\s+(?P<obj>.+)$", re.IGNORECASE)),

    # owns
    ("owns", "owns:en",
     re.compile(r"^(?P<subj>.+?)\s+(?:owns|is owner of|is the owner of|owner of)\s+(?P<obj>.+)$", re.IGNORECASE)),
    ("owns", "owns:es",
     re.compile(r"^(?P<subj>.+?)\s+(?:es due[ñn]o de|es la due[ñn]a de|gestiona|maneja|administra)\s+(?P<obj>.+)$", re.IGNORECASE)),

    # depends_on
    ("depends_on", "depends_on:en",
     re.compile(r"^(?P<subj>.+?)\s+(?:depends on|depend on|depends_on)\s+(?P<obj>.+)$", re.IGNORECASE)),
    ("depends_on", "depends_on:es",
     re.compile(r"^(?P<subj>.+?)\s+(?:depende de|dependen de)\s+(?P<obj>.+)$", re.IGNORECASE)),

    # uses_provider — most generic, tried last.
    ("uses_provider", "uses_provider:en",
     re.compile(r"^(?P<subj>.+?)\s+(?:uses|use|using|uses provider)\s+(?P<obj>.+)$", re.IGNORECASE)),
    ("uses_provider", "uses_provider:es",
     re.compile(r"^(?P<subj>.+?)\s+(?:usa|usan|utiliza|utilizan)\s+(?P<obj>.+)$", re.IGNORECASE)),
]

# Split text into clauses. We deliberately do NOT split on commas so multi-part
# idioms ("ya no usar X, usar Y") survive as one clause. Sentence punctuation only
# splits at a real boundary (followed by whitespace or end of string) so a dot
# inside a domain like ``example.com/app`` does not fracture the clause.
_CLAUSE_SPLIT = re.compile(r"[;\n]+|[.!?]+(?=\s|$)")

# Split a captured object into multiple targets ("Redis and Postgres").
_OBJECT_SPLIT = re.compile(r"\s*(?:,|\band\b|\by\b)\s*", re.IGNORECASE)

# Entity scan for the co_occurs fallback: channels, URLs, and known providers.
_CHANNEL_RE = re.compile(r"#[A-Za-z0-9][A-Za-z0-9_\-]+")
_URL_TOKEN_RE = re.compile(r"\b(?:[a-z][a-z0-9+.\-]*://)?[a-z0-9\-]+(?:\.[a-z0-9\-]+)+(?:/\S*)?", re.IGNORECASE)
_WORD_RE = re.compile(r"[A-Za-z0-9_]+")


def _clauses(text: str) -> List[str]:
    return [c.strip() for c in _CLAUSE_SPLIT.split(text or "") if c.strip()]


def _split_objects(obj: str) -> List[str]:
    parts = _OBJECT_SPLIT.split(obj)
    return [p.strip() for p in parts if p.strip()]


def _usable(name: str) -> bool:
    """A canonical name is usable iff it is non-empty, in-bounds, not a stopword,
    and not secret/PII-shaped."""
    if not name or len(name) > MAX_NAME_CHARS:
        return False
    # Reject sentence-like fragments: a real entity is a short noun phrase. This
    # keeps trailing prose (and thus body text) out of the graph.
    if len(name.split()) > MAX_NAME_WORDS:
        return False
    if name in _STOPWORDS:
        return False
    if secret_reason(name) is not None or pii_reason(name) is not None:
        return False
    return True


@dataclass
class _RawEdge:
    rel: str
    subject: str
    subject_kind: str
    object: str
    object_kind: str
    rule: str


def _extract_relations(text: str) -> List[_RawEdge]:
    """Run the rule table over ``text`` clause by clause.

    Maintains a ``last_subject`` across clauses so a subject-less clause (e.g. a
    bare ``fallback a X``) binds to the nearest *preceding* subject rather than
    the first global one. State is per call (i.e. per memory), so fallbacks never
    leak across memories.
    """
    edges: List[_RawEdge] = []
    last_subject: Optional[Tuple[str, str]] = None  # (canonical_name, raw_for_kind)

    for clause in _clauses(text):
        for rel, label, regex in _RULES:
            m = regex.match(clause)
            if not m:
                continue
            groups = m.groupdict()
            raw_subj = groups.get("subj")
            subj_name = canonical_name(raw_subj) if raw_subj else None

            if subj_name and _usable(subj_name):
                subj_kind = infer_entity_kind(subj_name, "subject", rel)
                last_subject = (subj_name, subj_kind)
            elif raw_subj is None:
                # Subject-less rule: bind to nearest preceding subject.
                if last_subject is None:
                    if rel == "sensitive_write":
                        subj_name = None  # filled from object below (self-flag)
                    else:
                        break  # cannot bind; abandon this clause
                else:
                    subj_name, subj_kind = last_subject
            else:
                break  # had a subject group but it was unusable

            for raw_obj in _split_objects(groups["obj"]):
                obj_name = canonical_name(raw_obj)
                if not _usable(obj_name):
                    continue
                obj_kind = infer_entity_kind(obj_name, "object", rel)

                if subj_name is None:  # sensitive_write self-flag
                    s_name, s_kind = obj_name, infer_entity_kind(obj_name, "subject", rel)
                else:
                    s_name, s_kind = subj_name, infer_entity_kind(subj_name, "subject", rel)

                if s_name == obj_name and rel != "sensitive_write":
                    continue  # drop degenerate self loops
                edges.append(_RawEdge(rel, s_name, s_kind, obj_name, obj_kind, label))
            break  # first matching rule wins for this clause

        if len(edges) >= MAX_RELATIONS_PER_MEMORY:
            break
    return edges


def _scan_entities(text: str) -> List[Tuple[str, str]]:
    """Scan free text for high-signal entities for the co_occurs fallback.

    Returns ``(canonical_name, kind)`` for channels, URLs, and known providers,
    in first-appearance order with duplicates removed. Intentionally narrow — we
    do not guess at arbitrary noun phrases, only shapes we can recognise safely.
    """
    found: List[Tuple[str, str]] = []
    seen = set()

    def _add(raw: str, kind: str) -> None:
        name = canonical_name(raw)
        if _usable(name) and name not in seen:
            seen.add(name)
            found.append((name, kind))

    for match in _CHANNEL_RE.finditer(text or ""):
        _add(match.group(0), "channel")
    for match in _URL_TOKEN_RE.finditer(text or ""):
        token = match.group(0)
        if "." in token and _is_url(canonical_name(token)):
            _add(token, "url")
    for word in _WORD_RE.findall(text or ""):
        low = ALIAS_MAP.get(word.lower(), word.lower())
        if low in PROVIDER_LEXICON:
            _add(low, "provider")
    return found


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------


@dataclass
class Graph:
    """The extracted graph for one namespace: entities, edges, and co-occurrences."""

    namespace: Namespace
    entities: List[GraphEntity] = field(default_factory=list)
    relations: List[GraphRelation] = field(default_factory=list)
    co_occurs: List[GraphRelation] = field(default_factory=list)


def _memory_text(memory: Memory) -> str:
    return f"{memory.title}. {memory.body}"


def extract_graph(memories: Sequence[Memory], namespace: Namespace) -> Graph:
    """Build the semantic graph for ``namespace`` from its memories.

    The caller is expected to pass an already scope-filtered set; we re-check
    every memory's namespace regardless (defense in depth — extraction can never
    mix scopes). Entities and relations are de-duplicated; co_occurs edges are
    only emitted for memories that yielded no semantic relation.
    """
    graph = Graph(namespace=namespace)
    seen_entities: set = set()
    seen_triples: set = set()
    seen_cooccurs: set = set()

    for memory in memories:
        if memory.namespace != namespace:
            continue  # never cross scope
        base_conf = memory.confidence
        src_id, src_title = memory.id, memory.title
        src_ref = memory.source.ref if memory.source else None

        edges = _extract_relations(_memory_text(memory))

        def _register_entity(name: str, kind: str, conf_mult: float) -> None:
            ent = GraphEntity(
                kind=kind, name=name, namespace=namespace,
                source_memory_id=src_id, source_title=src_title, source_ref=src_ref,
                confidence=round(base_conf * conf_mult, 4), extraction_rule="",
            )
            if ent.key() not in seen_entities:
                seen_entities.add(ent.key())
                graph.entities.append(ent)

        for edge in edges:
            _register_entity(edge.subject, edge.subject_kind, SEMANTIC_CONFIDENCE)
            _register_entity(edge.object, edge.object_kind, SEMANTIC_CONFIDENCE)
            relation = GraphRelation(
                rel=edge.rel, subject=edge.subject, object=edge.object,
                namespace=namespace, subject_kind=edge.subject_kind,
                object_kind=edge.object_kind, source_memory_id=src_id,
                source_title=src_title, source_ref=src_ref,
                confidence=round(base_conf * SEMANTIC_CONFIDENCE, 4),
                extraction_rule=edge.rule,
            )
            if relation.triple() not in seen_triples:
                seen_triples.add(relation.triple())
                graph.relations.append(relation)

        if edges:
            continue  # semantic relations win; skip co_occurs for this memory

        # Fallback: no semantic relation — record co-occurrence of scanned entities.
        scanned = _scan_entities(_memory_text(memory))
        for name, kind in scanned:
            _register_entity(name, kind, CO_OCCURS_CONFIDENCE)
        for i in range(len(scanned)):
            for j in range(i + 1, len(scanned)):
                a, _ = scanned[i]
                b, _ = scanned[j]
                pair_key = (namespace.as_key(), CO_OCCURS, a, b)
                if pair_key in seen_cooccurs:
                    continue
                seen_cooccurs.add(pair_key)
                graph.co_occurs.append(GraphRelation(
                    rel=CO_OCCURS, subject=a, object=b, namespace=namespace,
                    subject_kind=scanned[i][1], object_kind=scanned[j][1],
                    source_memory_id=src_id, source_title=src_title, source_ref=src_ref,
                    confidence=round(base_conf * CO_OCCURS_CONFIDENCE, 4),
                    extraction_rule="co_occurs:scan",
                ))

    return graph


def extract_from_memory(memory: Memory) -> Graph:
    """Convenience: extract the graph for a single memory in its own namespace."""
    return extract_graph([memory], memory.namespace)


# Statuses the graph considers by default (mirrors recall: active only).
GRAPH_STATUSES = RECALL_STATUSES
