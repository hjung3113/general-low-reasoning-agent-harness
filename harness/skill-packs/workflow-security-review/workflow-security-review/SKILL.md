---
name: workflow-security-review
description: Use for changes involving credentials, auth, permissions, network calls, persistence, user data, dependencies, or generated automation.
---

# Workflow Security Review

Use this skill before implementing or releasing changes with trust boundaries.

## Low-Reasoning Contract

Do not treat security as a final checklist. Identify trust boundaries before editing.

## Activation Evidence

- auth, secrets, tokens, keys, or environment variables
- database writes, migrations, file writes, uploads, or exports
- network calls, webhooks, queues, MCP servers, plugins, or connectors
- dependency, CI, release, or installer changes

## Stop Conditions

- secret handling is unclear
- production data is needed for verification
- permissions or destructive operations are not approved
- generated scripts would run unreviewed external code

## Workflow

1. Identify assets, actors, entry points, and trust boundaries.
2. Record sensitive data and secret handling.
3. Check least privilege and write/destructive actions.
4. Define abuse cases and failure modes.
5. Add verification that does not expose secrets.
6. Record residual risk before release.

## Output Contract

```yaml
assets: []
trust_boundaries: []
secret_handling: ""
write_or_destructive_actions: []
abuse_cases: []
verification: []
residual_risk: []
```

