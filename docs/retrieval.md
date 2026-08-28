# Retrieval

Recall always runs **after** the store has filtered by tenant, project, thread,
status, and TTL. Ranking can only reorder or drop that authorized set.

## Modes

| Mode | What it is | Default |
| --- | --- | --- |
| `classic` | v1.0 blended lexical/confidence/recency/status scorer | **yes** |
| `lexical` | Okapi BM25 over the authorized set | opt-in |
| `vector` | Local token-hash cosine similarity (no network, no paid API) | opt-in |
| `hybrid` | Reciprocal Rank Fusion of BM25 + vector, then bounded metadata boosts | opt-in |

v1.0.0 callers that omit `--mode` keep the classic ranking.

The local vector is a hashing trick, not a semantic encoder. It keeps hybrid
ranking deterministic and dependency-free. Fusion refuses any id that was not
in the authorized candidate set.

## CLI

```bash
memory-unlocked --path ./mem recall \
  --tenant acme --project billing \
  --query "refund worker" \
  --mode hybrid
```

## MCP

`memory_recall` and `memory_context` accept optional `mode`. The model still
cannot name a namespace or thread.
