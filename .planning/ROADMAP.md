# ROADMAP - General Harness Release

## Phases

- [x] **Phase 1: Generalized Harness Release** - Publish the stack-neutral harness with OpenCode compatibility and composable workflow skill packs.
- [ ] **Phase 2: v0.8.0 Minimal Workflow Release** - Ship the four-command navigator workflow while preserving approval, adapter, JSON, release, and security boundaries.

## Phase Details

### Phase 1: Generalized Harness Release

**Goal**: Turn the prior project-specific harness into a reusable source repository.

**Success criteria**:

1. README and protocol docs describe a client-neutral, stack-neutral harness.
2. Installer supports core-only, Roo, OpenCode, and combined adapter targets.
3. Default skill pack installs generic workflow plugins.
4. Tests cover core-only, OpenCode-only, and skill-pack installation.
5. Source and target checks pass before push.

### Phase 2: v0.8.0 Minimal Workflow Release

**Goal**: Replace the normal v0.7.2 low-level phase-machine UX with a four-command navigator surface.

**Success criteria**:

1. Normal user-facing CLI is capped at `harness`, `harness next`, `harness run`, and `harness check`.
2. Normal happy path has no flags and fits in one short copyable transcript.
3. Roo/OpenCode adapter happy paths use high-level machine mode and do not require low-level phase/state knowledge.
4. Approval, execute prerequisites, malformed state, JSON contracts, release checks, and security-sensitive flows remain hard boundaries.
5. README, manual, internal UML, installed-user workflow UML, specialist reviews, Claude review, tests, release checks, and `v0.8.0` tag are complete.

## Progress

| Phase | Plans Complete | Status | Completed |
| --- | ---: | --- | --- |
| 1. Generalized Harness Release | 1/1 | Complete | 2026-05-15 |
| 2. v0.8.0 Minimal Workflow Release | 0/1 | Proposed / not executable yet | - |
