# Phase Gate Hardening Round-6 Review Notes

Date: 2026-05-17

Target: `docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md`

Method: five adversarial subagents reviewed the design against the project purpose: a client-neutral, stack-neutral low-reasoning agent harness where `.planning/**` is canonical, `.scratch/phase-state.json` is only the live gate, and Roo/OpenCode are adapters rather than sources of truth.

Verdict before edits: BLOCK. The design was directionally correct but still allowed spoofed non-TTY authorization, trusted directly edited state, attached approval too late, mixed adapter details into the core contract, and lacked release-grade evidence.

## What changed

### 1. CI authorization is no longer env-only

Problem: `HARNESS_AUTOMATION` / `HARNESS_BY_TRUST` plus provider env vars could be forged by an agent shell.

Change: §3.5.1 now requires cryptographically verified CI attestation. GitHub/GitLab/Buildkite require OIDC/JWT validation and claim matching. CircleCI/Jenkins are absent until they have an explicit proof contract.

Why: low-reasoning agents can mechanically set env vars. A non-TTY gate must rely on proof the local shell cannot fabricate.

### 2. Direct state edits fail closed

Problem: lock and transaction journal protect harness-managed writes, but raw `Edit`/`Write` can overwrite `.scratch/phase-state.json` without taking the lock.

Change: §2.6 adds a state trust preflight. Every CLI command must compare canonical current state hash with the latest audit `after_sha256` before trusting state.

Why: the live gate is only meaningful if forged `approved=true` or `execution_mode=chain_autopilot` edits are rejected before use.

### 3. Approval moved to execute entry

Problem: approval was primarily checked on `execute -> done`, allowing an agent to enter `execute` before human approval.

Change: §3.6 now requires `approved=true` and `approved_at >= plan_finalized_at` for `plan -> execute`. `execute -> done` keeps a secondary stale-approval check.

Why: the safety invariant is "no code-executing phase without prior human approval," not "no completion without approval."

### 4. Core protocol no longer stores adapter tool names

Problem: budget keys such as `bash` and `edit` leaked Claude/Roo-shaped tool names into core state.

Change: §1.1 replaces them with capability-neutral keys: `shell_invocations`, `file_mutation_ops`, and `wall_seconds`.

Why: the harness core must remain client-neutral; adapter-specific tool mapping belongs in adapter contracts.

### 5. Slash commands became wrapper prompts

Problem: adapter Markdown embedded POSIX shell snippets and direct `harness phase autopilot start` calls. That was non-portable and mismatched Roo/OpenCode command-file reality.

Change: §3.5 introduces `harness fsd-run-phase` and `harness fsd-run-all` wrappers. §4.3/§4.4 adapter command bodies are now prompts that invoke those wrappers, with no shell parsing.

Why: runnable behavior belongs in the cross-platform CLI. Adapter files should instruct weak agents, not become shell scripts.

### 6. OpenCode positional behavior is no longer contradictory

Problem: one section said OpenCode ignores trailing tokens; another smoke test expected `/fsd-run-phase phase-x` to set `phase-x`.

Change: §3.5 splits smoke expectations by adapter. Roo honors positional slug. OpenCode no-arg uses `next-pending`; trailing tokens are ignored and tested as a negative positional case.

Why: weak implementers need one oracle per adapter, not a shared assertion that contradicts the adapter contract.

### 7. Human-only next actions are not shell-capturable

Problem: `harness next` was designed for shell capture but still printed human-only commands such as approval.

Change: §3.9 separates human-readable `harness next`, safe `harness next --shell`, and structured `harness next --json`.

Why: agents will mechanically execute stdout. Human-only commands must not appear as successful shell output.

### 8. Release readiness became evidence-based

Problem: ADR files were placeholders, smoke command paths were inconsistent, CI matrix requirements were not tied to workflow changes, and slice results had no durable evidence path.

Change: §7.1 requires a release workflow matrix. §8 pins real ADR filenames and `Status: Accepted` checks. §9 uses the canonical `scripts/release_smoke_test.py` path. §9.1 adds migration/state-tamper fixtures. §9.2 adds a release evidence contract under `.planning/phases/<phase-id>/evidence/<slice-id>/`.

Why: implementation should not begin until prerequisites and release evidence are machine-checkable.

## Remaining constraints

- Raw adapter tool calls are still outside v0.7 hard enforcement. The design now says this honestly and limits hard-stop claims to harness-mediated operations.
- True adapter pre-tool hooks, multi-user approver management, and real container isolation remain out of scope.
- The design is still a planning artifact. Code, tests, ADR files, and CI workflow changes must land in later implementation slices.
