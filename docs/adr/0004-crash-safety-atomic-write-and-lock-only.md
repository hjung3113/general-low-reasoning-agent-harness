# Crash-safety is atomic write + primary lock; no anti-tamper semantics

The harness keeps two crash-safety primitives: atomic file writes (`scripts/lib/atomic_io.py`, `durable_fs.py`) and an O_EXCL primary lock with dead-process detection (`phase_lock.py`). These protect against the developer's own machine crashing mid-state-mutation, which is the realistic failure mode for an internal tool. Anti-tamper / state-trust semantics that assume a malicious actor on the same machine (`state_trust.py` 364 LOC; the full recovery matrix in `phase_txn.py`) are **not** part of the contract; ADR-0002 already excludes that threat model.

Standing rule: new code may rely on atomic writes and the primary lock for correctness, but should not add tamper-detection, integrity proofs, or recovery ceremonies that only make sense under an attacker model. Trim candidates surfaced by the 2026-05-23 grill: `state_trust.py` whole-module strip, `phase_txn.py` recovery matrix simplification (keep 5-step txn shape if it remains the simplest way to land an atomic state+audit write; drop journal-replay paths if they only matter for attacker recovery).

Reversing this means re-introducing the threat model from ADR-0002 first, then re-adding the matching guards. Standing decision precedes any guard.
