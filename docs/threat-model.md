# Threat Model

Memory Unlocked assumes an AI agent can propose memory writes and ask for recall, but should not be trusted with storage scope or secret decisions.

## Assets

- Durable memories and provenance metadata.
- Audit event log.
- Namespace boundaries between tenants/projects/channels/workspaces.
- Operator trust that recalled context is safe to put into a model prompt.

## Trust boundaries

1. **Operator/runtime boundary:** chooses `tenant`, `project`, backend, and store path.
2. **Model/tool boundary:** model can propose title/body/source/tags/query, but not widen namespace.
3. **Persistence boundary:** JSONL/SQLite is local; backups/export may leave the machine and must be reviewed.

## Main threats and mitigations

| Threat | Mitigation |
| --- | --- |
| Model stores a secret | policy gate scans title/body/source/tags and rejects before persistence |
| Rejection leaks the secret | reject events contain reason codes only, never rejected content |
| Model reads another project | namespace is server/CLI configured and query filters before ranking |
| Prompt injection inside memory | context renderer marks memory as untrusted data and strips control-like wrappers |
| Oversized memory floods context | write size limits and token-budget context assembly |
| Stale/bad memory keeps influencing agent | lifecycle statuses and governance audit/review commands |
| Duplicates crowd useful recall | duplicate groups in governance reports and ranking dedupe |
| Public repo exposes private deployment details | docs/examples use generic placeholders only |

## Residual risk

Regex-based DLP is not complete. Treat Memory Unlocked as a strong default safety layer, not a replacement for organizational DLP, human review, encryption, and access control.
