# MCP Server — undecided / future

**Captured**: 2026-05-17 during Round-5 design review of v0.7 phase gate hardening.

**Promotion trigger** (any one): corporate environment gains a stronger AI model that reliably honors MCP tool descriptions, OR community demand to consume harness state as MCP tools from a non-Roo/non-OpenCode client.

**Current decision**: do NOT build for v0.7~v0.9. Reasons:
- Weak corporate model = unreliable MCP invocation. Agent often skips MCP tool calls unless forced via skill text, and skill text is itself unreliable for weak agents.
- Browser dashboard (v0.9) covers the dashboard / control-center use case without requiring agent cooperation.
- MCP adds protocol surface (transport, server lifecycle, tool/resource schema, Roo MCP config UX) for value that doesn't materialize at the current model strength.

---

## What MCP would add

Agent-side, not human-side. The browser dashboard already covers humans.

| Capability | Without MCP | With MCP |
|---|---|---|
| Agent reads current phase | skill text "read state.json" (passive) | `harness/status` tool (active, structured) |
| Agent validates transition before mutating | n/a | `harness/validate_transition(slug)` |
| Agent searches audit for prior context | n/a | `harness/audit_search(query)` |
| Agent fetches skill definitions dynamically | not possible (skills are static system-prompt) | resources/listChanged + read |
| Agent reads halt diary from another run | n/a | `harness/last_halt_diary` |
| Agent budgets self-check | n/a | `harness/budgets_remaining` |
| Cross-project skill / pattern reuse | manual copy | resource |

Multiplier on agent capability. Multiplier on a weak agent ≈ 0.5x.

## Sketch (if/when promoted)

### Transport

- **stdio default** (Roo MCP config style). Subprocess; zero network surface. Passes any corp policy that already allows Roo/OpenCode.
- HTTP/SSE only if multi-client or remote — out of scope today.

### Tools (initial)

- `harness/status` → returns the same payload as `harness status --json`
- `harness/next` → returns `harness next --json`
- `harness/audit_search(query, limit)` → grep over audit.log
- `harness/halt_diary` → state.last_halt
- `harness/validate_transition(from, to)` → ADR-001 dry-run; returns ok / reason
- `harness/budgets_remaining` → cli_budgets_remaining snapshot

Read-only first. State-mutation tools (`phase set`, `autopilot start`) deliberately omitted from MCP — those should remain under the human-gate / TTY-only path even when MCP exists. MCP exposes context, not control.

### Resources

- `phase/current` → state.json
- `phase/roadmap` → planning files
- `skills/active` → install-record.json approvers + skill pack list
- `audit/tail` → last N audit entries

### Prompts

- `phase/discuss-template`
- `phase/plan-template`
- `phase/execute-template`
- `phase/done-template`

Mirror the existing skill templates; allow Roo to surface them via the `/` slash command + Prompts list UI.

## Open questions for promotion day

- Does Roo offer a way to force MCP tool calls per-turn (e.g. "must call X first"), beyond skill-text instruction? If yes, weak-model reliability improves and the promotion trigger relaxes.
- OpenCode MCP behavior: not deeply explored. Verify before committing.
- Should MCP server share the `harness serve` daemon process (v0.9) or run as a separate stdio subprocess? Sharing complicates lifecycle; separate is cleaner.
- License / packaging: ship MCP server with the harness, or as a separate optional install (`pip install harness[mcp]`)? Optional install matches the "not core" framing.

## REJECTED conditions (would close this file)

- Roo/OpenCode drop MCP support entirely → MCP server has no client → close.
- A simpler mechanism replaces MCP (e.g. Roo gains a first-class "context provider" API that the harness can plug into directly) → close, write replacement.
