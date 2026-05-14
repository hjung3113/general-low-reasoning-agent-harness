# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`.planning/STATE.md`**, **`.planning/ROADMAP.md`**, and the active phase checkpoint under **`.planning/phases/`**.
- **`.planning/codebase/`** notes for architecture, stack, structure, conventions, testing, integrations, and concerns when they exist.
- **`CONTEXT.md`** at the repo root, or
- **`CONTEXT-MAP.md`** at the repo root if it exists; it points at one `CONTEXT.md` per context. Read each one relevant to the topic.
- **`docs/adr/`**; read ADRs that touch the area you're about to work in. In multi-context repos, also check `src/<context>/docs/adr/` for context-scoped decisions.

If root `CONTEXT.md`, `CONTEXT-MAP.md`, or `docs/adr/` don't exist, proceed silently only after checking `.planning/` first. Don't flag missing root domain docs by default; the producer skill (`/grill-with-docs`) creates them lazily when terms or decisions actually get resolved.

## Repo-specific planning memory

This repository intentionally uses `.planning/` as the durable project context even when root `CONTEXT.md` or ADRs are absent. Before treating missing domain docs as missing context, read:

- `.planning/PROJECT.md`
- `.planning/DECISIONS.md`
- `.planning/STATE.md`
- `.planning/ROADMAP.md`
- `.planning/codebase/ARCHITECTURE.md`
- `.planning/codebase/STACK.md`
- `.planning/codebase/STRUCTURE.md`
- `.planning/codebase/CONVENTIONS.md`
- `.planning/codebase/TESTING.md`
- `.planning/codebase/INTEGRATIONS.md`
- `.planning/codebase/CONCERNS.md`
- the active phase context, plan, checkpoint, review, verification, and summary files under `.planning/phases/`

For existing-repository harness adoption, placeholder-only `.planning/codebase/**` or `.planning/phases/**` files are not valid context. Hydrate or reconcile them from the real repository before relying on ADR output, issue plans, or phase-state approval.

## File structure

Single-context repo (most repos):

```text
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-event-sourced-orders.md
│   └── 0002-postgres-for-write-model.md
└── src/
```

Multi-context repo (presence of `CONTEXT-MAP.md` at the root):

```text
/
├── CONTEXT-MAP.md
├── docs/adr/                          <- system-wide decisions
└── src/
    ├── ordering/
    │   ├── CONTEXT.md
    │   └── docs/adr/                  <- context-specific decisions
    └── billing/
        ├── CONTEXT.md
        └── docs/adr/
```

## Use the glossary's vocabulary

When your output names a domain concept in an issue title, a refactor proposal, a hypothesis, or a test name, use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use, or there's a real gap to note for `/grill-with-docs`.

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding.
