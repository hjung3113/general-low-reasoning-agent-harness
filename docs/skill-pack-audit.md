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

---

## Phase 2 — Classification Report

Classification key:
- **keep-default**: selected by at least one profile or DB config
- **keep-manual**: manual-only but has explicit evidence (test coverage, docs, meaningful SKILL.md content)
- **delete-candidate**: manual-only, no profile/DB selection, low evidence
- **explicit-decision**: manual-only, useful content, codex flagged as requiring user confirmation before deleting

### Classification Table

| Pack | Class | Rationale |
|------|-------|-----------|
| `workflow-core` | **keep-default** | Generic default for all 4 profiles. 9 subskills, 21 test refs. Load-bearing. |
| `workflow-etl` | **keep-default** | Selected by dotnet-etl, python-etl profiles. 8 test refs. ETL backbone. |
| `workflow-web-development` | **keep-default** | Selected by react-web profile. 3 test refs. |
| `workflow-db-context` | **keep-default** | Selected by mssql+postgresql DB configs. 12 test refs. |
| `tech-csharp` | **keep-default** | Selected by dotnet-etl profile. 7 test refs. |
| `tech-python` | **keep-default** | Selected by python-etl profile. 6 test refs. |
| `tech-react` | **keep-default** | Selected by react-web profile. 3 test refs. |
| `tech-typescript` | **keep-default** | Selected by react-web profile. 3 test refs. |
| `tech-tailwind` | **keep-default** | Selected by react-web profile. 3 test refs. |
| `tech-mssql` | **keep-default** | Selected by mssql DB config. 15 test refs. |
| `tech-postgresql` | **keep-default** | Selected by postgresql DB config. 5 test refs. |
| `workflow-skill-authoring` | **delete-candidate** | Manual-only. No profile/DB selection. 3 test refs (all in quality/install test). SKILL.md covers skill-authoring meta-workflow with no real operator target story. Lowest-risk delete: this harness is not a skill-authoring tool; it's a deployment harness. Group A. |
| `workflow-security-review` | **delete-candidate** | Manual-only. No profile/DB selection. 8 test refs (majority in quality/install tests and parse_pack_selection helper). SKILL.md is well-structured but no evidence of any operator selecting this pack. Group A. |
| `workflow-data-analysis` | **delete-candidate** | Manual-only. 1 test ref (in bulk all-pack install test). No activation evidence, no target story. Data analysis is not a use case this harness was built for. Group C. |
| `workflow-data-processing` | **delete-candidate** | Manual-only. 1 test ref (in bulk all-pack install test). No activation evidence, no target story. Same rationale as workflow-data-analysis. Group C. |
| `workflow-code-review` | **explicit-decision** | Manual-only. 4 test refs. Broadly useful; codex flagged for user decision. SKILL.md quality is high (review lenses, findings-first contract). No operator evidence but could be a real operator selection. Group B. **Awaiting user decision.** |
| `workflow-tdd` | **explicit-decision** | Manual-only. 14 test refs — highest among manual-only packs. Codex flagged as risky to delete. SKILL.md is concrete and well-structured. High test visibility suggests real usage. Group D. **Awaiting user decision.** |
| `workflow-debugging` | **explicit-decision** | Manual-only. 3 test refs. Codex flagged for user decision. SKILL.md is concrete (reproduce → minimize → instrument). Broadly useful across all project types. Group D. **Awaiting user decision.** |

### Summary by Action Group

| Group | Packs | Proposed action | Requires user confirm? |
|-------|-------|-----------------|----------------------|
| A | `workflow-skill-authoring`, `workflow-security-review` | Delete | No (delete-candidate) |
| B | `workflow-code-review` | Delete or keep | **YES** |
| C | `workflow-data-analysis`, `workflow-data-processing` | Delete | No (delete-candidate) |
| D | `workflow-tdd`, `workflow-debugging` | Delete or keep | **YES** |

### Notes on test-ref counts

The test counts above include occurrences in `test_quality_workflow_packs_install_low_reasoning_contracts`
and `test_requested_tech_and_workflow_packs_install_as_composable_skills` — these are install/quality
assertion tests that exist specifically to prove the pack works, not evidence of operator usage.
If a pack is culled, these test entries are removed as part of the same commit.
For `workflow-tdd`, 14 refs is notable but 11+ are in those same install tests plus two integration
tests that use it as a convenient manual-pack stand-in. No production operator story was found.

