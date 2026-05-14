# PROJECT - General Low-Reasoning Agent Harness

## One-Liner

Client-neutral workflow harness that keeps low-reasoning agents inside a concrete, resumable `discuss -> plan -> execute -> done` protocol.

## Scope

- Core planning protocol.
- Phase gate schema and validation.
- Roo and OpenCode adapters.
- Generic profiles.
- Composable workflow skill packs.
- Target init, check, and upgrade tooling.

## Decisions

### DEC-0001 - `.planning/**` is canonical memory

Accepted. The live gate points to durable planning docs but does not replace them.

### DEC-0002 - `.scratch/phase-state.json` is only the live gate

Accepted. It approves or blocks current work and must carry approval evidence for execute.

### DEC-0003 - Skills are composable plugins

Accepted. Skill packs provide reusable workflow concerns that can be combined per request. They are not fixed technology presets.

### DEC-0004 - Adapters do not own project truth

Accepted. Roo, OpenCode, and future adapters translate the shared protocol into client commands.

