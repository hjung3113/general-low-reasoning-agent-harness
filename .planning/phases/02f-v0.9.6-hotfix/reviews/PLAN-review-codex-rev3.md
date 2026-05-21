# Codex Plan Review REV-3 — v0.9.7

Verdict: BLOCK

## Closure

| Prior | REV-3 Status | Note |
| C-1 | PARTIAL | Pending-manifest sidecar before batch and final `os.replace(pending, installed-manifest.json)` fix the post-batch/pre-stamp crash window in the success path, but §7.2 recovery can still finalize an incomplete install. |
| C-3 | CLOSED | §3.2/§7.3 scrub the actual v0.9.4 host-specific fields: top-level `source`, `git_user_email_at_install_sha256`, optional `source_provenance`, per-file `installed_at`, plus audit log churn. `files.*.applied_sha256` exists conditionally in v0.9.4 but is content-derived, not host-specific. |
| N-1 | CLOSED | §3.1/§7.1 unambiguously preserve `defer_cleanup=False` as default legacy behavior and require new two-phase callers to pass `True`. |

## NEW

N-2 BLOCK: §7.2 treats `has_error == False` and no `.aborted` sentinel as sufficient to finalize the pending manifest. That is unsafe for crashes during staging or mid-batch: `journal_path` may be absent or contain only a subset of completed renames, `staging_dir` may still contain uninstalled files, and recovery would still `os.replace(pending, installed-manifest.json)`. Finalization needs positive proof of completion, e.g. existing journal, no errors/sentinel, completed journal rels match the expected batch rels from the pending manifest/batch plan, and staging has no remaining expected files. Otherwise rollback or quarantine.

Audit note: `install.recovery.manifest_finalized` is emitted after `os.replace`; a crash there can miss the audit row while the manifest is correct. Non-blocking unless audit completeness is a hard contract.

## Recommended next step

Patch §7.2 to require explicit full-batch completion proof before pending-manifest finalization, then move to ImplPlan.
