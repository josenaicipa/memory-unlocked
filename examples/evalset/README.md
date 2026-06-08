# Evalset Example

Run:

```bash
memory-unlocked eval examples/evalset/basic.json
```

The eval verifies:

- expected memories are recalled for a scoped query;
- another namespace does not leak those memories;
- context stays inside the requested token budget.
