"""Prompt-injection-safe rendering of stored memories into a context block.

Stored memories are *data*, not instructions. But they are ultimately written
into a prompt, so a memory body that contains text like "ignore all previous
instructions" or a fake ``# Memory context`` header could try to steer the model
or forge the surrounding structure. This module renders memory content so that:

* control characters are stripped,
* lines that mimic the block's own delimiters/headers are neutralised so a
  memory cannot forge structure or impersonate a system message,
* each memory is wrapped in an explicit, clearly-labelled data fence,
* per-field length is clamped so one memory cannot blow the context budget.

This is defence in depth, not a guarantee against every adversarial string. The
write-time policy gate is the primary control; this keeps a *stored* memory from
escalating into an instruction at *render* time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Memory

# Strip ASCII control chars except tab/newline, which we handle explicitly.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Lines that try to forge the context structure or impersonate a controlling
# role. We do not delete the text (that would hide tampering); we defang it by
# prefixing a marker so it can never be read as a live directive or header.
_FORGERY_RE = re.compile(
    r"^\s*(#{1,6}\s|<\/?(system|context|instructions?|tool|assistant|user)\b"
    r"|system\s*:|assistant\s*:|begin\s+system|end\s+context)",
    re.IGNORECASE,
)

# Common direct-injection imperatives. Neutralised inline, not removed.
_INJECTION_RE = re.compile(
    r"\b(ignore|disregard|forget|override)\b[^.\n]*\b"
    r"(previous|prior|above|earlier|all)\b[^.\n]*\b"
    r"(instruction|instructions|prompt|prompts|context|rule|rules|directive)\b",
    re.IGNORECASE,
)


@dataclass
class RenderConfig:
    """Limits and toggles for safe rendering."""

    max_title_chars: int = 200
    max_body_chars: int = 2000
    neutralize_injections: bool = True
    fence: str = "  | "  # prefix every body line so it reads as quoted data


def _clamp(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def sanitize_text(text: str, config: RenderConfig | None = None) -> str:
    """Return a single-block, injection-defanged version of ``text``."""
    cfg = config or RenderConfig()
    text = _CONTROL_RE.sub("", text or "")
    out_lines = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if _FORGERY_RE.match(line):
            # Defang a forged header/role marker so it is inert text.
            line = "[memory-data] " + line.lstrip("#").lstrip()
        if cfg.neutralize_injections:
            line = _INJECTION_RE.sub(
                lambda m: "[neutralized-instruction: " + m.group(0) + "]", line
            )
        out_lines.append(line)
    return "\n".join(out_lines).strip()


def render_memory(memory: Memory, config: RenderConfig | None = None) -> str:
    """Render one memory as a safe, fenced context entry."""
    cfg = config or RenderConfig()
    title = _clamp(sanitize_text(memory.title, cfg), cfg.max_title_chars)
    body = _clamp(sanitize_text(memory.body, cfg), cfg.max_body_chars)
    body = body.replace("\n", "\n" + cfg.fence)
    tags = f" [{', '.join(memory.tags)}]" if memory.tags else ""
    src = f" (source: {memory.source.kind}:{memory.source.ref})" if memory.source else ""
    status = "" if memory.status == "active" else f" (status: {memory.status})"
    return f"- **{title}**{tags}{status}:\n{cfg.fence}{body}{src}"
