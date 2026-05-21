# Codex ImplPlan Review — v0.9.7

Verdict: BLOCK

## CRIT

- T2/T4: stale `.complete` sentinel can falsely finalize a new pending manifest. PLAN keys all artifacts by PID only: pending path at `.planning/phases/02f-v0.9.6-hotfix/plans/PLAN.md:210`, recovery derives `.staging-<P>.complete` from that PID at `.planning/phases/02f-v0.9.6-hotfix/plans/PLAN.md:91-95`, and finalizes on sentinel presence alone at `.planning/phases/02f-v0.9.6-hotfix/plans/PLAN.md:95`. IMPL-PLAN does not require preflight cleanup/nonce naming before init or upgrade; T3 only says cleanup after success at `.planning/phases/02f-v0.9.6-hotfix/plans/IMPL-PLAN.md:83`, and T4 only says "Apply T3 pattern" at `.planning/phases/02f-v0.9.6-hotfix/plans/IMPL-PLAN.md:105`. PID reuse plus leftover `.staging-<pid>.complete` can make recovery finalize a torn current batch.

## MAJOR

- T3/T4: upgrade wire-in is under-specified because `upgrade.py` does not use `write_install_state`; it mutates an `installed` dict through the flow and writes it at the end. Evidence: `scripts/lib/upgrade.py:651` reads state, `scripts/lib/upgrade.py:757-763` mutates file entries during writes, `scripts/lib/upgrade.py:806-815` stamps version/source fields, `scripts/lib/upgrade.py:900-905` stamps v2 manifest fields, and `scripts/lib/upgrade.py:926-927` writes final JSON. IMPL-PLAN's state.py extraction at `.planning/phases/02f-v0.9.6-hotfix/plans/IMPL-PLAN.md:76-80` only covers init-style payload building, then T4 says "Apply T3 pattern" at `.planning/phases/02f-v0.9.6-hotfix/plans/IMPL-PLAN.md:105`; that is not enough to preserve upgrade semantics.

- T3: pending sidecar atomicity is implicit in IMPL-PLAN, not in the `write_install_state_to` contract. PLAN requires temp+`os.replace` at `.planning/phases/02f-v0.9.6-hotfix/plans/PLAN.md:82-88`, but IMPL-PLAN only says `write_install_state_to(path, ...) writes payload to arbitrary path` at `.planning/phases/02f-v0.9.6-hotfix/plans/IMPL-PLAN.md:76-80`. The implementation task should explicitly require `write_install_state_to` to route through `write_json`/`atomic_write_text`; current `write_json` is atomic at `scripts/lib/state.py:79-84`.

- T1: sentinel ordering is flush-ordered but not durable-proof as written. Current journal appends call `jf.flush()` after success at `scripts/lib/atomic_io.py:457-463`, and the PLAN sentinel write uses `sentinel_tmp.write_bytes(b"")` then `os.replace` at `.planning/phases/02f-v0.9.6-hotfix/plans/PLAN.md:271-275`. That satisfies "after last flush" only if inserted after the `with open(...)` block, but it does not `fsync` journal or sentinel temp. If the contract keeps using "durable proof" wording at `.planning/phases/02f-v0.9.6-hotfix/plans/PLAN.md:101`, tests should assert close/fsync ordering or the text should downgrade to process-crash proof.

- T9: drift gate cache policy is contradictory. PLAN says CI/dev generate `.harness-test-cache/junit.xml` before the drift test at `.planning/phases/02f-v0.9.6-hotfix/plans/PLAN.md:449`, while IMPL-PLAN says to read cached XML and skip if missing at `.planning/phases/02f-v0.9.6-hotfix/plans/IMPL-PLAN.md:202-205`, but its risk row allows "commit junit cache" at `.planning/phases/02f-v0.9.6-hotfix/plans/IMPL-PLAN.md:285`. Do not commit `.harness-test-cache/junit.xml`; make it generated-only and document the seeding command.

## MINOR

- T2 matrix should spell out inconsistent-state precedence. PLAN finalizes on sentinel presence before checking `.aborted` at `.planning/phases/02f-v0.9.6-hotfix/plans/PLAN.md:354-359`; IMPL-PLAN tests only the clean sentinel path and aborted-without-sentinel path at `.planning/phases/02f-v0.9.6-hotfix/plans/IMPL-PLAN.md:59-62`. Add a test for sentinel + `.aborted` and either quarantine or prefer rollback.

- T5 will warn on a currently-running install once the journal exists. IMPL-PLAN qualifies any `.staging-*` with sibling journal at `.planning/phases/02f-v0.9.6-hotfix/plans/IMPL-PLAN.md:122-132`; existing recovery has an age threshold/stale concept at `scripts/lib/install_recovery.py:105-110`. Either share that threshold or state that `check` intentionally warns on in-progress batches.

- T6 guard depends on `version`; missing state returns `{"version": None}` at `scripts/lib/state.py:315-318` and upgrade enters adoption at `scripts/lib/upgrade.py:667-680`. If the v0.9.4 fixture ever lacks `version`, the direct-skip guard can be bypassed. Test missing-version v0.9.4-shaped manifests explicitly.

- T11 says "wherever version constant lives" and "Any other version-ref locations" at `.planning/phases/02f-v0.9.6-hotfix/plans/IMPL-PLAN.md:225-226`, but concrete stale locations exist: `README.md:225`, `docs/site/index.html:6-7`, `docs/site/use-cases.html:18`, and `docs/USER_MANUAL.md:1`. Add an `rg 'v0\\.9\\.6|0\\.9\\.6'` release-gate acceptance check.

## Recommended amendments

- Use a nonce/run-id, not PID alone, for pending/staging/journal/sentinel names; include the same id in the pending payload and validate it during recovery.
- Before starting init/upgrade, recover or quarantine all existing `installed-manifest.json.pending-*`, `.staging-*.complete`, `.staging-*.journal.jsonl`, and `.staging-*` artifacts for the target.
- Define a dedicated upgrade pending-manifest builder after `_stamp_installed_manifest_v2` and before harness-owned batch mutation; do not rely on the init `write_install_state_to` extraction for upgrade.
- Make `write_install_state_to` explicitly atomic via temp+replace and add a torn-pending negative test.
- Keep `.harness-test-cache/junit.xml` untracked; add a make/script command that generates it and a clear skip message when absent.
