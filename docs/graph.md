# Semantic Graph

Memory Unlocked v0.3.2 includes a small, deterministic semantic graph layer over stored memories plus public-safe temporal, lineage, and effective-backend graph reports.

It is **not** a visual graph UI yet. It is an agent-facing backend feature: turn stable memory prose into compact, typed relations that can be recalled safely.

## What it extracts

Semantic relation vocabulary:

- `owns`
- `routes_to`
- `separate_from`
- `uses_provider`
- `fallback_provider`
- `deploys_to`
- `source_of_truth_for`
- `sensitive_write`
- `depends_on`
- `supersedes`

Low-priority fallback:

- `co_occurs`

Entity kinds:

- `project`
- `channel`
- `repo`
- `url`
- `provider`
- `service`
- `workflow`
- `decision`
- `source_of_truth`
- `module`
- `topic`

## Examples

```text
Billing service owns refunds.
Worker depends on Redis.
Landing AI usa Gemini. CallCenter usa OpenAI. fallback a local_ollama.
CRM es la fuente de verdad de revenue.
No mezclar ventas con soporte.
```

The fallback example binds `fallback_provider` to the nearest preceding subject (`callcenter`), not to the first subject in the memory.

## CLI

```bash
memory-unlocked --path ./.memory write \
  --tenant acme --project demo \
  --title "Graph demo" \
  --body "Billing service owns refunds. Worker depends on Redis." \
  --source docs/graph.md

memory-unlocked --path ./.memory graph \
  --tenant acme --project demo --json

memory-unlocked --path ./.memory graph-context \
  --tenant acme --project demo --token-budget 200

memory-unlocked --path ./.memory graph-temporal \
  --tenant acme --project demo --json

memory-unlocked --path ./.memory graph-lineage \
  --tenant acme --project demo --json

memory-unlocked --path ./.memory graph-effective-backend \
  --tenant acme --project demo --json
```

## Public-safe graph report surfaces

- `graph-temporal` / `memory_graph_temporal` — current/historical relation rows using the source memory timestamp as `valid_from`; no raw ids or source refs.
- `graph-lineage` / `memory_graph_lineage` — relation evidence and source-memory lineage as opaque handles (`r1`, `m1`) with PII/secret redaction.
- `graph-effective-backend` / `memory_graph_effective_backend` — scoped graph payload for agent readers with `effective_backend=memory_unlocked`, `dry_run=true`, and `writes_performed=0`.

These are deliberately read-only. They are safe to expose over the MCP stdio server because the namespace is still bound by the runtime, not by the model.

## MCP

The MCP server exposes:

- `memory_graph_context`
- `memory_graph_temporal`
- `memory_graph_lineage`
- `memory_graph_effective_backend`

It returns compact, public-safe semantic graph data for the runtime-bound namespace.

## Safety model

- Extraction is deterministic regex only: no LLM extraction, no network calls.
- Graph extraction receives already scope-filtered memories and re-checks namespace.
- Entity/relation names pass the secret/PII detectors; unsafe fragments are dropped.
- Reports and context never include raw memory bodies.
- Generic aliasing only; the public package has no private channel/project/domain map.

## Governance

`graph` reports include warnings for:

- no semantic relations found;
- many low-priority co-occurrence edges;
- duplicate/noisy entity names.

Use those warnings to rewrite memories into clearer relation phrasing like `X owns Y`, `X uses_provider Y`, or `X source_of_truth_for Y`.
