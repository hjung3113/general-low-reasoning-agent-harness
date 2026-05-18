# v0.8.0 — UX Polish

> **S13 release smoke (landed in v0.7 develop):** Run `python scripts/release_smoke_test.py --release --evidence-dir <dir>` to execute the full §12.10 case catalogue and write per-case evidence to `<dir>/<case_name>/{result.json,stdout.txt,stderr.txt,...}`. The exit code is 0 if all cases pass, 1 on any failure. Per §7.1, `.github/workflows/release.yml` expands to 7 release-gate rows × OS/Python/shell matrix (ubuntu 3.11/3.12 bash, macos 3.11/3.12 zsh, windows 3.11/3.12 pwsh) plus 3 nice-to-have rows and 1 degraded-tolerant row (windows cmd — runs but does not block release per §12.13). Each CI row uploads its evidence dir as an artifact even on failure.

**Status**: planned. v0.7.2 is shipped; v0.8.0 design is being narrowed around the minimal workflow surface.

**Trigger**: ~1 sprint of real v0.7 use OR clear pain after first install. The kind of work that fixes "어 이거 명령 뭐였지?" / "지금 어디지?" / "왜 막혔지?".

**Audience**: same persona as v0.7 (corp-mandated Roo/OpenCode, weak corp model, large projects) — but smoother onboarding + lower per-day friction.

**Out of scope here**: browser dashboard (→ `v0.9.0_todo/`), MCP server (→ `future_undecided/`).

## Documents

- `2026-05-17-ux-polish.md` — todo list + slice sketch
- `../2026-05-18-ux-design-touch.md` — command/JSON/install/security-boundary findings
- `../2026-05-19-v0.8.0-minimal-workflow-design.md` — active minimal workflow design patch after adversarial review

## What v0.7 already covers (was originally v0.8)

Three items promoted to v0.7 because Model B halt → manual handoff is unusable without them:

- ✅ `harness status` (v0.7 slice S15)
- ✅ `harness next` (v0.7 slice S15)
- ✅ `Fix:` error standard (v0.7 slice S16)
- ✅ `/fsd-status` slash (v0.7 slice S15)

## Original v0.8 candidates

- **E.** One-page cheatsheet (`docs/cheatsheet.md`)
- **F.** `harness onboarding` interactive walkthrough (5-step first-run setup)
- **G.** `harness slash list` (slash command discovery)
- **H.** `.harness/CURRENT` single-line heartbeat sink (for future IDE plugins)
- **I.** `harness phase autopilot start --dry-run` (audit plan before mutating)
- **J.** `harness phase back` (alias for `phase reopen --to plan`)

## Current v0.8 design direction

The active design rejects adding normal-path commands for onboarding, slash discovery, heartbeat, autopilot dry-run, and phase-back/reopen UX. They may remain future or advanced/debug work only if they do not expand the normal workflow.

The v0.8 normal surface is capped at:

- `harness`
- `harness next`
- `harness run`
- `harness check`

See `../2026-05-19-v0.8.0-minimal-workflow-design.md` before implementing any v0.8 slice.

## Open questions for kickoff

- Should `harness status` (already v0.7) gain Markdown-formatted output for `/fsd-status` after dogfood feedback?
- Cheatsheet language: Korean + English? Korean-only?
- Onboarding write-once flag or always re-run?
