# Memory Unlocked

A **privacy-first, scoped memory fabric** for AI agents. Memory Unlocked gives
agents durable, project-scoped memory without leaking secrets or letting one
project's context bleed into another.

It is installable today as a dependency-free Python package with:

- durable local JSONL and SQLite stores,
- a practical CLI (`memory-unlocked`),
- a dependency-free MCP stdio server (`memory-unlocked-mcp`),
- lifecycle/governance commands for candidate review, archival, and forgetting,
- token-budgeted context assembly and offline recall/privacy evals,
- a deterministic semantic graph layer for typed agent context,
- audit events for writes, recalls, updates, forgets, and rejections,
- tests and CI for the privacy/scope guarantees.

The core stays deliberately small so teams can audit it, ship it locally, and
adapt it to their own database, vector index, or hosted service later.

---

## Why this exists

Long-running agents need to remember things between sessions — decisions,
conventions, gotchas, references. But naive "just dump everything into a vector
store" memory has two failure modes:

1. **Secret leakage** — credentials, tokens, customer data, and PII end up
   persisted and later surfaced in unrelated contexts.
2. **Scope bleed** — memory from Project A contaminates answers about Project B.

Memory Unlocked treats both as first-class concerns. Every memory is scoped to a
namespace, every write passes a redaction/policy gate, and recall is filtered by
scope before anything reaches the model.

---

## Who it is for

- Builders of multi-project agent systems who need **isolated** memory per scope.
- Teams that want **auditable, reviewable** writes instead of a black-box store.
- Anyone who wants a **readable reference architecture** they can port to their
  own database, vector index, or MCP server.

---

## Quickstart

```bash
pipx install memory-unlocked
# or: uv tool install memory-unlocked
```

From source:

```bash
git clone https://github.com/josenaicipa/memory-unlocked.git
cd memory-unlocked
python -m pip install -e '.[dev]'
python -m pytest -q
```

Write and recall a memory from the CLI:

```bash
memory-unlocked --path ./mem init
memory-unlocked --path ./mem write \
  --tenant acme --project billing \
  --title "Refunds run through the async queue" \
  --body "Refund requests are enqueued and processed by a worker, not inline." \
  --source docs/refunds.md \
  --tags billing,architecture
memory-unlocked --path ./mem context \
  --tenant acme --project billing --query refund --token-budget 200
```

Review candidate memories and run governance/eval checks:

```bash
memory-unlocked --path ./mem write \
  --tenant acme --project billing \
  --title "Candidate fact" --body "Needs human approval." \
  --source docs/review.md --status candidate
memory-unlocked --path ./mem review --tenant acme --project billing
memory-unlocked --path ./mem audit --json
memory-unlocked eval examples/evalset/basic.json
```

Use SQLite for a more production-like local backend:

```bash
memory-unlocked --backend sqlite --path ./mem-sqlite init
```

Extract semantic graph context and the public-safe graph reports:

```bash
memory-unlocked --path ./mem write \
  --tenant acme --project billing \
  --title "Graph demo" \
  --body "Billing service owns refunds. Worker depends on Redis." \
  --source docs/graph.md
memory-unlocked --path ./mem graph-context \
  --tenant acme --project billing --token-budget 200
memory-unlocked --path ./mem graph-temporal \
  --tenant acme --project billing --json
memory-unlocked --path ./mem graph-lineage \
  --tenant acme --project billing --json
memory-unlocked --path ./mem graph-effective-backend \
  --tenant acme --project billing --json
```

The extra graph reports are read-only and public-safe: `graph-lineage` emits
opaque handles instead of raw memory ids/source refs, `graph-temporal` derives
relation validity from source-memory timestamps, and `graph-effective-backend`
returns the scoped graph as the canonical `memory_unlocked` backend payload for
agent/MCP consumers.


Run the MCP server for an agent runner:

```bash
MEMORY_UNLOCKED_TENANT=acme \
MEMORY_UNLOCKED_PROJECT=billing \
MEMORY_UNLOCKED_HOME="$HOME/.memory_unlocked" \
  memory-unlocked-mcp
```

Use the core package directly:

```python
from memory_unlocked import (
    Memory, Source, Namespace, MemoryStore, ContextAssembler, PolicyError,
)

store = MemoryStore()

store.add(Memory(
    namespace=Namespace("acme", "billing"),
    title="Refunds run through the async queue",
    body="Refund requests are enqueued and processed by a worker, not inline.",
    source=Source(kind="doc", ref="docs/refunds.md"),
    tags=["billing", "architecture"],
))

# Recall is scope-filtered: only memories in the requested namespace come back.
assembler = ContextAssembler(store)
context = assembler.assemble(Namespace("acme", "billing"), query="refund")
print(context)
```

Writes that contain obvious secrets, or that lack a verifiable source, are
rejected at the gate:

```python
store.add(Memory(
    namespace=Namespace("acme", "billing"),
    title="API key",
    body="AWS_SECRET_ACCESS_KEY=AKIA...",   # raises PolicyError
    source=Source(kind="doc", ref="notes.md"),
))
```

---

## Core concepts

| Concept | What it is |
| --- | --- |
| **Memory** | One atomic fact, with a title, body, tags, and a required source. |
| **Source** | Provenance for a memory (a file, URL, ticket, or run id). No source → no write. |
| **Namespace** | A `tenant / project` scope. Recall never crosses namespaces. |
| **Policy / redaction** | A gate every write passes before it is stored. |
| **Context assembler** | Builds a scope-filtered, ranked context block for the agent. |
| **Event** | An append-only record of writes and recalls for auditability. |

---

## Privacy-first guardrails

These are the defaults, not opt-ins:

- **Never store secrets.** Writes are scanned for credential-shaped content and
  rejected. See [`docs/privacy-and-redaction.md`](docs/privacy-and-redaction.md).
- **Every memory needs a source.** Unattributed claims are rejected so memory
  stays verifiable.
- **Scope isolation by default.** A recall in `tenant/project` cannot return a
  memory written under any other scope.
- **No raw transcripts, no PII, no customer/lead data.** Store durable, stable
  facts — not transient progress or personal information.
- **Writes are reviewable.** Every write and recall emits an event so you can
  audit what the memory fabric learned and surfaced.

---

## Documentation

- [Install & CLI](docs/install.md) — package install, JSONL/SQLite stores, CLI commands.
- [Hermes / MCP](docs/hermes.md) — run the MCP server and bind it to a project scope.
- [Semantic graph](docs/graph.md) — typed relation extraction and graph context.
- [Threat model](docs/threat-model.md) — public security boundaries and residual risk.
- [Release checklist](docs/release-checklist.md) — repeatable PyPI/release process.
- [Architecture](docs/architecture.md) — components, data flow, scope policy.
- [Privacy & redaction](docs/privacy-and-redaction.md) — what never to store and
  the write-review flow.
- [Schema](docs/schema.md) — the canonical memory, source, link, and event shapes.
- [Integrations](docs/integrations.md) — MCP / HTTP / CLI patterns for agent runners.

---

## License

MIT — see [LICENSE](LICENSE).
