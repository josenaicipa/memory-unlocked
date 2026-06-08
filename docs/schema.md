# Schema

The canonical shapes Memory Unlocked stores. These are generic and
storage-agnostic — map them onto columns, documents, or graph nodes as needed.
The reference Python package mirrors these as dataclasses.

## Memory

The atomic unit. One memory = one durable fact.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | string | assigned | Stable identifier (assigned on write). |
| `namespace` | Namespace | yes | The `(tenant, project)` scope. |
| `title` | string | yes | Short, human-readable summary. |
| `body` | string | yes | The fact itself. Stable and self-contained. |
| `kind` | enum | no | `fact` \| `decision` \| `convention` \| `reference`. Default `fact`. |
| `tags` | string[] | no | Lowercase keywords for retrieval. |
| `source` | Source | yes | Provenance. A write with no source is rejected. |
| `links` | Link[] | no | Relations to other memories. |
| `created_at` | timestamp | assigned | Set by the store on write. |
| `confidence` | float (0–1) | no | Optional trust weight for ranking. |

### Example

```yaml
id: mem_<uuid>
namespace: { tenant: acme, project: billing }
title: Refunds run through the async queue
body: >
  Refund requests are enqueued and processed by a background worker rather than
  inline in the request handler, to keep checkout latency low.
kind: decision
tags: [billing, architecture, refunds]
source: { kind: doc, ref: docs/refunds.md }
links: []
created_at: 2026-01-01T00:00:00Z
confidence: 0.9
```

## Source

Provenance for a memory. Mandatory — it is what makes a memory verifiable.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `kind` | enum | yes | `doc` \| `url` \| `ticket` \| `commit` \| `run` \| `message`. |
| `ref` | string | yes | A reference within that kind (path, URL, id, run id). |
| `note` | string | no | Optional human context about the source. |

A source `ref` must be non-empty. Use opaque references (a path, a ticket id)
rather than pasting source content into the memory body.

## Link

A typed relation between two memories. Enables a lightweight memory graph.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `rel` | enum | yes | `relates_to` \| `supersedes` \| `contradicts` \| `derived_from`. |
| `target_id` | string | yes | The `id` of the linked memory. |

Links should stay within a namespace. A `supersedes` link is how you retire an
old fact without deleting its history.

## Event

Append-only audit record. Every write and recall emits one.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `type` | enum | yes | `memory.write` \| `memory.recall` \| `memory.reject`. |
| `namespace` | Namespace | yes | Scope the event occurred in. |
| `at` | timestamp | yes | When it happened. |
| `detail` | object | no | Type-specific payload (query, memory id, reject reason). |

Events never contain secret values. A `memory.reject` event records *that* a
write was rejected and *why* (e.g. `reason: secret_detected`) — never the
offending secret itself.

## Namespace

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `tenant` | string | yes | Hard isolation boundary. |
| `project` | string | yes | Soft isolation boundary within a tenant. |

Serialized form: `tenant/project`. Recall matches the full pair exactly.
