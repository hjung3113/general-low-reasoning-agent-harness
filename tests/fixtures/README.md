# tests/fixtures — v0.9.4 fixture tarballs

## Purpose

Two tarballs capture a v0.9.4 install state for T15 upgrade-compat tests:

| File | Description |
|---|---|
| `v094-clean.tar.gz` | Vanilla v0.9.4 init — 35 lib modules absent from manifest (BUG-1 as-shipped) |
| `v094-with-workaround.tar.gz` | Same + the 35 missing lib modules copied in (replicates the dogfood manual workaround) |

The `.tar.gz` files are **gitignored** — never committed. Only the `.sha256` pin files are
checked-in. CI rebuilds the tarballs before the T15 tests and verifies the hash.

## Provenance

- Source tag: `v0.9.4` (`bd5fa83`)
- Builder: `scripts/build_v094_fixture.py`
- mtime pin: `1748822400` (2026-05-21 00:00:00 UTC)
- Tool: Python `tarfile` + `gzip.GzipFile(mtime=0)` — stdlib only, no bsdtar / GNU tar

## Rebuild

```bash
python3 scripts/build_v094_fixture.py [--output-dir tests/fixtures]
```

The script:
1. Checks out `v0.9.4` via `git worktree add`.
2. Runs `python3 <worktree>/scripts/harness.py init --target <scratch> --adapters none`.
3. Archives the scratch dir with fully-normalised TarInfo entries (mtime=0, uid/gid=0,
   uname/gname="", mode 0o644/0o755, entries sorted lexicographically).
4. For the workaround variant: copies the 35 missing `scripts/lib/*.py` modules from the
   v0.9.4 worktree source into the install target before archiving.
5. Writes sha256 digests to the `.sha256` files alongside the tarballs.
6. Cleans up the worktrees and scratch dirs.

The output is byte-identical across macOS and Linux because gzip header timestamps are
suppressed (`mtime=0`) and all filesystem metadata is normalised before archiving.

## Hash verification

```bash
# After rebuild, verify against the pinned hashes:
shasum -a 256 -c tests/fixtures/v094-clean.tar.gz.sha256
shasum -a 256 -c tests/fixtures/v094-with-workaround.tar.gz.sha256
```

## Design notes

- **No LFS, no S3**: always rebuilt from the v0.9.4 tag. The tag is immutable; the
  rebuild is deterministic; CI can always reconstruct.
- **Stdlib only**: `tarfile` + `gzip` — no dependency on bsdtar (macOS) or GNU tar
  (Linux), both of which differ in `--sort` / `--mtime` flag support (codex C-3).
- **Missing 35 modules** (`approval_nonce.py`, `audit.py`, `audit_chain.py`, …): these
  are present in the v0.9.4 *source tree* but absent from `harness/manifest.json` — the
  root cause of the v0.9.4 install-broken P0 bug tracked in memory note
  `project_v094_install_broken.md`.
