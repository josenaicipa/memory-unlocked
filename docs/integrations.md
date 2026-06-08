# Integrations

Memory Unlocked is designed to sit behind whatever interface your agent runner
already speaks. The core package has no transport opinions — you wrap it. Three
common patterns follow.

> Two of these ship in the box:
> - a **CLI** (`python -m memory_unlocked`) — see [`install.md`](install.md);
> - a **dependency-free MCP stdio server** (`python -m memory_unlocked.mcp_server`)
>   — see [`hermes.md`](hermes.md).
>
> The sketches below explain the design those implementations follow. The HTTP
> service is left as a pattern for you to wrap.

In all cases the rules are the same:

- The runner **always** passes a namespace. Never let the model pick its own
  scope freely; derive it from the active project/tenant context.
- Writes go through the policy gate. The transport layer does not get to bypass it.
- Recall is scope-filtered by the store, not by the caller.

## 1. MCP (Model Context Protocol) tools

Expose two tools to the agent. Keep the surface minimal so the model can't
widen scope or skip the gate.

**`memory_recall`**

```json
{
  "name": "memory_recall",
  "description": "Recall durable facts for the current project scope.",
  "input_schema": {
    "type": "object",
    "properties": {
      "query": { "type": "string", "description": "What to recall." }
    },
    "required": ["query"]
  }
}
```

**`memory_write`**

```json
{
  "name": "memory_write",
  "description": "Propose a durable, non-sensitive fact to remember.",
  "input_schema": {
    "type": "object",
    "properties": {
      "title":  { "type": "string" },
      "body":   { "type": "string" },
      "tags":   { "type": "array", "items": { "type": "string" } },
      "source": { "type": "string", "description": "A doc path, URL, or id." }
    },
    "required": ["title", "body", "source"]
  }
}
```

The namespace is **not** a tool parameter — the server injects it from the
session's project context. The model cannot choose to read another scope.

Server-side handler sketch:

```python
def handle_memory_write(session, args):
    ns = session.namespace                # injected, not model-controlled
    try:
        mem = store.add(Memory(
            namespace=ns,
            title=args["title"],
            body=args["body"],
            tags=args.get("tags", []),
            source=Source(kind="doc", ref=args["source"]),
        ))
        return {"ok": True, "id": mem.id}
    except PolicyError as e:
        return {"ok": False, "rejected": str(e)}   # never echo the raw input back
```

## 2. HTTP service

A thin REST wrapper. Authenticate the caller and resolve the namespace from the
authenticated principal — not from the request body.

```
POST /v1/memories
  Authorization: Bearer <token>          # resolves to tenant/project
  { "title": "...", "body": "...", "tags": [], "source": "docs/x.md" }
  -> 201 { "id": "mem_<uuid>" }
  -> 422 { "rejected": "secret_detected" }

GET /v1/memories?query=refund
  Authorization: Bearer <token>
  -> 200 { "context": "...", "matches": [ ... ] }   # scope-filtered server-side
```

Notes:

- The token determines the scope. The body never carries a tenant id.
- Rejections return a reason code, never the offending content.
- Rate-limit writes; memory should grow slowly and deliberately.

## 3. CLI / library

For local agent runners, embed the package directly.

```python
from memory_unlocked import Memory, Source, Namespace, MemoryStore, ContextAssembler

store = MemoryStore.open("./local_memory")   # or your own backend
ns = Namespace(tenant="acme", project="billing")

# write
store.add(Memory(
    namespace=ns,
    title="Build needs the offline flag in CI",
    body="CI runs with --offline because the registry mirror is read-only there.",
    source=Source(kind="commit", ref="abc123"),
    tags=["ci", "build"],
))

# recall, scope-filtered
ctx = ContextAssembler(store).assemble(ns, query="ci build")
```

## Wiring it into an agent loop

A typical loop:

1. **Session start** — resolve the namespace from the active project.
2. **Before reasoning** — call recall with the user's task to load relevant facts.
3. **After completing durable work** — propose a write summarizing the stable
   learning (not the steps taken).
4. **Audit** — periodically review the event log per scope.

Keep the model on a tight surface: it queries and proposes, the fabric decides
what is allowed and what scope applies.
