---
name: workflow-data-processing
description: Use for batch or streaming transformations, file processing, normalization, validation, enrichment, or generated datasets.
---

# Workflow Data Processing

## Workflow

1. Identify inputs, outputs, data contracts, and failure handling.
2. Define transformation stages and invariants.
3. Record idempotency, retry, ordering, and partial failure expectations.
4. Choose fixture or sample verification before execute.
5. Record operational signals needed to trust the process.

## Stop Conditions

- input/output shape is unknown
- error handling is undefined
- rerun behavior is ambiguous
- data loss risk has no rollback plan

