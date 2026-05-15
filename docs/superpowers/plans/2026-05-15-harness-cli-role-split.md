# Harness CLI Role Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the harness command surface into clearer source-side and target-side scripts while preserving `scripts/harness.py` compatibility, target-local upgrade, install-state version provenance, and existing upgrade safety.

**Architecture:** Keep `scripts/harness.py` as the compatibility dispatcher and source-side policy engine for the first implementation slice. Add thin human-facing scripts for install, upgrade, check, doctor, and release workflows that delegate into `scripts/harness.py` instead of reimplementing policy. Defer deep module extraction until wrapper behavior, version provenance, and target-local upgrade UX are verified.

**Tech Stack:** Python standard library, `argparse`, `unittest`, existing manifest-driven harness installer, Git/GitHub release source retrieval through subprocess only.

---

## File Map

- Create: `scripts/install_harness.py` - source-side install CLI with `--interactive` wizard and the existing flag path.
- Create: `scripts/upgrade_harness.py` - target-side upgrade bootstrapper with `--version`, `--source`, `--repo`, `--ref`, `--dry-run`, `--force`, `--adopt-existing`, scope flags, and delegation to the resolved source-side engine.
- Create: `scripts/check_harness.py` - target self-check CLI. It must not claim to replace source-side `check --target`.
- Create: `scripts/doctor_harness.py` - target diagnostics CLI.
- Create: `scripts/release_harness.py` - source release-check CLI.
- Modify: `scripts/harness.py` - keep all existing subcommands, improve dry-run output, and record delegated source provenance when provided by the bootstrapper.
- Modify: `harness/manifest.json` - install target-side scripts and required target-side libraries only.
- Modify: `README.md` and `harness/skeleton/clean/README.md` - document clear source/target command use and target-local release upgrade.
- Modify: `docs/script-oriented-harness-workflow.md` - record the clarified split, version provenance rule, and self-check vs source-check distinction.
- Modify: `scripts/test_harness.py` - add regression tests for wrappers, target-local upgrade bootstrap, version stamping, dry-run output, manifest entries, and legacy compatibility.

## Non-Negotiable Contracts

- `scripts/harness.py` remains valid for `init`, `upgrade`, `check`, `doctor`, and `release-check`.
- Target-local `upgrade_harness.py` may locate or download a release source, but it must delegate actual mutation to source-side distribution logic.
- A selected release version must be passed through as `--version vMAJOR.MINOR.PATCH`; release archives without `.git` must not stamp `0.0.0-dev+unknown`.
- Target self-check validates the installed target against its recorded install state. Source-side check validates a target against the current source manifest and is still required after upgrade.
- `--adopt-existing`, managed-append markers, retired files, `.new`/`.retired`/`.adopted` conflicts, symlink safety, remembered scope, and project-owned preservation must remain behaviorally unchanged.
- Dry-run commands must print the selected source/version, target path, planned mutation summary, conflicts, and `no mutation performed`.
- Before application-code style edits, confirm this work is explicitly user-requested harness tooling work. If the live gate is not `phase=execute`, do not broaden beyond `scripts/`, `harness/`, `README.md`, and docs explicitly named in this plan.
- Real sibling target smoke against `../new project` must be non-mutating unless the user gives a separate explicit approval. Mutating smoke must use a temporary copy.

---

### Task 1: Add Behavior Locks and Compatibility Tests

**Files:**
- Test: `scripts/test_harness.py`

- [ ] **Step 1: Add behavior-lock tests for existing version and upgrade-source resolution**

Add tests that prove:

```python
def test_target_local_upgrade_uses_recorded_source_tree(self) -> None:
    source = harness.repo_root()
    with tempfile.TemporaryDirectory() as tmpdir:
        target = Path(tmpdir) / "target"
        harness.run(["--version", "v9.8.7", "init", "--target", str(target), "--adapters", "none"])
        installed_path = target / ".harness/installed-manifest.json"
        installed = json.loads(installed_path.read_text(encoding="utf-8"))
        installed["source"] = str(source)
        installed_path.write_text(json.dumps(installed), encoding="utf-8")

        with mock.patch.object(harness, "repo_root", return_value=target):
            result = harness.run(["--version", "v9.8.8", "upgrade", "--target", str(target), "--dry-run"])

        self.assertEqual(0, result)
```

Also keep the existing release-version tests green.

- [ ] **Step 2: Add installed compatibility test**

