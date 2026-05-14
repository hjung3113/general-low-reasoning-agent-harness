---
name: skill-plugin-composition
description: Use when choosing which workflow skill plugins should be active for a project, phase, or implementation slice.
---

# Skill Plugin Composition

Use this skill after repository evidence has been gathered.

## Low-Reasoning Contract

Choose plugins by evidence, not by preference. A low-reasoning model must be able to explain every active skill with one confirmed input and one expected output.

If a skill is "nice to have" but has no phase duty, reject it for this phase.

## Rules

- Skills are composable plugins, not fixed tech-stack presets.
- Do not activate a skill because a filename merely resembles a stack.
- Activate the smallest set of skills that covers the current phase.
- Record why each skill is active, which evidence supports it, and which skills were rejected.
- A project can combine skills across concerns, for example data workflow plus API integration plus verification contract.
- Prefer workflow skills for task shape and tech skills for confirmed implementation facts.
- Keep `workflow-core` active unless the user explicitly requests a bare skeleton.

## Selection Steps

1. Start with `repository-evidence-research`.
2. Add workflow skills for the user-visible work type.
3. Add tech skills only for confirmed stack evidence or explicit user instruction.
4. Add `verification-contract` before execute work.
5. Add `risk-review` before phase commitments, broad refactors, release, or push.
6. Add `multi-agent-review` when the work needs independent adversarial review.
7. Record rejected skills so later agents do not re-add them by guesswork.

## Composition Record

Record:

- `active_skills`
- `reason`
- `evidence_paths`
- `phase_scope`
- `rejected_skills`
- `blocked_until`

## Example

```yaml
active_skills:
  - repository-evidence-research
  - integration-boundary
  - verification-contract
  - risk-review
reason: "API-backed feature phase with unknown implementation stack."
evidence_paths:
  - "README.md"
  - "src/**"
rejected_skills:
  - skill: tech-specific-pack
    reason: "No confirmed stack evidence yet."
blocked_until: null
```

Unknown project shape means use only generic workflow skills.
