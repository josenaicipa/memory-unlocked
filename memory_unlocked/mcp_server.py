"""A dependency-free MCP (Model Context Protocol) stdio server.

Run it with::

    python -m memory_unlocked.mcp_server

It speaks JSON-RPC 2.0 over newline-delimited stdio — the MCP stdio transport —
and exposes these tools to an agent runner such as Hermes or Claude:

    memory_write          propose a durable, non-sensitive fact
    memory_recall          recall scope-filtered structured matches for the current project
    memory_context         build a token-budgeted prompt context block
    memory_graph_context   render a compact, token-budgeted semantic-graph block
    memory_list            list the memories in the current scope
    memory_stats           counts of memories and audit events
    memory_curate          propose-only governance plan; never writes

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
from .retrieval import DEFAULT_RETRIEVAL_MODE, RETRIEVAL_MODES, normalize_mode
from .store import MemoryStore
from .thread_scope import ThreadScopeError, normalize_thread

SUPPORTED_PROTOCOL_VERSIONS = (
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
    "2025-11-25",
)
LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[-1]
# Backward-compatible public constant.
PROTOCOL_VERSION = LATEST_PROTOCOL_VERSION
SERVER_NAME = "memory-unlocked"
JSONRPC_VERSION = "2.0"

# JSON-RPC 2.0 error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

ENV_PATH = "MEMORY_UNLOCKED_HOME"
ENV_BACKEND = "MEMORY_UNLOCKED_BACKEND"
ENV_TENANT = "MEMORY_UNLOCKED_TENANT"
ENV_PROJECT = "MEMORY_UNLOCKED_PROJECT"
ENV_THREAD = "MEMORY_UNLOCKED_THREAD"
DEFAULT_PATH = "./.memory_unlocked"
# Scope is process-bound. A model cannot name these as tool arguments.
FORBIDDEN_SCOPE_KEYS = frozenset(
    {"tenant", "project", "namespace", "thread", "scope_thread", "all_threads"}
)


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
                    "status": {
                        "type": "string",
                        "enum": ["candidate", "active"],
                        "description": "Lifecycle status. MCP defaults to candidate for human review.",
                    },
                    "kind": {
                        "type": "string",
                        "enum": ["fact", "decision", "convention", "reference"],
                    },
                    "ttl_days": {
                        "type": "integer",
                        "description": "Optional time-to-live in days. Expired memories leave recall.",
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
                    "mode": {
                        "type": "string",
                        "enum": list(RETRIEVAL_MODES),
                        "description": "classic (default), lexical, vector, or hybrid.",
                    },
                },
                "required": ["query"],
            },
        },
        {
            "name": "memory_context",
            "description": "Build a token-budgeted context block for the current project scope.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What the agent is working on."},
                    "token_budget": {"type": "integer", "description": "Approximate max tokens."},
                    "max_memories": {"type": "integer", "description": "Optional hard cap."},
                    "mode": {
                        "type": "string",
                        "enum": list(RETRIEVAL_MODES),
                        "description": "classic (default), lexical, vector, or hybrid.",
                    },
                },
                "required": ["query"],
            },
        },
        {
            "name": "memory_graph_context",
            "description": (
                "Render a compact, token-budgeted semantic-graph block for the "
                "current project scope: typed relations (owns, uses_provider, "
                "depends_on, etc.) between entities, with co-occurrences as a "
                "low-priority tail. No bodies, secrets, or PII."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Narrow the graph to matching memories."},
                    "token_budget": {"type": "integer", "description": "Approximate max tokens."},
                },
            },
        },
        {
            "name": "memory_graph_temporal",
            "description": "Read-only temporal relation report for the current project scope; no raw ids/source refs.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "current_only": {"type": "boolean"},
                },
            },
        },
        {
            "name": "memory_graph_lineage",
            "description": "Redacted relation evidence and source-memory lineage handles for the current scope.",
            "inputSchema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
        },
        {
            "name": "memory_graph_effective_backend",
            "description": "Public-safe effective graph backend read for scoped agent consumers; read-only.",
            "inputSchema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
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
        {
            "name": "memory_curate",
            "description": (
                "Propose-only governance plan for the current project scope. "
                "Never writes, never promotes, never archives."
            ),
            "inputSchema": {"type": "object", "properties": {}},
        },
    ]


class MemoryMcpServer:
    """Routes JSON-RPC requests to the memory service for a fixed namespace."""

    def __init__(
        self,
        store: MemoryStore,
        namespace: Namespace,
        thread: Optional[str] = None,
    ) -> None:
        self._store = store
        self._namespace = namespace
        try:
            self._thread = normalize_thread(thread)
        except ThreadScopeError as exc:
            raise SystemExit(f"error: {exc}") from exc

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
        backend = os.environ.get(ENV_BACKEND) or "jsonl"
        store = MemoryStore.open(path, backend=backend, clock=_utc_clock)
        return cls(
            store=store,
            namespace=Namespace(tenant=tenant, project=project),
            thread=os.environ.get(ENV_THREAD),
        )

    # --- Request routing -----------------------------------------------------

    def handle(self, request: Any) -> Optional[Dict[str, Any]]:
        """Handle one JSON-RPC message. Returns None for notifications."""
        if not isinstance(request, dict):
            return self._error(None, INVALID_REQUEST, "invalid request")

        request_id = request.get("id")
        method = request.get("method")
        if request.get("jsonrpc") != JSONRPC_VERSION or not isinstance(method, str):
            return self._error(request_id, INVALID_REQUEST, "invalid request")

        # MCP lifecycle notifications do not require work here. Ignore every
        # request without an id so a mutating tool can never execute as a
        # fire-and-forget notification, and JSON-RPC never receives a reply.
        if "id" not in request:
            return None

        params = request.get("params")
        if params is not None and not isinstance(params, dict):
            return self._error(request_id, INVALID_PARAMS, "invalid params")
        params = params or {}
        if not self._valid_method_params(method, params):
            return self._error(request_id, INVALID_PARAMS, "invalid params")

        if method == "initialize":
            return self._result(request_id, self._initialize(params))
        if method == "notifications/initialized":
            return None
        if method == "ping":
            return self._result(request_id, {})
        if method == "tools/list":
            return self._result(request_id, {"tools": build_tools()})
        if method == "tools/call":
            return self._result(request_id, self._call_tool(params or {}))

        return self._error(request_id, METHOD_NOT_FOUND, "method not found")

    @staticmethod
    def _valid_method_params(method: str, params: Dict[str, Any]) -> bool:
        if method == "initialize":
            protocol = params.get("protocolVersion")
            capabilities = params.get("capabilities")
            client = params.get("clientInfo")
            return (
                isinstance(protocol, str)
                and bool(protocol.strip())
                and isinstance(capabilities, dict)
                and isinstance(client, dict)
                and isinstance(client.get("name"), str)
                and bool(client["name"].strip())
                and isinstance(client.get("version"), str)
                and bool(client["version"].strip())
            )
        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments", {})
            return (
                isinstance(name, str)
                and bool(name.strip())
                and isinstance(arguments, dict)
            )
        if method == "tools/list":
            return "cursor" not in params or isinstance(params["cursor"], str)
        if method == "ping":
            return not params
        return True

    def _initialize(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        requested = (params or {}).get("protocolVersion")
        negotiated = (
            requested if requested in SUPPORTED_PROTOCOL_VERSIONS else LATEST_PROTOCOL_VERSION
        )
        return {
            "protocolVersion": negotiated,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": __version__},
        }

    def _call_tool(self, params: Dict[str, Any]) -> Dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if FORBIDDEN_SCOPE_KEYS.intersection(arguments):
            return self._tool_error("scope is bound by the runner, not tool arguments")
        try:
            if name == "memory_write":
                return self._tool_write(arguments)
            if name == "memory_recall":
                return self._tool_recall(arguments)
            if name == "memory_context":
                return self._tool_context(arguments)
            if name == "memory_graph_context":
                return self._tool_graph_context(arguments)
            if name == "memory_graph_temporal":
                return self._tool_graph_temporal(arguments)
            if name == "memory_graph_lineage":
                return self._tool_graph_lineage(arguments)
            if name == "memory_graph_effective_backend":
                return self._tool_graph_effective_backend(arguments)
            if name == "memory_list":
                return self._tool_list()
            if name == "memory_stats":
                return self._tool_stats()
            if name == "memory_curate":
                return self._tool_curate()
            return self._tool_error("unknown tool")
        except Exception:  # noqa: BLE001 - tool errors are returned, not raised
            return self._tool_error("tool failed: internal error")

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
            status=args.get("status", "candidate"),
            thread=self._thread,
            ttl_days=args.get("ttl_days"),
        )
        if result["ok"]:
            text = f"stored {result['id']}"
        else:
            detail = f" ({result['detail']})" if result.get("detail") else ""
            text = f"rejected: {result['rejected']}{detail}"
        return self._tool_result(text, result, is_error=not result["ok"])

    def _mode(self, args: Dict[str, Any]) -> str:
        mode = args.get("mode", DEFAULT_RETRIEVAL_MODE)
        try:
            return normalize_mode(mode)
        except ValueError:
            return DEFAULT_RETRIEVAL_MODE

    def _tool_recall(self, args: Dict[str, Any]) -> Dict[str, Any]:
        result = ops.recall(
            self._store,
            self._namespace,
            query=args.get("query", ""),
            thread=self._thread,
            mode=self._mode(args),
        )
        text = result["context"] or "(no matching memories)"
        return self._tool_result(text, result)

    def _tool_context(self, args: Dict[str, Any]) -> Dict[str, Any]:
        result = ops.build_context(
            self._store,
            self._namespace,
            query=args.get("query", ""),
            token_budget=args.get("token_budget"),
            max_memories=args.get("max_memories"),
            thread=self._thread,
            mode=self._mode(args),
        )
        text = result["context"] or "(no matching memories)"
        return self._tool_result(text, result)

    def _tool_graph_context(self, args: Dict[str, Any]) -> Dict[str, Any]:
        result = ops.graph_context(
            self._store,
            self._namespace,
            query=args.get("query", ""),
            token_budget=args.get("token_budget"),
            thread=self._thread,
        )
        text = result["context"] or "(no semantic relations in scope)"
        return self._tool_result(text, result)

    def _tool_graph_temporal(self, args: Dict[str, Any]) -> Dict[str, Any]:
        result = ops.graph_temporal_report(
            self._store,
            self._namespace,
            query=args.get("query", ""),
            current_only=bool(args.get("current_only", False)),
            thread=self._thread,
        )
        return self._tool_result(json.dumps(result), result)

    def _tool_graph_lineage(self, args: Dict[str, Any]) -> Dict[str, Any]:
        result = ops.graph_lineage_report(
            self._store,
            self._namespace,
            query=args.get("query", ""),
            thread=self._thread,
        )
        return self._tool_result(json.dumps(result), result)

    def _tool_graph_effective_backend(self, args: Dict[str, Any]) -> Dict[str, Any]:
        result = ops.graph_effective_backend(
            self._store,
            self._namespace,
            query=args.get("query", ""),
            thread=self._thread,
        )
        return self._tool_result(json.dumps(result), result)

    def _tool_list(self) -> Dict[str, Any]:
        result = ops.list_memories(self._store, self._namespace, thread=self._thread)
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

    def _tool_curate(self) -> Dict[str, Any]:
        result = ops.curate_store(
            self._store, namespace=self._namespace, thread=self._thread
        )
        text = (
            f"curator plan {result['plan_id']}: {result['counts']['proposals']} "
            "proposal(s); propose-only, no writes"
        )
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
        return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "error": {"code": code, "message": message},
        }

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
            except Exception:  # noqa: BLE001 - never let one bad call kill the loop
                response = self._error(request.get("id"), INTERNAL_ERROR, "internal error")
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
