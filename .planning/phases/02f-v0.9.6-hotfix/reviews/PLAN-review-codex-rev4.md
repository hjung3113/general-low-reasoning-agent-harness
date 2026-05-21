# Codex Plan Review REV-4 — v0.9.7

Verdict: BLOCK

## N-2 status: CLOSED

Sentinel presence is now positive completion proof, and the write point is correct: after successful per-file renames and journal flushes, before `atomic_install_batch(..., defer_cleanup=True)` returns.

## NEW

N-3 BLOCK: §7.2 says "sentinel absent" means ROLLBACK, but the pseudocode calls existing `_recover_one(...)`. Current `_recover_one` resumes non-`.aborted` staging via `atomic_install_batch`; it does not roll back. That can finish installing files, delete the pending manifest, and leave `installed-manifest.json` stale/missing. Implement a real rollback path for sentinel-absent pending-manifest recovery, or change the matrix to resume and then finalize the pending manifest.

## Recommended next step

Patch §7.2 so sentinel-absent recovery uses semantics that match the decision matrix, then move to ImplPlan.
