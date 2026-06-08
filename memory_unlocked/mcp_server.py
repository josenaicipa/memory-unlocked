"""A dependency-free MCP (Model Context Protocol) stdio server.

Run it with::

    python -m memory_unlocked.mcp_server

It speaks JSON-RPC 2.0 over newline-delimited stdio — the MCP stdio transport —
and exposes four tools to an agent runner such as Hermes or Claude:

    memory_write   propose a durable, non-sensitive fact
    memory_recall  recall scope-filtered context for the current project
    memory_list    list the memories in the current scope
    memory_stats   counts of memories and audit events

The security model from the docs is enforced here: **the namespace is never a
tool argument.** The runner picks the scope by launching the server with
``MEMORY_UNLOCKED_TENANT`` / ``MEMORY_UNLOCKED_PROJECT`` set, so the model can
neither widen its scope nor read another project's memory. Writes still pass the
policy gate, and rejections return a reason code, never the offending content.

No third-party ``mcp`` package is required; the protocol surface implemented
here (``initialize``, ``tools/list``, ``tools/call``, ``ping``) is enough for a
standard MCP client to connect and call tools.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TextIO

from . import __version__, ops
from .models import Namespace
from .persistence import JsonlStore
from .store import MemoryStore

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "memory-unlocked"

# JSON-RPC 2.0 error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

ENV_PATH = "MEMORY_UNLOCKED_HOME"
ENV_TENANT = "MEMORY_UNLOCKED_TENANT"
ENV_PROJECT = "MEMORY_UNLOCKED_PROJECT"
DEFAULT_PATH = "./.memory_unlocked"


def _utc_clock() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_tools() -> List[Dict[str, Any]]:
    """The tool catalogue. Namespace is injected server-side, never exposed."""
    return [
        {
            "name": "memory_write",
            "description": (
                "Propose a durable, non-sensitive fact to remember for the "
                "current project scope. Rejected if it looks like a secret or "
                "lacks a source."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short summary."},
                    "body": {"type": "string", "description": "The stable fact."},
                    "source": {"type": "string", "description": "A doc path, URL, or id."},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "kind": {
                        "type": "string",
                        "enum": ["fact", "decision", "convention", "reference"],
                    },
                },
                "required": ["title", "body", "source"],
            },
        },
        {
            "name": "memory_recall",
            "description": "Recall durable facts for the current project scope.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to recall."},
                },
                "required": ["query"],
            },
        },
        {
            "name": "memory_list",
            "description": "List all memories stored in the current project scope.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "memory_stats",
            "description": "Counts of memories and audit events for the current scope.",
            "inputSchema": {"type": "object", "properties": {}},
        },
    ]


class MemoryMcpServer:
    """Routes JSON-RPC requests to the memory service for a fixed namespace."""

    def __init__(self, store: MemoryStore, namespace: Namespace) -> None:
        self._store = store
        self._namespace = namespace

    @classmethod
    def from_env(cls) -> "MemoryMcpServer":
        """Build a server from environment configuration set by the runner."""
        tenant = os.environ.get(ENV_TENANT)
        project = os.environ.get(ENV_PROJECT)
        if not tenant or not project:
            raise SystemExit(
                f"error: set {ENV_TENANT} and {ENV_PROJECT} to bind the server "
                "to a project scope (the namespace is never model-controlled)."
            )
        path = os.environ.get(ENV_PATH) or DEFAULT_PATH
        store = JsonlStore(path, clock=_utc_clock)
        return cls(store=store, namespace=Namespace(tenant=tenant, project=project))

    # --- Request routing -----------------------------------------------------

    def handle(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle one JSON-RPC message. Returns None for notifications."""
        request_id = request.get("id")
        method = request.get("method")
        is_notification = "id" not in request

        if method == "initialize":
            return self._result(request_id, self._initialize())
        if method == "notifications/initialized" or (is_notification and method != "ping"):
            return None
        if method == "ping":
            return self._result(request_id, {})
        if method == "tools/list":
            return self._result(request_id, {"tools": build_tools()})
        if method == "tools/call":
            return self._result(request_id, self._call_tool(request.get("params") or {}))

        return self._error(request_id, METHOD_NOT_FOUND, f"unknown method: {method}")

    def _initialize(self) -> Dict[str, Any]:
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": __version__},
        }

    def _call_tool(self, params: Dict[str, Any]) -> Dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            if name == "memory_write":
                return self._tool_write(arguments)
            if name == "memory_recall":
                return self._tool_recall(arguments)
            if name == "memory_list":
                return self._tool_list()
            if name == "memory_stats":
                return self._tool_stats()
            return self._tool_error(f"unknown tool: {name}")
        except Exception as exc:  # noqa: BLE001 - tool errors are returned, not raised
            return self._tool_error(f"tool failed: {exc}")

    # --- Tools ---------------------------------------------------------------

    def _tool_write(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if "title" not in args or "body" not in args or "source" not in args:
            return self._tool_error("memory_write requires title, body, and source")
        result = ops.write_memory(
            self._store,
            namespace=self._namespace,
            title=args["title"],
            body=args["body"],
            source=args["source"],
            source_kind=args.get("source_kind", "doc"),
            kind=args.get("kind", "fact"),
            tags=args.get("tags"),
        )
        if result["ok"]:
            text = f"stored {result['id']}"
        else:
            detail = f" ({result['detail']})" if result.get("detail") else ""
            text = f"rejected: {result['rejected']}{detail}"
        return self._tool_result(text, result, is_error=not result["ok"])

    def _tool_recall(self, args: Dict[str, Any]) -> Dict[str, Any]:
        result = ops.recall(self._store, self._namespace, query=args.get("query", ""))
        text = result["context"] or "(no matching memories)"
        return self._tool_result(text, result)

    def _tool_list(self) -> Dict[str, Any]:
        result = ops.list_memories(self._store, self._namespace)
        if not result["memories"]:
            text = "(no memories in scope)"
        else:
            text = "\n".join(
                f"- {m['id']}  {m['title']}" for m in result["memories"]
            )
        return self._tool_result(text, result)

    def _tool_stats(self) -> Dict[str, Any]:
        result = ops.compute_stats(self._store, self._namespace)
        text = f"{result['total']} memories in {self._namespace.as_key()}"
        return self._tool_result(text, result)

    # --- Response builders ---------------------------------------------------

    @staticmethod
    def _tool_result(text: str, structured: Dict[str, Any], is_error: bool = False) -> Dict[str, Any]:
        return {
            "content": [{"type": "text", "text": text}],
            "structuredContent": structured,
            "isError": is_error,
        }

    @staticmethod
    def _tool_error(message: str) -> Dict[str, Any]:
        return {
            "content": [{"type": "text", "text": message}],
            "isError": True,
        }

    @staticmethod
    def _result(request_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    # --- stdio loop ----------------------------------------------------------

    def serve(self, stdin: TextIO, stdout: TextIO) -> None:
        """Read newline-delimited JSON-RPC from ``stdin``, reply on ``stdout``."""
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                self._write(stdout, self._error(None, PARSE_ERROR, "invalid JSON"))
                continue
            try:
                response = self.handle(request)
            except Exception as exc:  # noqa: BLE001 - never let one bad call kill the loop
                response = self._error(request.get("id"), INTERNAL_ERROR, str(exc))
            if response is not None:
                self._write(stdout, response)

    @staticmethod
    def _write(stdout: TextIO, message: Dict[str, Any]) -> None:
        stdout.write(json.dumps(message) + "\n")
        stdout.flush()


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - stdio loop
    server = MemoryMcpServer.from_env()
    server.serve(sys.stdin, sys.stdout)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
