# Codex Plan Review REV-2 — v0.9.7

Verdict: BLOCK

## Closure table
| Prior | Status | Note |
|---|---|---|
| C-1 | PARTIAL | Durable journal anchor is now explicit, but `atomic_io` journal rows only carry `src_rel`/`dst_rel`/`rename_at_iso`; they do not carry version, source root, source hashes, manifest hash, chain data, adapters/profiles/packs, or enough data to rebuild a valid `installed-manifest.json` from an orphan journal. |
| C-2 | CLOSED | REV-2 uses the sibling journal path `staging_dir.parent / (staging_dir.name + ".journal.jsonl")`, matching `install_recovery._staging_journal_path`. |
| C-3 | PARTIAL | Determinism gate is good, and v0.9.4 supports `HARNESS_FIXED_NOW_ISO`; however §7.3 normalizes `source_root` and `entries`, while v0.9.4 state uses top-level `source` and a `files` dict. The planned scrub would leave absolute source path drift unnormalized. |
| C-4 | CLOSED | REV-2 explicitly deletes `_seed_v094_manifest` / `_seed_v094_full_manifest` and requires extracted fixtures to contain `.harness/installed-manifest.json`. |
| C-5 | CLOSED | REV-2 switches to node-id set equality and reports both new failures and unexpectedly passing known failures. |
| M-1 | CLOSED | `upgrade.py:738-794` is now explicitly in scope for harness-owned writes, with conflict sidecars documented out of scope. |
| M-2 | CLOSED | `harness check` now gets precise staging detection requiring `.harness/.staging-*` plus sibling journal. |
| M-3 | CLOSED | Silent cross-FS fallback is removed; non-atomic fallback requires explicit opt-in. |
| M-4 | CLOSED | REV-2 adds a v0.9.4 -> v0.9.7 skip-upgrade guard with actionable remediation and override. |
| M-5 | CLOSED | REV-2 uses v0.9.7 wording and honest partial-atomicity language. |

## NEW issues
- N-1: §3.1 line 60 says `defer_cleanup=False` but also says "default True for new callers"; §7.1 passes `defer_cleanup=True`. Make the contract unambiguous: default must preserve legacy cleanup, new two-phase callers pass `True`.

## Recommended next step
REV-3 minimum surgical changes:

1. Expand the orphan-journal recovery contract so the retained durable artifact contains enough state to re-stamp a valid manifest, or state that orphan-journal recovery can only clean up and must fail with actionable repair instructions when manifest data is missing.
2. Fix fixture normalization to scrub actual v0.9.4 fields: top-level `source` and per-file data under `files`, not `source_root` / `entries`.
3. Clarify the `defer_cleanup` default and caller contract in §3.1.
