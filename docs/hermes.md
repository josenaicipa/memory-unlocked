# Using the MCP server (Hermes / Claude / any MCP client)

Memory Unlocked ships a dependency-free **MCP stdio server** so an agent runner
can give a model durable, scope-isolated memory through standard tool calls. It
implements JSON-RPC 2.0 over newline-delimited stdio (the MCP stdio transport)
and needs no third-party `mcp` package.

```bash
python -m memory_unlocked.mcp_server
# or, after install:
memory-unlocked-mcp
```

## The scope is chosen by the runner, not the model

This is the core safety property. **The namespace is never a tool argument.**
The runner binds the server to one `tenant/project` via environment variables
when it launches the process:

| Variable | Meaning | Required |
| --- | --- | --- |
| `MEMORY_UNLOCKED_TENANT` | hard isolation boundary | yes |
| `MEMORY_UNLOCKED_PROJECT` | project within the tenant | yes |
| `MEMORY_UNLOCKED_HOME` | store directory (default `./.memory_unlocked`) | no |

Because the model can only ever read and write the scope it was launched with,
it cannot widen scope or reach another project's memory. Run **one server per
scope** — point several at the same `MEMORY_UNLOCKED_HOME` and each stays
isolated to its own namespace while sharing the on-disk store.

## Tools exposed

| Tool | Arguments | Purpose |
| --- | --- | --- |
| `memory_write` | `title`, `body`, `source` (required); `tags`, `kind` | Propose a durable fact. Secrets and source-less writes are rejected. |
| `memory_recall` | `query` | Recall scope-filtered context. |
| `memory_list` | — | List memories in the current scope. |
| `memory_stats` | — | Counts of memories and audit events. |

Rejections come back as a tool result with `isError: true` and a reason code
(e.g. `secret_detected`) — never the offending content.

## Register it with a client

### Hermes Agent CLI

After installing the package, bind one MCP server to one project scope. The
command below keeps the store local and injects scope through environment
variables before the server starts:

```bash
hermes mcp add memory-unlocked \
  --command "env MEMORY_UNLOCKED_TENANT=acme MEMORY_UNLOCKED_PROJECT=billing MEMORY_UNLOCKED_HOME=$HOME/.memory_unlocked memory-unlocked-mcp"
hermes mcp test memory-unlocked
```

If your Hermes version prefers module form, use:

```bash
hermes mcp add memory-unlocked \
  --command "env MEMORY_UNLOCKED_TENANT=acme MEMORY_UNLOCKED_PROJECT=billing MEMORY_UNLOCKED_HOME=$HOME/.memory_unlocked python -m memory_unlocked.mcp_server"
```

Use a different MCP server name per scope, for example
`memory-acme-billing`, `memory-acme-support`, etc. Do not run one global server
that accepts tenant/project from the model.

### Claude Code / Claude Desktop style

```bash
claude mcp add memory-unlocked \
  --env MEMORY_UNLOCKED_TENANT=acme \
  --env MEMORY_UNLOCKED_PROJECT=billing \
  --env MEMORY_UNLOCKED_HOME=/path/to/store \
  -- python -m memory_unlocked.mcp_server
```

### Raw MCP client config (JSON)

```json
{
  "mcpServers": {
    "memory-unlocked": {
      "command": "python",
      "args": ["-m", "memory_unlocked.mcp_server"],
      "env": {
        "MEMORY_UNLOCKED_TENANT": "acme",
        "MEMORY_UNLOCKED_PROJECT": "billing",
        "MEMORY_UNLOCKED_HOME": "/path/to/store"
      }
    }
  }
}
```

### Hermes-style runner

A runner that derives the scope from the active project can launch the server
per session:

```bash
MEMORY_UNLOCKED_TENANT="$PROJECT_TENANT" \
MEMORY_UNLOCKED_PROJECT="$PROJECT_NAME" \
MEMORY_UNLOCKED_HOME="$HOME/.memory_unlocked" \
  memory-unlocked-mcp
```

## Talking to it directly

Every message is one line of JSON. A minimal handshake plus a write and recall:

```jsonc
// → initialize
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05"}}
// ← {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"memory-unlocked","version":"0.2.0"}}}

// → list tools
{"jsonrpc":"2.0","id":2,"method":"tools/list"}

// → write a fact
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"memory_write","arguments":{"title":"Refunds are async","body":"Processed by a worker.","source":"docs/refunds.md","tags":["billing"]}}}
// ← result.structuredContent = {"ok":true,"id":"mem_<uuid>"}

// → recall
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"memory_recall","arguments":{"query":"refunds"}}}
// ← result.content[0].text contains the scope-filtered context block
```

Quick smoke test from a shell:

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
| MEMORY_UNLOCKED_TENANT=acme MEMORY_UNLOCKED_PROJECT=billing \
  python -m memory_unlocked.mcp_server
```

## Recommended agent loop

1. **Session start** — the runner sets the tenant/project env and launches the server.
2. **Before reasoning** — call `memory_recall` with the user's task to load facts.
3. **After durable work** — call `memory_write` with the stable learning (the
   conclusion, not the steps). The gate rejects secrets and source-less writes.
4. **Audit** — periodically review `events.jsonl` or `memory_stats` per scope.

Keep the model on a tight surface: it queries and proposes; the fabric decides
what is allowed and which scope applies.
