# Install & CLI

Memory Unlocked is a single dependency-free Python package. It runs on Python
3.9+ with nothing but the standard library. `pytest` is needed only to run the
tests.

## Install

From a clone (editable, recommended while evaluating):

```bash
git clone https://github.com/josenaicipa/memory-unlocked.git
cd memory-unlocked
python -m pip install -e .
```

Or install straight from the repo:

```bash
python -m pip install "git+https://github.com/josenaicipa/memory-unlocked.git"
```

Installing exposes two console scripts:

| Command | What it does |
| --- | --- |
| `memory-unlocked` | The CLI (same as `python -m memory_unlocked`). |
| `memory-unlocked-mcp` | The MCP stdio server (same as `python -m memory_unlocked.mcp_server`). |

You can always use the module form without installing — from the repo root:

```bash
python -m memory_unlocked --help
```

## Where memory is stored

Everything is local. A store is just a directory with two append-only JSON Lines
files:

```
<store>/
├── memories.jsonl   one accepted fact per line
└── events.jsonl     one audit event per line (write / recall / reject)
```

The store path is resolved in this order:

1. `--path <dir>` on the command line
2. the `MEMORY_UNLOCKED_HOME` environment variable
3. `./.memory_unlocked` (default)

## CLI tour

All examples use generic scopes (`acme/billing`). Pick your own `tenant` and
`project`.

### Initialize

```bash
memory-unlocked --path ./mem init
```

### Write a durable fact

A write always requires a `--source`. Writes that look like secrets are rejected
at the gate (exit code `3`) and the offending value is never echoed back.

```bash
memory-unlocked --path ./mem write \
  --tenant acme --project billing \
  --title "Refunds run through the async queue" \
  --body  "Refund requests are enqueued and processed by a worker, not inline." \
  --source docs/refunds.md \
  --tags billing,architecture \
  --kind decision
```

Pipe a longer body in via stdin with `--body -`:

```bash
cat notes.md | memory-unlocked --path ./mem write \
  --tenant acme --project billing --title "Build notes" --source commit:abc123 --body -
```

### Recall scope-filtered context

```bash
memory-unlocked --path ./mem recall \
  --tenant acme --project billing --query "refund"
```

Recall only ever returns memories written under the exact same `tenant/project`.

### List, stats, export, import

```bash
memory-unlocked --path ./mem list  --tenant acme --project billing
memory-unlocked --path ./mem stats                         # all scopes
memory-unlocked --path ./mem export > backup.json          # JSON to stdout
memory-unlocked --path ./mem import --in backup.json       # re-gated on import
```

Add `--json` to `write`, `recall`, `list`, and `stats` for machine-readable
output you can pipe into `jq` or another agent.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | success |
| `2` | usage error (bad/missing arguments) |
| `3` | a write was rejected by the policy gate |
| `1` | any other runtime error |

## Library use

The same store is importable:

```python
from memory_unlocked import JsonlStore, Memory, Namespace, Source, ContextAssembler

store = JsonlStore("./mem")            # durable, file-backed
ns = Namespace("acme", "billing")

store.add(Memory(
    namespace=ns,
    title="CI runs with the offline flag",
    body="The registry mirror is read-only in CI, so builds pass --offline.",
    source=Source(kind="commit", ref="abc123"),
    tags=["ci", "build"],
))

print(ContextAssembler(store).assemble(ns, query="ci build"))
```

For wiring the MCP server into an agent runner, see
[`docs/hermes.md`](hermes.md).
