# Audit log is plain JSON-lines; no hash chain

The audit log (`.harness/audit.jsonl`) is a simple append-only JSON-lines file. Each entry records a timestamp, event, phase, actor, target path, and outcome — nothing more cryptographic than that. The per-entry SHA-256 hash chain in `scripts/lib/audit_chain.py` (126 LOC) is **not** part of the contract and should be removed; it has no verify path (`verify_chain` / `walk_chain` were deleted in Milestone 2 Item 5), and under ADR-0002 there is no attacker model that justifies write-only tamper-evidence.

Standing rule: audit entries are diagnostic, not forensic. A reader trusts the file because they trust the machine and the operator (ADR-0002). New audit fields go through the JSONL writer; new code must not add hash-chaining, RFC 8785 canonicalization, or any other anti-tamper machinery to the audit path. `audit_rotation.py` (60 LOC) stays only if real-world logs cross its threshold; otherwise the same strip applies.

Reversing this would require both an attacker model and a verify path. The grilling session that produced this ADR (2026-05-23, with codex) treated write-only crypto as "metadata decoration" — keep the warning if anyone proposes reinstating it without those two pieces.
