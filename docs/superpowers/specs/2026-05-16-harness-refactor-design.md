# `scripts/harness.py` Refactor: Role-Based Module Split

Status: Draft (design approved 2026-05-16)
Owner: harness-maintainer

## Goal

Split `scripts/harness.py` (2561 lines, 121 top-level defs/classes covering ~13
distinct concerns) into focused modules under `scripts/lib/`. After the
refactor `scripts/harness.py` is a thin CLI dispatcher that imports from the
new modules and re-exports the same public symbols the existing tests and
callers already rely on. No behavior change is intended.

## Why now

`harness.py` has accumulated responsibilities: CLI dispatch, profile/pack
resolution, manifest model and selection, install + upgrade + adoption flows,
check + worktree gates, doctor diagnostics, roadmap/state parsing,
append-block management, and release/version helpers. The file no longer fits
in working context for routine edits. Recent feature work (profile
unification, per-profile augment rules) added another ~150 lines and made
existing seams more obvious. Splitting now avoids accreting more into a single
file.

## Non-goals

- No new functionality.
- No public API rename. Every symbol currently importable as
  `scripts.harness.X` remains importable as `scripts.harness.X` after the
  refactor.
- No reformat of cut/paste content. Function bodies move verbatim. Style
  changes are out of scope (run a separate pass if desired).
- No change to existing root-level CLI scripts (`install_harness.py`,
  `upgrade_harness.py`, `uninstall_harness.py`, `check_harness.py`,
  `doctor_harness.py`, `show_phase_status.py`, etc.). They keep their current
  thin-wrapper shape.

## Final module layout

```
scripts/
  harness.py             # thin CLI dispatcher + re-exports
  install_harness.py     # (unchanged)
  upgrade_harness.py     # (unchanged)
  uninstall_harness.py   # (unchanged)
  check_harness.py       # (unchanged)
  doctor_harness.py      # (unchanged)
  show_phase_status.py   # (unchanged)
  release_smoke_test.py  # (unchanged)
  release.py             # (unchanged)
  target_smoke_test.py   # (unchanged)
  project_dashboard.py   # (unchanged)
  test_harness.py        # (unchanged — runs against the new layout)
  lib/
    __init__.py          # (existing)
    roomodes_writer.py   # (existing)
    workflow_static_checks.py  # (existing)
    version.py           # NEW
    profiles.py          # NEW
    manifest.py          # NEW
    append_block.py      # NEW
    state.py             # NEW
    roadmap_state.py     # NEW
    worktree.py          # NEW
    adoption.py          # NEW
    check.py             # NEW
    doctor.py            # NEW
    install.py           # NEW
    upgrade.py           # NEW
```

`scripts/harness.py` after the refactor consists of:

1. Module docstring stating it is a CLI dispatcher.
2. `run(argv)` and a small `run_delegated_command()` helper (the only logic it
   still owns).
3. Re-export block importing every public symbol the existing tests and
   callers reach for through `scripts.harness`.

The order and existence of every existing `scripts.harness.X` symbol must be
preserved. New symbols introduced in lib/ modules are not added to the
re-export list unless tests need them.

## Module contents

Each row lists the canonical home for symbols that currently live in
`scripts/harness.py`. The "Depends on" column is the import direction; the
graph is acyclic.

