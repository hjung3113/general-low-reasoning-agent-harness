---
roo_mode: review
opencode: true
title: UI review checklist
---

Reviewing UI changes, prioritize:

1. Behavior correctness on the golden path.
2. Responsive behavior at the project's documented breakpoints (or at least
   one narrow viewport if no breakpoint doc exists).
3. Keyboard focus order and visible focus indicator.
4. Empty, loading, error, and disabled states for every new interactive
   element.
5. Tailwind class hygiene: no inline arbitrary-value classes that duplicate an
   existing utility; no class strings that exceed the team's readability bar.
6. TypeScript: no `any` introduced without an explanatory comment.
