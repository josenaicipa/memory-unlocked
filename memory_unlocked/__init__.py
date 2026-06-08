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
from .models import Event, Link, Memory, Namespace, Source
from .persistence import JsonlStore
from .sqlite_store import SqliteStore
from .policy import PolicyConfig, PolicyError, review
from .serialize import (
    event_from_dict,
    event_to_dict,
    memory_from_dict,
    memory_to_dict,
)
from .store import MemoryStore

__version__ = "0.3.0"

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
    "memory_to_dict",
    "memory_from_dict",
    "event_to_dict",
    "event_from_dict",
    "__version__",
]
