# Hermes / MCP Quickstart

Memory Unlocked exposes a dependency-free MCP stdio server. The important security rule: **Hermes/runtime binds the namespace with environment variables; the model never chooses tenant/project.**

## 5-minute setup

```bash
uv tool install memory-unlocked
mkdir -p "$HOME/.memory-unlocked/acme-demo"
```

Register the MCP server with placeholders adapted to your Hermes setup:

```bash
hermes mcp add memory-unlocked \
  --env MEMORY_UNLOCKED_HOME="$HOME/.memory-unlocked/acme-demo" \
  --env MEMORY_UNLOCKED_BACKEND="sqlite" \
  --env MEMORY_UNLOCKED_TENANT="acme" \
  --env MEMORY_UNLOCKED_PROJECT="demo" \
  -- memory-unlocked-mcp
```

If your Hermes version uses config files instead of `hermes mcp add`, use the equivalent stdio command and environment variables.

## Tools exposed

- `memory_write` — proposes a durable memory for the bound scope. Defaults to `candidate` so model-originated memories can be reviewed before recall; pass `status: "active"` only for trusted automations.
- `memory_recall` — returns structured scope-filtered active matches and context.
- `memory_context` — returns a token-budgeted prompt context block.
- `memory_list` — lists scope-local memories.
- `memory_stats` — counts memories and events for the bound scope.

## Smoke with CLI first

```bash
memory-unlocked --backend sqlite --path "$HOME/.memory-unlocked/acme-demo" write \
  --tenant acme --project demo \
  --title "Hermes MCP configured" \
  --body "The server is bound to tenant acme and project demo." \
  --source docs/hermes.md

memory-unlocked --backend sqlite --path "$HOME/.memory-unlocked/acme-demo" context \
  --tenant acme --project demo --query "Hermes MCP" --token-budget 200
```

## Namespace mapping suggestions

| Runtime scope | Suggested fields |
| --- | --- |
| Personal agent | `tenant=<user-or-org>`, `project=personal` |
| Repo coding agent | `tenant=<org>`, `project=<repo-slug>` |
| Team channel | `tenant=<org>`, `project=<channel-or-team>` |
| Workspace/product | `tenant=<org>`, `project=<product-slug>` |

Never put secrets, emails, phone numbers, account IDs, or internal domains in namespace names for public examples.