Add a test that installs a target, then runs the installed target's compatibility command:

```python
result = subprocess.run(
    [sys.executable, str(target / "scripts/harness.py"), "upgrade", "--target", str(target), "--dry-run"],
    cwd=target,
    capture_output=True,
    text=True,
)
self.assertEqual(0, result.returncode, result.stderr)
```

This proves `scripts/harness.py upgrade --target .` remains valid after wrappers are added.

- [ ] **Step 3: Verify compatibility**

Run:

```bash
python3 -m unittest scripts/test_harness.py
python3 scripts/harness.py check
```

Expected: both commands exit `0`.

### Task 2: Add Explicit Dry-Run Planning Output

**Files:**
- Modify: `scripts/lib/harness_distribution.py`
- Modify: `scripts/harness.py`
- Test: `scripts/test_harness.py`

- [ ] **Step 1: Add dry-run output tests**

Add tests proving:

```python
def test_init_dry_run_reports_selected_scope_and_no_mutation(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        target = Path(tmpdir) / "target"
        result = subprocess.run(
            [
                sys.executable,
                str(Path("scripts/harness.py")),
                "init",
                "--target",
                str(target),
                "--adapters",
                "opencode",
                "--packs",
                "workflow-core,workflow-tdd",
                "--dry-run",
            ],
            cwd=harness.repo_root(),
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, result.returncode)
        self.assertIn("dry-run", result.stdout)
        self.assertIn("target=", result.stdout)
        self.assertIn("adapters=opencode", result.stdout)
        self.assertIn("packs=workflow-core,workflow-tdd", result.stdout)
        self.assertIn("no mutation performed", result.stdout)
        self.assertFalse(target.exists())
```

Add an upgrade dry-run test that creates a conflict and asserts the conflict path is printed.

- [ ] **Step 2: Implement a small dry-run report object**

Add a report builder that records:

```python
command
target
source
version
adapters
profiles
packs
planned_writes
planned_appends
planned_removals
conflicts
dry_run
```

Print concise text output by default. Do not make JSON the default for human commands.

- [ ] **Step 3: Preserve existing return codes**

Keep `upgrade` returning `1` when conflicts exist and `0` otherwise. Dry-run must not write `.harness/installed-manifest.json` or `.harness/conflicts/**`.

- [ ] **Step 4: Verify**

Run:

```bash
python3 -m unittest scripts.test_harness.HarnessToolTests
```

Expected: PASS.

### Task 3: Add Source-Side Install CLI and Interactive Wizard

**Files:**
- Create: `scripts/install_harness.py`
- Modify: `scripts/harness.py`
- Test: `scripts/test_harness.py`

- [ ] **Step 1: Add wrapper tests**

Add tests proving `scripts/install_harness.py` produces the same install state as `scripts/harness.py init` for non-interactive flags.

- [ ] **Step 2: Implement non-interactive wrapper**

`scripts/install_harness.py` must parse:

```text
--target PATH
--dry-run
--adapters VALUE
--profiles VALUE
--packs VALUE
--version VALUE
--interactive
```

For non-interactive mode, call the same distribution engine as `harness.py init`.

- [ ] **Step 3: Implement dependency-free interactive prompts**

Use standard input/output only. Prompt in this order:

1. target path;
2. adapter selection: `roo`, `opencode`, `both`, `none`;
3. profile selection: single or comma list from available profiles;
4. pack selection: comma-separated numbers, always showing `workflow-core` as recommended;
5. dry-run confirmation before mutation.

Print the final equivalent command before executing.

- [ ] **Step 4: Verify**

Run:

```bash
python3 -m unittest scripts/test_harness.py
python3 scripts/install_harness.py --target /tmp/harness-install-smoke --adapters none --packs none --dry-run
```

Expected: tests pass and dry-run prints no mutation.

### Task 4: Add Target-Local Upgrade Bootstrapper With Version Provenance

**Files:**
- Create: `scripts/upgrade_harness.py`
- Modify: `scripts/harness.py`
- Modify: `harness/manifest.json`
- Test: `scripts/test_harness.py`

- [ ] **Step 1: Add bootstrap tests**

Add tests proving:

