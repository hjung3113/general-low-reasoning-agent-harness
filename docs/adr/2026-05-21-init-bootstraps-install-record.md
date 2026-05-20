# ADR: `harness init` Bootstraps `.harness/install-record.json`

**Date**: 2026-05-21
**Status**: Accepted (v0.9.5)
**Amends**: `2026-05-17-approver-provenance-and-execution-mode.md` — install-record creation path
**Companion ADR**: `2026-05-19-phase-approve-speed-bump.md` (speed-bump model preserved unchanged)

## Context

Prior to v0.9.5, `harness init` did not write `.harness/install-record.json`. This file is required by `phase approve` (step 3 of the approver-membership gate) — its absence caused `phase approve` to exit with `exit_code=6 / sub_reason=install_record_missing`, blocking the entire lifecycle on every fresh install (NEW-1 from the v0.9.5 smoke report).

The v0.9.4 design assumed users would populate `install-record.json` manually or via a separate mint step that was never implemented. The net effect: `harness init` on a new machine → `phase approve` always exits 6 regardless of identity.

## Decision

`harness init` now writes `.harness/install-record.json` immediately after copying harness files and before the success message. The operator's email address is resolved at init time using the following priority chain:

1. `--approver-email <addr>` CLI flag (for CI/automation)
2. `HARNESS_INSTALL_APPROVER=<addr>` environment variable
3. `git config user.email` (default for interactive use)
4. Hard refuse with actionable error citing all three fallbacks

The resolved email is sanitized (trim ASCII whitespace, reject empty, reject control chars and multi-line input, lowercase for storage). The stored value is always lowercase; the `added_at` timestamp is set to the install instant.

The bootstrap record schema (schema_version 1):

```json
{
  "schema_version": 1,
  "harness_version": "<version>",
  "installed_at_iso": "<UTC-Z ISO-8601>",
  "bootstrap_source": "cli-flag" | "env" | "git-config",
  "approvers": [
    {"email": "<lowercase-email>", "added_at": "<UTC-Z>", "source": "bootstrap"}
  ],
  "source_provenance": {"commit": "<sha>", "tag": "<tag-or-empty>", "dirty": false}
}
```

The `approvers` array uses the dict format that `phase_preflight.approvers_emails()` already handles, so `phase approve` works immediately without changes to that module.

An `install_record.bootstrap` audit row is appended to `.harness/audit.log` via `lib.audit.audit_append` (chain-integrated per ADR-003; never raw JSON).

### Idempotency

Re-running `harness init` on a target that already has an `install-record.json` (e.g. after `harness upgrade`) logs an advisory to stderr and preserves the existing file. No audit row is written on the skip path. This ensures TTY-minted approvers added after the initial bootstrap are not silently clobbered.

### `--dry-run` behaviour

Approver-email resolution is skipped entirely for `--dry-run` runs. No file is written and no audit row is appended.

## Threat Model

Per [[internal-only-threat-model]] memo: repo-local attackers are explicitly out of scope for this tool. Auto-bootstrap of `install-record.json` from `git config user.email` is therefore safe — any attacker who can edit git config already has code-execution as the user.

The speed-bump TTY gate on `phase approve` is **not** weakened by this change. The only effect is that the approver membership check (step 3) now has a file to read instead of refusing immediately.

## Consequences

**Positive**:

- Fresh `harness init` → `phase approve` works without any extra steps.
- CI installations can pass `--approver-email` to set the bot identity non-interactively.
- `HARNESS_INSTALL_APPROVER` supports container/environment-variable–driven installs.

**Negative / trade-offs**:

- Operator must have `git config user.email` set (or pass `--approver-email`) for init to succeed. This is intentional: a nameless install is unusable for phase lifecycle.

## Alternatives Considered

- **Separate `harness bootstrap-install-record` verb**: Adds a step not documented in the install guide. Rejected — v0.9.5 was already broken due to missing file; adding a second manual step repeats the problem.
- **Write install-record with no approvers and let users add manually**: Defers the exit-6 to `phase approve` time rather than fixing it at init. Rejected — same user experience as the pre-existing bug.
- **Fallback to repo-committer email from `git log`**: Fragile (initial commit may differ from current operator). Rejected in favour of `git config user.email` which reflects the current machine identity.

## Cross-references

- Resolved by: `scripts/lib/install.py` (`write_install_record`, `resolve_approver_email`)
- CLI: `scripts/harness.py` (`--approver-email` flag on `init` subparser)
- Consumer: `scripts/lib/phase_approve.py` step 3 (no change required)
- Audit verb: `install_record.bootstrap` (registered in `scripts/lib/audit.py:KNOWN_VERBS`)
- Tests: `tests/test_install_record_bootstrap.py`
- ADR 003a (speed bump): `docs/adr/2026-05-19-phase-approve-speed-bump.md` (preserved unchanged)
