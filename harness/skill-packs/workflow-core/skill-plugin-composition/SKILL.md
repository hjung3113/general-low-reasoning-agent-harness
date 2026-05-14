---
name: skill-plugin-composition
description: Use when choosing which workflow skill plugins should be active for a project, phase, or implementation slice.
---

# Skill Plugin Composition

Use this skill after repository evidence has been gathered.

## Rules

- Skills are composable plugins, not fixed tech-stack presets.
- Do not activate a skill because a filename merely resembles a stack.
- Activate the smallest set of skills that covers the current phase.
- Record why each skill is active, which evidence supports it, and which skills were rejected.
- A project can combine skills across concerns, for example data workflow plus API integration plus verification contract.

## Composition Record

Record:

- `active_skills`
- `reason`
- `evidence_paths`
- `phase_scope`
- `rejected_skills`
- `blocked_until`

Unknown project shape means use only generic workflow skills.

