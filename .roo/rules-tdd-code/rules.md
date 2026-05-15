# TDD Code Rules

- Apply `.roo/rules-orchestrator/rules.md` before these mode rules.
- Start with red evidence before production edits: a new failing test, a clearly identified existing failing test, or a captured failing reproduction converted into a regression test.
- Do not edit production code until the red test has been run and its failure is recorded.
- Use the repository's existing test framework, assertion style, and package manager.
- Do not assume a language, framework, database, or test tool unless confirmed by repository evidence or active packs.
- Keep production changes as small as possible until the test passes.
- After the implementation, run the focused test and record green evidence.
- Refactor only after green evidence exists, then rerun the focused tests.
- There is no "tests later" exception for behavior changes.
- Do not mix unrelated refactors into feature work.