```python
def test_upgrade_harness_source_option_delegates_with_version(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        source = harness.repo_root()
        target = Path(tmpdir) / "target"
        harness.run(["--version", "v1.0.0", "init", "--target", str(target), "--adapters", "none"])

        result = subprocess.run(
            [
                sys.executable,
                str(target / "scripts/upgrade_harness.py"),
                "--source",
                str(source),
                "--version",
                "v1.2.3",
                "--dry-run",
            ],
            cwd=target,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, result.returncode)
        self.assertIn("selected version=v1.2.3", result.stdout)
        self.assertIn("delegating", result.stdout)
        self.assertIn("no mutation performed", result.stdout)
```

Add a real upgrade test without `--dry-run` that asserts `.harness/installed-manifest.json["version"] == "1.2.3"`.

- [ ] **Step 2: Record and validate delegated source provenance**

When `upgrade_harness.py` delegates, pass environment variables:

```text
HARNESS_DELEGATED_SOURCE_KIND=path|release|ref|recorded-source
HARNESS_DELEGATED_SOURCE_REF=<version-or-ref-or-path>
HARNESS_DELEGATED_SOURCE_VERSION=<normalized-version-if-known>
```

`scripts/harness.py upgrade` must record these values in `.harness/installed-manifest.json` under:

```json
"source_provenance": {
  "kind": "path",
  "ref": "/path/to/source",
  "version": "1.2.3"
}
```

If `--version vX.Y.Z` is provided with `--source PATH`, require the source manifest to exist and the delegated command to stamp `X.Y.Z`. Do not assert the arbitrary local source is actually a matching git tag unless `--verify-source-tag` is added in a later phase.

- [ ] **Step 3: Implement source resolution order**

`scripts/upgrade_harness.py` resolves source in this order:

1. `--source PATH`;
2. `--version vX.Y.Z` by cloning/downloading the configured repo into `.harness/sources/<version>/`;
3. `--repo URL --ref REF` into `.harness/sources/<safe-ref>/`;
4. installed `.harness/installed-manifest.json["source"]`;
5. fail with a message that names `--source` and `--version`.

For the first implementation, if network release retrieval is not yet available, implement the path and recorded-source flows and make `--version` without `--source` fail with a clear unsupported message. Add the release retrieval in Task 5.

- [ ] **Step 4: Delegate instead of reimplementing**

Run:

```python
[
    sys.executable,
    str(source / "scripts/harness.py"),
    "--version",
    selected_version,
    "upgrade",
    "--target",
    str(target),
    ...
]
```

Pass through `--dry-run`, `--force`, `--adopt-existing`, `--adapters`, `--profiles`, and `--packs`.

- [ ] **Step 5: Install bootstrapper in manifest**

Add `scripts/upgrade_harness.py` to `harness/manifest.json` as `harness-owned`. Do not install source-only `install_harness.py` or `release_harness.py`.

- [ ] **Step 6: Verify**

Run:

```bash
python3 -m unittest scripts/test_harness.py
python3 scripts/harness.py check
```

Expected: PASS.

### Task 5: Add GitHub Release/Ref Source Retrieval

**Files:**
- Modify: `scripts/upgrade_harness.py`
- Test: `scripts/test_harness.py`

- [ ] **Step 1: Add retrieval command-construction tests**

Mock `subprocess.check_call` and assert:

```python
git clone --depth 1 --branch v1.2.3 <repo> .harness/sources/v1.2.3
```

is used for `--version v1.2.3` when the source cache is missing.

- [ ] **Step 2: Implement default repo constant**

Define:

```python
DEFAULT_HARNESS_REPO = "https://github.com/hjung3113/general-low-reasoning-agent-harness.git"
```

Allow `--repo` to override it. Keep `--ref` for non-release refs. For `--version`, normalize to `vX.Y.Z` for clone branch and pass `--version vX.Y.Z` to delegated upgrade.

- [ ] **Step 3: Cache sources safely**

Clone into `.harness/sources/<normalized-ref>/`. If the directory exists and contains `harness/manifest.json`, reuse it. If it exists without a manifest, fail and ask the user to remove the bad cache path.

- [ ] **Step 4: Verify mocked tests**

Run:

```bash
python3 -m unittest scripts.test_harness.HarnessToolTests.test_upgrade_harness_version_clones_release_source
```

Expected: PASS.

### Task 6: Add Target Check/Doctor/Release Wrappers

**Files:**
- Create: `scripts/check_harness.py`
- Create: `scripts/doctor_harness.py`
- Create: `scripts/release_harness.py`
- Modify: `scripts/harness.py`
- Modify: `harness/manifest.json`
- Test: `scripts/test_harness.py`

