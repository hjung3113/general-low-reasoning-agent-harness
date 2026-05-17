# `tests/fixtures/state/` — pinned phase-state fixtures (design §9.1)

Each subdirectory is a self-contained `.scratch/`-shaped layout used by the
S01-series test suites. Per
`docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md` §9.1.

| Path | Shape | Used by |
|---|---|---|
| `v061_no_execution_or_automation/` | Neither `execution_mode` nor `automation_mode` present. `forward()` must default `execution_mode=manual` and emit one `migrate.state_v2` audit entry. | S01-A |
| `v070_automation_manual_only/` | Legacy `automation_mode=manual`. Read migration is idempotent; new `execution_mode=manual` is added by `forward()` while the legacy alias is preserved on the wire. | S01-A |
| `v070_automation_chain/` | Legacy `automation_mode=chain`. Migrates to `execution_mode=phase_autopilot`. | S01-A |
| `v070_automation_auto/` | Legacy `automation_mode=auto`. Migrates to `execution_mode=chain_autopilot`. | S01-A |
| `tampered_approved_true/` | State hand-edited to `approved=true` without a corresponding audit entry. The state-trust preflight (S01-E) MUST reject this fixture before any transition. | S01-A (pin), S01-E (reject), S03 |
| `tampered_chain_autopilot/` | State hand-edited to `execution_mode=chain_autopilot` without a `phase.autopilot.start` audit entry. Same rejection semantics as above. | S01-A (pin), S01-E (reject), S07-prep |

The `tampered_*` fixtures are intentionally readable / parseable v2 records.
Their *forgery* signal is the absent audit anchor, not malformed JSON — the
state-trust preflight in S01-E is what detects them. S01-A only pins them
on disk so subsequent slices have a deterministic input to test against.
