# v0.9.0 — Browser Dashboard Design

**Captured**: 2026-05-17. Not yet a phase spec; high-level sketch + scope.

**Origin**: late v0.7 review pass. The static `scripts/project_dashboard.py` HTML generator already exists and renders most of what a user needs. v0.9 makes it live + clickable so the user rarely types into a terminal.

**Prerequisite**: v0.7 (phase gate hardening) shipped + dogfooded. v0.8 (UX polish) shipped.

---

## 1. Architecture

```
┌─────────────────────────────────────┐
│ Browser   http://localhost:7777     │
│   - phase visualization              │
│   - halt diary panel                 │
│   - "next action" button             │
│   - audit log search                 │
│   - skill / profile toggle GUI       │
│   - approve via Touch ID / nonce     │
└───────────────┬─────────────────────┘
                │ HTTP + WebSocket (localhost only)
┌───────────────▼─────────────────────┐
│ harness serve   (FastAPI daemon)    │
│   - reads .scratch/phase-state.json │
│   - watches audit.log (inotify/      │
│     ReadDirectoryChanges)            │
│   - pushes WS notifications          │
│   - POST /api/run/<verb> → subprocess│
│   - Touch ID / WebAuthn gate before  │
│     allocating PTY for approve       │
└───────────────┬─────────────────────┘
                │ subprocess.run(["harness", ...])
┌───────────────▼─────────────────────┐
│ harness CLI (existing v0.7 surface) │
└─────────────────────────────────────┘

[Roo / OpenCode in IDE]
  - independent of daemon
  - reads state.json + skill files (no MCP)
  - agent stays passive, skill-driven
```

The browser drives the daemon. The daemon drives the existing v0.7 CLI. Roo/OpenCode keep working as today; they do NOT talk to the daemon.

## 2. Verbs the browser maps to

### Read-only (executed silently on view load + on every WS push)

- `harness status --json`
- `harness next --json`
- `harness verify --audit --json`
- `harness phase next-pending`

### State mutation (button click → subprocess.run)

- `harness phase set <slug>`
- `harness phase autopilot start --phase <slug> --mode {phase|chain}`
- `harness phase autopilot stop --reason <text>`
- `harness halt-diary clear`
- `harness repair --strip-bom <path>`

### Human-gate (button click → Touch ID / OS prompt → daemon allocates PTY → subprocess.run)

- `harness phase approve`
- `harness phase reopen --to <plan|discuss> --reason <text>`

### Install / config (GUI form → subprocess)

- `harness install` → form replaces the four interactive prompts
- `harness approver add|remove|list` (already v0.7 verb if multi-user ever lands)

## 3. UI panels (rough)

| Panel | Source | Behavior |
|---|---|---|
| Current phase card | state.json | live; click → expand details |
| Halt diary | state.last_halt | shown when non-null; "next action" button copies suggested command and/or executes it |
| Roadmap timeline | .planning/* + state | green/grey per phase |
| Audit log search | audit.log | text query, hash-chain integrity badge |
| Skill / profile panel | install-record.json + manifest | toggles → daemon rewrites and audits |
| Approve panel | state.execution_mode | shown only when approve is the next action; Touch ID button |
| Live agent transcript link | n/a | hint "switch to your IDE to type prompts"; browser cannot inject |

## 4. Human gate — three implementations to evaluate

1. **WebAuthn / platform authenticator** (Touch ID on macOS, Windows Hello, FIDO key).
   - Browser-native API; daemon registers a credential on first run.
   - UX: tap fingerprint → daemon receives signed assertion → allocates PTY → runs `harness phase approve`.
   - Agent cannot simulate the assertion. **Strongest UX + strongest defense.**

2. **OS credential prompt** (fallback when WebAuthn unavailable).
   - macOS `security`/`osascript` dialog, Linux `pinentry`, Windows `CredUIPromptForWindowsCredentials`.
   - User types pre-registered passphrase.
   - Daemon receives ok → allocates PTY.

3. **Nonce paste** (universal fallback).
   - Browser shows "open terminal, run `harness approve-nonce mint`, paste code below".
   - Same as v0.7 §3.1.1 mechanic but UI is browser-side.
   - Always available.

Default: try (1) → fall back to (2) → fall back to (3).

## 5. Implementation modules (rough)

| Module | Purpose |
|---|---|
| `scripts/lib/serve/app.py` | FastAPI app, routes, WS endpoint |
| `scripts/lib/serve/state_watch.py` | file watch over .scratch/ + audit |
| `scripts/lib/serve/executor.py` | subprocess wrapper, PTY allocation for human-gate verbs |
| `scripts/lib/serve/auth.py` | WebAuthn / OS credential / nonce gate |
| `scripts/lib/serve/audit_search.py` | audit.log query |
| `scripts/lib/browser_ui/` | React/Vite app (or vanilla HTML/JS to keep deps low) |
| `harness serve` CLI verb | argparse entry; `--port`, `--no-browser`, `--bind 127.0.0.1` |

## 6. Security boundaries

- Bind to `127.0.0.1` only. Refuse `0.0.0.0` even with flag (single-user model).
- Daemon refuses requests without a session cookie set at startup (cookie stored only in browser localStorage; not on disk).
- Agent CANNOT acquire the session cookie (it lives in browser memory; agent's Bash tool cannot read browser process memory).
- However, agent COULD start a fresh browser session and request a new cookie if the daemon is running unauthenticated on first connect. So: daemon requires explicit user action (Touch ID or "click here to authorize" gesture) before issuing the cookie at first connect.
- All human-gate verbs re-require Touch ID per invocation (no "remember me").
- Daemon refuses to run when `state.execution_mode != manual` AND the verb requested would mutate state, unless the verb is `phase autopilot stop` or `halt-diary clear`. (Mirrors the CLI's existing gates; daemon is a thin shim.)

## 7. CI / smoke

- `pytest tests/serve/` — daemon route tests with mocked subprocess.
- `python scripts/smoke/browser_dashboard_e2e.py` — Playwright-based e2e: spawn daemon, drive browser, click through a full phase lifecycle, assert state + audit at each step.
- Release matrix: same OS/Python rows as v0.7 §7.1.

## 8. Migration from static dashboard

`scripts/project_dashboard.py` stays as a fallback (no-daemon, file-output mode) for users who don't want to run a daemon. The HTML template + `renderer.py` is refactored into shared components consumed by both the static generator and the dynamic UI.

## 9. Out of scope for v0.9 (tracked elsewhere)

- MCP server (→ `future_undecided/`)
- Multi-user / shared dashboard (→ multi-user phase, not currently scheduled)
- Remote access / tunneled dashboard
- IDE plugin (VS Code extension) — possible v1.x

## 10. Open questions

- Choose React/Vite vs vanilla JS — vanilla wins on simplicity; React wins on iteration speed. Decide at v0.9 kickoff.
- WebAuthn cross-browser compatibility on Windows + corporate environments (some IT policies disable platform authenticators).
- Embedded terminal (xterm.js) yes/no — adds ~200 KB JS, but means user never opens external terminal. Tentative yes.
- How does the daemon process die / restart? `systemd --user` on Linux, `launchd` on macOS, Windows Task Scheduler — or just `harness serve` foreground? Tentative: foreground for v0.9, daemon-supervisor later.
