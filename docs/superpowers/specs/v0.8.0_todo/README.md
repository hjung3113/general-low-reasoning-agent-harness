# v0.8.0 — UX Polish

**Status**: planned. Starts after v0.7 dogfood produces concrete friction data.

**Trigger**: ~1 sprint of real v0.7 use OR clear pain after first install. The kind of work that fixes "어 이거 명령 뭐였지?" / "지금 어디지?" / "왜 막혔지?".

**Audience**: same persona as v0.7 (corp-mandated Roo/OpenCode, weak corp model, large projects) — but smoother onboarding + lower per-day friction.

**Out of scope here**: browser dashboard (→ `v0.9.0_todo/`), MCP server (→ `future_undecided/`).

## Documents

- `2026-05-17-ux-polish.md` — todo list + slice sketch

## What v0.7 already covers (was originally v0.8)

Three items promoted to v0.7 because Model B halt → manual handoff is unusable without them:

- ✅ `harness status` (v0.7 slice S15)
- ✅ `harness next` (v0.7 slice S15)
- ✅ `Fix:` error standard (v0.7 slice S16)
- ✅ `/fsd-status` slash (v0.7 slice S15)

## What remains in v0.8 scope

- **E.** One-page cheatsheet (`docs/cheatsheet.md`)
- **F.** `harness onboarding` interactive walkthrough (5-step first-run setup)
- **G.** `harness slash list` (slash command discovery)
- **H.** `.harness/CURRENT` single-line heartbeat sink (for future IDE plugins)
- **I.** `harness phase autopilot start --dry-run` (audit plan before mutating)
- **J.** `harness phase back` (alias for `phase reopen --to plan`)

## Open questions for kickoff

- Should `harness status` (already v0.7) gain Markdown-formatted output for `/fsd-status` after dogfood feedback?
- Cheatsheet language: Korean + English? Korean-only?
- Onboarding write-once flag or always re-run?
