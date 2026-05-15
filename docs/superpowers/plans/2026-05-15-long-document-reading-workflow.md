# Long Document Reading Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lightweight planning-document reading protocol that reduces repeated broad reads and subagent context loops without changing canonical planning memory.

**Architecture:** Keep `AGENTS.md` as a short routing layer and place detailed rules in `.planning/workflows/long-document-reading.md`. The workflow treats indexes and slices as routing aids, preserves `.planning/**` as canonical memory, and requires explicit approval before creating slice documents.

**Tech Stack:** Markdown documentation only.

---

### Task 1: Add Routing Trigger

**Files:**
- Modify: `AGENTS.md`

- [x] **Step 1: Add a concise trigger section**

Insert a `Planning Document Reads` section after `Planning State` that points to `.planning/workflows/long-document-reading.md` for broad planning reads, repeated reads, subagent planning/spec review, or loop detection.

- [x] **Step 2: Keep the trigger root-only**

Do not modify `harness/skeleton/clean/AGENTS.md` in this task because the workflow is repository-specific until generalized for downstream harness installs.

### Task 2: Add Workflow Details

**Files:**
- Create: `.planning/workflows/long-document-reading.md`

- [x] **Step 1: Create the workflow document**

Document the entry order, canonical truth rule, definitions for full reads and attempts, stop conditions after repeated broad reads, subagent delegation discipline, and slice approval rules.

- [x] **Step 2: Include explicit low-reasoning guardrails**

Define valid and invalid subagent assignment examples, require exact missing headings/ranges when context is insufficient, and prohibit repeated full-document scans after three unsuccessful broad attempts.

### Task 3: Verify

**Files:**
- Verify: `AGENTS.md`
- Verify: `.planning/workflows/long-document-reading.md`
- Verify: `docs/superpowers/plans/2026-05-15-long-document-reading-workflow.md`

- [x] **Step 1: Run repository status gate**

Run: `python3 scripts/show_phase_status.py`

Expected: Command succeeds; docs/workflow edits remain within explicitly requested allowed change type.

- [x] **Step 2: Run harness verification**

Run: `python3 scripts/harness.py check`

Expected: Command exits 0.

- [x] **Step 3: Inspect git diff**

Run: `git diff -- AGENTS.md .planning/workflows/long-document-reading.md docs/superpowers/plans/2026-05-15-long-document-reading-workflow.md`

Expected: Diff is limited to the requested documentation/workflow changes.