- [ ] **Step 1: Add wrapper equivalence tests**

Assert:

```python
python3 scripts/check_harness.py
python3 scripts/harness.py check
```

both pass in an installed target, and:

```python
python3 scripts/doctor_harness.py --format json
python3 scripts/harness.py doctor --format json
```

return the same JSON object.

- [ ] **Step 2: Implement wrappers**

`check_harness.py` calls the same check helper as `harness.py check` and exposes `--target`, `--base`, `--worktree`, and `--adapter`.

`doctor_harness.py` exposes `--target` and `--format markdown|json`.

`release_harness.py` exposes `--expected-version` and `--require-origin-main`; do not install this file into targets.

- [ ] **Step 3: Manifest target-side wrappers**

Install only:

```text
scripts/upgrade_harness.py
scripts/check_harness.py
scripts/doctor_harness.py
```

Do not install:

```text
scripts/install_harness.py
scripts/release_harness.py
scripts/lib/harness_release.py unless a target-installed wrapper imports it
```

- [ ] **Step 4: Verify**

Run:

```bash
python3 -m unittest scripts/test_harness.py
python3 scripts/harness.py check
```

Expected: PASS.

### Task 7: Add Project-Owned Instruction Drift Diagnostics

**Files:**
- Modify: `scripts/lib/harness_doctor.py`
- Modify: `scripts/harness.py`
- Test: `scripts/test_harness.py`

- [ ] **Step 1: Add failing doctor test**

Create an installed target with a stale project-owned `README.md` that says to use a removed or contradictory upgrade command. Assert doctor JSON includes:

```json
{
  "code": "project_owned_instruction_drift",
  "severity": "P2",
  "path": "README.md"
}
```

- [ ] **Step 2: Implement drift detection**

Check project-owned docs for stale upgrade instructions that contradict installed command availability. Start narrowly with README references to missing `scripts/show_phase_status.py`, missing `scripts/upgrade_harness.py`, or obsolete “read all planning docs first” guidance when the status script exists.

- [ ] **Step 3: Verify**

Run:

```bash
python3 -m unittest scripts.test_harness.HarnessToolTests.test_doctor_reports_project_owned_instruction_drift
```

Expected: PASS.

### Task 8: Documentation, Manifest, and Real Target Smoke

**Files:**
- Modify: `README.md`
- Modify: `harness/skeleton/clean/README.md`
- Modify: `docs/script-oriented-harness-workflow.md`
- Modify: `harness/manifest.json`
- Test: `scripts/test_harness.py`

- [ ] **Step 1: Update docs**

Document:

```bash
python3 /path/to/source/scripts/install_harness.py --interactive
python3 scripts/upgrade_harness.py --version vX.Y.Z --dry-run
python3 scripts/upgrade_harness.py --version vX.Y.Z
python3 scripts/check_harness.py
python3 scripts/doctor_harness.py
python3 /path/to/source/scripts/harness.py check --target /path/to/project
```

Clarify that target self-check and source-side current-manifest check answer different questions.

- [ ] **Step 2: Run source verification**

Run:

```bash
python3 -m unittest scripts/test_harness.py
python3 scripts/harness.py check
python3 scripts/harness.py check --worktree
python3 scripts/release_smoke_test.py
```

Expected: all exit `0`.

- [ ] **Step 3: Run non-mutating real target smoke against `../new project`**

If the path exists, run:

```bash
python3 scripts/install_harness.py --target "../new project" --adapters none --packs workflow-core --dry-run
python3 scripts/harness.py upgrade --target "../new project" --dry-run
python3 "../new project/scripts/upgrade_harness.py" --source "$PWD" --version v9.9.9 --dry-run
```

Expected: dry-runs mutate nothing. Do not run mutating upgrade against the sibling project without a separate explicit approval.

- [ ] **Step 4: Run mutating smoke against a temporary target copy**

If `../new project` exists, copy it to a temp directory and run the wrapper commands against the temp copy. If it does not exist, create a fresh temp target with `install_harness.py`, then run `upgrade_harness.py --source "$PWD" --version v9.9.9`, `check_harness.py`, and `doctor_harness.py --format json`.

- [ ] **Step 5: Run adversarial post-implementation review**

Ask a reviewer to inspect the final diff for lost upgrade behavior, target/source confusion, version stamping, wrapper install scope, dry-run usefulness, and smoke coverage. Fix P1/P2 findings before final response.
