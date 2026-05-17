# v0.9.0 — Browser Dashboard (dynamic + interactive)

**Status**: planned. Starts after v0.8 lands.

**Goal**: turn the existing static `scripts/project_dashboard.py` HTML generator into a live, button-driven control center. Eliminate most CLI-typing for the user.

**Audience**: same persona as v0.7/v0.8. The friction-killer that finally makes harness feel "쓸만함" for users who hate switching to a terminal repeatedly.

## Documents

- `2026-05-17-browser-dashboard-design.md` — architecture sketch + scope

## Core idea (one paragraph)

A local daemon (`harness serve`) reads state under lock, watches `.scratch/phase-state.json` + audit, and pushes updates over WebSocket to a browser UI at `localhost:7777`. Buttons on the browser POST to the daemon → daemon shells out to `harness <verb>` → returns result. Read verbs (`status`, `next`, `verify --audit`) and state-mutation verbs (`phase set`, `phase autopilot start|stop`) wired directly. Human-gate verbs (`phase approve`, `phase reopen`) gated by Touch ID / OS credential prompt before daemon allocates a PTY and runs the CLI. The agent does NOT talk to the daemon — Roo/OpenCode keep using skill files + state.json reads as today. Browser is human-facing only.

## What v0.9 produces

- `harness serve [--port 7777]` new verb.
- `scripts/lib/browser/` module: FastAPI app, WebSocket state push, button → CLI executor.
- React (or vanilla) UI replacing the static HTML template — phase visualization, halt diary, audit search, skill toggle GUI, "next action" button.
- Touch ID / Windows Hello / pinentry adapter for browser-side human gate.
- Optional: embedded terminal (xterm.js) for users who prefer typing.

## Explicit non-goals

- **No MCP server.** Agent stays passive (skill-driven). MCP tracked in `future_undecided/`.
- **No agent prompt injection.** Browser cannot push messages into a running Roo/OpenCode turn. User still types in IDE for new prompts.
- **No remote / multi-user.** Localhost only. Single-user/single-machine project model preserved.

## Why v0.9 not v0.8

v0.8 is CLI/UX polish (cheatsheet, onboarding, error messages) — small, safe, ships fast.

v0.9 introduces a daemon, browser process, WebSocket, button → subprocess plumbing, Touch ID integration. Larger surface, separate sprint. Should not block v0.8 ship.
