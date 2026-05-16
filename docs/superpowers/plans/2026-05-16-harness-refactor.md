# `scripts/harness.py` Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `scripts/harness.py` (2561 lines, 121 top-level defs/classes) into 12 focused modules under `scripts/lib/`. `scripts/harness.py` becomes a thin CLI dispatcher (~250 lines) that re-exports every existing public symbol so the ~100 `from scripts import harness as h; h.X` callsites in tests keep working.

**Architecture:** Mechanical cut/paste, leaf-first dependency order. Each task creates one new lib module, moves the listed symbols out of `harness.py`, replaces them with an explicit re-export, runs unit tests, commits. No behavior change. The release smoke matrix runs at steps 1, 5, 11, and 13 (it is slow); unit tests run every step.

**Tech Stack:** Python 3 stdlib only. `unittest`. No new dependencies.

---

## Universal recipe

Every extraction task follows the same five-step recipe. Read it once here, then each task only lists the symbols and the new module path.

- [ ] **Step A: Create the new module file**

Open the new file under `scripts/lib/<module>.py`. Header:

```python
"""<one-line summary>."""
from __future__ import annotations

# imports go here — copy exactly the ones the moved code actually uses
```

Determine imports by reading the moved code and copying every `import` line it references. Stdlib first, then `from scripts.lib.<X> import ...` for already-extracted modules.

- [ ] **Step B: Cut symbols out of `scripts/harness.py`**

Locate every symbol listed in the task's "Move" set inside `scripts/harness.py`. Cut (not copy) each one — the definition AND any module-level constant lines that are part of the listed set. Paste into the new module file in the same order.

Do not reformat. Do not rename. Function bodies move verbatim.

- [ ] **Step C: Re-import in `scripts/harness.py`**

