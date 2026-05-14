---
name: tech-typescript
description: Use when TypeScript is confirmed. Keeps type safety and build checks explicit.
---

# Tech TypeScript

Use only after TypeScript is confirmed.

## Evidence

Look for `tsconfig.json`, `.ts` or `.tsx` files, TypeScript dependencies, build scripts, or user confirmation.

## Rules

- Do not assume npm, pnpm, yarn, bun, Vite, Next.js, or tsc command names.
- Prefer typed interfaces at module boundaries.
- Avoid `any` and broad type assertions unless an approved plan explains why.
- Run the repository's typecheck/build command before done.

## Verification

Use existing commands such as `npm run typecheck`, `pnpm typecheck`, `tsc --noEmit`, or project build scripts.

