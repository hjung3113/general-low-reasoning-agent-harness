---
roo_mode: diagnose
opencode: true
title: Python data bug tracing
---

For data correctness bugs (wrong row counts, wrong values, duplicates,
missing rows):

1. Identify the smallest reproducing input. If the symptom is at the load
   step, trace one example row backwards through each confirmed stage.
2. At every stage, print or persist that one row's projection. Do not skip a
   stage because "it should be fine"; that is the stage most likely to be
   wrong.
3. Distinguish three failure shapes before proposing a fix:
   - Wrong source data (fix at extract, add validation).
   - Wrong transform (fix transform, add invariant test).
   - Correct transform applied to wrong scope (fix predicate, add scoping test).
4. Do not patch the symptom at the load step if the cause is upstream.
