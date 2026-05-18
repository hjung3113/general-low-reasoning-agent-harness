# Friendly Workflow CLI Minimization Design

Date: 2026-05-18
Status: proposed design
Scope: reduce user-facing CLI complexity while keeping strong agent guidance

## Goal

Make the harness feel like a workflow guide, not a security product.

The harness should still make it hard for an agent to silently skip `discuss -> plan -> approve -> execute -> done`, but it does not need to make skipping systemically impossible in normal local use. Hard enforcement should remain available for CI, release, protected branches, and teams that explicitly opt into it.

Important distinction: "not systemically impossible" applies to human local work. Adapter-facing commands must never return "safe to edit" when the approval boundary has not been crossed. The softer UX is for humans; the machine contract for agents still needs hard stop states.

## Current Purpose

The project is a generalized low-reasoning agent harness. Its durable source of truth is `.planning/**`; its live gate is `.scratch/phase-state.json`; adapters such as Roo and OpenCode are clients, not the source of truth.

The existing CLI currently serves two different jobs:

1. State machine and provenance:
   - `harness phase set discuss|plan|execute|done`
   - `harness phase approve`
   - `harness phase reopen`
   - `harness state show`
2. Enforcement and diagnostics:
   - `harness check`
   - `harness check --worktree`
   - `harness doctor`
   - `harness install --pre-commit`
   - `harness phase autopilot start|stop`
   - `harness approve-nonce mint`
   - `harness session unlock`

This is powerful, but it asks users to know the workflow internals. That is the wrong default for a low-reasoning harness.

## How The Current CLI Prevents Agent Skips

### Prompt-Level Controls

Roo and OpenCode command files tell the agent to:

- start by running `harness check`;
- treat `discuss` as read-only discovery;
- treat `plan` as planning/doc-only work;
- require explicit approval before execute;
- modify only `allowed_paths`;
- run `harness check --worktree` before finishing.

This is guidance, not mechanical enforcement. It catches cooperative agents, not adversarial or confused ones.

### Live Gate Projection

`show_phase_status.py` and `harness check` project whether execute is valid. A valid execute gate requires the live state to be `phase=execute`, approval to be present, planning pointers to be durable, and key fields such as `plan_id`, `allowed_paths`, `verification`, and `acceptance_criteria` to be populated.

This is useful because the agent can be told: "If projection is invalid, stop and report the next required step."

### Transition Validation

`phase set` rejects invalid transitions and validates state shape. Moving into execute is not just a raw JSON edit when done through the CLI. It requires plan metadata and approval prerequisites.

This prevents an agent that follows the CLI from jumping straight into implementation.

### Human Approval Gate

`phase approve` is the strongest current anti-agent mechanism:

- refuses non-TTY callers;
- resolves identity from `--by` or `git config user.email`;
- checks install-record approver membership;
- runs anchor and state-trust preflight;
- refuses approval during autopilot;
- requires a human-presence nonce.

This is stronger than the target default UX. It belongs in enforce mode, not the everyday path.

### Worktree Scope Check

`harness check --worktree` compares changed files against `allowed_paths` and returns scope violation exit code 4. The optional pre-commit hook runs this check and blocks commits.

This is the best mechanical guard because it acts at the commit boundary, not at every thought or edit. It should remain available, but the default behavior should be configurable as warning-first.

### Filesystem Fence

`fs_fence.py` defines path-level write enforcement for autopilot modes, but it is not fully wired into production callers yet. It also explicitly allows manual mode. This means it is not currently the main safety mechanism for ordinary local work.

## Product Direction

Move from "many explicit lifecycle commands" to "one status-aware command surface".

Recommended user-facing commands:

```text
harness          # default dashboard + next action
harness next     # explain the next safe workflow step
harness run      # perform the next safe low-risk step, or stop with a clear prompt
harness check    # report drift, warnings, and enforcement status
harness mode     # switch guide/enforce behavior
```

Power-user commands can remain, but should be documented as internal or advanced:

```text
harness phase set ...
harness phase approve
harness phase reopen
harness approve-nonce mint
harness install --pre-commit
harness session unlock
harness state show
```

