# ADR: phase.approve Speed Bump Model (v0.9.0)

**Date**: 2026-05-19
**Status**: Accepted
**Partially supersedes**: `2026-05-17-approver-provenance-and-execution-mode.md` (phase.approve scope only)

## Context

The 2026-05-17 ADR established phase.approve as a cryptographically-bound human-presence proof using an HMAC approval-nonce, audience binding, 120-second TTL, and minter/consumer TTY separation. The mechanism was designed to defend against agent self-approval.

In v0.8.x dogfooding, the owner determined the workflow cost exceeds the security benefit for this tool's intended scope (a personal/small-team dev harness). Users reported friction: a separate verb, a second terminal, TTL races, and unfamiliar terminology ("nonce", "audience", "HMAC", "consumer_tty"). The owner accepts that an agent with PTY access can defeat any prompt-based check and chose not to defend against that threat in this path.

## Decision

For `harness phase approve` only:

- Remove HMAC-nonce, audience, TTL, and minter/consumer TTY separation.
- Add a `[y/N]` prompt on the user's TTY.
- Halt with `EXIT_HUMAN_CONFIRMATION_REQUIRED=17` + `sub_reason=non_tty_approval_blocked` when stdin is non-TTY.
- Stamp `proof_class=soft_tty` in the audit row (chain-verified row, no separate signature).

For `harness release` and every other release-path verb: **no change**. Signed tags, OIDC, HMAC nonces, and release_trust verification all remain as specified in the 2026-05-17 ADR.

## Consequences

- An agent running in the user's TTY can drive `[y/N]` with expect/pexpect. This is explicitly accepted. The speed bump is a workflow checkpoint, not a security boundary.
- Audit rows for phase.approve can no longer prove a human typed the response. The audit chain still detects tampering.
- The CLI verb `approve-nonce mint --audience phase.approve` becomes a deprecated no-op in v0.9.0 and is removed in v1.0. Other audiences unaffected.
- The 2026-05-17 ADR's threat model and mitigations remain in force for the release path.

## Non-goals

- Removing autopilot. Autopilot proceeds without asking; the speed bump always asks. They are orthogonal features.
- Defending phase.approve against PTY-automating agents.
- Touching `harness release`, `release.py`, `release_smoke_test.py`, `release_trust.py`, `verify_release_tag`, `.github/workflows/release.yml`, `docs/trust/`, or any signed-tag / OIDC code path.
