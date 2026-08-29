"""Optional conversation-thread isolation inside a tenant/project.

A *thread* is a sub-scope inside a project: a conversation, agent session, or
ticket. Two threads in the same project are mutually untrusted by default. A
memory written in thread ``A`` must never surface for a query scoped to sibling
thread ``B``.

This module is pure and free of I/O. The store applies :func:`admits_thread` as
a **hard filter before ranking**. No retrieval mode, BM25 score, vector score,
or fusion step can re-admit a row this predicate excluded.

Fallback policy (explicit, never implicit)
------------------------------------------
``thread=None`` means "the caller did not name a thread". It does **not** mean
"give me every thread". Omitting a thread therefore admits only project-level
rows (``memory.thread is None``).

=============== ==============================================================
Mode            Rows admitted
=============== ==============================================================
``null_only``   ``thread is None`` — project-level rows only. **Default when
                no thread is named.** Fail-closed.
``exact``       ``thread == X`` only. Project-level rows are excluded too.
``inherit``     ``thread == X or thread is None``. The named thread plus
                project-level rows. **Default when a thread is named.**
=============== ==============================================================

``all_threads`` is intentionally absent. Crossing thread boundaries is a
privilege that must not be expressible in CLI flags, MCP tool arguments, or
other caller-controlled data. Governance surfaces that need a sweep iterate
``store.all()`` in-process.

Backward compatibility
----------------------
Memories written before v1.1 have ``thread is None``, so the default unnamed
predicate matches all of them and existing queries keep their results. The
fail-closed default only affects memories explicitly written into a thread.
"""

from __future__ import annotations

from typing import Optional

THREAD_MODES = ("null_only", "exact", "inherit")
DEFAULT_UNNAMED_MODE = "null_only"
DEFAULT_NAMED_MODE = "inherit"
# Names a caller might try in order to widen scope. All are rejected.
_FORBIDDEN_WILDCARDS = frozenset(
    {"*", "all", "all_threads", "any", "any_thread", "cross_thread"}
)


class ThreadScopeError(ValueError):
    """Raised when a caller asks for a thread mode that would widen scope."""


def normalize_thread(value: Optional[str]) -> Optional[str]:
    """Return a stripped thread name, or ``None`` when no thread is named.

    Empty strings are treated as omitted (so ``--thread ''`` cannot smuggle a
    wildcard). Named wildcards that would cross siblings are rejected.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lower() in _FORBIDDEN_WILDCARDS:
        raise ThreadScopeError(
            "cross-thread wildcards are not selectable from a request"
        )
    return text


def resolve_mode(
    thread: Optional[str],
    mode: Optional[str] = None,
) -> str:
    """Pick the thread filter mode. Request-controlled values must narrow."""
    requested = normalize_thread(thread)
    if mode is None or mode == "":
        return DEFAULT_NAMED_MODE if requested else DEFAULT_UNNAMED_MODE
    resolved = str(mode).strip().lower()
    if resolved not in THREAD_MODES:
        raise ThreadScopeError(
            f"thread mode must be one of {THREAD_MODES}, not {mode!r}"
        )
    if requested is None and resolved == "exact":
        raise ThreadScopeError("exact thread mode requires a named thread")
    return resolved


def admits_thread(
    memory_thread: Optional[str],
    requested_thread: Optional[str] = None,
    mode: Optional[str] = None,
) -> bool:
    """True when ``memory_thread`` may be shown to a query for ``requested_thread``.

    The invariant for every selectable mode: a row whose thread is a **different
    non-NULL value** than the requested thread is never admitted.
    """
    requested = normalize_thread(requested_thread)
    stored = normalize_thread(memory_thread)
    resolved = resolve_mode(requested, mode)
    if resolved == "null_only":
        return stored is None
    if resolved == "exact":
        return requested is not None and stored == requested
    # inherit
    if requested is None:
        return stored is None
    return stored is None or stored == requested
