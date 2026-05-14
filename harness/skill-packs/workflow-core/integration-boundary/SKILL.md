---
name: integration-boundary
description: Use when a phase touches external services, APIs, queues, databases, filesystems, auth, or deployment boundaries.
---

# Integration Boundary

Use this skill to keep external boundary work explicit.

## Workflow

1. Identify the boundary and owner.
2. Record credentials, environment, rate limits, failure modes, and local substitutes.
3. Decide whether verification can run locally, in CI, or only through a mocked contract.
4. Define rollback and observability expectations.
5. Stop if secrets, production access, or unclear side effects are required.

Do not assume a vendor, protocol, cloud, database, or framework.

