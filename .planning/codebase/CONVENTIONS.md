# CONVENTIONS - General Harness

- Keep core instructions stack-neutral.
- Put client-specific behavior in adapter files.
- Put reusable workflow concerns in skill packs.
- Put target-project facts in project-owned `.planning/**` after init.
- Use focused tests for installer/checker behavior.
- Do not let generated `.scratch/reports/**` become canonical planning state.