The important change is not deleting capabilities. It is changing the default UX so users and agents do not need to memorize the lifecycle API.

## Enforcement Model

### Guide Mode

Default for local development.

Guide mode should:

- never silently approve or execute;
- never tell an adapter that editing is allowed before explicit approval;
- warn loudly when the agent is out of phase;
- produce a concrete next action;
- make drift visible in final status;
- avoid blocking local work unless the user explicitly asked for hard enforcement.

Recommended behavior:

| Condition | Guide mode result |
| --- | --- |
| execute requested before approval by a human-facing command | warning + next action |
| execute requested before approval by an adapter-facing/JSON command | blocked status + non-zero exit |
| implementation edits during discuss/plan | warning + drift report |
| changed path outside `allowed_paths` | warning + remediation |
| missing verification | warning + suggested command |
| state JSON malformed | hard error |
| planning pointers stale | warning unless command would mutate state |

Guide mode still helps low-reasoning agents because adapter prompts can require: "Before continuing, run `harness next`; if it reports warnings, show them and ask the user."

That prompt rule is not enough by itself. The adapter-facing contract must be machine-readable and conservative:

```json
{
  "status": "blocked",
  "boundary": "approval_required",
  "may_edit": false,
  "requires_user_approval": true,
  "next_user_prompt": "Approve plan <plan_id> before execute?",
  "next_command": "harness run --approve"
}
```

An agent should only edit when the machine output includes `status="ok"` and `may_edit=true`.

### Enforce Mode

Opt-in for CI, release, protected branches, high-risk repos, and teams that want strict gates.

Enforce mode should:

- keep non-zero exits for scope violations;
- block commits via pre-commit/pre-push hooks;
- require explicit approval provenance;
- require human proof where configured;
- reject invalid phase transitions;
- fail closed on malformed state or trust-anchor mismatch.

Recommended behavior:

| Condition | Enforce mode result |
| --- | --- |
| execute requested before approval | hard error |
| implementation edits during discuss/plan | hard error at `check --worktree` or hook |
| changed path outside `allowed_paths` | hard error |
| missing verification | hard error before execute |
| state JSON malformed | hard error |
| planning pointers stale | hard error |

### Suggested State Field

Add or normalize:

```json
{
  "enforcement": "guide",
  "approval_policy": "explicit",
  "identity_policy": "optional_git_email"
}
```

Allowed values:

- `enforcement`: `guide`, `enforce`
- `approval_policy`: `explicit`, `nonce`, `external`
- `identity_policy`: `none`, `optional_git_email`, `required_approver`

This decouples "human approval happened" from "local Git identity must be cryptographically trusted."

## Git Email And Approval Identity

Keep git email support, but do not require it in default guide mode.

Current git-email behavior is useful for audit provenance, but too heavy as a universal local workflow requirement. A solo user or lightweight project should not be blocked because `git config user.email` is missing.

Recommended policy:

### Guide Mode

- If `git config user.email` exists, stamp it as `approved_by`.
- If missing, stamp `approved_by` as `local-user` or require an inline label prompt.
- Do not require install-record approver membership.
- Do not require cross-TTY nonce.
- Record `approval_source`: `gitconfig`, `prompt`, or `unknown-local`.

### Enforce Mode

- Require git email or explicit `--by`.
- Require approver membership when configured.
- Keep nonce/human-proof for autopilot, CI handoff, and sensitive repos.
- Keep audit anchor and state-trust preflight.

This preserves provenance without making the normal user fight local Git configuration.

## Proposed Command Semantics

### `harness`

No arguments should be useful. It should print:

- current phase;
- whether execute is currently recommended;
- warnings;
- next action;
- enforcement mode;
- one command to continue.

It should not mutate state.

### `harness next`

Read-only planner. It should decide the next workflow step:

- no phase state: initialize planning state;
- `discuss`: summarize required discovery output;
- `plan`: ask for or validate plan fields;
- approved plan but not execute: suggest transition;
- `execute`: show allowed paths and verification;
- `done`: suggest summary/verification closeout or next phase.

It should be the main command adapters call before acting.

### `harness run`

State-aware runner. It may perform only safe, reversible, or explicitly approved steps:

