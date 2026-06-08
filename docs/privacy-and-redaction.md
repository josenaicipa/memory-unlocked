# Privacy & Redaction

Memory Unlocked is privacy-first by construction. This document defines what may
be stored, what must never be stored, and the review flow every write passes
through.

## Principle

> Memory should hold **durable, stable, non-sensitive facts** — the kind of
> thing you would write in a project README. It is not a log, not a transcript,
> and not a data lake.

If a piece of information is transient, sensitive, or personal, it does not
belong in the memory fabric.

## What must never be stored

The policy gate rejects writes that look like any of these. Treat the list as a
floor, not a ceiling — extend it for your domain.

- **Credentials and secrets** — API keys, access tokens, passwords, private
  keys, connection strings, session cookies.
- **Environment values** — contents of `.env` files or any real secret value
  (names are fine in the abstract; values are not).
- **Personal data (PII)** — names tied to identifiers, emails, phone numbers,
  addresses, government ids, payment details.
- **Customer / lead / end-user data** — anything belonging to the people your
  product serves. Keep it in your application's system of record, not memory.
- **Raw transcripts and message dumps** — summarize the durable conclusion
  instead of storing the conversation.
- **Transient progress** — "currently running step 3" is not a memory.

## What is good to store

- Architectural decisions and the reasoning behind them.
- Conventions, naming rules, and project boundaries.
- Stable gotchas ("this build needs flag X because Y").
- References to canonical docs, tickets, or files (as **sources**, not copies).

## The redaction & write-review flow

```
proposed write
      │
      ▼
┌──────────────────────┐
│ 1. Secret scan        │  reject on match (hard fail)
├──────────────────────┤
│ 2. Source check       │  reject if no usable source ref
├──────────────────────┤
│ 3. Optional redaction │  implement if you prefer scrub-over-reject
├──────────────────────┤
│ 4. Scope tagging      │  attach namespace; record provenance
└──────────────────────┘
      │
      ▼
   stored + event emitted
```

1. **Secret scan.** Every model-controlled text field is matched against
   credential-shaped patterns: title, body, source ref, source note, and tags.
   Any match is a hard rejection (`PolicyError`). The write is never stored, not
   even partially.
2. **Source check.** A memory with no usable source reference is rejected.
   Provenance is mandatory so every stored fact is verifiable later.
3. **Optional redaction hook.** The default policy hard-rejects obvious
   credentials instead of trying to scrub them. If your deployment prefers
   scrub-over-reject for borderline content, implement that as an explicit
   policy extension after the hard-fail checks.
4. **Scope tagging.** The namespace is attached and recorded in the event log.

## Human / agent review

Because every write and recall emits an event, you can:

- review what the memory fabric has learned for a given scope before trusting it;
- diff proposed writes against existing memories to catch drift;
- replay the event log to reconstruct how a scope's memory evolved.

For higher-stakes deployments, gate writes behind an explicit approval step:
the agent **proposes**, a reviewer (human or a separate policy agent) **approves**,
and only then does the store commit.

## Public-safe checklist

Before open-sourcing or sharing any memory export:

- [ ] No credentials, tokens, or secret values anywhere.
- [ ] No PII or customer/lead data.
- [ ] No internal hostnames, private URLs, or infrastructure addresses.
- [ ] No raw transcripts.
- [ ] Every memory has a source you are allowed to reference publicly.
- [ ] Namespaces use neutral, non-identifying names in examples.
