# `tests/fixtures/crash/` — pinned 12-row recovery matrix (design §9.1)

Each subdirectory contains a frozen `.scratch/`-shaped layout that
represents one row of the §3.8 crash-recovery decision matrix
(`docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md`).
Row 12 is the §12.5 #2 audit-partial-write extension. Predicates:

* **J** — `phase-state.json.journal` present
* **T** — `phase-state.json.tmp` present
* **A** — last audit-tail entry's `txn_id` matches journal's `txn_id`

| Row | J | T | A | state-on-disk hash | Decision | Exit |
|---|---|---|---|---|---|---|
| 01_quiescent | 0 | 0 | 0 | any | no-op | 0 |
| 02_orphan_tmp | 0 | 1 | 0 | any | unlink tmp | 0 |
| 03_state_accepted_audit_durable | 0 | 0 | 1 | == after | no-op | 0 |
| 04_tmp_present_audit_durable | 0 | 1 | 1 | == after | unlink tmp | 0 |
| 05_journal_only_before | 1 | 0 | 0 | == before | rollback (unlink journal) | 0 |
| 06_journal_and_tmp_before | 1 | 1 | 0 | == before | rollback (unlink both) | 0 |
| 07_roll_forward | 1 | 1 | 1 | == before AND sha(tmp) == after | `os.replace(tmp, state)` | 0 |
| 08a_finalize_no_tmp | 1 | 0 | 1 | == after | finalize (unlink journal) | 0 |
| 08b_finalize_with_tmp | 1 | 1 | 1 | == after | finalize (unlink both) | 0 |
| 09_undecidable_state_hash | 1 | * | 1 | ∉ {before, after} | undecidable | 14 |
| 10_corrupt_journal_tmp | 1 | 1 | 0 | != before | corruption | 14 |
| 11_corrupt_journal_only | 1 | 0 | 0 | != before | corruption | 14 |
| 12_audit_partial_write | * | * | last record fails JSON-parse | * | `audit_partial_write` | 14 |
| 13_malformed_journal | journal-fails-parse | * | * | * | `malformed_journal` | 14 |

Row 13 is an S01-D.2 review-fix addition (out-of-band relative to the
design §3.8 table): if the journal file exists but fails JSON-parse,
recovery must NOT silently fall into J=0 rows 1/2/3/4 and risk
deleting tmp data. Operator action is required.

Tests `tests/phase_txn/test_recovery_matrix.py` build the same shapes
in `tmp_path` so the matrix is exercised in isolation per test. These
on-disk fixtures pin the canonical bytes (`_canonical_bytes` output)
so a future serializer change can never silently invalidate the
recovery oracle — S06 (audit-chain) and S13 (release smoke) consume
the same layout for regression.

All fixtures use a discuss-phase v0-shape `phase-state.json` body with
`{"phase": "discuss"}` ("before") and `{"phase": "plan"}` ("after");
corruption rows use `{"phase": "garbage"}`. Each row's `audit_entry_draft`
verb is `phase.set` and the journal carries `txn_id`s in distinct hex
patterns (`"5" * 32`, `"6" * 32`, ...) for easy visual diff.
