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
from .assets import AssetRegistry, GovernedAsset
from .channel_rollout import ChannelContract, build_channel_contracts, validate_channel_contracts
from .consolidation import ConsolidationProposal, plan_consolidation
from .control_loop import control_loop_report
from .dashboard import dashboard_data, render_dashboard
from .mirror import MarkdownMirror, mirror_relpath, render_markdown
from .namespaces import NAMESPACE_PROFILES, profile_namespace, profile_of
from .reflex import reflex_post_task, reflex_pre_task
from .retrieval_v2 import RankedMemory, rank_v2
from .semantic_review import review_memory_record, review_namespace

__version__ = "1.2.1"

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
    "NAMESPACE_PROFILES",
    "profile_namespace",
    "profile_of",
    "MarkdownMirror",
    "mirror_relpath",
    "render_markdown",
    "dashboard_data",
    "render_dashboard",
    "reflex_pre_task",
    "reflex_post_task",
    "ConsolidationProposal",
    "plan_consolidation",
    "GovernedAsset",
    "AssetRegistry",
    "control_loop_report",
    "review_namespace",
    "review_memory_record",
    "RankedMemory",
    "rank_v2",
    "ChannelContract",
    "build_channel_contracts",
    "validate_channel_contracts",
    "__version__",
]
