# Mid-Stream Phase Addition Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lightweight workflow for handling user requests to add or split phases while preserving the active phase gate and the harness lifecycle.

**Architecture:** Keep `AGENTS.md` as a short routing layer and place detailed rules in `.planning/workflows/mid-stream-phase-addition.md`. The workflow treats mid-stream phase additions as proposals until a separate phase lifecycle opens the execute gate.

**Tech Stack:** Markdown documentation only.

---

### Task 1: Add Routing Trigger

**Files:**
- Modify: `AGENTS.md`

- [x] **Step 1: Add the trigger section**

Add a `Mid-Stream Phase Additions` section that routes phase-addition, scope-split, deferral, and phase-sized decision-record requests to `.planning/workflows/mid-stream-phase-addition.md`.

- [x] **Step 2: Preserve execute gate authority**

State that the routing rule does not change `.scratch/phase-state.json` and does not authorize setting `phase=execute` or `approved=true`.

### Task 2: Add Workflow Details

**Files:**
- Create: `.planning/workflows/mid-stream-phase-addition.md`

- [x] **Step 1: Define triggers and entry order**

Document trigger phrases, non-trigger examples, `show_phase_status.py` as the first read, status-warning handling, and fallback behavior.

- [x] **Step 2: Define authority and core rule**

Document that the workflow grants routing authority only, not edit authority, and that ADRs, decision records, ROADMAP entries, and phase context notes do not open the execute gate.

- [x] **Step 3: Define compatibility and command mapping**

Document ROADMAP compatibility, decision-record criteria, safe user command mapping, and bounded subagent delegation.

### Task 3: Verify

**Files:**
- Verify: `AGENTS.md`
- Verify: `.planning/workflows/mid-stream-phase-addition.md`
- Verify: `docs/superpowers/plans/2026-05-16-mid-stream-phase-addition-workflow.md`

- [x] **Step 1: Run repository status gate**

Run: `python3 scripts/show_phase_status.py`

Expected: Command succeeds; docs/workflow edits remain within explicitly requested allowed change type.

- [x] **Step 2: Run harness verification**

Run:

```bash
python3 -m unittest scripts/test_harness.py
python3 scripts/harness.py check
python3 scripts/harness.py check --worktree
python3 scripts/release_smoke_test.py
```

Expected: All commands exit 0.

- [x] **Step 3: Run adversarial workflow review**

Ask a subagent to review compatibility with existing projects, phase lifecycle integrity, phase-state gate preservation, canonical `.planning/**`, and low-reasoning behavior.
