---
name: data-workflow
description: Use for projects or phases involving data ingestion, transformation, analysis, migration, reporting, or generated datasets regardless of language or database.
---

# Data Workflow

Use this skill when the work depends on data shape or data movement.

This skill is intentionally not tied to any language, database vendor, named pipeline style, notebook tool, or framework.

## Workflow

1. Identify inputs, outputs, refresh cadence, ownership, and privacy constraints.
2. Record known schemas or sample shapes with evidence paths.
3. Separate deterministic transformations from exploratory work.
4. Define fixture, sample, or dry-run verification before execute.
5. Stop if production data is required but unavailable or unsafe.

## Do Not Assume

- database vendor
- file format
- notebook usage
- dataframe library
- orchestration tool
- batch or streaming architecture
