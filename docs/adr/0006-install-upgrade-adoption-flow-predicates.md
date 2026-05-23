# install / upgrade / adoption — flow predicates and idempotency

The three entry flows are disjoint and selected by the predicate on the target repo's state, not by the user passing a flag. Predicates:

- **install**: no valid `.harness/install-record.json` **and** no managed skeleton files present.
- **upgrade**: a valid `.harness/install-record.json` exists.
- **adoption**: managed-looking skeleton files present **but** no valid install record. Used after a manual file drop or a partial restore.

A target that does not match any predicate (partial state — install record corrupt, partial skeleton, mixed versions) is treated as ambiguous. The harness **refuses to route automatically** and emits a diagnostic with the explicit remediation flag (typically `--adopt-existing` or manual repair). Silent re-installs are the failure mode that destroys project-owned edits, so the refusal is by design.

Idempotency:
- `install` against an already-installed target → refuses with "already installed; use `upgrade` or `status`".
- `upgrade` when versions match → no-op with a clear "nothing to do at vX.Y.Z" message; `--force` re-applies the manifest.
- `adoption` always requires explicit operator intent; never invoked automatically by another flow.

Reversing the predicate split (e.g., collapsing `adoption` into `install`) would mean re-deciding what "trust existing files" means and re-litigating the partial-state policy. Adoption stays a separate module (`scripts/lib/adoption.py`) for the same reason. Grilled and agreed with codex 2026-05-23.