| Module | Symbols | Depends on |
| --- | --- | --- |
| `lib/version.py` | `repo_root`, `upgrade_source_root`, `normalize_release_version`, `git_output`, `is_git_worktree_dirty`, `exact_release_tag_version`, `development_version`, `git_source_provenance`, `source_provenance`, `resolve_harness_version`, `release_check`, `readme_release_versions`, `check_readme_release_versions` | stdlib |
| `lib/profiles.py` | `KNOWN_PROFILES`, `LEGACY_PROFILE_ALIASES`, `_PROFILE_DEFAULT_PACKS`, `_DB_PACKS`, `PROFILE_MODE_OWNERS`, `default_packs_for_profile`, `db_packs`, `normalize_profiles` | stdlib |
| `lib/manifest.py` | `ManifestEntry`, `KNOWN_ADAPTERS`, `KNOWN_POLICIES`, `KNOWN_PACKS`, `load_manifest`, `load_manifest_data`, `selected_pack_metadata`, `select_entries`, `validate_scope_names`, `infer_adapter`, `infer_pack`, `infer_owner`, `source_path`, `destination_path` | `version`, `profiles` |
| `lib/append_block.py` | `AppendBlockPlan`, `ParsedAppendBlock`, `validate_managed_append_destinations`, `marker_start`, `marker_end_for_path`, `marker_end`, `render_append_block`, `parse_append_block`, `append_block_to_text`, `replace_block`, `write_managed_append`, `plan_managed_append`, `plan_managed_append_retirement` | `manifest` |
| `lib/state.py` | `scope_record`, `delegated_source_provenance`, `installed_scope`, `available_scopes`, `parse_optional_scope`, `parse_scope`, `write_install_state`, `read_install_state`, `validate_installed_scope_names`, `validate_installed_managed_append`, `required_phrase_scope`, `write_json`, `file_hash`, `now_utc`, `manifest_sha256`, `sha256_text`, `normalize_payload` | `manifest`, `version` |
| `lib/roadmap_state.py` | `RoadmapPhase`, `StateSnapshot`, `parse_roadmap_phases`, `parse_state_snapshot`, `parse_frontmatter`, `split_frontmatter_pair`, `int_value`, `markdown_section`, `check_roadmap_state_sync`, `roadmap_state_sync_applicable`, `find_roadmap_state_sync_findings` | stdlib |
| `lib/worktree.py` | `check_changed_paths`, `check_worktree_paths`, `changed_path_gate_allows_state`, `git_changed_paths`, `git_worktree_paths`, `path_allowed`, `matches_any`, `normalize_path`, `is_relative_to`, `is_text_file` | stdlib |
| `lib/adoption.py` | `AdoptionConflict`, `AdoptionPlan`, `normalize_selected_project_owned_state`, `build_adopted_install_state`, `is_required_adoption_project_owned_path`, `is_optional_project_owned_path`, `is_existing_harness_artifact` | `manifest`, `state` |
| `lib/check.py` | `check`, `check_installed_target`, `_check_roomodes_profile_sync`, `should_check_as_installed_target`, `check_clean_skeleton`, `check_json`, `check_phase_state_semantics`, `check_command_modes`, `check_phase_reference_drift`, `check_phase_state_paths` | `manifest`, `state`, `roadmap_state`, `roomodes_writer`, `worktree` |
| `lib/doctor.py` | `DoctorFinding`, `doctor`, `collect_doctor_findings`, `phase_status_projection_doctor_findings`, `projection_warning_severity`, `roadmap_state_doctor_findings`, `phase_state_path_doctor_findings`, `verification_contract_doctor_findings`, `installed_scope_doctor_findings`, `command_mode_doctor_findings`, `db_context_doctor_findings`, `opencode_profile_rules_doctor_findings`, `render_doctor_report` | `manifest`, `state`, `roadmap_state`, `roomodes_writer` |
| `lib/install.py` | `install`, `sync_roomodes_profile_modes`, `write_copy`, `write_text_file`, `file_state`, `assert_safe_write_destination`, `remove_empty_parents`, `write_text_conflict` | `manifest`, `state`, `append_block`, `roomodes_writer`, `profiles` |
| `lib/upgrade.py` | `upgrade`, `migrate_install_state`, `install_state_migration_report` | `install`, `state`, `manifest`, `profiles` |

`run()` in `scripts/harness.py` imports and calls the entry points
(`install`, `upgrade`, `check`, `doctor`, etc.) directly.

## Re-export strategy

`scripts/harness.py` uses explicit re-exports (no star imports):

