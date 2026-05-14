---
name: tech-tailwind
description: Use when Tailwind CSS is confirmed. Keeps utility styling consistent with the target design system.
---

# Tech Tailwind

Use only after Tailwind CSS is confirmed.

## Evidence

Look for Tailwind config files, Tailwind imports, utility classes, PostCSS config, framework integration, or user confirmation.

## Rules

- Do not assume Tailwind version, plugin set, design tokens, or component library.
- Prefer existing tokens, spacing, color, and responsive patterns.
- Keep class composition readable and local conventions intact.
- Verify layout at relevant breakpoints when UI changes.

## Verification

Use existing lint, build, visual, or browser smoke checks.

