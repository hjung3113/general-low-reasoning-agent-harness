# Release Version Unification

This document defines the repository-side work needed to make the Git release
tag the single version source of truth for harness releases.

## Goal

Use one release version value:

```text
Git tag / release: v0.4.2
installed harness version: 0.4.2
```

Do not maintain a separate manually edited harness version that can drift from
the Git release number.

## Repository Changes

### 1. Stop hardcoding the harness version

Replace static release values:

- `scripts/harness.py` resolves `HARNESS_VERSION` at runtime.
- `harness/manifest.json` keeps `"version": "__release__"` as a source-tree
  placeholder.

with release-derived version resolution.

Recommended resolution order:

1. Explicit CLI option, for harness stamping only: `--version v0.4.2`
2. Environment variable, for harness stamping only:
   `HARNESS_VERSION=v0.4.2`
3. Exact Git tag on the current commit: `git describe --tags --exact-match`
4. Development fallback: `0.0.0-dev+<short-sha>` or
   `0.0.0-dev+<short-sha>.dirty`

`--version` and `HARNESS_VERSION` are convenience inputs for local stamping and
tests. They do not satisfy the release gate. Official releases must pass
`release-check`, which independently requires an exact clean `vMAJOR.MINOR.PATCH`
tag.

`release_smoke_test.py --release` removes ambient `HARNESS_VERSION` from child
processes and passes `--version <expected-tag>` into source-tree harness
commands so release smoke installs are stamped with the verified tag version.

Normalize leading `v` when writing install state:

```text
v0.4.2 -> 0.4.2
```

### 2. Generate or validate manifest version from the release tag

The manifest should not require a human to update `"version"` separately from
the release tag.

Implementation:

- Keep `harness/manifest.json` with `"version": "__release__"` in source.
- `scripts/harness.py` validates the raw source manifest version before
  injection. Source manifests must contain `"__release__"`; generated artifacts
  may contain the already-resolved release version.
- Release verification injects the exact tag version and rejects untagged or
  dirty source trees.

The important invariant is:

```text
resolved release version == manifest version used by init/upgrade
```

### 3. Record the resolved version in target install state

`init` and `upgrade` should continue writing the installed version to:

```text
.harness/installed-manifest.json
```

The value should come from the resolved release version, not from a manually
edited constant.

Existing installed manifests remain valid. `upgrade` must not reject a target
just because its previous `.harness/installed-manifest.json` version is older.
Touched file records and top-level install metadata are normalized to the
current resolved version on successful non-dry-run `init`, `upgrade`, or
`--adopt-existing`.

### 4. Add release verification

`scripts/harness.py release-check` fails unless the tag, manifest, and source
state are release-safe.

Minimum checks:

```text
current commit has exact tag vX.Y.Z
worktree is clean
manifest version used for release is X.Y.Z
optional expected version matches vX.Y.Z
unit tests pass
release smoke test passes
```

Suggested commands to keep passing before release:

```bash
python3 -m unittest scripts/test_harness.py
python3 scripts/harness.py check
python3 scripts/release_smoke_test.py
```

Release-only command:

```bash
python3 scripts/release_smoke_test.py --release --expected-version v0.4.2
```

### 5. Document development fallback behavior

When the working tree is not on an exact clean release tag, the harness reports
a development version such as:

```text
0.0.0-dev+abc1234
0.0.0-dev+abc1234.dirty
```

This prevents untagged or locally modified builds from pretending to be an
official release.

## Remote Repository Requirements

### Main branch policy

Treat `main` as the release branch. Merge into `main` only when creating a new
release or applying an urgent hotfix.

Allowed `main` merge sources:

- `develop` for normal releases.
- `hotfix/*` for urgent release-line fixes.

Do not merge feature, docs, or experiment branches directly into `main`; merge
them into `develop` first. Local git hooks enforce this by blocking `main`
merge commits whose source is not `develop` or `hotfix/*`, and by blocking
`main` pushes that contain bypassed merge commits from other sources.

### 1. Use release tags as the only human-managed version number

Create releases from immutable annotated tags on `origin/main` only, after
`develop` has been merged and pushed to `main`.

```bash
git fetch --tags origin
git switch develop
git pull --ff-only origin develop
git switch main
git pull --ff-only origin main
git merge --no-ff develop -m "merge: release v0.4.2"
python3 -m unittest scripts/test_harness.py
python3 scripts/harness.py check
python3 scripts/release_smoke_test.py
git push origin main
git tag -a v0.4.2 -m "v0.4.2"
python3 scripts/release_smoke_test.py --release --expected-version v0.4.2
git push origin v0.4.2
RUN_ID="$(gh run list --workflow Release --branch v0.4.2 --limit 1 --json databaseId --jq '.[0].databaseId')"
gh run watch "$RUN_ID" --exit-status
```

The Git release name should match the tag:

```text
v0.4.2
```

### 2. Do not move published tags

After a tag has been used for a release, do not retarget it to another commit.

If a release was wrong, publish a new tag instead:

```text
v0.4.3
```

Do not publish suffix repair tags such as `v0.4.2-1`; the release tooling only
accepts stable `vMAJOR.MINOR.PATCH` tags.

Protect `v*` tags in GitHub repository rules so published tags cannot be
force-pushed or deleted.

### 3. Release from the tagged commit only

Release artifacts must be built from the exact commit pointed to by the release
tag. The release pipeline rejects builds from untagged or dirty commits.

The repository workflow `.github/workflows/release.yml` runs on `v*` tag pushes
and verifies:

```text
python3 scripts/harness.py release-check --expected-version "$VERSION" --require-origin-main
python3 -m unittest scripts/test_harness.py
python3 scripts/harness.py check
python3 scripts/release_smoke_test.py --release --expected-version "$VERSION"
```

`release-check` is the tag/source provenance gate. The full release gate is the
workflow command set above.

### 4. Keep tag naming stable

Use one tag format consistently:

```text
vMAJOR.MINOR.PATCH
```

Examples:

```text
v0.4.2
v0.5.0
v1.0.0
```

### 5. Create GitHub Release from the existing tag

Create the GitHub Release from the pushed tag, not from a branch draft.
Wait for the `Release` workflow on that tag to pass before creating the GitHub
Release.

CLI path:

```bash
gh release create v0.4.2 --verify-tag --title v0.4.2 --notes "v0.4.2"
```

Manual UI path:

1. Choose the existing tag `v0.4.2`.
2. Set the release title to `v0.4.2`.
3. Confirm the release target SHA equals `git rev-parse v0.4.2`.

## Non-Goals

This document does not define internal repository mirroring, internal release
approval, or internal deployment steps.

Those processes may use the same tag names, but they are outside this
repository-side version unification scope.
