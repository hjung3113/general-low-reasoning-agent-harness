# Adopt Existing Harness Install Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add opt-in `upgrade --adopt-existing` support for manually copied harness targets without weakening normal upgrade safety.

**Architecture:** Keep implementation inside `scripts/harness.py`. Add an adoption preflight that builds safe in-memory install state only for selected manifest entries, then routes into the existing upgrade loop with a flag that suppresses install-state writes on conflict. Preserve the existing managed-append planner and whole-file `--force` semantics.

**Tech Stack:** Python standard library, `unittest`, existing manifest-driven harness installer.

---

### Task 1: CLI and Missing-State Routing

**Files:**
- Modify: `scripts/harness.py`
- Test: `scripts/test_harness.py`

- [ ] **Step 1: Write failing tests**

Add tests proving `upgrade --adopt-existing` accepts a missing-state target while normal `upgrade` still refuses it:

```python
def test_upgrade_adopt_existing_creates_install_state_for_manual_target(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        target = Path(tmpdir) / "target"
        harness.run(["init", "--target", str(target), "--adapters", "none"])
        (target / ".harness/installed-manifest.json").unlink()

        result = harness.run(["upgrade", "--target", str(target), "--adopt-existing", "--adapters", "none"])

        self.assertEqual(0, result)
        installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(harness.HARNESS_VERSION, installed["version"])
        self.assertEqual([], installed["adapters"])
        self.assertIn("AGENTS.md", installed["files"])
        self.assertIn(".gitignore", installed["files"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest scripts.test_harness.HarnessTests.test_upgrade_adopt_existing_creates_install_state_for_manual_target`
Expected: FAIL because `--adopt-existing` is unknown or upgrade still reports "not initialized".

- [ ] **Step 3: Add CLI option and route**

Add `upgrade_parser.add_argument("--adopt-existing", action="store_true", ...)`, pass it into `upgrade`, and allow missing install state only when this flag is set.

- [ ] **Step 4: Verify green for this test**

Run the same unittest. Expected: PASS after adoption state support from Task 2 is present.

### Task 2: Adoption Preflight and State Builder

**Files:**
- Modify: `scripts/harness.py`
- Test: `scripts/test_harness.py`

- [ ] **Step 1: Write failing safety tests**

Add tests for whole-file conflict without `--force`, whole-file overwrite with `--force`, project-owned preservation, and install-state non-creation on conflict.

- [ ] **Step 2: Run tests to verify they fail**

Run focused unittest names for the new adoption tests. Expected: FAIL until adoption preflight exists.

- [ ] **Step 3: Implement `build_adopted_install_state`**

Create a helper that accepts `root`, `target`, `entries`, `adapters`, `profiles`, `packs`, and `force`. It should:

- validate destination paths and symlink safety for selected existing destinations;
- seed top-level install-state metadata;
- record current source-matching `harness-owned`/`managed` entries;
- leave forced differing whole-file entries unrecorded so upgrade overwrites them;
- conflict differing whole-file entries when `force=False`;
- record existing `project-owned` destinations without causing upgrade writes;
- collect conflicts before any write.

- [ ] **Step 4: Wire upgrade state writes**

When `adopt_existing=True`, do not write `.harness/installed-manifest.json` if adoption preflight or upgrade returns conflicts. Outside dry-run, conflict artifacts may be written by normal upgrade, but install state must remain absent on exit code `1`.

### Task 3: Managed-Append Adoption

**Files:**
- Modify: `scripts/harness.py`
- Test: `scripts/test_harness.py`

- [ ] **Step 1: Write failing managed-append tests**

Add tests for:

- existing `.gitignore` without marker gets marker appended and project lines preserved;
- existing current marker is recorded without rewrite;
- existing marker with local edit inside block conflicts and preserves file;
- malformed marker fails before earlier selected files are modified;
- dry-run adoption has no state or conflict artifacts.

- [ ] **Step 2: Run tests to verify they fail**

Run the focused managed-append adoption tests. Expected: FAIL until marker preflight exists.

- [ ] **Step 3: Implement marker adoption checks**

In `build_adopted_install_state`, parse existing marker blocks. If absent, leave unrecorded. If malformed, conflict. If present, accept only when current block equals rendered source block or payload-normalized content matches current source. Local payload edits conflict.

- [ ] **Step 4: Verify managed-append tests**

Run the focused managed-append adoption tests. Expected: PASS.

### Task 4: Documentation and Compatibility Verification

**Files:**
- Modify: `README.md`
- Test: `scripts/test_harness.py`

- [ ] **Step 1: Add README usage**

Document `upgrade --adopt-existing` as an opt-in path for manual/old harness targets, including the warning that explicit scope flags may be needed and `--force` keeps its narrow meaning.

- [ ] **Step 2: Run full verification**

Run:

```bash
python3 -m unittest scripts/test_harness.py
python3 scripts/harness.py check
python3 scripts/release_smoke_test.py
```

Expected: all commands exit `0`.

- [ ] **Step 3: Real-target smoke**

Run against `../New project`:

```bash
python3 scripts/harness.py upgrade --target "../New project" --adopt-existing --force --dry-run
python3 scripts/harness.py upgrade --target "../New project" --adopt-existing --force
python3 scripts/harness.py check --target "../New project"
```

Expected: dry-run has no side effects; real upgrade creates `.harness/installed-manifest.json`; check exits `0`. If scope is not default Roo + generic + workflow-core, rerun with explicit `--adapters`, `--profiles`, and `--packs`.