- create missing skeleton files;
- render status;
- move `discuss -> plan` only with explicit `--apply`;
- never move `plan -> execute` unless approval is already recorded and the command is explicitly applying that transition;
- never create approval by itself;
- refuse or prompt when approval is needed;
- in guide mode, warn instead of blocking when possible;
- in enforce mode, preserve current hard errors.

It should never silently approve a plan.

For adapter-facing use, `harness run --json` must be conservative: no approval, no execute transition, and no edit permission unless the live state is already valid for execute.

### `harness check`

Unified checker. Replace "which check do I run?" confusion with flags controlled by mode:

- guide mode: report warnings and exit 0 unless state is unreadable;
- adapter/JSON mode: return non-zero for boundary violations even in guide mode;
- enforce mode: exit non-zero on gate/scope violations;
- `--strict`: one-shot enforce behavior;
- `--for-agent`: machine contract for adapters; equivalent to conservative JSON mode;
- `--worktree`: still supported but shown as advanced.

### `harness mode`

Simple mode command:

```text
harness mode guide
harness mode enforce
harness mode show
```

This replaces hidden policy assumptions inside scattered commands.

## Adapter Prompt Changes

Adapters should stop telling agents to manually sequence low-level commands.

Replace:

```text
harness phase approve
harness phase set execute
harness check --worktree
```

With:

```text
Run `harness next` before acting.
If it says approval is required, ask the user.
If it says execute is allowed, stay inside the listed allowed paths.
Before final response, run `harness check`.
```

For enforce mode, adapter prompts may still mention that hooks or CI can block the work.

Preferred adapter form:

```text
Run `harness next --for-agent --json`.
Proceed with edits only if `status=ok` and `may_edit=true`.
If `status=blocked`, show `next_user_prompt` to the user and stop.
```

## Migration Plan

1. Add `enforcement` and policy fields to state, defaulting to guide mode.
2. Add read-only `harness next` as the primary adapter command.
3. Change no-arg `harness` to show status and next action.
4. Add `harness mode guide|enforce|show`.
5. Change `harness check` to warning-first in guide mode and strict in enforce mode.
6. Add `--for-agent --json` output for `next` and `check`; boundary violations must produce `status=blocked`, `may_edit=false`, and non-zero exit.
7. Keep existing phase commands as advanced compatibility APIs, but route them through the same transition validator.
8. Update Roo/OpenCode prompts to call `harness next --for-agent --json` and `harness check --for-agent --json`, not low-level phase commands.
9. Make pre-commit hook opt-in enforce behavior, or warning-only unless `enforcement=enforce`.
10. Relax git email and nonce requirements in guide mode while preserving them in enforce mode.
11. Update docs to present the minimal CLI first and move lifecycle internals to an advanced appendix.

## Adversarial Review

### Reviewer A: Workflow Safety Reviewer

Lenses:

- Can a low-reasoning agent still skip planning without noticing?
- Are warnings concrete enough for a weak model to act on?
- Does guide mode accidentally normalize unsafe implementation?

Findings:

1. A warning-only system can be ignored unless adapter prompts require the agent to surface warnings to the user.
2. `harness next` must return structured, low-ambiguity output: current state, violation, exact next action, and whether user approval is required.
3. Guide mode should still hard-fail unreadable state. If the state cannot be parsed, guidance is not trustworthy.
4. The design must keep enforce mode available and easy to enable for CI.

Reinforcement applied:

- `harness next` is read-only and becomes the adapter-facing gate.
- malformed state remains a hard error in both modes.
- enforce mode remains first-class.
- adapter prompts are updated to require surfacing warnings.

### Reviewer B: UX And Adoption Reviewer

Lenses:

- Does a normal user need to memorize workflow internals?
- Can a new user recover when the harness complains?
- Is git email approval too much ceremony?

Findings:

1. The current CLI exposes too many lifecycle internals. That makes the harness feel brittle even when the model is good.
2. Approval should be a product concept, not a Git configuration puzzle.
3. The no-arg command should be useful. Users naturally try `harness` first.
4. The pre-commit hook should not surprise users by blocking commits unless enforce mode is visible.

