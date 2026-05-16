---
roo_mode: review
opencode: true
title: ETL review checklist
---

Reviewing ETL changes, prioritize in this order:

1. Idempotency: can the change run twice without duplicating or corrupting?
2. Failure recovery: where can it crash, and what is the recovery path?
3. Schema drift: does the change tolerate the source adding or renaming a
   column?
4. Observability: are log fields sufficient for an operator to find a failed
   run?
5. Performance: only flag if the change demonstrably regresses runtime or
   memory; do not speculate.
6. Test coverage gaps: name them explicitly, do not generalize.
