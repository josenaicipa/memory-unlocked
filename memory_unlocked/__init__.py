"""Memory Unlocked — a privacy-first, scoped memory fabric for AI agents.

Public surface:

    from memory_unlocked import (
        Memory, Source, Link, Event, Namespace,
        MemoryStore, ContextAssembler, AssemblerConfig,
        PolicyConfig, PolicyError,
    )
"""

from .assembler import AssemblerConfig, ContextAssembler
from .models import Event, Link, Memory, Namespace, Source
from .policy import PolicyConfig, PolicyError, review
from .store import MemoryStore

__version__ = "0.1.0"

__all__ = [
    "Memory",
    "Source",
    "Link",
    "Event",
    "Namespace",
    "MemoryStore",
    "ContextAssembler",
    "AssemblerConfig",
    "PolicyConfig",
    "PolicyError",
    "review",
    "__version__",
]
