---
name: ecosystem-skill-research
description: Use when researching external agent skills, plugins, command packs, marketplaces, or workflow catalogs before changing local skill packs.
---

# Ecosystem Skill Research

Use this skill before importing ideas from external skill ecosystems.

## Low-Reasoning Contract

Do not copy external skills wholesale. Extract reusable workflow patterns, then translate them into stack-neutral, client-neutral local skills.

Every adopted idea needs:

- source URL or repository path
- observed pattern
- local adaptation
- reason it helps low-reasoning agents
- reason it does not make core stack-specific

## Research Targets

Prefer reputable sources first:

- official Anthropic skills and plugins
- established workflow frameworks such as Superpowers
- curated Claude Code or OpenCode catalogs
- project-local skills already used successfully

## Workflow

1. List the user goal as workflow categories, not implementation wishes.
2. Search external sources for matching skill categories.
3. Record patterns, not full content.
4. Reject patterns that require a specific client, SaaS account, language, or stack unless they belong in an optional pack.
5. Convert accepted patterns into one of:
   - workflow-core skill
   - optional workflow pack
   - optional tech pack
   - README example
   - release/check script
6. Record unresolved ideas as future pack candidates, not hidden assumptions.

## Output Ledger

```yaml
sources:
  - source: ""
    patterns:
      - ""
accepted_patterns:
  - pattern: ""
    local_artifact: ""
    low_reasoning_value: ""
rejected_patterns:
  - pattern: ""
    reason: ""
future_candidates:
  - pack_or_skill: ""
    trigger: ""
```

