# ADR: Remove Out-of-Repo Audit-Tip Anchor — 2026-05-20

## Status

Accepted (v0.9.3, 2026-05-20).

Supersedes §D-7 of `docs/adr/2026-05-17-audit-canonicalization-locking-and-state-trust.md`. The rest of that ADR remains in force.

## Context

Three independent reasons drove the removal of the out-of-repo audit-tip anchor (`~/.harness/audit-tip/<id>.json` / `%LOCALAPPDATA%\Harness\audit-tip\<id>.json`):

1. **Fresh-install UX regression**: `harness next` (and every CLI entry point that runs state-trust preflight) errored with `audit-tip anchor not found` on a clean install because the anchor was never auto-minted. The user was expected to run `harness anchor repair` first — a step not documented in the install guide and not obvious from the error. This broke the zero-config install promise introduced in v0.7.

2. **Threat class is out of scope**: The anchor defended against a _repo-local attacker_ — an adversary with sufficient access to rewrite every `audit.log*` entry and recompute every `entry_hash`. This threat class is **intentionally out of scope** for an internal-only tool: any such attacker already has code execution as the user, meaning the harness process itself, the Python interpreter, and the secret key at `~/.harness/secret.key` are all compromised. The anchor provided defense-in-depth only, at meaningful operational cost.

3. **Smoke tests masked the bug**: Pre-existing smoke-test fixtures pre-minted anchor files, so the fresh-install regression was never caught by CI. Removing the anchor closes the fixture gap entirely rather than papering over it with a new fixture.

## Decision

Remove the audit-tip anchor entirely from v0.9.3:

- `harness anchor` subcommand removed.
- `~/.harness/secret.key` minting removed.
- D-7 anchor update step removed from the five-step crash-safe transaction protocol.
- D-8 state-trust preflight steps 4–5 (anchor verification) removed.
- D-9 anchor ordering section removed.

**Vestigial files**: Existing `~/.harness/audit-tip/<id>.json` and `~/.harness/secret.key` left on user machines from prior installs are silently ignored. No automatic cleanup. No error. Users who wish to reclaim disk space may delete `~/.harness/audit-tip/` manually.

## Consequences

**Positive**:

- Fresh install works without any manual anchor-mint step. `harness next` on a new machine exits 0.
- Audit-integrity claim is simplified to "chain-integrity only" — the per-entry `entry_hash` / `previous_entry_hash` chain (D-3B) detects accidental edits, truncation, partial rewrites, and rotation-seam corruption. This was always the primary integrity mechanism; the anchor was an additional layer.
- Operational complexity reduced: `~/.harness/secret.key` rotation, anchor-update failure paths (exit 14 `anchor_update_failed`), and `.seen.json` rollback tracking all removed.
- Smoke-test fixture surface shrinks: no pre-minted anchor files needed.

**Negative**:

- Coordinated audit-log replay by a repo-local attacker (rewrite all entries + recompute all `entry_hash` values) is no longer mitigated by an external anchor. This threat class was already documented out of scope and requires compromising the user account.

**Hardening retained**:

- `state_trust.preflight` is _hardened_ in this release: it now refuses to trust state when the audit log is empty or missing but the state file has been advanced past the install baseline (`sub_reason: state_advanced_without_audit_evidence`). This catches the case where a user accidentally deletes `audit.log` — it does not silently pass preflight.
- TXN-verb audit entries missing `after_sha256` now raise (`txn_entry_missing_after_sha256`) instead of being silently walked past.

## Alternatives Considered

- **Auto-mint anchor on first run**: Closes the fresh-install regression but keeps the operational surface (key management, key loss, adapter `permissions.deny` requirements). Rejected because the defended threat class is out of scope.
- **Soft anchor (no HMAC signature, just a pointer file)**: Removes key management but provides no tamper evidence. A repo-local attacker can rewrite the pointer. Rejected as security theater.
- **Keep anchor, fix installer**: Patch the install script to call `harness anchor repair` automatically. Does not address the threat-model argument; adds fragile install-time side effect. Rejected.

## Cross-references

- Superseded: `docs/adr/2026-05-17-audit-canonicalization-locking-and-state-trust.md` §D-7, §D-8 (steps 4–5), §D-9.
- Chain integrity still governed by: `docs/adr/2026-05-17-audit-canonicalization-locking-and-state-trust.md` §D-1 through §D-6, §D-8 (steps 1–3).
- Slices 1 and 2 of this removal: `anchor-removal` branch (code + tests).
- Upgrade-compat smoke case: `upgrade-from-v091-with-vestigial-anchor` in `scripts/release_smoke_test.py`.
