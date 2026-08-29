# Thread scope

v1.1 adds an optional conversation thread inside a `tenant/project` namespace.
Two threads in the same project are mutually untrusted by default.

## Rules

| Request | What recall returns |
| --- | --- |
| No thread | Project-level memories only (`thread` is empty). **Default.** |
| `--thread X` | Memories written to `X`, plus project-level memories. |
| `--thread X` with exact mode (library only) | Only memories written to `X`. |

A memory written in thread `A` never surfaces for a query scoped to sibling thread `B`. Cross-thread wildcards (`*`, `all`, `all_threads`) are rejected.

Memories written by v1.0.0 have no thread, so existing queries keep their results.

## CLI

```bash
memory-unlocked --path ./mem write \
  --tenant acme --project billing --thread ticket-42 \
  --title "Ticket uses the worker" \
  --body "Ticket 42 refunds go through the async worker." \
  --source docs/ticket.md

memory-unlocked --path ./mem recall \
  --tenant acme --project billing --thread ticket-42 \
  --query worker
```

## MCP

The runner binds thread the same way it binds tenant/project — with environment
variables, never tool arguments:

```bash
MEMORY_UNLOCKED_TENANT=acme \
MEMORY_UNLOCKED_PROJECT=billing \
MEMORY_UNLOCKED_THREAD=ticket-42 \
  memory-unlocked-mcp
```

If `MEMORY_UNLOCKED_THREAD` is unset, the server stays on project-level rows.
Passing `thread`, `tenant`, `project`, or `namespace` as a tool argument is rejected.
