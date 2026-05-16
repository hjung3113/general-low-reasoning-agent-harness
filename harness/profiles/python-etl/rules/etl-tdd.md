---
roo_mode: tdd-code
opencode: true
title: Python ETL TDD discipline
---

When implementing or modifying ETL behavior in this repository, follow these
rules in addition to the universal TDD workflow:

1. Phrase each red test as a row-level or batch-level invariant ("input batch
   {X} produces stage {Y} with row count {Z} and no duplicates"), not as a
   line-of-code assertion.
2. Use the smallest data fixture that can fail meaningfully. Prefer in-memory
   fakes; only touch a real database when the assertion is about engine
   behavior the fake cannot reproduce (e.g. unique-constraint conflicts).
3. Every load step must have at least one test that runs the same input twice
   in a row and asserts the load is idempotent (rerun produces no duplicates,
   no orphaned staging rows).
4. Every transform must have at least one test for the empty-input case.
5. Do not declare a step done without verifying the regression test fails on a
   reverted implementation.