In place of the cut content (or near the top with the other re-exports — order doesn't matter for behavior, but keeping the block contiguous is cleaner), add:

```python
from scripts.lib.<module> import (
    Symbol1,
    Symbol2,
    ...
)
```

The list must include every public symbol from the task's "Move" set. Private (leading-underscore) symbols are imported only if existing tests reach them through `scripts.harness`. Check with:

```bash
grep -nE 'scripts\.harness\.<symbol>|from scripts.harness import <symbol>' scripts/test_harness.py
```

If a private symbol is referenced from outside, re-export it too. Otherwise leave it module-private.

- [ ] **Step D: Run unit tests**

```bash
python3 -m unittest scripts/test_harness.py 2>&1 | grep -E '^(OK|FAIL|ERROR|Ran)'
```

Expected output: `Ran 163 tests in ... OK`.

If a test fails:
1. Read the failure. Most likely cause is a missed re-export or a forward dependency on a not-yet-extracted symbol.
2. For a missed re-export: add it to the import block in `scripts/harness.py`.
3. For a forward dependency: the moved code calls something still in `harness.py`. Import that name into the new module via `from scripts.harness import X`. This transitional import becomes `from scripts.lib.<X_module> import X` once that module ships.
4. Re-run.

- [ ] **Step E: Commit**

```bash
git add scripts/lib/<module>.py scripts/harness.py
git commit -m "refactor(harness): extract <module> module"
```

Done with the task.

---

## Pre-flight

- [ ] **Step 0.1: Branch and baseline**

```bash
git checkout develop
git pull --ff-only 2>/dev/null || true
git checkout -b refactor/harness-split
python3 -m unittest scripts/test_harness.py 2>&1 | grep -E '^(OK|FAIL|ERROR|Ran)'
python3 scripts/harness.py check
```

Expected: `Ran 163 tests ... OK` and `check` exits 0.

- [ ] **Step 0.2: Snapshot the public surface**

Capture every name accessed through `scripts.harness` so we can audit re-exports at step 13:

```bash
grep -RhnE 'from scripts(\.harness)? import |scripts\.harness\.[A-Za-z_]+' scripts/ docs/ harness/ \
  | sed -E 's/.*from scripts(\.harness)? import //; s/.*scripts\.harness\.([A-Za-z_]+).*/\1/' \
  | tr ',' '\n' \
  | tr -d ' ()' \
  | sort -u > /tmp/harness-public-surface.txt
wc -l /tmp/harness-public-surface.txt
```

Save the file — step 13 diffs against it.

---

## Task 1: Extract `lib/version.py`

**Files:**
- Create: `scripts/lib/version.py`
- Modify: `scripts/harness.py`

**Move:**
- `repo_root`
- `upgrade_source_root`
- `normalize_release_version`
- `git_output`
- `is_git_worktree_dirty`
- `exact_release_tag_version`
- `development_version`
- `git_source_provenance`
- `source_provenance`
- `resolve_harness_version`
- `release_check`
- `readme_release_versions`
- `check_readme_release_versions`

**Imports for the new module:**

```python
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
```

Apply the universal recipe (Steps A–E). On step E commit message:

```
refactor(harness): extract version module
```

After step D, also run the release smoke (this is a step-1 smoke run):

```bash
python3 scripts/release_smoke_test.py 2>&1 | tail -5
```

Expected: all PASS lines, ending with `TMP /var/folders/.../harness-release-smoke...`.

---

## Task 2: Extract `lib/profiles.py`

**Files:**
- Create: `scripts/lib/profiles.py`
- Modify: `scripts/harness.py`

**Move:**
- `KNOWN_PROFILES`
- `LEGACY_PROFILE_ALIASES`
- `_PROFILE_DEFAULT_PACKS`
- `_DB_PACKS`
- `PROFILE_MODE_OWNERS`
- `default_packs_for_profile`
- `db_packs`
- `normalize_profiles`

**Imports for the new module:**

```python
from __future__ import annotations

import sys
from typing import Iterable
```

Apply universal recipe.

Re-export block addition in `scripts/harness.py`:

```python
from scripts.lib.profiles import (
    KNOWN_PROFILES,
    LEGACY_PROFILE_ALIASES,
    PROFILE_MODE_OWNERS,
    default_packs_for_profile,
    db_packs,
    normalize_profiles,
)
```

Check whether existing tests reach `_PROFILE_DEFAULT_PACKS` or `_DB_PACKS` via `scripts.harness`:

```bash
grep -nE 'scripts\.harness\._PROFILE_DEFAULT_PACKS|scripts\.harness\._DB_PACKS|from scripts.harness import _PROFILE_DEFAULT_PACKS|from scripts.harness import _DB_PACKS' scripts/test_harness.py
```

If yes, add them to the re-export. If no, leave them module-private.

Commit message: `refactor(harness): extract profiles module`.

---

## Task 3: Extract `lib/manifest.py`

**Files:**
- Create: `scripts/lib/manifest.py`
- Modify: `scripts/harness.py`

**Move:**
- `ManifestEntry`
- `KNOWN_ADAPTERS`
- `KNOWN_POLICIES`
- `KNOWN_PACKS`
- `load_manifest`
- `load_manifest_data`
- `selected_pack_metadata`
- `select_entries`
- `validate_scope_names`
- `infer_adapter`
- `infer_pack`
- `infer_owner`
- `source_path`
- `destination_path`

**Imports for the new module:**

```python
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from scripts.lib.profiles import KNOWN_PROFILES
from scripts.lib.version import repo_root, resolve_harness_version
```

Apply universal recipe.

Re-export in `scripts/harness.py`:

```python
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
```

Commit: `refactor(harness): extract manifest module`.

---

## Task 4: Extract `lib/append_block.py`

**Files:**
- Create: `scripts/lib/append_block.py`
- Modify: `scripts/harness.py`

**Move:**
- `AppendBlockPlan`
- `ParsedAppendBlock`
- `validate_managed_append_destinations`
- `marker_start`
- `marker_end_for_path`
- `marker_end`
- `render_append_block`
- `parse_append_block`
- `append_block_to_text`
- `replace_block`
- `write_managed_append`
- `plan_managed_append`
- `plan_managed_append_retirement`

**Imports for the new module:**

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from scripts.lib.manifest import ManifestEntry
```

Apply universal recipe.

Re-export block:

```python
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
```

Commit: `refactor(harness): extract append_block module`.

---

## Task 5: Extract `lib/state.py`

**Files:**
- Create: `scripts/lib/state.py`
- Modify: `scripts/harness.py`

**Move:**
- `scope_record`
- `delegated_source_provenance`
- `installed_scope`
- `available_scopes`
- `parse_optional_scope`
- `parse_scope`
- `write_install_state`
- `read_install_state`
- `validate_installed_scope_names`
- `validate_installed_managed_append`
- `required_phrase_scope`
- `write_json`
- `file_hash`
- `now_utc`
- `manifest_sha256`
- `sha256_text`
- `normalize_payload`

**Imports:**

```python
from __future__ import annotations

import datetime
import hashlib
import json
import os
import unicodedata
from pathlib import Path
from typing import Iterable

from scripts.lib.manifest import (
    KNOWN_ADAPTERS,
    KNOWN_PACKS,
    ManifestEntry,
    load_manifest,
    select_entries,
    selected_pack_metadata,
)
from scripts.lib.profiles import KNOWN_PROFILES
from scripts.lib.version import manifest_sha256 if False else None  # placeholder — see note
```

Note: if `manifest_sha256` ends up moving here (it depends only on the manifest file), drop that placeholder. Verify by reading the existing body — most likely `manifest_sha256` belongs in `state.py` next to `sha256_text`. Adjust imports accordingly and remove the placeholder line.

Apply universal recipe.

Re-export block:

```python
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
```

After step D, run the release smoke (step-5 smoke run):

```bash
python3 scripts/release_smoke_test.py 2>&1 | tail -5
```

Commit: `refactor(harness): extract state module`.

---

## Task 6: Extract `lib/roadmap_state.py`

**Files:**
- Create: `scripts/lib/roadmap_state.py`
- Modify: `scripts/harness.py`

**Move:**
- `RoadmapPhase`
- `StateSnapshot`
- `parse_roadmap_phases`
- `parse_state_snapshot`
- `parse_frontmatter`
- `split_frontmatter_pair`
- `int_value`
- `markdown_section`
- `check_roadmap_state_sync`
- `roadmap_state_sync_applicable`
- `find_roadmap_state_sync_findings`

**Imports:**

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
```

Apply universal recipe.

Re-export block:

```python
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
```

Commit: `refactor(harness): extract roadmap_state module`.

---

## Task 7: Extract `lib/worktree.py`

**Files:**
- Create: `scripts/lib/worktree.py`
- Modify: `scripts/harness.py`

**Move:**
- `check_changed_paths`
- `check_worktree_paths`
- `changed_path_gate_allows_state`
- `git_changed_paths`
- `git_worktree_paths`
- `path_allowed`
- `matches_any`
- `normalize_path`
- `is_relative_to`
- `is_text_file`

**Imports:**

```python
from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path
from typing import Iterable
```

Apply universal recipe.

Re-export block:

```python
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
```

Commit: `refactor(harness): extract worktree module`.

---

## Task 8: Extract `lib/adoption.py`

**Files:**
- Create: `scripts/lib/adoption.py`
- Modify: `scripts/harness.py`

**Move:**
- `AdoptionConflict`
- `AdoptionPlan`
- `normalize_selected_project_owned_state`
- `build_adopted_install_state`
- `is_required_adoption_project_owned_path`
- `is_optional_project_owned_path`
- `is_existing_harness_artifact`

**Imports:**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from scripts.lib.manifest import ManifestEntry
from scripts.lib.state import sha256_text, file_hash
```

Apply universal recipe.

Re-export block:

```python
from scripts.lib.adoption import (
    AdoptionConflict,
    AdoptionPlan,
    normalize_selected_project_owned_state,
    build_adopted_install_state,
    is_required_adoption_project_owned_path,
    is_optional_project_owned_path,
    is_existing_harness_artifact,
)
```

Commit: `refactor(harness): extract adoption module`.

---

## Task 9: Extract `lib/check.py`

**Files:**
- Create: `scripts/lib/check.py`
- Modify: `scripts/harness.py`

**Move:**
- `check`
- `check_installed_target`
- `_check_roomodes_profile_sync`
- `should_check_as_installed_target`
- `check_clean_skeleton`
- `check_json`
- `check_phase_state_semantics`
- `check_command_modes`
- `check_phase_reference_drift`
- `check_phase_state_paths`

**Imports:**

```python
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Iterable

from scripts.lib.manifest import (
    ManifestEntry,
    load_manifest,
    select_entries,
    source_path,
    destination_path,
)
from scripts.lib.profiles import PROFILE_MODE_OWNERS
from scripts.lib.roadmap_state import (
    check_roadmap_state_sync,
)
from scripts.lib.state import (
    read_install_state,
    validate_installed_scope_names,
    file_hash,
    manifest_sha256,
)
from scripts.lib.version import (
    check_readme_release_versions,
    resolve_harness_version,
)
from scripts.lib.worktree import (
    check_changed_paths,
    check_worktree_paths,
)
```

Apply universal recipe.

Re-export block:

```python
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
```

`_check_roomodes_profile_sync` is private. Skip re-export unless the test grep finds a reference. Run:

```bash
grep -nE '_check_roomodes_profile_sync' scripts/test_harness.py
```

Commit: `refactor(harness): extract check module`.

---

## Task 10: Extract `lib/doctor.py`

**Files:**
- Create: `scripts/lib/doctor.py`
- Modify: `scripts/harness.py`

**Move:**
- `DoctorFinding`
- `doctor`
- `collect_doctor_findings`
- `phase_status_projection_doctor_findings`
- `projection_warning_severity`
- `roadmap_state_doctor_findings`
- `phase_state_path_doctor_findings`
- `verification_contract_doctor_findings`
- `installed_scope_doctor_findings`
- `command_mode_doctor_findings`
- `db_context_doctor_findings`
- `opencode_profile_rules_doctor_findings`
- `render_doctor_report`

**Imports:**

```python
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from scripts.lib.manifest import (
    ManifestEntry,
    load_manifest,
    select_entries,
)
from scripts.lib.roadmap_state import (
    parse_roadmap_phases,
    parse_state_snapshot,
)
from scripts.lib.state import (
    read_install_state,
    installed_scope,
)
```

Apply universal recipe.

Re-export block:

```python
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
```

Commit: `refactor(harness): extract doctor module`.

---

## Task 11: Extract `lib/install.py`

**Files:**
- Create: `scripts/lib/install.py`
- Modify: `scripts/harness.py`

**Move:**
- `install`
- `sync_roomodes_profile_modes`
- `write_copy`
- `write_text_file`
- `file_state`
- `assert_safe_write_destination`
- `remove_empty_parents`
- `write_text_conflict`

**Imports:**

```python
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Iterable

from scripts.lib.append_block import (
    plan_managed_append,
    write_managed_append,
    validate_managed_append_destinations,
)
from scripts.lib.manifest import (
    ManifestEntry,
    load_manifest,
    select_entries,
    source_path,
    destination_path,
    validate_scope_names,
    selected_pack_metadata,
)
from scripts.lib.profiles import default_packs_for_profile, normalize_profiles, db_packs
from scripts.lib.roomodes_writer import set_profile_modes, BASE_MODE_SLUGS
from scripts.lib.state import (
    scope_record,
    delegated_source_provenance,
    write_install_state,
    write_json,
    now_utc,
    file_hash,
    manifest_sha256,
    sha256_text,
)
from scripts.lib.version import (
    repo_root,
    resolve_harness_version,
    git_source_provenance,
    source_provenance,
)
```

Apply universal recipe.

Re-export block:

```python
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
```

After step D, run release smoke (step-11 smoke run):

```bash
python3 scripts/release_smoke_test.py 2>&1 | tail -5
```

Commit: `refactor(harness): extract install module`.

---

## Task 12: Extract `lib/upgrade.py`

**Files:**
- Create: `scripts/lib/upgrade.py`
- Modify: `scripts/harness.py`

**Move:**
- `upgrade`
- `migrate_install_state`
- `install_state_migration_report`

**Imports:**

```python
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Iterable

from scripts.lib.adoption import (
    AdoptionConflict,
    AdoptionPlan,
    build_adopted_install_state,
)
from scripts.lib.install import (
    install,
    sync_roomodes_profile_modes,
)
from scripts.lib.manifest import (
    ManifestEntry,
    load_manifest,
    select_entries,
    validate_scope_names,
)
from scripts.lib.profiles import LEGACY_PROFILE_ALIASES, normalize_profiles
from scripts.lib.state import (
    read_install_state,
    scope_record,
    write_install_state,
    write_json,
)
from scripts.lib.version import (
    repo_root,
    resolve_harness_version,
)
```

Apply universal recipe.

Re-export block:

```python
from scripts.lib.upgrade import (
    upgrade,
    migrate_install_state,
    install_state_migration_report,
)
```

Commit: `refactor(harness): extract upgrade module`.

---

## Task 13: Final pass on `scripts/harness.py`

After Task 12, `scripts/harness.py` should contain only:

1. Module docstring.
2. `from __future__ import annotations` and a small `import` block (argparse, subprocess, sys, Path).
3. The re-export block (all `from scripts.lib.<module> import (...)`).
4. `run_delegated_command()`.
5. `run(argv)` (the argparse dispatcher).
6. `if __name__ == "__main__": raise SystemExit(run())`.

If anything else remains (helper functions, dead imports, leftover constants), it was missed by an earlier task — assign it to the right module and re-do the extraction.

**Files:**
- Modify: `scripts/harness.py`

- [ ] **Step 13.1: Confirm `scripts/harness.py` line count is in the expected range**

```bash
wc -l scripts/harness.py
```

Expected: ~200–300 lines. If it is closer to 500+, dead code or missed extractions are still present.

- [ ] **Step 13.2: Add `__all__` populated from the re-export imports**

At the bottom of the import block (before `run_delegated_command`), add:

```python
__all__ = [
    # from scripts.lib.profiles
    "KNOWN_PROFILES",
    "LEGACY_PROFILE_ALIASES",
    "PROFILE_MODE_OWNERS",
    "default_packs_for_profile",
    "db_packs",
    "normalize_profiles",
    # from scripts.lib.manifest
    "ManifestEntry",
    "KNOWN_ADAPTERS",
    "KNOWN_POLICIES",
    "KNOWN_PACKS",
    "load_manifest",
    "load_manifest_data",
    "selected_pack_metadata",
    "select_entries",
    "validate_scope_names",
    "infer_adapter",
    "infer_pack",
    "infer_owner",
    "source_path",
    "destination_path",
    # from scripts.lib.append_block
    "AppendBlockPlan",
    "ParsedAppendBlock",
    "validate_managed_append_destinations",
    "marker_start",
    "marker_end",
    "marker_end_for_path",
    "render_append_block",
    "parse_append_block",
    "append_block_to_text",
    "replace_block",
    "write_managed_append",
    "plan_managed_append",
    "plan_managed_append_retirement",
    # from scripts.lib.state
    "scope_record",
    "delegated_source_provenance",
    "installed_scope",
    "available_scopes",
    "parse_optional_scope",
    "parse_scope",
    "write_install_state",
    "read_install_state",
    "validate_installed_scope_names",
    "validate_installed_managed_append",
    "required_phrase_scope",
    "write_json",
    "file_hash",
    "now_utc",
    "manifest_sha256",
    "sha256_text",
    "normalize_payload",
    # from scripts.lib.roadmap_state
    "RoadmapPhase",
    "StateSnapshot",
    "parse_roadmap_phases",
    "parse_state_snapshot",
    "parse_frontmatter",
    "split_frontmatter_pair",
    "int_value",
    "markdown_section",
    "check_roadmap_state_sync",
    "roadmap_state_sync_applicable",
    "find_roadmap_state_sync_findings",
    # from scripts.lib.worktree
    "check_changed_paths",
    "check_worktree_paths",
    "changed_path_gate_allows_state",
    "git_changed_paths",
    "git_worktree_paths",
    "path_allowed",
    "matches_any",
    "normalize_path",
    "is_relative_to",
    "is_text_file",
    # from scripts.lib.adoption
    "AdoptionConflict",
    "AdoptionPlan",
    "normalize_selected_project_owned_state",
    "build_adopted_install_state",
    "is_required_adoption_project_owned_path",
    "is_optional_project_owned_path",
    "is_existing_harness_artifact",
    # from scripts.lib.check
    "check",
    "check_installed_target",
    "should_check_as_installed_target",
    "check_clean_skeleton",
    "check_json",
    "check_phase_state_semantics",
    "check_command_modes",
    "check_phase_reference_drift",
    "check_phase_state_paths",
    # from scripts.lib.doctor
    "DoctorFinding",
    "doctor",
    "collect_doctor_findings",
    "phase_status_projection_doctor_findings",
    "projection_warning_severity",
    "roadmap_state_doctor_findings",
    "phase_state_path_doctor_findings",
    "verification_contract_doctor_findings",
    "installed_scope_doctor_findings",
    "command_mode_doctor_findings",
    "db_context_doctor_findings",
    "opencode_profile_rules_doctor_findings",
    "render_doctor_report",
    # from scripts.lib.install
    "install",
    "sync_roomodes_profile_modes",
    "write_copy",
    "write_text_file",
    "file_state",
    "assert_safe_write_destination",
    "remove_empty_parents",
    "write_text_conflict",
    # from scripts.lib.upgrade
    "upgrade",
    "migrate_install_state",
    "install_state_migration_report",
    # from scripts.lib.version
    "repo_root",
    "upgrade_source_root",
    "normalize_release_version",
    "git_output",
    "is_git_worktree_dirty",
    "exact_release_tag_version",
    "development_version",
    "git_source_provenance",
    "source_provenance",
    "resolve_harness_version",
    "release_check",
    "readme_release_versions",
    "check_readme_release_versions",
    # local
    "run",
    "run_delegated_command",
]
```

If a test reaches for any symbol not listed, add it. Run the test suite after editing to confirm:

```bash
python3 -m unittest scripts/test_harness.py 2>&1 | grep -E '^(OK|FAIL|ERROR|Ran)'
```

- [ ] **Step 13.3: Diff the public surface against the step-0 snapshot**

```bash
python3 -c "
import scripts.harness as h
public = sorted(name for name in vars(h) if not name.startswith('__'))
print('\n'.join(public))
" > /tmp/harness-public-now.txt
diff /tmp/harness-public-surface.txt /tmp/harness-public-now.txt | head -40
```

Names appearing only in `/tmp/harness-public-surface.txt` are missing re-exports — add them.
Names appearing only in `/tmp/harness-public-now.txt` are new private helpers that leaked through — make them private in the source lib module (do not remove them from `harness.py` if existing tests use them).

- [ ] **Step 13.4: Update module docstring**

Replace the existing docstring at the top of `scripts/harness.py` with:

```python
"""Thin CLI dispatcher for the harness.

All non-CLI logic lives under ``scripts.lib.*``. This module imports each
public symbol and re-exports it so existing callers — including the test
suite and target-installed wrappers — continue to import names from
``scripts.harness``.

When adding a new function or class, prefer placing it directly in the
appropriate ``scripts.lib`` module and adding a single import line here.
"""
```

- [ ] **Step 13.5: Run the full verification suite**

```bash
python3 -m unittest scripts/test_harness.py 2>&1 | grep -E '^(OK|FAIL|ERROR|Ran)'
python3 scripts/harness.py check
python3 scripts/harness.py check --worktree
python3 scripts/release_smoke_test.py 2>&1 | tail -10
python3 scripts/harness.py release-check --expected-version v0.6.0 2>&1 | tail -10
```

Expected: 163 tests OK, both `check` exit 0, smoke shows all PASS lines, release-check prints expected version without errors.

- [ ] **Step 13.6: Commit final pass**

```bash
git add scripts/harness.py
git commit -m "refactor(harness): final pass — docstring, __all__, dead-import sweep"
```

- [ ] **Step 13.7: Merge to develop**

```bash
git checkout develop
git merge --no-ff refactor/harness-split -m "merge: split scripts/harness.py into lib/ modules

13 commits; 163 tests OK; release smoke green. No behavior change."
```

Push is left to the user.

---

## Self-Review

1. **Spec coverage:**
   - Module layout matches spec section "Final module layout" — all 12 new modules listed, all symbol assignments preserved.
   - Re-export strategy matches spec section "Re-export strategy" — explicit imports, no star imports, `__all__` added at step 13.
   - Migration order matches spec section "Migration order" — leaf-first, install before upgrade, smoke runs at steps 1, 5, 11, 13.
   - Verification checklist matches spec section "Verification".
   - Risk mitigations (circular imports, skipped re-exports) addressed via step 0.2 snapshot + step 13.3 diff.

2. **Placeholder scan:**
   - Step 5 has a `placeholder — see note` line for `manifest_sha256` placement. Resolution is described inline (read existing body, decide once). Acceptable — the engineer has enough information to make the call without inventing requirements.

3. **Type consistency:**
   - Symbol names are quoted verbatim from `grep -n "^def \|^class " scripts/harness.py` output. No renames.
   - Re-export blocks in each task and the final `__all__` in step 13 list the same names with no spelling drift.
   - `sync_roomodes_profile_modes` consistently lives in `lib/install.py` per Task 11 and the spec.
