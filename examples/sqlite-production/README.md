# SQLite Production Example

SQLite is the recommended single-machine backend once you move beyond quick demos.

```bash
STORE=/var/lib/memory-unlocked/acme-demo
memory-unlocked --backend sqlite --path "$STORE" init

memory-unlocked --backend sqlite --path "$STORE" write \
  --tenant acme --project demo \
  --title "SQLite selected" \
  --body "This deployment uses local SQLite for durable agent memory." \
  --source examples/sqlite-production/README.md \
  --tags production,sqlite

memory-unlocked --backend sqlite --path "$STORE" stats
```

Operational notes:

- Back up `memory.db` like any other local database.
- Use file permissions so only the agent runtime user can read the store.
- Keep `.env` and other secrets outside the store path.
- Use `memory-unlocked audit --json` before exports.
