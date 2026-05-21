# Codex ImplPlan Review REV-2

Verdict: PASS-WITH-CONDITIONS

## Closure
| Prior | Status | Note |
|---|---|---|
| Codex CRIT-1: pid collision | CLOSED | REV-2 replaces bare pid names with `runid = pid + iso + nonce` and carries it through pending/staging/journal/sentinel paths. |
| Codex MAJOR-1: upgrade wire-in | CLOSED | T4 now explicitly wires upgrade through pending sidecar + atomic batch + finalize/verify. |
| Codex MAJOR-2: pending atomicity | CLOSED | New phase order writes pending after staging and before target atomic rename; recovery scans pending first. |
| Codex MAJOR-3: sentinel durability | CLOSED | T1 specifies fsync of sentinel tmp and parent dir after `os.replace`. |
| Codex MAJOR-4: drift gate cache policy | PARTIAL | Cache is generated-only and gitignored, but stale cache only warns, so false-green drift remains possible. |
| Architect C-1: `file_state` pre-batch hash | CLOSED | T1.5 adds staged hashing and `build_install_state_payload(staging_map=...)`. |
| Architect C-2: `pairs=` arg | CLOSED | T1 pins `atomic_install_batch(..., pairs=...)` contract and T3/T4 consume it. |
| Architect C-3: upgrade loop-derived | CLOSED | T4 is now two-pass: Pass A computes `plan.installed`, Pass B writes pending and finalizes. |
| Architect C-4: sentinel fsync | CLOSED | T1 includes fsync-safe sentinel temp write and parent directory fsync. |
| Hawk C-1: pid collision | CLOSED | Nonce runid prevents stale bare-pid artifact collision. |
| Hawk C-2: post-finalize sanity | CLOSED | T2/T3 require re-reading final manifest and asserting expected version after replace. |
| Hawk C-3: `.complete.tmp` orphans | CLOSED | T2 scan removes stale `.complete.tmp` orphans. |
| Hawk C-4: sentinel + `.aborted` coexist | PARTIAL | T2 tests aborted-without-sentinel, but coexistence precedence is not directly specified/tested. |
| Hawk C-5: resume idempotency torn-state | CLOSED | T2 and T4 require `state repair` 3x idempotency tests. |
| LRR C-1: `InstallFailed` pointer | CLOSED | REV-2 pins bilingual next-action text with `state repair` command pointer. |
| LRR C-2: exit codes | CLOSED | REV-2 pins `state repair` rc 0/1/2 semantics. |
| LRR C-3: 3x idempotency | CLOSED | T2/T4/T12 include 3 consecutive `state repair` assertions. |
| LRR C-4: bilingual | CLOSED | REV-2 chooses Korean primary + English bracketed for v0.9.7 errors. |

## NEW

- T4 consistency claim is broader than implementation scope: T4 says conflict copies and managed-append remain in-place/out-of-scope, but its SIGTERM test promises a fully consistent v0.9.6 or v0.9.7 state. Narrow the claim to manifest/harness-owned files or make those writes recoverable.
- T9 stale junit cache check warns instead of failing; a stale cache can still produce a green drift gate.

## Recommended next step

Patch T2 to specify/test sentinel + `.aborted` precedence, patch T4 wording or recovery scope, and make stale T9 cache fail unless explicitly bypassed.
