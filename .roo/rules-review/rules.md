# Review Rules

- Apply `.roo/rules-orchestrator/rules.md` before these mode rules.
- Lead with findings ordered by severity.
- Include file and line references when available.
- Prioritize correctness, data loss, security, performance, reliability, and missing tests.
- Review implementation against active tech and workflow packs.
- Review TDD evidence: red evidence before production edits, green evidence after implementation, refactor only after green, and no "tests later" loophole.
- Review integration and persistence behavior using the verification strategy approved for the target project.
- Treat unconfirmed tool, runtime, database, package manager, or framework assumptions as risks.
- If no issues are found, state remaining test gaps or residual risk.
