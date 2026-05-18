# Phase 2 Checkpoints - v0.8.0 Minimal Workflow Release

## CP-02-01 - Design Locked

Status: Complete for planning.

- Active design doc written.
- gpt-5.5 design synthesis completed.
- Claude adversarial design review completed.
- Claude re-review blockers patched.
- Claude third review returned GO for implementation planning.

## CP-02-02 - Contract and Behavior

Status: Pending.

- High-level machine JSON goldens land first.
- `harness`, `harness run`, and normal `harness check` behavior implemented.
- TTY approval challenge and non-TTY refusal tested.
- Error scrub tests cover stdout, stderr, docs, and adapter prompts.

## CP-02-03 - Docs and Adapters

Status: Pending.

- README and manual teach simplified workflow first.
- Internal UML and installed-user workflow UML added under `docs/`.
- Roo/OpenCode adapter prompts use `HARNESS_MACHINE=1 harness next/run/check`.

## CP-02-04 - Reviews and Release

Status: Pending.

- CLI/UX, workflow safety, adapter consistency, docs/onboarding, and release/CI specialist reviews completed.
- Combined brief reviewed by Claude.
- Release checks pass.
- v0.8.0 tag pushed.
