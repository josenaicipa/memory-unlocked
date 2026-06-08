# Security Policy

Memory Unlocked is designed to reject secrets and isolate agent memory by namespace.

## Reporting vulnerabilities

Use GitHub private vulnerability reporting / security advisories for this repository. Do not open a public issue containing exploit details or sensitive data.

## Supported versions

The latest minor release receives security fixes.

## Security design promises

- Namespace is selected by the operator/runtime, not by the model.
- Rejected writes do not store the rejected content.
- Governance reports omit memory bodies.
- Secret-shaped queries are redacted in audit events.
- The core package does not call external services.

## What not to submit

Please do not send real API keys, credentials, customer records, private internal URLs, or private conversation transcripts in issues, PRs, examples, or tests.
