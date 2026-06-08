# Team Memory Example

Use one physical store with separate namespaces per team/project.

```bash
STORE=./.memory-team
memory-unlocked --path "$STORE" write --tenant acme --project support \
  --title "Refund SLA" --body "Support replies to refund requests within one business day." \
  --source examples/team-memory/README.md --tags support,refunds

memory-unlocked --path "$STORE" write --tenant acme --project engineering \
  --title "API style" --body "Public APIs return JSON objects with stable top-level keys." \
  --source examples/team-memory/README.md --tags api,convention

memory-unlocked --path "$STORE" list --tenant acme --project support
memory-unlocked --path "$STORE" list --tenant acme --project engineering
```

The two projects share disk but not recall scope.
