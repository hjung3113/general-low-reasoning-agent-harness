---
name: tech-react
description: Use when React is confirmed. Guides component, state, accessibility, and interaction work without assuming a framework.
---

# Tech React

Use only after React is confirmed.

## Evidence

Look for React dependencies, JSX/TSX files, component folders, router setup, test setup, or user confirmation.

## Rules

- Do not assume Next.js, Vite, Remix, CRA, React Router, Jest, Vitest, or Testing Library.
- Match existing component structure and state patterns.
- Preserve accessibility semantics for controls, forms, dialogs, and navigation.
- Verify user-facing behavior with the repository's test or browser workflow.

## Verification

Use existing project commands only, such as `npm test`, `npm run test`, `pnpm test`, `npm run build`, or an approved browser smoke check.

