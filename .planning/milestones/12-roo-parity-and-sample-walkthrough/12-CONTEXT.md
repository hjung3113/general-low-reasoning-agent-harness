# M12 Context — Roo Adapter Parity + Sample Walkthrough

## Why

M11 hardening (4-iter live test on calc) closed CC9 (workflow bypass) for opencode adapter via 5-layer defense. Roo adapter was not re-hardened — `.roo/rules/phase-gate.md` lacks the STOP banner + refusal template that AGENTS.md managed block and `.opencode/commands/*.md` now carry. User confirmed Roo is their next target environment (no hook infra; needs prompt-layer defense parity).

Additionally, M11 produced a 4-iteration test artifact (`/Users/hyojung/Desktop/2026/calc-iter4/`) that is currently invisible to first-time users — there's no in-repo example showing "prompt → opencode action → state/doc change" flow.

## Confirmed Facts

- `.roo/` adapter exists (rules + commands + skills); manifest tracks 97 roo entries.
- `.roo/rules/phase-gate.md` covers behavioral rules but no STOP banner / no refusal template / no `harness next --prompt` STEP 0.
- `.roo/commands/phase-execute.md` lacks STEP 0 guard check (opencode parity gap).
- Pre-commit hook (`harness install --pre-commit`) is editor-agnostic → already protects Roo at commit boundary.
- AGENTS.md managed block is editor-agnostic if Roo reads it (Roo does read `AGENTS.md`).

## Inferred Facts

- Roo achievable defense strength: same prompt-layer defense as opencode; tool-call veto unavailable in both (no plugin API used).
- HTML walkthrough best lives under `docs/examples/` (new dir); README link from "Getting Started".

## Scope

In:
- Mirror opencode STOP banner / STEP 0 / refusal template into `.roo/rules/phase-gate.md` + `.roo/commands/phase-{discuss,plan,execute}.md`.
- Sync skeleton/clean if Roo files are deployed there (manifest-driven; check).
- `docs/examples/calc-walkthrough.html` — single-file presentation rebuilt from `/Users/hyojung/Desktop/2026/calc-iter4/FINAL-REPORT.html` content but reframed as **usage tutorial** (per-step prompt + opencode action + state/file delta), not as hardening retro.
- README/MANUAL: add "Roo Code" mention parity with opencode; link to walkthrough.

Out (defer):
- opencode plugin write-time veto (M13 candidate; opencode-only, learning cost).
- `harness phase override` CLI (no real blocked case yet).
- `harness phase suggest-transition` / `phase status` (UX-redundant with `next --prompt`).
- Telemetry (no analytics infra).

## Risks

- Mirroring opencode banners verbatim into Roo may collide with Roo's existing `--auto`/`--chain` rules — verify no conflicting instructions.
- Sample HTML must not double as marketing (caveman tone OK in docs; this is tutorial — write normal).
