# v1.2 Functional Parity Inventory

This inventory compares the public v1.1.0 baseline with an internal reference
only at the capability level. The public implementation is a clean-room,
dependency-free rewrite; it contains no internal memory records, routes,
identities, infrastructure, or operational mappings.

| Capability | v1.1.0 gap | v1.2 public capability |
| --- | --- | --- |
| Namespace classes | Only raw tenant/project pairs | Generic `internal`, `lead`, `customer`, `bot`, and `agent` profile helpers that retain the existing two-field schema. |
| Markdown mirror | Missing | Opt-in, deterministic local Markdown projection of active memories. |
| Dashboard/audit | Audit JSON only | Body-free data snapshot and standalone HTML dashboard. |
| Reflex | Missing | Read-first pre-task context and post-task candidate proposal. |
| Consolidation | Curator suggestions only | Scope-bound, approval-required duplicate merge proposals. |
| Governed assets | Missing | Local versioned asset registry with candidate/active/archive/reject lifecycle. |
| Control loop / Kaizen | Missing | Dry-run remediation report; it never changes state. |
| Semantic namespace/schema review | Schema validation dispersed across writes | Explicit record and namespace review helpers. |
| Retrieval v2 ranking | Hybrid ranking had no explanation surface | Explainable ordinal v2 ranking over the already-authorized set. |
| Channel rollout | Missing | Explicit caller-provided channel contracts and fail-closed validation. |
| Native Hermes provider | MCP only | Generic `memory_fabric` plugin with a `MemoryProvider`, configuration-bound scope, and read-first behavior. |

## Deliberate exclusions

The following reference-system details are not portable and are intentionally
excluded: real memory records and exports; organization-specific project or
channel maps; live deployment/control-loop jobs; credentials and secret
registries; private dashboard metrics; account identifiers; and any host or
network integration. They are operational data or proprietary deployment IP,
not reusable library behavior. The public APIs accept only explicit,
third-party-supplied configuration and data.

## Safety invariants

- Existing `Memory` serialization and its `(tenant, project)` schema are unchanged.
- Ranking, reflexes, consolidation, dashboards, and rollout review operate
  after a caller has selected a namespace; none can widen scope.
- Mirror, asset registry, and provider writes are explicit and local. No module
  contacts a service or ships a memory database.

## Public API entry points

Import these features from `memory_unlocked`: `profile_namespace`,
`MarkdownMirror`, `dashboard_data` / `render_dashboard`, `reflex_pre_task` /
`reflex_post_task`, `plan_consolidation`, `AssetRegistry`,
`control_loop_report`, `review_namespace` / `review_memory_record`, `rank_v2`,
and `build_channel_contracts` / `validate_channel_contracts`. Each accepts
explicit local objects; none discovers projects, channels, or credentials.
