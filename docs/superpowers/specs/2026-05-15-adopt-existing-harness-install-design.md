# Adopt Existing Harness Install Design

## Goal

Allow an older or manually copied harness target that lacks `.harness/installed-manifest.json` to enter the normal upgrade path without treating the target as a fresh init.

## Problem

`scripts/harness.py upgrade` currently refuses any target whose install state is missing. That is correct for unknown projects because upgrade needs ownership provenance before overwriting files. It blocks a practical case: a project already has harness files, planning files, adapter files, and marker-managed `.gitignore`, but was created before install state existed or was copied manually.

`--force` must not silently broaden into adoption. Today it means "overwrite locally modified whole-file `harness-owned` or `managed` files during upgrade." Adoption has different risk: the tool is creating the provenance record that future upgrades will trust.

## Command Surface

Add one explicit upgrade option:

```text
python3 scripts/harness.py upgrade --target /path/to/project --adopt-existing
```

`--adopt-existing` is valid only for `upgrade`. It is only used when `.harness/installed-manifest.json` is missing. If install state already exists, the option is a no-op and the normal upgrade path runs.

Scope selection follows normal upgrade parsing with one important difference: when install state is missing, there is no remembered scope. The command must use explicit or default scopes:

- omitted `--adapters` means the existing default `roo`;
- omitted `--profiles` means `generic`;
- omitted `--packs` means `workflow-core`;
- explicit `--adapters none`, `--profiles ...`, or `--packs ...` select the exact adoption scope.

This keeps the first version deterministic. It does not infer scope from filesystem contents.

`--force` keeps its existing meaning. It applies only after adoption has built in-memory state and only to whole-file `harness-owned` and `managed` conflicts in the normal upgrade loop. It does not force adoption to claim arbitrary non-selected files.

## Adoption Model

Adoption builds an in-memory install state for the selected manifest entries, then calls the existing upgrade logic. It must not treat arbitrary existing bytes as trusted harness provenance.

For each selected entry:

- `exclude`: ignored.
- `project-owned`: if the destination exists, record the current target file hash as project-owned provenance. If it is missing, do not create it during adoption.
- `managed-append`: if destination exists with a well-formed marker block whose payload matches the current rendered source block, record the current marker block hash and full-file hash. Version-only marker differences are accepted. If it is missing or has no marker block, leave it unrecorded so the normal upgrade path can create or append the marker block. If the marker is malformed or the marker payload has local edits, conflict before writing anything.
- `harness-owned` and `managed`: if destination exists and matches the current source hash, record the current target file hash as the baseline. If it exists and differs from the current source hash, conflict unless `--force`; with `--force`, write the existing destination to `.harness/conflicts/<path>.adopted`, then leave it unrecorded so the normal upgrade loop overwrites it. If it is missing, leave it unrecorded so the normal upgrade path can install it.

After this state is built, the existing upgrade loop decides what to write:

- matching whole-file entries remain under normal upgrade management;
- missing selected harness-owned files are installed;
- missing managed-append blocks are appended/created by the existing policy;
- project-owned planning files are not overwritten.

Adoption itself writes `.harness/installed-manifest.json` only when the upgrade command exits `0` and is not a dry run. If adoption or the following upgrade reports conflicts, target content is preserved according to normal conflict rules and no install state is created for a previously uninitialized target.

Adoption is not init. A target must already contain the core project-owned planning/live-gate files: `.planning/STATE.md`, `.planning/ROADMAP.md`, `.scratch/phase-state.json`, and `.planning/codebase/**`. It must also contain at least one selected non-project-owned harness artifact such as `AGENTS.md`, `.roo/**`, `.opencode/**`, `.agents/**`, or a selected managed-append file. If these are absent, adoption fails and the user should run `init` instead.

## Safety Rules

The adoption pass must fail before any target write when it finds:

- malformed managed-append marker state;
- a selected destination path that escapes the target;
- a selected destination or parent path that is a symlink.
- a selected existing whole-file destination that differs from current source and `--force` is not set;
- a selected existing managed-append marker block whose payload differs from current source.
- required core project-owned planning/live-gate files are absent.
- no selected non-project-owned harness artifact exists.

Adoption intentionally does not classify non-selected files. It does not delete files, retire old files, or infer adapters/packs from directories.

The implementation must run an adoption preflight across all selected entries before invoking any write-capable upgrade behavior. The preflight classifies conflicts and safety failures first so an early selected entry cannot be written before a later selected entry fails.

Dry-run with `--adopt-existing` must have no filesystem side effects. It should still return the same exit code that the normal upgrade would return after adoption.

## User-Facing Behavior

Successful adoption produces a normal `.harness/installed-manifest.json` with `state_schema_version`, selected scope, manifest hash, and per-file provenance. Subsequent `upgrade` commands work without `--adopt-existing`.

For a manual target like `../New project`, the intended command is:

```text
python3 scripts/harness.py upgrade --target "../New project" --adopt-existing --force
```

Use explicit scope flags if the target is not the default Roo + generic + workflow-core shape.

## Non-Goals

- No new standalone `adopt` subcommand in this change.
- No automatic scope inference from existing `.roo`, `.opencode`, `.agents`, or profile files.
- No overwrite of project-owned `.planning/**` or `.scratch/phase-state.json`.
- No broadening of `--force` beyond whole-file `harness-owned` and `managed` replacement.
- No adoption of arbitrary user files outside the selected manifest scope.

## Tests

Add focused tests for:

- `upgrade --adopt-existing` creates install state for a manual target with selected harness files.
- adoption preserves project-owned `.planning/STATE.md`.
- adoption plus `--force` can overwrite a locally changed selected whole-file managed file.
- adoption plus `--force` writes a `.harness/conflicts/<path>.adopted` backup before overwriting a changed selected whole-file file.
- adoption without `--force` reports a conflict for locally changed selected whole-file files and writes conflict artifacts only outside dry-run.
- adoption rejects empty targets or targets missing required core project-owned planning/live-gate files.
- adoption rejects planning-only targets that have no selected harness-owned, managed, or managed-append artifact.
- adoption appends or records `.gitignore` marker state without deleting project lines.
- adoption conflicts and preserves `.gitignore` when an existing marker block contains local edits.
- adoption conflict does not create `.harness/installed-manifest.json`.
- adoption preflight failure leaves earlier selected files untouched.
- dry-run adoption does not create `.harness/installed-manifest.json` or conflict artifacts.
- normal upgrade without `--adopt-existing` still refuses missing install state.
- already initialized targets ignore `--adopt-existing` and follow normal upgrade behavior.

## Compatibility Check

The previous managed-append workflow remains intact because this design reuses the existing marker parser, block planner, and upgrade conflict rules. Existing initialized targets keep using remembered scope from install state. The only new path is opt-in and active only when install state is missing.
