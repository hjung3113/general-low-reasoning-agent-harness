# Remote Source Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let installed targets remember the harness git remote/ref used at install time so later upgrades default to the same public or internal repository.

**Architecture:** `scripts/harness.py init` records optional source provenance in `.harness/installed-manifest.json`. `scripts/upgrade_harness.py` reads that provenance and uses it as the default repository unless the user passes `--repo`, `--source`, or another explicit source selector.

**Tech Stack:** Python standard library, existing unittest suite, existing manifest/install state model.

---

### Task 1: Test Install-Time Provenance

**Files:**
- Modify: `scripts/test_harness.py`
- Modify: `scripts/harness.py`

- [ ] Add a test that patches git metadata discovery and asserts `init` records `source_provenance.repo`, `ref`, `commit`, and `version`.
- [ ] Run the focused test and verify it fails because `init` does not record git provenance yet.
- [ ] Implement minimal provenance discovery and install-state recording.
- [ ] Re-run the focused test and verify it passes.

### Task 2: Test Upgrade Bootstrap Defaults

**Files:**
- Modify: `scripts/test_harness.py`
- Modify: `scripts/upgrade_harness.py`

- [ ] Add a test that writes installed provenance with an internal repo and runs `upgrade_harness.py --version ... --dry-run` without `--repo`.
- [ ] Verify the dry-run output uses the installed internal repo rather than the built-in public default.
- [ ] Add a second assertion that explicit `--repo` still wins.
- [ ] Implement installed provenance parsing and default repo selection.
- [ ] Re-run the focused tests and verify they pass.

### Task 3: Document Commands and Fallbacks

**Files:**
- Modify: `README.md`
- Modify: `harness/skeleton/clean/README.md`

- [ ] Document one-command remote clone plus interactive install.
- [ ] Document internal mirror upgrade defaulting and explicit fallback with `--repo` and `--source`.
- [ ] Keep examples stack-neutral and avoid claiming automatic auth handling beyond git.

### Task 4: Verify and Smoke Test

**Files:**
- Test only: `../rooenvtest`

- [ ] Run `python3 -m unittest scripts/test_harness.py`.
- [ ] Run `python3 scripts/harness.py check`.
- [ ] Run `git diff --cached --check`.
- [ ] Run a dry-run upgrade in `../rooenvtest` using this local source.
- [ ] Inspect the diff and confirm only expected files changed.

### Adversarial Review

- Explicit `--repo` must override installed provenance.
- Missing or malformed installed provenance must fall back to the current default repo.
- Local `--source` upgrades must keep recording path provenance.
- Dry-run must not clone or mutate `.harness/sources`.
- Stored provenance must not require public repo access when the target was installed from an internal mirror.