```python
"""Thin CLI dispatcher. Implementation lives under scripts.lib.*"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from scripts.lib.profiles import (
    KNOWN_PROFILES,
    LEGACY_PROFILE_ALIASES,
    PROFILE_MODE_OWNERS,
    default_packs_for_profile,
    db_packs,
    normalize_profiles,
)
from scripts.lib.manifest import (
    ManifestEntry,
    KNOWN_ADAPTERS,
    KNOWN_POLICIES,
    KNOWN_PACKS,
    load_manifest,
    load_manifest_data,
    selected_pack_metadata,
    select_entries,
    validate_scope_names,
    infer_adapter,
    infer_pack,
    infer_owner,
    source_path,
    destination_path,
)
from scripts.lib.append_block import (
    AppendBlockPlan,
    ParsedAppendBlock,
    validate_managed_append_destinations,
    marker_start,
    marker_end,
    marker_end_for_path,
    render_append_block,
    parse_append_block,
    append_block_to_text,
    replace_block,
    write_managed_append,
    plan_managed_append,
    plan_managed_append_retirement,
)
from scripts.lib.state import (
    scope_record,
    delegated_source_provenance,
    installed_scope,
    available_scopes,
    parse_optional_scope,
    parse_scope,
    write_install_state,
    read_install_state,
    validate_installed_scope_names,
    validate_installed_managed_append,
    required_phrase_scope,
    write_json,
    file_hash,
    now_utc,
    manifest_sha256,
    sha256_text,
    normalize_payload,
)
from scripts.lib.roadmap_state import (
    RoadmapPhase,
    StateSnapshot,
    parse_roadmap_phases,
    parse_state_snapshot,
    parse_frontmatter,
    split_frontmatter_pair,
    int_value,
    markdown_section,
    check_roadmap_state_sync,
    roadmap_state_sync_applicable,
    find_roadmap_state_sync_findings,
)
from scripts.lib.worktree import (
    check_changed_paths,
    check_worktree_paths,
    changed_path_gate_allows_state,
    git_changed_paths,
    git_worktree_paths,
    path_allowed,
    matches_any,
    normalize_path,
    is_relative_to,
    is_text_file,
)
from scripts.lib.adoption import (
    AdoptionConflict,
    AdoptionPlan,
    normalize_selected_project_owned_state,
    build_adopted_install_state,
    is_required_adoption_project_owned_path,
    is_optional_project_owned_path,
    is_existing_harness_artifact,
)
from scripts.lib.check import (
    check,
    check_installed_target,
    should_check_as_installed_target,
    check_clean_skeleton,
    check_json,
    check_phase_state_semantics,
    check_command_modes,
    check_phase_reference_drift,
    check_phase_state_paths,
)
from scripts.lib.doctor import (
    DoctorFinding,
    doctor,
    collect_doctor_findings,
    phase_status_projection_doctor_findings,
    projection_warning_severity,
    roadmap_state_doctor_findings,
    phase_state_path_doctor_findings,
    verification_contract_doctor_findings,
    installed_scope_doctor_findings,
    command_mode_doctor_findings,
    db_context_doctor_findings,
    opencode_profile_rules_doctor_findings,
    render_doctor_report,
)
from scripts.lib.install import (
    install,
    sync_roomodes_profile_modes,
    write_copy,
    write_text_file,
    file_state,
    assert_safe_write_destination,
    remove_empty_parents,
    write_text_conflict,
)
from scripts.lib.upgrade import (
    upgrade,
    migrate_install_state,
    install_state_migration_report,
)
from scripts.lib.version import (
    repo_root,
    upgrade_source_root,
    normalize_release_version,
    git_output,
    is_git_worktree_dirty,
    exact_release_tag_version,
    development_version,
    git_source_provenance,
    source_provenance,
    resolve_harness_version,
    release_check,
    readme_release_versions,
    check_readme_release_versions,
)


def run_delegated_command(command: list[str], cwd: Path) -> int:
    """Subprocess helper kept here because it is only used by `run()`."""
    result = subprocess.run(command, cwd=cwd, check=False)
    return result.returncode


def run(argv: list[str] | None = None) -> int:
    # argparse + dispatch (cut/paste verbatim from current run()).
    ...
```

