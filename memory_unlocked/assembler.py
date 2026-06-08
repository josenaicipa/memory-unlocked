"""Context assembler: select, rank, and render scope-filtered context.

The assembler never widens scope — it delegates the scope filter to the store
and only ranks/renders what comes back.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .models import Memory, Namespace
from .store import MemoryStore


@dataclass
class AssemblerConfig:
    """Tunables for context assembly."""

    max_memories: int = 8           # hard cap on how many facts enter context
    max_chars: int = 4000           # rough budget for the rendered block
    tag_boost: float = 0.5          # added to score per query-term/tag overlap


class ContextAssembler:
    """Builds a bounded, ranked context block for a single namespace."""

    def __init__(self, store: MemoryStore, config: AssemblerConfig | None = None) -> None:
        self._store = store
        self._config = config or AssemblerConfig()

    def select(self, namespace: Namespace, query: str = "") -> List[Memory]:
        """Return the ranked, capped set of in-scope memories for a query."""
        candidates = self._store.query(namespace, text=query or None)
        terms = [t for t in query.lower().split() if t] if query else []

        scored = sorted(
            candidates,
            key=lambda m: self._score(m, terms),
            reverse=True,
        )
        return scored[: self._config.max_memories]

    def assemble(self, namespace: Namespace, query: str = "") -> str:
        """Render a context block string for the given scope and query."""
        selected = self.select(namespace, query)
        if not selected:
            return ""

        lines: List[str] = [f"# Memory context — {namespace.as_key()}"]
        budget = self._config.max_chars
        for mem in selected:
            block = self._render(mem)
            if len(block) > budget:
                break
            lines.append(block)
            budget -= len(block)
        return "\n".join(lines).strip()

    def _score(self, memory: Memory, terms: List[str]) -> float:
        """Rank by query overlap + tag match + confidence.

        Recency is approximated by id order at the store level; here we keep the
        scoring pure and deterministic so it is testable.
        """
        if not terms:
            return memory.confidence

        text = f"{memory.title} {memory.body}".lower()
        overlap = sum(1 for t in terms if t in text)
        tag_hits = sum(1 for t in terms if any(t in tag for tag in memory.tags))
        return memory.confidence + overlap + (tag_hits * self._config.tag_boost)

    @staticmethod
    def _render(memory: Memory) -> str:
        tags = f" [{', '.join(memory.tags)}]" if memory.tags else ""
        src = f" (source: {memory.source.kind}:{memory.source.ref})"
        return f"- **{memory.title}**{tags}: {memory.body.strip()}{src}"
