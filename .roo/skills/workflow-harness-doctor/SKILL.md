---
name: workflow-harness-doctor
trigger: Use when the user invokes /doctor or asks for harness diagnostics, document/Roo drift, DB context readiness, or mutation-readiness checks.
description: Runs read-only harness diagnostics for planning, Roo command/mode, DB context config, and diff-before-mutation readiness.
---

# Workflow: Harness Doctor

## Purpose

Use this workflow to diagnose harness drift before repair work starts. It is read-only and must not mutate files.

## Steps

1. Read `AGENTS.md`, `.planning/STATE.md`, `.planning/ROADMAP.md`, the active checkpoint, `.planning/codebase/**`, active phase docs, and `.scratch/phase-state.json`.
2. Run `python3 scripts/harness.py doctor` or `python3 scripts/harness.py doctor --format json`.
3. Report findings using the script vocabulary: `severity`, `code`, `path`, `cause`, `impact`, `fix`, `evidence`, and `connects_to_db`.
4. Treat P0/P1 findings as blockers before PR, merge, or implementation.
5. For any repair, run or describe a diff-before-mutation path first, such as `python3 scripts/harness.py upgrade --target <path> --dry-run` and `git diff`.

## Stop Conditions

- Do not edit files from `/doctor`.
- Do not connect to a database.
- Do not treat a P3 diff-before-mutation advisory as failure by itself.
- If the user asks to apply fixes, route to the owning workflow and require an approved phase gate when files will be edited.
