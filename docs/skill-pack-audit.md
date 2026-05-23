# Skill-Pack Audit Report — Milestone 7

Generated from: `harness/manifest.json`  
Total packs found: **18** (manifest) / **18** (dirs)
Total manifest files: **183**

## Per-Pack Evidence Table

| Pack | Profile-selected | DB-selected | Manifest files | Test refs | Dir? | SKILL.md count | usage_status | target_story |
|------|-----------------|-------------|---------------|-----------|------|----------------|--------------|--------------|
| `tech-csharp` | dotnet-etl | - | 1 | 7 | yes | 1 | - | - |
| `tech-mssql` | - | mssql | 1 | 15 | yes | 1 | - | - |
| `tech-postgresql` | - | postgresql | 1 | 5 | yes | 1 | - | - |
| `tech-python` | python-etl | - | 1 | 6 | yes | 1 | - | - |
| `tech-react` | react-web | - | 1 | 3 | yes | 1 | - | - |
| `tech-tailwind` | react-web | - | 1 | 3 | yes | 1 | - | - |
| `tech-typescript` | react-web | - | 1 | 3 | yes | 1 | - | - |
| `workflow-code-review` | - | - | 1 | 4 | yes | 1 | - | - |
| `workflow-core` | dotnet-etl, generic, python-etl, react-web | - | 9 | 21 | yes | 9 | - | - |
| `workflow-data-analysis` | - | - | 1 | 1 | yes | 1 | - | - |
| `workflow-data-processing` | - | - | 1 | 1 | yes | 1 | - | - |
| `workflow-db-context` | - | mssql, postgresql | 1 | 12 | yes | 1 | - | - |
| `workflow-debugging` | - | - | 1 | 3 | yes | 1 | - | - |
| `workflow-etl` | dotnet-etl, python-etl | - | 1 | 8 | yes | 1 | - | - |
| `workflow-security-review` | - | - | 1 | 8 | yes | 1 | - | - |
| `workflow-skill-authoring` | - | - | 1 | 3 | yes | 1 | - | - |
| `workflow-tdd` | - | - | 1 | 14 | yes | 1 | - | - |
| `workflow-web-development` | react-web | - | 1 | 3 | yes | 1 | - | - |

## Manual-Only Packs (no profile/DB selection)

These packs require explicit justification (usage_status, target_story, or activation_evidence) or are delete candidates.

- `workflow-code-review`: NO metadata — test_refs=4, SKILL.md=1
- `workflow-data-analysis`: NO metadata — test_refs=1, SKILL.md=1
- `workflow-data-processing`: NO metadata — test_refs=1, SKILL.md=1
- `workflow-debugging`: NO metadata — test_refs=3, SKILL.md=1
- `workflow-security-review`: NO metadata — test_refs=8, SKILL.md=1
- `workflow-skill-authoring`: NO metadata — test_refs=3, SKILL.md=1
- `workflow-tdd`: NO metadata — test_refs=14, SKILL.md=1

## Gate Checks

**PASS** — all gate checks pass.

**WARNING** — manual-only packs without any explicit metadata (candidates for cull or justification):

- `workflow-code-review`
- `workflow-data-analysis`
- `workflow-data-processing`
- `workflow-debugging`
- `workflow-security-review`
- `workflow-skill-authoring`
- `workflow-tdd`

