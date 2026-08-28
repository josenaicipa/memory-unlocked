"""Context assembler: select, rank, and render scope-filtered context.

The assembler never widens scope — it delegates the scope filter to the store
and only ranks/renders what comes back. Ranking is deterministic and fully local
(see :mod:`memory_unlocked.ranking`); rendering is injection-defanged (see
:mod:`memory_unlocked.render`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .models import RECALL_STATUSES, Memory, Namespace
from .ranking import (
    RankingConfig,
    Scorer,
    dedupe as dedupe_memories,
    estimate_tokens,
    tokenize,
)
from .render import RenderConfig, render_memory
from .retrieval import DEFAULT_RETRIEVAL_MODE, normalize_mode, rank_candidates
from .store import MemoryStore


@dataclass
class AssemblerConfig:
    """Tunables for context assembly.

    The first three fields are kept for backward compatibility with earlier
    releases; ``tag_boost`` feeds the ranking ``tag_weight``.
    """

    max_memories: int = 8           # hard cap on how many facts enter context
    max_chars: int = 4000           # rough character budget for the rendered block
    tag_boost: float = 0.5          # weight per query-term/tag overlap
    max_tokens: Optional[int] = None  # optional token budget (estimated)
    dedupe: bool = True             # drop near-duplicate memories
    # Which lifecycle statuses recall surfaces. Default: active only.
    statuses: tuple = RECALL_STATUSES
    ranking: RankingConfig = field(default_factory=RankingConfig)
    render: RenderConfig = field(default_factory=RenderConfig)
    thread: Optional[str] = None
    retrieval_mode: str = DEFAULT_RETRIEVAL_MODE

    def __post_init__(self) -> None:
        # Keep the legacy ``tag_boost`` knob authoritative over ranking.tag_weight.
        self.ranking.tag_weight = self.tag_boost
        self.retrieval_mode = normalize_mode(self.retrieval_mode)


class ContextAssembler:
    """Builds a bounded, ranked context block for a single namespace."""

    def __init__(self, store: MemoryStore, config: AssemblerConfig | None = None) -> None:
        self._store = store
        self._config = config or AssemblerConfig()

    def select(self, namespace: Namespace, query: str = "") -> List[Memory]:
        """Return the ranked, capped set of in-scope memories for a query.

        Fetches the full in-scope set for the configured statuses (not a
        substring pre-filter) so ranking sees every candidate, then ranks,
        drops zero-relevance entries when a query is present, de-duplicates,
        and caps. Scope is enforced inside the store before any of this.
        """
        candidates = self._store.query(
            namespace,
            text=query or None,
            statuses=self._config.statuses,
            match=False,
            thread=self._config.thread,
        )
        if self._config.retrieval_mode == DEFAULT_RETRIEVAL_MODE:
            terms = tokenize(query)
            scorer = Scorer(candidates, self._config.ranking)
            ranked = sorted(
                candidates,
                key=lambda m: (-scorer.score(m, terms), m.created_at or "", m.id or ""),
            )
            if terms:
                ranked = [m for m in ranked if self._is_relevant(m, terms, scorer)]
        else:
            ranked = rank_candidates(
                candidates, query=query, mode=self._config.retrieval_mode
            )
        if self._config.dedupe:
            ranked = dedupe_memories(ranked, self._config.ranking.dedupe_threshold)
        return ranked[: self._config.max_memories]

    @staticmethod
    def _is_relevant(memory: Memory, terms, scorer: Scorer) -> bool:
        """A memory matches a query if it shares any token or tag with it."""
        if scorer._lexical(memory, terms) > 0:
            return True
        return scorer._tag_overlap(memory, terms) > 0

    def assemble(
        self,
        namespace: Namespace,
        query: str = "",
        selected: Optional[List[Memory]] = None,
    ) -> str:
        """Render a context block string for the given scope and query."""
        selected = self.select(namespace, query) if selected is None else selected
        if not selected:
            return ""

        header = f"# Memory context — {namespace.as_key()}"
        lines: List[str] = [header]
        char_budget = self._config.max_chars
        token_budget = self._config.max_tokens
        used_tokens = estimate_tokens(header)
        if token_budget is not None and used_tokens > token_budget:
            return ""
        for mem in selected:
            block = render_memory(mem, self._config.render)
            block_tokens = estimate_tokens(block)
            if len(block) > char_budget:
                break
            if token_budget is not None and used_tokens + block_tokens > token_budget:
                break
            lines.append(block)
            char_budget -= len(block)
            used_tokens += block_tokens
        return "\n".join(lines).strip()

    def estimate_tokens(self, text: str) -> int:
        """Expose the deterministic token estimate used for budgeting."""
        return estimate_tokens(text)
