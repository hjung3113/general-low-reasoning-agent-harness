---
name: workflow-skill-authoring
description: Use when creating, editing, or validating project-local skills, workflow packs, tech packs, or skill documentation.
---

# Workflow Skill Authoring

Use this skill to make skills concrete enough for low-reasoning models.

## Low-Reasoning Contract

A useful skill must say when to use it, when to stop, what to produce, and how to verify. Avoid advice-only skills.

## Minimum Skill Shape

- YAML frontmatter with specific activation description
- purpose in one paragraph
- activation evidence
- stop conditions
- step-by-step workflow
- output contract or ledger
- one worked example
- references or scripts only when they reduce context or make execution deterministic

## Workflow

1. Classify the skill as `workflow`, `tech`, `profile`, or `adapter`.
2. Define what evidence activates it.
3. Define what must block execution.
4. Add an output contract a later agent can audit.
5. Add a small worked example.
6. Add the skill to the manifest and install tests.
7. Run source and target checks.

## Output Contract

```yaml
skill_name: ""
category: ""
activation_evidence: []
stop_conditions: []
output_contract: ""
manifest_entry: ""
tests: []
```

