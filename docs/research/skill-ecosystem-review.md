# Skill Ecosystem Review

This review records patterns borrowed from public agent-skill ecosystems and how they were adapted into this stack-neutral harness.

## Sources Reviewed

| Source | Relevant Pattern | Local Adaptation |
| --- | --- | --- |
| Anthropic Skills overview, `https://claude.com/docs/skills/overview` | Skills are directories with `SKILL.md`; resources and scripts should load only when needed to protect context. | Keep pack skills small, add explicit output contracts, and reserve bundled references/scripts for deterministic execution instead of copying large guidance into core prompts. |
| Claude Agent Skills docs, `https://docs.claude.com/en/docs/agents-and-tools/agent-skills` | Skills compose domain workflows and can include scripts, templates, references, and examples. | Treat `workflow-*` and `tech-*` packs as composable optional plugins, with manifest entries and install tests for each shipped skill. |
| Anthropic official skills repository, `https://github.com/anthropics/skills/tree/main/skills` | Broad skill categories cover documents, frontend design, MCP building, testing, and artifacts rather than only coding. | Add `ecosystem-skill-research`, `workflow-skill-authoring`, and stronger README examples so future packs can be researched and added without making core stack-specific. |
| Anthropic official plugins repository, `https://github.com/anthropics/claude-plugins-official/tree/main/plugins` | Plugins bundle skills, slash commands, subagents, MCP servers, and setup workflows. | Keep Roo/OpenCode files as adapters and add `multi-agent-review` plus release readiness checks as workflow skills, not client-specific assumptions. |
| Superpowers skills, `https://github.com/obra/superpowers/tree/main/skills` and plugin page `https://claude.com/plugins/superpowers` | Strong workflows include brainstorming, TDD, systematic debugging, code review, verification before completion, and subagent review. | Add optional neutral packs for `workflow-tdd`, `workflow-debugging`, `workflow-code-review`, and core skills for multi-agent review and release audit. |
| Everything Claude Code skills, `https://github.com/affaan-m/everything-claude-code/tree/main/skills` | Curated skill collections emphasize repeated workflow packaging and task-specific triggers. | Add activation evidence, stop conditions, and output contracts so low-reasoning models know when to use or reject a skill. |
| Awesome OpenCode, `https://github.com/awesome-opencode/awesome-opencode` and `https://www.awesome-opencode.com/` | OpenCode ecosystem is command/plugin oriented and should not require Roo-specific files. | Preserve OpenCode as an adapter target and verify OpenCode-only installs in the release smoke matrix. |

## Accepted Patterns

| Pattern | Local Artifact | Low-Reasoning Value |
| --- | --- | --- |
| Progressive disclosure | `workflow-core/ecosystem-skill-research` and small focused `SKILL.md` files | Agents load only relevant workflow instructions. |
| Explicit stop conditions | All new workflow-quality packs | Low-reasoning agents stop instead of guessing. |
| Review before completion | `multi-agent-review`, `release-readiness-audit`, README push prompt | Completion claims require evidence, not intent. |
| Test-first bug/feature workflow | `workflow-tdd` | Visible red/green evidence reduces accidental implementation drift. |
| Reproduce-minimize-debug loop | `workflow-debugging` | Prevents symptom patching. |
| Security as trust-boundary workflow | `workflow-security-review` | Keeps secrets, writes, and external systems explicit. |
| Skill-authoring checklist | `workflow-skill-authoring` | Prevents advice-only skills that are too vague for low-reasoning models. |

## Rejected Patterns

| Pattern | Reason |
| --- | --- |
| Make document, presentation, spreadsheet, or PDF skills default | Useful, but document-production skills are not universal core harness behavior. They should be optional future packs. |
| Make a specific language server, MCP server, or cloud connector default | Violates client-neutral and stack-neutral core. |
| Copy external skill text into this repository | Creates licensing, drift, and context bloat risk. This harness adapts patterns, not full content. |
| Require Roo for OpenCode workflows | Breaks adapter independence. OpenCode-only targets must remain valid. |

## Future Pack Candidates

- `workflow-brainstorming`: alignment and requirement sharpening before planning.
- `workflow-parallel-agents`: decomposition patterns for independent subagent work.
- `workflow-release-git`: commit, PR, changelog, and branch cleanup workflows.
- `workflow-tool-integration`: MCP/plugin/API integration boundary checks.
- `workflow-documents`: optional document/PDF/spreadsheet/presentation production pack.

