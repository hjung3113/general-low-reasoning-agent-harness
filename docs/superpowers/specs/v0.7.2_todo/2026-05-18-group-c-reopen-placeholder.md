# v0.7.2 Group C — `phase reopen --reason` placeholder patch

**Source spec:** `docs/superpowers/specs/v0.7.2_todo/2026-05-18-ux-quick-wins.md` Group C (C1).
**Target file:** `scripts/lib/status_next.py`
**Goal:** Replace fleet-wide identical reopen reason literal `"fix and re-approve"` with a placeholder `<describe what you fixed>` so agents must substitute concrete text → audit-trail no longer polluted by uniform meaningless reasons.

## Exact edits

| Site | Line | Before (exact) | After (exact) |
|---|---|---|---|
| `scripts/lib/status_next.py` (function returning suggested command — `next_command` branch) | 178 | `        return 'harness phase reopen --to plan --reason "fix and re-approve"'` | `        return f'harness phase reopen --to plan --reason "{_REOPEN_REASON_PLACEHOLDER}"'` |
| `scripts/lib/status_next.py` (`NextResult` for stale execute approval) | 319 | `                command='harness phase reopen --to plan --reason "fix and re-approve"',` | `                command=f'harness phase reopen --to plan --reason "{_REOPEN_REASON_PLACEHOLDER}"',` |

Both sites currently emit the exact same string. They are simple (non-f) string literals — switching to f-strings is the minimal mechanical change.

## Constant extraction (DRY)

Add a module-level constant near the top of `scripts/lib/status_next.py` (after imports, before first function):

```python
# Placeholder reason for reopen suggestion — agents MUST replace before running.
# Keeping it as a sentinel forces a substitution step rather than letting the
# fleet stamp identical meaningless reasons into the audit trail.
_REOPEN_REASON_PLACEHOLDER = "<describe what you fixed>"
```

Single source of truth; both call sites interpolate it. Module-private (underscore prefix) — not part of public API.

## Test impact

Repo-wide grep for `"fix and re-approve"` outside `scripts/lib/status_next.py` and the two spec docs: **zero hits**. No test currently asserts the exact reason string, so no test updates needed. If any future test pins the suggested command, it should match against `_REOPEN_REASON_PLACEHOLDER` rather than re-hardcoding the literal.

## Verification grep

After patch:

```bash
grep -rn '"fix and re-approve"' scripts/ tests/      # expect 0
grep -n '_REOPEN_REASON_PLACEHOLDER' scripts/lib/status_next.py  # expect 3 (def + 2 uses)
```

Spec docs (`docs/superpowers/specs/2026-05-18-ux-improvements-discovery.md:142` and `v0.7.2_todo/2026-05-18-ux-quick-wins.md:65,69`) still mention the old literal as historical reference — leave untouched.

## Placeholder wording rationale

`<describe what you fixed>` chosen over alternatives:

- `<reason>` — too terse; doesn't signal *what kind* of reason.
- `TODO: reason` — looks like accidentally-shipped code, not an instruction.
- `<why are you reopening>` — phase-agnostic but doesn't hint at the typical execute→plan reopen cause (a fix mid-execute).
- `<describe what you fixed>` — angle-bracket sentinel convention is universally recognized as "substitute me"; verb "fixed" matches the execute-phase reopen semantics (post-failure remediation) where this command surfaces.

The angle brackets also make the command **fail loudly** if pasted verbatim into a shell (unquoted `<` is a redirect), giving a second guardrail against blind copy-paste.
