#!/usr/bin/env python3
"""Smoke the exact installed CLI/MCP artifact as a new local student."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

EXPECTED_VERSION = "1.0.0"
EXPECTED_PROTOCOL = "2025-11-25"
EXPECTED_TOOLS = {
    "memory_write",
    "memory_recall",
    "memory_context",
    "memory_graph_context",
    "memory_graph_temporal",
    "memory_graph_lineage",
    "memory_graph_effective_backend",
    "memory_list",
    "memory_stats",
}


def run_mcp(home: Path, project: str, requests: List[Any]) -> List[Dict]:
    env = os.environ.copy()
    env.update(
        {
            "MEMORY_UNLOCKED_HOME": str(home),
            "MEMORY_UNLOCKED_BACKEND": "sqlite",
            "MEMORY_UNLOCKED_TENANT": "student-local",
            "MEMORY_UNLOCKED_PROJECT": project,
        }
    )
    process = subprocess.run(
        ["memory-unlocked-mcp"],
        input="\n".join(json.dumps(item) for item in requests) + "\n",
        text=True,
        capture_output=True,
        env=env,
        check=True,
        timeout=20,
    )
    if process.stderr.strip():
        raise AssertionError("MCP wrote unexpected stderr")
    return [json.loads(line) for line in process.stdout.splitlines() if line.strip()]


def request(request_id: int, method: str, params: Optional[Dict] = None) -> Dict:
    payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


def main() -> None:
    with (
        tempfile.TemporaryDirectory(prefix="memory-unlocked-v1-") as raw_home,
        tempfile.TemporaryDirectory(prefix="memory-unlocked-v1-other-") as raw_other_home,
    ):
        home = Path(raw_home)
        other_home = Path(raw_other_home)

        rpc_responses = run_mcp(
            home,
            "rpc-check",
            [
                [],
                {"jsonrpc": "2.0", "method": "ping"},
                request(89, "tools/call", {"name": "memory_stats", "arguments": []}),
                request(90, "ping"),
            ],
        )
        if len(rpc_responses) != 3:
            raise AssertionError("notification produced a response")
        if rpc_responses[0].get("error", {}).get("code") != -32600:
            raise AssertionError("non-object JSON-RPC input was not rejected")
        if rpc_responses[1].get("error", {}).get("code") != -32602:
            raise AssertionError("semantic MCP params were not rejected")
        if rpc_responses[2] != {"jsonrpc": "2.0", "id": 90, "result": {}}:
            raise AssertionError("MCP server did not continue after invalid input")

        version = subprocess.run(
            ["memory-unlocked", "--version"],
            text=True,
            capture_output=True,
            check=True,
            timeout=10,
        ).stdout.strip()
        if version != f"memory-unlocked {EXPECTED_VERSION}":
            raise AssertionError("unexpected installed version")

        doctor = subprocess.run(
            [
                "memory-unlocked",
                "--backend",
                "sqlite",
                "--path",
                str(home),
                "doctor",
                "--tenant",
                "student-local",
                "--project",
                "course-project",
                "--json",
            ],
            text=True,
            capture_output=True,
            check=True,
            timeout=10,
        )
        health = json.loads(doctor.stdout)
        if not health["ok"] or health["memories"] != 0:
            raise AssertionError("fresh local store is not healthy and empty")

        initial = run_mcp(
            home,
            "course-project",
            [
                request(
                    1,
                    "initialize",
                    {
                        "protocolVersion": EXPECTED_PROTOCOL,
                        "capabilities": {},
                        "clientInfo": {"name": "release-smoke", "version": "1"},
                    },
                ),
                request(2, "tools/list", {}),
                request(3, "tools/call", {"name": "memory_stats", "arguments": {}}),
            ],
        )
        if initial[0]["result"]["protocolVersion"] != EXPECTED_PROTOCOL:
            raise AssertionError("current MCP protocol was not negotiated")
        tools = {item["name"] for item in initial[1]["result"]["tools"]}
        if tools != EXPECTED_TOOLS:
            raise AssertionError("unexpected MCP tool surface")
        if initial[2]["result"]["structuredContent"]["total"] != 0:
            raise AssertionError("fresh MCP scope did not start with zero memories")

        written = run_mcp(
            home,
            "course-project",
            [
                request(
                    4,
                    "tools/call",
                    {
                        "name": "memory_write",
                        "arguments": {
                            "title": "Local smoke memory",
                            "body": "This harmless fact belongs only to the course project.",
                            "source": "release-smoke",
                            "status": "active",
                        },
                    },
                ),
                request(5, "tools/call", {"name": "memory_stats", "arguments": {}}),
            ],
        )
        if written[0]["result"]["isError"]:
            raise AssertionError("MCP write failed")
        if written[1]["result"]["structuredContent"]["total"] != 1:
            raise AssertionError("same-scope write was not visible")

        isolated = run_mcp(
            home,
            "other-project",
            [request(6, "tools/call", {"name": "memory_stats", "arguments": {}})],
        )
        if isolated[0]["result"]["structuredContent"]["total"] != 0:
            raise AssertionError("memory crossed project scope")

        other_installation = run_mcp(
            other_home,
            "course-project",
            [request(7, "tools/call", {"name": "memory_stats", "arguments": {}})],
        )
        if other_installation[0]["result"]["structuredContent"]["total"] != 0:
            raise AssertionError("memory crossed installation home")

        print(
            json.dumps(
                {
                    "version": EXPECTED_VERSION,
                    "protocol": EXPECTED_PROTOCOL,
                    "tools": len(tools),
                    "initial_memories": 0,
                    "cross_scope_memories": 0,
                    "cross_installation_memories": 0,
                    "status": "PASS",
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
