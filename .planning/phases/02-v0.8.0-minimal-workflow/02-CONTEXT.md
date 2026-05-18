# Phase 2 Context - v0.8.0 Minimal Workflow Release

## Status

Proposed / not executable yet.

Do not implement this phase until `.scratch/phase-state.json` names this phase, reports `phase=execute`, reports `approved=true`, and includes the required paths.

## Background

v0.7.2 shipped at `29c1736` with tag `v0.7.2`. It preserved strong phase-gate ceremony, JSON byte-equality coverage, release checks, and adapter contracts, but left v0.8.0 UX deferrals in `docs/superpowers/specs/v0.8.0_todo/`.

The active v0.8.0 direction is to make the harness feel like a navigator rather than a lockbox:

- four or fewer normal user-facing commands;
- no flags on the normal happy path;
- GPT-4-era adapter safety through a pinned machine contract;
- low-level phase, nonce, trust, anchor, repair, and autopilot internals moved to advanced/debug/CI surfaces;
- hard boundaries retained for approval, edit permission, malformed state, adapter contracts, release, and security-sensitive flows.

## Design Evidence

- `docs/superpowers/specs/2026-05-19-v0.8.0-minimal-workflow-design.md`
- `docs/superpowers/plans/2026-05-19-v0.8.0-minimal-workflow.md`
- `docs/superpowers/specs/v0.8.0_todo/README.md`

Adversarial review status:

- gpt-5.5 design synthesis: GO for implementation planning.
- Claude third review: GO for implementation planning, no remaining design blockers.

## Non-Goals

- Do not delete low-level compatibility commands in v0.8.0.
- Do not add `harness mode` to the normal surface.
- Do not make onboarding, slash discovery, heartbeat, autopilot dry-run, or `phase back` part of the normal path.
- Do not make Roo/OpenCode sources of truth.
- Do not add stack-specific behavior to core.
