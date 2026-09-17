"""Generic native Hermes ``memory_fabric`` provider for Memory Unlocked.

Configuration is read from the Hermes config's ``plugins.memory_fabric`` block
or from documented environment variables. The model never selects a namespace.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

try:  # Hermes supplies the real ABC at runtime.
    from agent.memory_provider import MemoryProvider
except ImportError:  # Makes the plugin importable for package tests and docs tooling.
    class MemoryProvider:  # type: ignore[no-redef]
        pass

from memory_unlocked import ContextAssembler, MemoryStore, Namespace
from memory_unlocked.ops import write_memory


def _load_config() -> tuple[dict[str, Any], Path]:
    """Read only the plugin block. Missing YAML support/config fails closed."""
    try:
        from hermes_constants import get_hermes_home
        import yaml
        home = Path(get_hermes_home())
        data = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8")) or {}
        block = data.get("plugins", {}).get("memory_fabric", {}) if isinstance(data, dict) else {}
        return (block if isinstance(block, dict) else {}), home
    except Exception:
        return {}, Path.cwd()


class MemoryFabricProvider(MemoryProvider):
    """Read-first provider with a fixed configuration-bound scope."""

    @property
    def name(self) -> str:
        return "memory_fabric"

    def __init__(self) -> None:
        config, base = _load_config()
        self._config = config
        self._base = base
        self._session_id = ""

    def _value(self, key: str, default: str = "") -> str:
        return str(os.environ.get("MEMORY_FABRIC_" + key.upper(), self._config.get(key, default))).strip()

    def _path(self) -> Path:
        value = self._value("path", "memory-fabric")
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("memory_fabric.path must be a relative path inside the Hermes profile")
        return self._base / path

    def _namespace(self) -> Namespace:
        tenant, project = self._value("tenant"), self._value("project")
        if not tenant or not project:
            raise ValueError("memory_fabric tenant and project must be configured")
        return Namespace(tenant, project)

    def is_available(self) -> bool:
        try:
            self._namespace()
            return True
        except ValueError:
            return False

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        self._session_id = str(session_id or "")

    def system_prompt_block(self) -> str:
        return "Memory Fabric is read-first and scope-bound. Propose only durable, non-sensitive facts with provenance."

    def _store(self) -> MemoryStore:
        return MemoryStore.open(str(self._path()), backend=self._value("backend", "sqlite"))

    def prefetch(self, query: str, **kwargs: Any) -> str:
        if not self.is_available() or not query.strip():
            return ""
        context = ContextAssembler(self._store()).assemble(self._namespace(), query)
        return "\n[Scoped memory context]\n" + context if context else ""

    def sync_turn(self, user_content: str, assistant_content: str, **kwargs: Any) -> None:
        # Automatic transcript persistence is deliberately not supported.
        return None

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {"name": "memory_fabric_context", "description": "Read scoped local context.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
            {"name": "memory_fabric_propose", "description": "Propose a reviewable memory in the configured scope.", "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "body": {"type": "string"}, "source": {"type": "string"}, "write": {"type": "boolean"}}, "required": ["title", "body", "source"]}},
        ]

    def handle_tool_call(self, tool_name: str, args: dict[str, Any], **kwargs: Any) -> str:
        if not self._session_id or not self.is_available():
            return json.dumps({"ok": False, "error": "provider_not_initialized_or_configured"})
        if tool_name == "memory_fabric_context":
            return json.dumps({"ok": True, "context": self.prefetch(str(args.get("query", "")))})
        if tool_name == "memory_fabric_propose":
            if not args.get("write", False):
                return json.dumps({"ok": True, "status": "proposal", "requires_review": True})
            result = write_memory(
                self._store(), namespace=self._namespace(), title=str(args["title"]),
                body=str(args["body"]), source=str(args["source"]), status="candidate",
            )
            return json.dumps(result)
        return json.dumps({"ok": False, "error": "unknown_tool"})
