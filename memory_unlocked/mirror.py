"""Deterministic, opt-in Markdown mirrors for public-safe memories."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from .models import Memory
from .policy import redact_if_secret

_SLUG = re.compile(r"[^a-z0-9]+")
MIRRORED_STATUSES = frozenset(("active",))


def safe_slug(value: str, fallback: str = "memory") -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = _SLUG.sub("-", ascii_value).strip("-")[:60].strip("-")
    return slug or fallback


def should_mirror(memory: Memory) -> bool:
    """Only recall-visible records can be mirrored."""
    return memory.status in MIRRORED_STATUSES


def mirror_relpath(memory: Memory) -> Path:
    """Return a stable relative path; no caller-controlled traversal."""
    if not memory.id:
        raise ValueError("a memory must be stored before it can be mirrored")
    filename = f"{safe_slug(memory.title)}-{safe_slug(memory.id, 'id')[-12:]}.md"
    return Path(safe_slug(memory.namespace.tenant)) / safe_slug(memory.namespace.project) / filename


def render_markdown(memory: Memory) -> str:
    """Render deterministic front matter without source notes or event details."""
    body = redact_if_secret(memory.body)
    return "\n".join((
        "---",
        f"id: {memory.id or ''}",
        f"namespace: {memory.namespace.as_key()}",
        f"kind: {memory.kind}",
        f"status: {memory.status}",
        f"confidence: {memory.confidence}",
        f"source: {memory.source.kind}:{redact_if_secret(memory.source.ref)}",
        "---",
        "",
        f"# {memory.title}",
        "",
        body,
        "",
    ))


class MarkdownMirror:
    """An idempotent local projection. It is never a source of truth."""

    def __init__(self, root: str | Path, enabled: bool = True) -> None:
        self.root = Path(root)
        self.enabled = enabled

    def path_for(self, memory: Memory) -> Path:
        return self.root / mirror_relpath(memory)

    def sync(self, memory: Memory) -> Path | None:
        if not self.enabled or not should_mirror(memory):
            return None
        target = self.path_for(memory)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_markdown(memory), encoding="utf-8")
        return target

    def remove(self, memory: Memory) -> bool:
        target = self.path_for(memory)
        if target.exists():
            target.unlink()
            return True
        return False
