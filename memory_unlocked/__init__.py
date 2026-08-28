"""Memory Unlocked — a privacy-first, scoped memory fabric for AI agents.

Public surface:

    from memory_unlocked import (
        Memory, Source, Link, Event, Namespace,
        MemoryStore, JsonlStore, ContextAssembler, AssemblerConfig,
        PolicyConfig, PolicyError,
        memory_to_dict, memory_from_dict,
    )

For the durable, file-backed store use ``JsonlStore`` (or ``MemoryStore.open``).
The CLI lives in ``memory_unlocked.cli`` and the MCP server in
``memory_unlocked.mcp_server``.
"""

from .assembler import AssemblerConfig, ContextAssembler
from .curator import curate
from .graph import (
    ALL_RELATIONS,
    CO_OCCURS,
    ENTITY_KINDS,
    SEMANTIC_RELATIONS,
    Graph,
    GraphEntity,
    GraphRelation,
    extract_graph,
)
from .models import Event, Link, Memory, Namespace, Source
from .persistence import JsonlStore
from .policy import PolicyConfig, PolicyError, review
from .retrieval import RETRIEVAL_MODES, rank_candidates
from .serialize import (
    event_from_dict,
    event_to_dict,
    memory_from_dict,
    memory_to_dict,
)
from .session import SessionSummary, summarize_session_events
from .sqlite_store import SqliteStore
from .store import MemoryStore
from .thread_scope import ThreadScopeError, admits_thread

__version__ = "1.1.0"

__all__ = [
    "Memory",
    "Source",
    "Link",
    "Event",
    "Namespace",
    "MemoryStore",
    "JsonlStore",
    "SqliteStore",
    "ContextAssembler",
    "AssemblerConfig",
    "PolicyConfig",
    "PolicyError",
    "review",
    "Graph",
    "GraphEntity",
    "GraphRelation",
    "extract_graph",
    "SEMANTIC_RELATIONS",
    "ALL_RELATIONS",
    "ENTITY_KINDS",
    "CO_OCCURS",
    "memory_to_dict",
    "memory_from_dict",
    "event_to_dict",
    "event_from_dict",
    "admits_thread",
    "ThreadScopeError",
    "rank_candidates",
    "RETRIEVAL_MODES",
    "curate",
    "summarize_session_events",
    "SessionSummary",
    "__version__",
]
