# Graph Basic Example

This example uses only generic public data.

```bash
STORE=./.memory-graph
memory-unlocked --path "$STORE" init

memory-unlocked --path "$STORE" write \
  --tenant acme --project demo \
  --title "Graph demo" \
  --body "Billing service owns refunds. Worker depends on Redis. CRM is the source of truth for revenue." \
  --source examples/graph-basic/README.md

memory-unlocked --path "$STORE" graph \
  --tenant acme --project demo --json

memory-unlocked --path "$STORE" graph-context \
  --tenant acme --project demo --token-budget 200
```

Expected graph relations include:

- `billing service --owns--> refunds`
- `worker --depends_on--> redis`
- `crm --source_of_truth_for--> revenue`