Symbols private to a single module (underscore-prefixed, e.g.
`_PROFILE_DEFAULT_PACKS`, `_DB_PACKS`, `_check_roomodes_profile_sync`) are
NOT re-exported. Existing tests that reach them through `scripts.harness`
must be inventoried up-front; if any test imports a single-underscore
symbol, it gets either (a) re-exported on the same name to keep the test
working, or (b) the test is updated to import from its new module home.

## Migration order

Each step:

1. Create the new module file in `scripts/lib/`.
2. Cut the listed symbols out of `scripts/harness.py`, paste into the new
   module verbatim. Add only the imports the new module needs.
3. Replace the deleted symbols in `scripts/harness.py` with an explicit
   re-export `from scripts.lib.<module> import (...)`.
4. Run `python3 -m unittest scripts/test_harness.py 2>&1 | tail -3`. Must
   show `Ran 163 tests ... OK`.
5. Commit with message `refactor(harness): extract <module> module`.

Order (leaf-first; install before upgrade):

1. `lib/version.py`
2. `lib/profiles.py`
3. `lib/manifest.py`
4. `lib/append_block.py`
5. `lib/state.py`
6. `lib/roadmap_state.py`
7. `lib/worktree.py`
8. `lib/adoption.py`
9. `lib/check.py`
10. `lib/doctor.py`
11. `lib/install.py`
12. `lib/upgrade.py`
13. `scripts/harness.py` final pass — replace any leftover transitional
    imports, tighten the re-export block, update the docstring, drop unused
    imports. Run the full release smoke (`python3 scripts/release_smoke_test.py`).

`release_smoke_test.py` is slow (~10 min). Run it only at steps 1, 5, 11, and
13 to bound elapsed time. Unit tests run at every step.

## Risk: circular imports during cut/paste

If a function in module A depends on a helper still in `harness.py` that
later moves to module B, A's import block has to be updated when B lands.
Mitigation:

- For each step, before paste-in, grep the relevant symbols in
  `scripts/harness.py` and confirm all transitive dependencies are either
  (a) in stdlib, (b) already moved to a lib module, or (c) explicitly
  exported by `scripts/harness.py` and not yet moved. If (c), keep the
  import as `from scripts.harness import X` until the originating module
  ships, then rewrite to `from scripts.lib.<X_module> import X`.
- A unit test (`scripts/test_harness.py`) that imports both `scripts.harness`
  and lib modules is the canary; circular import surfaces as an
  `ImportError` immediately.

## Risk: skipped re-exports

`from scripts import harness` callsites are the contract. Before step 13,
run a grep:

```bash
grep -RnE 'from scripts(\.harness)? import|scripts\.harness\.' scripts/ docs/ harness/
```

Cross-reference the matched symbols against the explicit re-export list in
`scripts/harness.py`. Missing symbols become re-export additions, not test
edits.

## Verification

After every step:

```bash
python3 -m unittest scripts/test_harness.py 2>&1 | grep -E '^(OK|FAIL|ERROR|Ran)'
```

Expected: `Ran 163 tests ... OK` (the count may shift if circular-import
canary tests are added; the count stays monotonic and never drops).

At steps 1, 5, 11, and 13:

```bash
python3 scripts/harness.py check
python3 scripts/harness.py check --worktree
python3 scripts/release_smoke_test.py
```

At step 13 only:

```bash
python3 scripts/harness.py release-check --expected-version v0.6.0
```

## Files changed

- Created: 12 new modules under `scripts/lib/`.
- Modified: `scripts/harness.py` (shrunk from ~2561 to ~250 lines, mostly
  imports + `run()` + `run_delegated_command()`).
- Unchanged: every other file in the repo.

## Open questions

- Whether `scripts/harness.py` should expose `__all__` to make the contract
  explicit and lint-checkable. Default answer: yes, add `__all__` at step 13
  populated from the import names.
- Whether to also rename `scripts/lib/workflow_static_checks.py` for
  consistency. Default answer: no, that file is target-installable and
  renaming would break installed targets that reference it by path.
