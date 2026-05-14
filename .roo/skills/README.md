# Roo Workflow Skills

Workflow skills are the main entry point once a command or mode has been chosen.

| Skill | Command | Mode | Sequence |
| --- | --- | --- | --- |
| `workflow-simple-task` | `/simple` | owning mode | classify type -> answer/edit/run minimally -> targeted verification -> report |
| `workflow-feature-tdd` | `/feature` | `tdd-code` | scope -> tests -> implementation -> review |
| `workflow-bug-diagnosis` | `/bugfix` | `diagnose` | reproduce -> minimize -> root cause -> regression test -> fix |
| `workflow-etl-pipeline` | `/etl` | `etl-pipeline` | contract -> stages -> ordering/state -> tests -> implement -> review |
| `workflow-db-change` | `/db` | `db-migration` | intent -> design -> test first -> implement safely -> review |
| `workflow-ops-observability` | `/ops` | `ops-observability` | phase gate -> classify -> observable contract -> red -> green -> refactor/verify |
| `workflow-architecture-decision` | `/adr` | `architect` | context -> options -> decision -> ADR -> implementation issues |
| `workflow-code-review` | `/review` | `review` | scope -> correctness -> SQL/persistence -> tests -> operations -> findings |
| `workflow-docs-to-issues` | `/issues` | `docs-issues` | source docs -> PRD -> vertical slices -> metadata |
| `workflow-phase-gate` | manual | any gated workflow | discuss -> plan -> execute -> done |

Use these skills instead of ad hoc orchestration when a request fits a known workflow.
