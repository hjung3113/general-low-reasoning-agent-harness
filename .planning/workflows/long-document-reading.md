# Long Document Reading Workflow

Use this workflow to avoid repeated broad scans of planning documents and to give subagents bounded context.

## Entry Order

1. First run `python3 scripts/show_phase_status.py`.
2. If it is missing, fails, emits malformed output, or reports an unsupported contract version, read `.scratch/phase-state.json` and follow the legacy durable planning read order.
3. If `.planning/plan-index.md` exists, use it as a routing aid before opening long planning documents.
4. Prefer targeted headings, anchors, or small ranges over full-document reads.

## Authority

`.planning/**` remains canonical memory. `.planning/plan-index.md` and `.planning/slices/**`, when present, are routing aids and summaries only. If they conflict with canonical planning docs, the canonical docs win unless a later explicit decision promotes the slice or index.

The workflow document does not grant permission to create or edit planning files. Create or edit slices only when the user explicitly requests that documentation change and the phase gate permits docs/workflow edits.

## Read Budget

A full read means reading most or all of a document, or reading enough chunks that the agent is effectively scanning the whole file.

A targeted read means reading one named heading, anchor, or small range for a specific question.

An attempt is one full read, broad search, or broad delegation pass aimed at answering the same planning question.

After 2 full reads of the same planning document for one task, stop broad reading before starting a third full read. Return one of:

- the exact missing section or heading needed
- a proposed `.planning/slices/<topic>.md` outline for user approval
- a narrower read/search plan with specific files and headings

After 3 unsuccessful broad attempts to answer the same planning question, change strategy. Summarize known facts, list the blocker, and ask for approval to create or request a focused slice. Do not continue full-document scans.

## Subagent Delegation

Do not assign subagents broad prompts such as "review planning docs" or "find relevant context."

Assign one file plus one heading/range/question whenever possible. Example:

```text
Read `.planning/ROADMAP.md`, heading `Phase 2`, and return only release-gate dependencies.
```

If the assigned scope is insufficient, the subagent should return the missing heading, file, or question it needs instead of scanning broadly.

## Planning Slices

Create `.planning/slices/` only when explicitly requested and only for repeated, narrow, stable context.

Each slice must include:

- source files and headings
- scope
- relevant decisions
- out-of-scope items
- verification expectations

Slices must not replace canonical planning docs unless an explicit later decision promotes them.