Reinforcement applied:

- minimal command surface is `harness`, `harness next`, `harness run`, `harness check`, `harness mode`.
- git email becomes optional in guide mode.
- hook behavior follows enforcement mode.
- advanced commands remain but are no longer the default documentation path.

## Reviewer Debate Summary

Safety reviewer wanted `approval_policy=nonce` to remain default because it is the strongest line against agent self-approval.

UX reviewer objected that cross-TTY nonce plus git email membership is too much ceremony for the common case and will cause users to bypass the harness entirely.

Resolution:

- default to `approval_policy=explicit` in guide mode;
- require the agent to ask the user and record the approval source;
- keep `approval_policy=nonce` available and recommended for enforce mode, CI handoff, and high-risk work;
- make `harness next` detect missing approval and phrase it as a user decision, not a stack trace.
- make adapter-facing `harness next --for-agent --json` return `status=blocked` and `may_edit=false` until approval is recorded.

Safety reviewer also wanted path scope violations to remain hard failures.

UX reviewer argued that local exploratory work often touches files before the plan catches up.

Resolution:

- guide mode reports path drift loudly but does not block;
- enforce mode blocks at `check --worktree`, pre-commit, pre-push, or CI;
- `harness run` never auto-expands `allowed_paths`; it asks the user to return to plan.

## External Adversarial Review Round

After the initial design was written, an independent workflow-safety reviewer attacked the proposal.

Findings accepted:

1. Guide mode cannot return success-like adapter output for missing approval. A weak model can treat warnings plus exit 0 as permission to continue.
2. Adapter compliance cannot be the only enforcement mechanism. The CLI needs a machine-readable blocked state.
3. `harness run` mutation policy was underspecified. It must not auto-approve or casually cross `plan -> execute`.
4. Human-friendly exit code behavior must be separated from agent-facing exit code behavior.
5. Existing low-level commands must share the same transition validator.
6. Guide-mode approval still needs a substitute invariant when git email, approver membership, and nonce are relaxed.

Design changes applied:

- added adapter-facing `--for-agent --json` contract;
- changed approval boundary in guide mode from warning-only to blocked for adapter-facing commands;
- constrained `harness run` so it never creates approval and never grants edit permission unless execute is already valid;
- required explicit approval provenance even in guide mode;
- expanded acceptance criteria with concrete negative cases.

## Open Questions

1. Should `harness run` ever mutate phase state, or should it only print the exact low-level command?
   - Recommendation: allow mutation only with `--apply`, never approval creation, and never adapter edit permission before execute is already valid.
2. Should `harness mode enforce` install hooks automatically?
   - Recommendation: yes, after a confirmation prompt; in non-interactive environments, print the command and exit non-zero.
3. Should guide mode use exit code 0 for warnings?
   - Recommendation: yes for human-facing local output only. Adapter-facing `--for-agent --json` must use non-zero exits for boundary violations.

## Acceptance Criteria

- A new user can operate the harness with `harness`, `harness next`, `harness run`, and `harness check`.
- Existing low-level commands keep working for compatibility.
- Guide mode does not require git email, approver membership, or nonce.
- Guide mode still records explicit approval provenance: approver label, timestamp, plan id or plan hash, and approval source.
- Enforce mode preserves strict approval, scope, and worktree behavior.
- Adapter prompts no longer require users to know `phase set`, `phase approve`, or `check --worktree`.
- Adapter-facing output includes at least: `status`, `phase`, `may_edit`, `boundary`, `requires_user_approval`, `next_user_prompt`, `next_command`, and `warnings`.
- Adapter-facing output never returns `may_edit=true` before approval is recorded and execute gate prerequisites are satisfied.
- Direct `phase set execute` fails unless the same approval, plan metadata, allowed path, and verification prerequisites are present.
- Malformed `.scratch/phase-state.json` is a hard error in guide and enforce modes.
- Test cases cover: no state means no edit permission; discuss/plan plus code changes creates blocked adapter status; plan without approval blocks execute; approval without plan metadata blocks execute; out-of-scope worktree changes are warnings for humans and blocked for `--for-agent`; direct low-level execute transition is rejected.
