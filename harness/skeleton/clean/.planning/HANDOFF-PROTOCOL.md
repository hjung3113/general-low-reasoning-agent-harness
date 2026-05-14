# HANDOFF PROTOCOL

Use this protocol after any reset, handoff, or new agent session.

## Fresh Session Start

1. Read `AGENTS.md`.
2. Read `.planning/STATE.md`.
3. Read `.planning/ROADMAP.md`.
4. Read `.planning/codebase/ARCHITECTURE.md`, `STACK.md`, `STRUCTURE.md`, `CONVENTIONS.md`, `TESTING.md`, `INTEGRATIONS.md`, and `CONCERNS.md` when they exist.
5. Read the active phase `*-CHECKPOINTS.md`.
6. Read the active phase context, plan, review, verification, and summary files when they exist.
7. Read `.scratch/phase-state.json` if it exists. If it does not exist, default to `discuss`.
8. Run `git status --short`.
9. Do not edit implementation files unless the live phase state permits it.

## During Work

- Update `.planning/STATE.md` when the current phase, plan, checkpoint, blocker, or next action changes.
- Update the active `*-CHECKPOINTS.md` after each checkpoint.
- Put command results and review outcomes in `*-VERIFICATION.md` or `*-REVIEW.md`.
- Promote durable decisions to `.planning/DECISIONS.md` or an ADR.

## Before Ending A Session

1. Ensure `.planning/STATE.md` has one concrete next action.
2. Ensure live `.scratch/phase-state.json` points to the active plan and checkpoint.
3. Ensure phase summary and verification are current.
4. If a temporary handoff is requested, reference these files instead of duplicating their full contents.
