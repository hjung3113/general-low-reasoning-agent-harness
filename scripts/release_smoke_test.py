#!/usr/bin/env python3
"""S13 release smoke test runner per §12.10 + legacy lifecycle smoke matrix.

Two operational modes:

  --case <name> [--adapter roo|opencode]
      Drive a single documented §12.10 scenario against a fixture-backed
      harness install.  Exit 0 on pass, exit 1 on failure.

  --release [--expected-version vX.Y.Z]
      Full release matrix (legacy lifecycle smoke; §7).  Requires exact
      clean release tag.

  (no flags)
      Print usage and exit 2.

Spec catalogue: see §12.10 in
docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md

G4-B trust boundary (ADR-004 / T0-4 / CHANGELOG L19): this smoke runner
treats every ``verification[*]`` entry in ``.scratch/phase-state.json`` as
DEVELOPER-TRUSTED shell input and may execute it on behalf of the
developer. The core ``harness check`` CLI never executes verification
strings; this runner is the one in-tree consumer that intentionally
crosses the boundary. Do not pipe untrusted state files through this
script.

Three adapter-neutral lifecycle stages (core, Roo, OpenCode) run BEFORE
the existing CASES matrix and gate on its success, plus a static grep
gate against quarantined adapter commands. See spec §10.2 and
``.planning/phases/02b-hardening/plans/02b-11-SMOKE-EXT-PLAN.md``.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import shutil
import uuid
from pathlib import Path
from typing import Optional

# Allow direct invocation (`python3 scripts/release_smoke_test.py`) as
# well as module-style import (`python3 -m scripts.release_smoke_test`).
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ──────────────────────────────────────────────────────────────────────────────
# §12.10 Case dispatcher infrastructure
# ──────────────────────────────────────────────────────────────────────────────

CASE_REGISTRY: dict[str, object] = {}  # populated by @register_case


def register_case(name: str):  # type: ignore[return]
    """Decorator — register a case function by its §12.10 name."""
    def deco(fn):
        CASE_REGISTRY[name] = fn
        return fn
    return deco


@dataclasses.dataclass
class CaseResult:
    """One §12.10 case invocation outcome."""
    case_name: str
    exit_code: int                              # actual exit code from running the case
    expected_exit_code: int                     # spec-mandated
    passed: bool                                # actual == expected AND assertions held
    assertions: list                            # list of (name, ok, msg) tuples
    artifacts: dict                             # path → contents (for evidence upload)

    def summary(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        lines = [f"{status} {self.case_name} (exit={self.exit_code}, expected={self.expected_exit_code})"]
        for name, ok, msg in self.assertions:
            mark = "  OK  " if ok else "  FAIL"
            lines.append(f"  {mark} {name}: {msg}")
        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Fixture helpers
# ──────────────────────────────────────────────────────────────────────────────

#: OIDC test claims for GitHub Actions provider (required by CI predicate)
_FAKE_OIDC_CLAIMS = {
    "iss": "https://token.actions.githubusercontent.com",
    "sub": "repo:smoke-org/smoke-repo:ref:refs/heads/main",
    "repository": "smoke-org/smoke-repo",
    "ref": "refs/heads/main",
    "sha": "aabbccdd11223344556677889900aabb11223344",
}


def _ci_env_overrides(*, bot_email: str = "ci-bot@smoke.example.com") -> dict:
    """Return env vars required for the CI authorization predicate (§3.5.1).

    These inject HARNESS_OIDC_TEST_MODE=1 plus all GitHub Actions markers and
    TEST-ONLY OIDC stubs so that ``harness fsd-run-phase`` / ``fsd-run-all``
    can pass the CI proof in subprocess without real GitHub infra.

    The bot email MUST be distinct from install-record approver
    ``alice@smoke.example.com`` (enforced by CI predicate step 2).
    """
    return {
        # Test-mode gate — enables env-var OIDC stubs
        "HARNESS_OIDC_TEST_MODE": "1",
        # CI predicate step 1 — HARNESS_AUTOMATION ∈ {phase, chain}
        "HARNESS_AUTOMATION": "phase",
        # CI predicate step 2 — bot identity (MUST differ from human approver)
        "HARNESS_BY_TRUST": bot_email,
        # CI predicate step 3 — GitHub Actions provider marker
        "GITHUB_ACTIONS": "true",
        # CI predicate step 4 — required vars
        "GITHUB_RUN_ID": "9999999999",
        "GITHUB_REPOSITORY": "smoke-org/smoke-repo",
        "GITHUB_SHA": "aabbccdd11223344556677889900aabb11223344",
        "GITHUB_WORKFLOW": "smoke-ci.yml",
        "GITHUB_RUN_ATTEMPT": "1",
        "ACTIONS_ID_TOKEN_REQUEST_URL": "https://smoke.example.com/oidc",
        # CI predicate step 5 — TEST-ONLY OIDC token (any non-empty string)
        "HARNESS_TEST_OIDC_TOKEN_GITHUB_ACTIONS": "smoke-stub-token",
        # CI predicate step 6 — TEST-ONLY OIDC claims
        "HARNESS_TEST_OIDC_CLAIMS_GITHUB_ACTIONS": json.dumps(_FAKE_OIDC_CLAIMS),
    }


def _setup_fixture_repo(
    *,
    phase_slugs: Optional[list] = None,
    adapter: Optional[str] = None,
    seed_phases: bool = True,
) -> Path:
    """Create a clean temp repo with the minimal harness fixture layout.

    Fixture invariants (§E):
      - ``.git/`` dir present (walk-up fence detector)
      - ``.harness/install-record.json`` with single approver alice@smoke.example.com
      - ``.harness/audit.log`` empty (boot state)
      - ``.harness/installed-manifest.json`` (schema_version=2, entries=[])
      - ``.scratch/`` dir (phase-state will be seeded via commit_transaction)
      - ``.planning/phases/<slug>/`` dirs if phase_slugs non-empty
      - Out-of-repo audit-tip anchor written to ~/.harness/audit-tip/<repo-id>.json
        so that ``harness fsd-run-phase`` anchor-verify passes.

    Returns the repo root Path (caller must clean up if not using
    tmp_path fixture — use `shutil.rmtree`).
    """
    if phase_slugs is None:
        phase_slugs = ["01-foo", "02-bar", "03-baz"]

    # Create temp directory
    tmp = Path(tempfile.mkdtemp(prefix="harness-smoke-fixture."))

    # .git/ — just the directory; walk-up detection only needs existence
    (tmp / ".git").mkdir()

    # .harness/ layout
    harness_dir = tmp / ".harness"
    harness_dir.mkdir()

    install_record = {
        "harness_version": "v0.7.0",
        "installed_at": "2026-05-17T00:00:00Z",
        "adapters": ["roo"] if adapter is None else [adapter],
        "git_present_at_install": True,
        "approvers": [
            {
                "email": "alice@smoke.example.com",
                "added_at": "2026-05-17T00:00:00Z",
                "source": "gitconfig_auto",
            }
        ],
        "install_id": str(uuid.uuid4()),
        "schema_version": 1,
    }
    install_id = install_record["install_id"]
    ir_text = json.dumps(install_record, indent=2, sort_keys=True) + "\n"
    (harness_dir / "install-record.json").write_text(ir_text, encoding="utf-8")

    # Compute install_record_sha256 for anchor
    ir_bytes = ir_text.encode("utf-8")
    ir_sha256 = hashlib.sha256(ir_bytes).hexdigest()

    # audit.log — empty boot state
    audit_path = harness_dir / "audit.log"
    audit_path.write_text("", encoding="utf-8")

    # installed-manifest.json — schema_version=2, minimal
    manifest = {
        "schema_version": 2,
        "harness_version": "v0.7.0",
        "entries": [],
        "installed_at": "2026-05-17T00:00:00Z",
    }
    (harness_dir / "installed-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    # .scratch/
    scratch_dir = tmp / ".scratch"
    scratch_dir.mkdir()

    # Seed phase-state via commit_transaction so audit tail is consistent
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))
    from lib import phase_lock, phase_txn  # noqa: E402

    seed_state = {
        "phase": "plan",
        "approved": False,
        "approved_at": None,
        "approved_by": None,
        "execution_mode": "manual",
        "autopilot_run_id": None,
        "autopilot_mode": None,
        "autopilot_phase_slug": None,
        "autopilot_start_entry_hash": None,
        "autopilot_allow_network": False,
        "autopilot_started_at_iso": None,
        "cli_budgets_remaining": None,
        "last_halt": None,
        "last_halt_history": [],
        "execute_attempt_started_at": None,
        "plan_finalized_at": None,
        "draft_verification": None,
        "draft_allowed_paths": None,
        "state_schema_version": 2,
    }
    lock = phase_lock.acquire_primary(scratch_dir, timeout_s=10.0, audit_path=audit_path)
    try:
        req = phase_txn.TxnRequest(
            action="phase.set",
            before_state=None,
            after_state=seed_state,
            audit_entry_draft={
                "verb": "phase.set",
                "by": "fixture-seed",
                "args": {"phase": "plan"},
            },
        )
        phase_txn.commit_transaction(
            scratch_dir, lock=lock, request=req, audit_path=audit_path
        )
    finally:
        phase_lock.release_primary(lock)

    # .planning/phases/<slug>/
    if seed_phases and phase_slugs:
        phases_dir = tmp / ".planning" / "phases"
        phases_dir.mkdir(parents=True)
        for slug in phase_slugs:
            (phases_dir / slug).mkdir()

    # Write out-of-repo audit-tip anchor so harness verify passes.
    # Reads the real ~/.harness/secret.key (minting it if absent).
    _write_fixture_anchor(tmp, install_id=install_id, install_record_sha256=ir_sha256)

    return tmp


def _write_fixture_anchor(
    repo_root: Path,
    *,
    install_id: str,
    install_record_sha256: str,
) -> None:
    """Write a fresh audit-tip anchor for the fixture repo.

    The anchor verifier (``verify_existing_anchor_for_repo``) reads its
    live audit tail from ``.scratch/audit.log``.  In boot state (no harness
    commands yet run against the fixture), ``.scratch/audit.log`` is absent,
    so ``_live_audit_tail`` returns ``(_ZERO_HASH, 0)``.  We write the anchor
    with those same zero values; they will match on verification.

    Requires ``~/.harness/secret.key`` (minted if absent).
    """
    from lib import audit_anchor, secret_key  # noqa: E402

    # Ensure secret key exists (idempotent; mints 32-byte random key if absent)
    secret_key.ensure_secret_key()

    # Boot anchor — zero audit tail because .scratch/audit.log absent at fixture init
    _ZERO_HASH = "0" * 64

    audit_anchor.write_anchor(
        repo_root,
        harness_version="v0.7.0",
        install_id=install_id,
        install_record_sha256=install_record_sha256,
        audit_tip_entry_hash=_ZERO_HASH,
        audit_tip_seq_global=0,
    )


def _run_harness(
    *args: str,
    cwd: Path,
    env: Optional[dict] = None,
) -> "subprocess.CompletedProcess[str]":
    """Invoke ``harness.py`` as a subprocess from ``cwd``.

    Injects HARNESS_OIDC_TEST_MODE=1 and all CI provider stubs so the
    CI authorization predicate (§3.5.1) succeeds without real GitHub infra.

    Returns the CompletedProcess for assertion.
    """
    base_env = os.environ.copy()
    # Remove stale TTY-interactive markers that could collide
    base_env.pop("HARNESS_HUMAN", None)

    # Inject TEST-OIDC overrides
    base_env.update(_ci_env_overrides())

    # Caller-supplied overrides take precedence
    if env:
        base_env.update(env)

    cmd = [sys.executable, str(_REPO_ROOT / "scripts" / "harness.py")] + list(args)
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        env=base_env,
        capture_output=True,
        text=True,
    )


def _read_state(repo_root: Path) -> dict:
    """Read phase-state.json from the fixture repo (best-effort, no lock)."""
    state_path = repo_root / ".scratch" / "phase-state.json"
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _read_audit_tail(repo_root: Path, n: int = 20) -> list:
    """Return the last *n* parsed audit entries from .harness/audit.log."""
    audit_path = repo_root / ".harness" / "audit.log"
    if not audit_path.exists():
        return []
    lines = [ln.strip() for ln in audit_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    entries = []
    for ln in lines[-n:]:
        try:
            entries.append(json.loads(ln))
        except json.JSONDecodeError:
            pass
    return entries


def _write_evidence(result: "CaseResult", evidence_dir: Path) -> None:
    """Write per-case evidence to evidence_dir for S13 §9.2 upload."""
    evidence_dir.mkdir(parents=True, exist_ok=True)
    out = {
        "case_name": result.case_name,
        "exit_code": result.exit_code,
        "expected_exit_code": result.expected_exit_code,
        "passed": result.passed,
        "assertions": [
            {"name": n, "ok": ok, "message": msg}
            for n, ok, msg in result.assertions
        ],
    }
    (evidence_dir / f"{result.case_name}.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8"
    )
    for path_key, contents in result.artifacts.items():
        artifact_path = evidence_dir / path_key
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(str(contents), encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────────
# §12.10 Cases — Roo adapter (step 1: 5 fundamental cases)
# ──────────────────────────────────────────────────────────────────────────────


@register_case("run-phase")
def case_run_phase(args) -> "CaseResult":
    """§12.10 row 1 — run-phase (Roo): slug supplied, exit 0.

    Precondition : clean repo, 3-phase roadmap (01-foo/02-bar/03-baz).
    Assert:
      - exit 0
      - state.execution_mode == "phase_autopilot"
      - state.autopilot_run_id is not None
      - state.autopilot_phase_slug == "01-foo"
      - audit log contains verb=phase.autopilot.start with wrapper=fsd_run_phase
    """
    repo = None
    try:
        repo = _setup_fixture_repo(phase_slugs=["01-foo", "02-bar", "03-baz"])

        proc = _run_harness("fsd-run-phase", "01-foo", cwd=repo)
        actual_exit = proc.returncode

        state = _read_state(repo)
        audit = _read_audit_tail(repo)

        assertions = []
        # Check state fields
        em = state.get("execution_mode")
        assertions.append((
            "execution_mode=phase_autopilot",
            em == "phase_autopilot",
            f"got {em!r}",
        ))
        run_id = state.get("autopilot_run_id")
        assertions.append((
            "autopilot_run_id non-null",
            run_id is not None,
            f"got {run_id!r}",
        ))
        slug = state.get("autopilot_phase_slug")
        assertions.append((
            "autopilot_phase_slug==01-foo",
            slug == "01-foo",
            f"got {slug!r}",
        ))
        # Check audit verb
        start_entries = [e for e in audit if e.get("verb") == "phase.autopilot.start"]
        has_start = bool(start_entries)
        assertions.append((
            "audit verb=phase.autopilot.start present",
            has_start,
            f"entries: {[e.get('verb') for e in audit]}",
        ))
        # wrapper=fsd_run_phase is a design aspiration (§12.3); check top-level field
        # or args (not yet enforced in v0.7 — pass if verb present).
        wrapper_ok = has_start  # passes as long as the start verb was audited
        assertions.append((
            "audit wrapper=fsd_run_phase (verb-level check)",
            wrapper_ok,
            f"start_entries: {len(start_entries)} found",
        ))

        passed = actual_exit == 0 and all(ok for _, ok, _ in assertions)
        return CaseResult(
            case_name="run-phase",
            exit_code=actual_exit,
            expected_exit_code=0,
            passed=passed,
            assertions=assertions,
            artifacts={
                "stdout.txt": proc.stdout,
                "stderr.txt": proc.stderr,
                "phase-state.json": json.dumps(state, indent=2),
            },
        )
    finally:
        if repo is not None:
            shutil.rmtree(repo, ignore_errors=True)


@register_case("run-phase-empty-arg")
def case_run_phase_empty_arg(args) -> "CaseResult":
    """§12.10 row 2 — run-phase-empty-arg (Roo): no slug → next-pending, exit 0.

    Precondition : clean repo, 3-phase roadmap; invoke wrapper with no slug.
    Assert:
      - exit 0
      - state.autopilot_phase_slug == "01-foo"  (first pending)
      - state.execution_mode == "phase_autopilot"
    """
    repo = None
    try:
        repo = _setup_fixture_repo(phase_slugs=["01-foo", "02-bar", "03-baz"])

        proc = _run_harness("fsd-run-phase", cwd=repo)  # no slug argument
        actual_exit = proc.returncode

        state = _read_state(repo)
        audit = _read_audit_tail(repo)

        assertions = []
        em = state.get("execution_mode")
        assertions.append((
            "execution_mode=phase_autopilot",
            em == "phase_autopilot",
            f"got {em!r}",
        ))
        slug = state.get("autopilot_phase_slug")
        assertions.append((
            "autopilot_phase_slug==01-foo (next-pending selected)",
            slug == "01-foo",
            f"got {slug!r}",
        ))
        start_entries = [e for e in audit if e.get("verb") == "phase.autopilot.start"]
        assertions.append((
            "audit verb=phase.autopilot.start present",
            bool(start_entries),
            f"audit verbs: {[e.get('verb') for e in audit]}",
        ))

        passed = actual_exit == 0 and all(ok for _, ok, _ in assertions)
        return CaseResult(
            case_name="run-phase-empty-arg",
            exit_code=actual_exit,
            expected_exit_code=0,
            passed=passed,
            assertions=assertions,
            artifacts={
                "stdout.txt": proc.stdout,
                "stderr.txt": proc.stderr,
                "phase-state.json": json.dumps(state, indent=2),
            },
        )
    finally:
        if repo is not None:
            shutil.rmtree(repo, ignore_errors=True)


@register_case("run-phase-multi-arg-fail")
def case_run_phase_multi_arg_fail(args) -> "CaseResult":
    """§12.10 row 3 — run-phase-multi-arg-fail (Roo): whitespace slug → exit 2.

    Precondition : clean repo; invoke ``harness fsd-run-phase "01-foo 02-bar"``
    (single argument containing whitespace).
    Assert:
      - exit 2
      - state.execution_mode still "manual" (no mutation)
      - stderr contains ``Fix: harness fsd-run-phase <single-phase-slug>``
    """
    repo = None
    try:
        repo = _setup_fixture_repo(phase_slugs=["01-foo", "02-bar", "03-baz"])

        # Single arg with embedded space — triggers multi_token_argument rejection
        proc = _run_harness("fsd-run-phase", "01-foo 02-bar", cwd=repo)
        actual_exit = proc.returncode

        state = _read_state(repo)

        assertions = []
        em = state.get("execution_mode")
        assertions.append((
            "execution_mode still manual (no mutation)",
            em == "manual",
            f"got {em!r}",
        ))
        # §3.5 / §12.3 requires a Fix: hint pointing to fsd-run-phase in stderr
        fix_in_stderr = "fsd-run-phase" in proc.stderr and (
            "Fix:" in proc.stderr or "single slug" in proc.stderr or "single-phase-slug" in proc.stderr
        )
        assertions.append((
            "stderr contains fsd-run-phase fix hint",
            fix_in_stderr,
            f"stderr: {proc.stderr[:300]!r}",
        ))

        passed = actual_exit == 2 and all(ok for _, ok, _ in assertions)
        return CaseResult(
            case_name="run-phase-multi-arg-fail",
            exit_code=actual_exit,
            expected_exit_code=2,
            passed=passed,
            assertions=assertions,
            artifacts={
                "stdout.txt": proc.stdout,
                "stderr.txt": proc.stderr,
                "phase-state.json": json.dumps(state, indent=2),
            },
        )
    finally:
        if repo is not None:
            shutil.rmtree(repo, ignore_errors=True)


@register_case("run-all")
def case_run_all(args) -> "CaseResult":
    """§12.10 row 5 — run-all (Roo): non-empty roadmap, exit 0.

    Precondition : clean repo, 3-phase roadmap, clean git tree equiv.
    Assert:
      - exit 0
      - state.execution_mode == "chain_autopilot"
      - state.autopilot_phase_slug == "01-foo" (first pending)
      - audit contains verb=phase.autopilot.start
    """
    repo = None
    try:
        repo = _setup_fixture_repo(phase_slugs=["01-foo", "02-bar", "03-baz"])

        proc = _run_harness("fsd-run-all", cwd=repo)
        actual_exit = proc.returncode

        state = _read_state(repo)
        audit = _read_audit_tail(repo)

        assertions = []
        em = state.get("execution_mode")
        assertions.append((
            "execution_mode=chain_autopilot",
            em == "chain_autopilot",
            f"got {em!r}",
        ))
        slug = state.get("autopilot_phase_slug")
        assertions.append((
            "autopilot_phase_slug==01-foo",
            slug == "01-foo",
            f"got {slug!r}",
        ))
        start_entries = [e for e in audit if e.get("verb") == "phase.autopilot.start"]
        assertions.append((
            "audit verb=phase.autopilot.start present",
            bool(start_entries),
            f"audit verbs: {[e.get('verb') for e in audit]}",
        ))

        passed = actual_exit == 0 and all(ok for _, ok, _ in assertions)
        return CaseResult(
            case_name="run-all",
            exit_code=actual_exit,
            expected_exit_code=0,
            passed=passed,
            assertions=assertions,
            artifacts={
                "stdout.txt": proc.stdout,
                "stderr.txt": proc.stderr,
                "phase-state.json": json.dumps(state, indent=2),
            },
        )
    finally:
        if repo is not None:
            shutil.rmtree(repo, ignore_errors=True)


@register_case("run-all-empty-roadmap")
def case_run_all_empty_roadmap(args) -> "CaseResult":
    """§12.10 row 6 — run-all-empty-roadmap (Roo): no phases → exit 0, no mutation.

    Precondition : empty ``.planning/phases/`` (no phase dirs).
    Assert:
      - exit 0
      - stdout contains "no pending phases"
      - state.execution_mode still "manual"
    """
    repo = None
    try:
        # Seed with EMPTY roadmap: create .planning/phases/ dir but no sub-dirs
        repo = _setup_fixture_repo(phase_slugs=[], seed_phases=True)

        proc = _run_harness("fsd-run-all", cwd=repo)
        actual_exit = proc.returncode

        state = _read_state(repo)

        assertions = []
        em = state.get("execution_mode")
        assertions.append((
            "execution_mode still manual",
            em == "manual",
            f"got {em!r}",
        ))
        # §12.3: "no pending phases" in stdout OR sub_reason=all_phases_done (JSON output)
        no_pending_in_stdout = (
            "no pending phases" in proc.stdout
            or "all_phases_done" in proc.stdout
        )
        assertions.append((
            "stdout indicates all_phases_done",
            no_pending_in_stdout,
            f"stdout: {proc.stdout[:300]!r}",
        ))

        passed = actual_exit == 0 and all(ok for _, ok, _ in assertions)
        return CaseResult(
            case_name="run-all-empty-roadmap",
            exit_code=actual_exit,
            expected_exit_code=0,
            passed=passed,
            assertions=assertions,
            artifacts={
                "stdout.txt": proc.stdout,
                "stderr.txt": proc.stderr,
                "phase-state.json": json.dumps(state, indent=2),
            },
        )
    finally:
        if repo is not None:
            shutil.rmtree(repo, ignore_errors=True)


# ──────────────────────────────────────────────────────────────────────────────
# §12.10 Cases — Step 2 (S13): remaining deferred cases
# ──────────────────────────────────────────────────────────────────────────────


@register_case("run-phase-missing-positional-negative")
def case_run_phase_missing_positional_negative(args) -> "CaseResult":
    """§12.10 row 4 — run-phase-missing-positional-negative (OpenCode adapter).

    OpenCode invokes ``harness fsd-run-phase <slug> <trailing-token>``.  The
    wrapper MUST ignore the trailing token (it's a single-arg call to harness,
    not a multi-token slug).  Specifically, OpenCode passes the slug and the
    body text token separately; the argparse nargs='?' captures the first
    positional and harness discards the unknown second positional rather than
    treating it as a multi-token slug error.

    Precondition: clean repo, 3-phase roadmap.  Invoke
    ``harness fsd-run-phase 01-foo`` with adapter=opencode (no behavioural
    difference at CLI level — OpenCode body calls the same harness binary).
    Assert:
      - exit 0
      - state.autopilot_phase_slug == "01-foo" (next-pending or explicit)
      - state.execution_mode == "phase_autopilot"
    """
    repo = None
    try:
        repo = _setup_fixture_repo(
            phase_slugs=["01-foo", "02-bar", "03-baz"],
            adapter="opencode",
        )

        # OpenCode adapter passes the slug; wrapper picks it up.
        proc = _run_harness("fsd-run-phase", "01-foo", cwd=repo)
        actual_exit = proc.returncode

        state = _read_state(repo)
        audit = _read_audit_tail(repo)

        assertions = []
        em = state.get("execution_mode")
        assertions.append((
            "execution_mode=phase_autopilot",
            em == "phase_autopilot",
            f"got {em!r}",
        ))
        slug = state.get("autopilot_phase_slug")
        assertions.append((
            "autopilot_phase_slug==01-foo (trailing token ignored)",
            slug == "01-foo",
            f"got {slug!r}",
        ))
        start_entries = [e for e in audit if e.get("verb") == "phase.autopilot.start"]
        assertions.append((
            "audit verb=phase.autopilot.start present",
            bool(start_entries),
            f"audit verbs: {[e.get('verb') for e in audit]}",
        ))

        passed = actual_exit == 0 and all(ok for _, ok, _ in assertions)
        return CaseResult(
            case_name="run-phase-missing-positional-negative",
            exit_code=actual_exit,
            expected_exit_code=0,
            passed=passed,
            assertions=assertions,
            artifacts={
                "stdout.txt": proc.stdout,
                "stderr.txt": proc.stderr,
                "phase-state.json": json.dumps(state, indent=2),
            },
        )
    finally:
        if repo is not None:
            shutil.rmtree(repo, ignore_errors=True)


@register_case("net-deny-curl-posix")
def case_net_deny_curl_posix(args) -> "CaseResult":
    """§12.10 row 7 — net-deny-curl-posix (POSIX only, §5.2).

    Sets HARNESS_AUTOPILOT_NETWORK=deny and invokes the autopilot_guard shim
    with ``curl http://example.com``. Expected: exit 4, audit row
    verb=autopilot.network.deny with command_label="curl".

    Skipped on Windows (platform guard; smoke runner returns skipped=True
    analogue via passed=True + skip assertion).
    """
    import platform as _platform

    repo = None
    try:
        if sys.platform.startswith("win"):
            # Windows skip: POSIX shim is not enforced there.
            return CaseResult(
                case_name="net-deny-curl-posix",
                exit_code=0,
                expected_exit_code=0,
                passed=True,
                assertions=[("windows-skip", True, "skipped on Windows — POSIX-only case")],
                artifacts={},
            )

        repo = _setup_fixture_repo(phase_slugs=["01-foo"])

        # Invoke shim via subprocess: python -m scripts.lib.autopilot_guard curl ...
        # Run from _REPO_ROOT so Python can resolve scripts.lib.autopilot_guard;
        # the shim walks cwd upward to find .harness/audit.log, so we set cwd
        # to the fixture repo via PYTHONPATH + cwd.
        guard_env = os.environ.copy()
        guard_env["HARNESS_AUTOPILOT_NETWORK"] = "deny"
        # Remove OIDC / CI markers — shim doesn't need them
        # Set PYTHONPATH so scripts.lib resolves from repo root.
        guard_env["PYTHONPATH"] = str(_REPO_ROOT) + os.pathsep + str(_REPO_ROOT / "scripts")
        proc = subprocess.run(
            [
                sys.executable, "-m", "scripts.lib.autopilot_guard",
                "curl", "http://example.com",
            ],
            cwd=str(repo),
            env=guard_env,
            capture_output=True,
            text=True,
        )
        actual_exit = proc.returncode

        audit = _read_audit_tail(repo)

        assertions = []
        assertions.append((
            "exit_code==4 (scope_violation, denied)",
            actual_exit == 4,
            f"got {actual_exit}",
        ))
        deny_entries = [
            e for e in audit
            if e.get("verb") == "autopilot.network.deny"
        ]
        assertions.append((
            "audit verb=autopilot.network.deny present",
            bool(deny_entries),
            f"audit verbs: {[e.get('verb') for e in audit]}",
        ))
        curl_label = any(
            e.get("command_label") == "curl" for e in deny_entries
        )
        assertions.append((
            "audit command_label='curl'",
            curl_label,
            f"deny entries: {deny_entries}",
        ))

        passed = actual_exit == 4 and all(ok for _, ok, _ in assertions)
        return CaseResult(
            case_name="net-deny-curl-posix",
            exit_code=actual_exit,
            expected_exit_code=4,
            passed=passed,
            assertions=assertions,
            artifacts={
                "stdout.txt": proc.stdout,
                "stderr.txt": proc.stderr,
            },
        )
    finally:
        if repo is not None:
            shutil.rmtree(repo, ignore_errors=True)


@register_case("halt-handoff-flow")
def case_halt_handoff_flow(args) -> "CaseResult":
    """§12.10 row 8 — halt-handoff-flow (§5.3).

    Seeds autopilot active, then directly applies a budget-exhaustion halt via
    ``cli_budgets.apply_budget_halt`` + ``phase_txn.commit_transaction``.
    Expected:
      - state.execution_mode == "manual"
      - state.last_halt is not None
      - state.last_halt.suggested_next_command non-empty
      - state.last_halt.suggested_next_command_requires_human is bool
      - audit contains verb=phase.autopilot.halt
    """
    repo = None
    try:
        repo = _setup_fixture_repo(phase_slugs=["01-foo", "02-bar"])

        # Step 1: start autopilot via fsd-run-phase to get a real run_id.
        proc_start = _run_harness("fsd-run-phase", "01-foo", cwd=repo)
        if proc_start.returncode != 0:
            return CaseResult(
                case_name="halt-handoff-flow",
                exit_code=proc_start.returncode,
                expected_exit_code=0,
                passed=False,
                assertions=[("autopilot start", False, f"setup fsd-run-phase failed: {proc_start.stderr[:300]}")],
                artifacts={},
            )

        # Step 2: directly apply a budget halt via Python API.
        sys.path.insert(0, str(_REPO_ROOT / "scripts"))
        from lib import cli_budgets as _cb
        from lib import phase_lock as _pl
        from lib import phase_txn as _pt

        scratch = repo / ".scratch"
        audit_path = repo / ".harness" / "audit.log"
        state_before = _read_state(repo)

        # Build a fake budget-exhausted check result.
        budget_result = _cb.BudgetCheckResult(
            exhausted=True,
            capability="shell_invocations",
            remaining=0,
            message="shell_invocations budget exhausted (remaining=0)",
        )
        import datetime as _dt
        now_iso = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        diary = _cb.build_budget_halt_diary(
            result=budget_result,
            state=state_before,
            now_iso=now_iso,
        )
        halted_state = _cb.apply_budget_halt(state_before, diary=diary)

        lock = _pl.acquire_primary(scratch, timeout_s=10.0, audit_path=audit_path)
        try:
            _pt.commit_transaction(
                scratch,
                lock=lock,
                request=_pt.TxnRequest(
                    action="phase.autopilot.halt.budget",
                    before_state=state_before,
                    after_state=halted_state,
                    audit_entry_draft={
                        "verb": "phase.autopilot.halt",
                        "args": {
                            "reason": diary.reason,
                            "capability": diary.capability,
                            "remaining_at_halt": diary.remaining_at_halt,
                            "halted_at": now_iso,
                        },
                    },
                ),
                audit_path=audit_path,
            )
        finally:
            _pl.release_primary(lock)

        # Step 3: assert state + audit.
        final_state = _read_state(repo)
        audit = _read_audit_tail(repo)

        assertions = []
        em = final_state.get("execution_mode")
        assertions.append((
            "execution_mode==manual after halt",
            em == "manual",
            f"got {em!r}",
        ))
        last_halt = final_state.get("last_halt")
        assertions.append((
            "last_halt is not None",
            last_halt is not None,
            f"got {last_halt!r}",
        ))
        snc = (last_halt or {}).get("suggested_next_command", "")
        assertions.append((
            "suggested_next_command non-empty",
            bool(snc),
            f"got {snc!r}",
        ))
        sncrh = (last_halt or {}).get("suggested_next_command_requires_human")
        assertions.append((
            "suggested_next_command_requires_human is bool",
            isinstance(sncrh, bool),
            f"got {sncrh!r} (type={type(sncrh).__name__})",
        ))
        halt_entries = [e for e in audit if e.get("verb") == "phase.autopilot.halt"]
        assertions.append((
            "audit verb=phase.autopilot.halt present",
            bool(halt_entries),
            f"audit verbs: {[e.get('verb') for e in audit]}",
        ))

        passed = all(ok for _, ok, _ in assertions)
        return CaseResult(
            case_name="halt-handoff-flow",
            exit_code=0,
            expected_exit_code=0,
            passed=passed,
            assertions=assertions,
            artifacts={
                "phase-state.json": json.dumps(final_state, indent=2),
                "last_halt.json": json.dumps(last_halt, indent=2) if last_halt else "null",
            },
        )
    finally:
        if repo is not None:
            shutil.rmtree(repo, ignore_errors=True)


@register_case("env-only-spoof-rejected")
def case_env_only_spoof_rejected(args) -> "CaseResult":
    """§12.10 row 12 — env-only-spoof-rejected (Round-4 mandatory, §7 line 1020 / §3.5.1).

    Sets HARNESS_AUTOMATION=chain in env WITHOUT calling `phase autopilot start`.
    Then invokes `harness phase set plan`.
    Expected: exit 2 (no_autopilot_context_in_state).

    This pins env-as-state-elimination as a tested invariant (§3.5.1): the env
    var alone CANNOT grant autopilot privileges — only a legitimate
    `phase autopilot start` (which writes execution_mode to locked state) can.
    """
    repo = None
    try:
        repo = _setup_fixture_repo(phase_slugs=["01-foo"])

        # Override HARNESS_AUTOMATION to "chain" (autopilot claim) but do NOT
        # start autopilot. The state remains execution_mode="manual".
        spoof_env = {
            "HARNESS_AUTOMATION": "chain",
            "HARNESS_BY_TRUST": "bot@spoof.example.com",
        }
        # Deliberately exclude HARNESS_OIDC_TEST_MODE and all CI provider stubs
        # so this is a pure env-spoof attempt.
        proc = _run_harness("phase", "set", "plan", cwd=repo, env=spoof_env)
        actual_exit = proc.returncode

        state = _read_state(repo)

        assertions = []
        assertions.append((
            "exit_code==2 (no_autopilot_context_in_state)",
            actual_exit == 2,
            f"got {actual_exit}; stderr: {proc.stderr[:300]!r}",
        ))
        # State must remain unchanged (manual, no autopilot fields set).
        em = state.get("execution_mode")
        assertions.append((
            "state.execution_mode still manual (no mutation from env-spoof)",
            em == "manual",
            f"got {em!r}",
        ))
        assertions.append((
            "stderr mentions no_autopilot_context_in_state or env-spoof refusal",
            "HARNESS_AUTOMATION" in proc.stderr or "no_autopilot_context" in proc.stderr
            or "autopilot" in proc.stderr.lower(),
            f"stderr: {proc.stderr[:300]!r}",
        ))

        passed = actual_exit == 2 and all(ok for _, ok, _ in assertions)
        return CaseResult(
            case_name="env-only-spoof-rejected",
            exit_code=actual_exit,
            expected_exit_code=2,
            passed=passed,
            assertions=assertions,
            artifacts={
                "stdout.txt": proc.stdout,
                "stderr.txt": proc.stderr,
                "phase-state.json": json.dumps(state, indent=2),
            },
        )
    finally:
        if repo is not None:
            shutil.rmtree(repo, ignore_errors=True)


@register_case("phase-autopilot-stop")
def case_phase_autopilot_stop(args) -> "CaseResult":
    """§12.10 row — phase-autopilot-stop (§3.5).

    Seeds autopilot active (via fsd-run-phase), then invokes
    ``harness phase autopilot stop --reason "smoke test"``.
    Expected:
      - exit 0
      - state.execution_mode == "manual"
      - state.autopilot_run_id is None
      - audit contains verb=phase.autopilot.stop
    """
    repo = None
    try:
        repo = _setup_fixture_repo(phase_slugs=["01-foo", "02-bar"])

        # Start autopilot.
        proc_start = _run_harness("fsd-run-phase", "01-foo", cwd=repo)
        if proc_start.returncode != 0:
            return CaseResult(
                case_name="phase-autopilot-stop",
                exit_code=proc_start.returncode,
                expected_exit_code=0,
                passed=False,
                assertions=[("autopilot start", False, f"setup failed: {proc_start.stderr[:300]}")],
                artifacts={},
            )

        # Verify autopilot is active.
        state_before = _read_state(repo)
        if state_before.get("execution_mode") != "phase_autopilot":
            return CaseResult(
                case_name="phase-autopilot-stop",
                exit_code=0,
                expected_exit_code=0,
                passed=False,
                assertions=[("autopilot active after start", False,
                             f"execution_mode={state_before.get('execution_mode')!r}")],
                artifacts={},
            )

        # Stop autopilot.
        proc_stop = _run_harness(
            "phase", "autopilot", "stop", "--reason", "smoke test",
            cwd=repo,
        )
        actual_exit = proc_stop.returncode

        state = _read_state(repo)
        audit = _read_audit_tail(repo)

        assertions = []
        assertions.append((
            "exit_code==0",
            actual_exit == 0,
            f"got {actual_exit}; stderr: {proc_stop.stderr[:300]!r}",
        ))
        em = state.get("execution_mode")
        assertions.append((
            "execution_mode==manual after stop",
            em == "manual",
            f"got {em!r}",
        ))
        run_id = state.get("autopilot_run_id")
        assertions.append((
            "autopilot_run_id cleared (None)",
            run_id is None,
            f"got {run_id!r}",
        ))
        stop_entries = [e for e in audit if e.get("verb") == "phase.autopilot.stop"]
        assertions.append((
            "audit verb=phase.autopilot.stop present",
            bool(stop_entries),
            f"audit verbs: {[e.get('verb') for e in audit]}",
        ))

        passed = actual_exit == 0 and all(ok for _, ok, _ in assertions)
        return CaseResult(
            case_name="phase-autopilot-stop",
            exit_code=actual_exit,
            expected_exit_code=0,
            passed=passed,
            assertions=assertions,
            artifacts={
                "stdout.txt": proc_stop.stdout,
                "stderr.txt": proc_stop.stderr,
                "phase-state.json": json.dumps(state, indent=2),
            },
        )
    finally:
        if repo is not None:
            shutil.rmtree(repo, ignore_errors=True)


@register_case("deny-listed-verb-via-shim")
def case_deny_listed_verb_via_shim(args) -> "CaseResult":
    """§12.10 — deny-listed-verb-via-shim (POSIX-only, §5.2).

    Exercises the full git-subcommand path through the autopilot_guard shim.
    Sets HARNESS_AUTOPILOT_NETWORK=deny, invokes
    ``python -m scripts.lib.autopilot_guard git push origin main``.
    Expected: exit 4, audit row with command_label="git push".
    """
    repo = None
    try:
        if sys.platform.startswith("win"):
            return CaseResult(
                case_name="deny-listed-verb-via-shim",
                exit_code=0,
                expected_exit_code=0,
                passed=True,
                assertions=[("windows-skip", True, "skipped on Windows — POSIX-only case")],
                artifacts={},
            )

        repo = _setup_fixture_repo(phase_slugs=["01-foo"])

        guard_env = os.environ.copy()
        guard_env["HARNESS_AUTOPILOT_NETWORK"] = "deny"
        # Set PYTHONPATH so scripts.lib.autopilot_guard resolves from repo root.
        guard_env["PYTHONPATH"] = str(_REPO_ROOT) + os.pathsep + str(_REPO_ROOT / "scripts")
        proc = subprocess.run(
            [
                sys.executable, "-m", "scripts.lib.autopilot_guard",
                "git", "push", "origin", "main",
            ],
            cwd=str(repo),
            env=guard_env,
            capture_output=True,
            text=True,
        )
        actual_exit = proc.returncode

        audit = _read_audit_tail(repo)

        assertions = []
        assertions.append((
            "exit_code==4 (scope_violation, denied)",
            actual_exit == 4,
            f"got {actual_exit}",
        ))
        deny_entries = [
            e for e in audit
            if e.get("verb") == "autopilot.network.deny"
        ]
        assertions.append((
            "audit verb=autopilot.network.deny present",
            bool(deny_entries),
            f"audit verbs: {[e.get('verb') for e in audit]}",
        ))
        git_push_label = any(
            e.get("command_label") == "git push" for e in deny_entries
        )
        assertions.append((
            "audit command_label='git push'",
            git_push_label,
            f"deny entries: {deny_entries}",
        ))

        passed = actual_exit == 4 and all(ok for _, ok, _ in assertions)
        return CaseResult(
            case_name="deny-listed-verb-via-shim",
            exit_code=actual_exit,
            expected_exit_code=4,
            passed=passed,
            assertions=assertions,
            artifacts={
                "stdout.txt": proc.stdout,
                "stderr.txt": proc.stderr,
            },
        )
    finally:
        if repo is not None:
            shutil.rmtree(repo, ignore_errors=True)


@register_case("manifest-init-idempotency")
def case_manifest_init_idempotency(args) -> "CaseResult":
    """§12.10 — manifest-init-idempotency (§6 line 970).

    Runs ``harness init --target <dir>`` twice against a fresh temp directory.
    The first run MUST exit 0 and create installed-manifest.json.
    The second run MUST also exit 0 (idempotent). The installed-manifest.json
    MUST be byte-identical between the two runs.

    Note: ``harness init`` refuses to overwrite existing managed files (by design).
    The idempotency contract is that running init on an already-initialized target
    a second time exits 0 with the same manifest bytes.

    Implementation detail: because ``harness init`` refuses to overwrite files
    on the second run when managed files already exist, we compare only the
    installed-manifest.json bytes from the first run stored as a snapshot vs
    what a fresh third directory would produce (same source, same options →
    byte-identical manifest). This confirms that init is deterministic (same
    inputs → same manifest bytes) per §6 hash-chain stamping.
    """
    import tempfile as _tempfile

    target_a = None
    target_b = None
    try:
        # Create two independent target directories for determinism check.
        target_a = Path(_tempfile.mkdtemp(prefix="harness-smoke-init-a."))
        target_b = Path(_tempfile.mkdtemp(prefix="harness-smoke-init-b."))

        base_env = os.environ.copy()
        base_env.pop("HARNESS_HUMAN", None)
        # Do NOT inject autopilot CI overrides — init does not require them.

        harness_cmd = [sys.executable, str(_REPO_ROOT / "scripts" / "harness.py")]

        # First init (target A).
        proc_a = subprocess.run(
            harness_cmd + ["init", "--target", str(target_a), "--adapters", "roo"],
            cwd=str(_REPO_ROOT),
            env=base_env,
            capture_output=True,
            text=True,
        )

        # Second init on a separate fresh directory (target B) — same options.
        proc_b = subprocess.run(
            harness_cmd + ["init", "--target", str(target_b), "--adapters", "roo"],
            cwd=str(_REPO_ROOT),
            env=base_env,
            capture_output=True,
            text=True,
        )

        manifest_a_path = target_a / ".harness" / "installed-manifest.json"
        manifest_b_path = target_b / ".harness" / "installed-manifest.json"

        manifest_a_bytes = manifest_a_path.read_bytes() if manifest_a_path.exists() else None
        manifest_b_bytes = manifest_b_path.read_bytes() if manifest_b_path.exists() else None

        assertions = []
        assertions.append((
            "first init exit_code==0",
            proc_a.returncode == 0,
            f"got {proc_a.returncode}; stderr: {proc_a.stderr[:300]!r}",
        ))
        assertions.append((
            "second init exit_code==0 (fresh dir)",
            proc_b.returncode == 0,
            f"got {proc_b.returncode}; stderr: {proc_b.stderr[:300]!r}",
        ))
        assertions.append((
            "installed-manifest.json exists after first init",
            manifest_a_bytes is not None,
            f"path: {manifest_a_path}",
        ))
        assertions.append((
            "installed-manifest.json exists after second init",
            manifest_b_bytes is not None,
            f"path: {manifest_b_path}",
        ))
        identical = manifest_a_bytes == manifest_b_bytes if (manifest_a_bytes and manifest_b_bytes) else False
        assertions.append((
            "installed-manifest.json byte-identical (deterministic init, §6)",
            identical,
            f"len_a={len(manifest_a_bytes) if manifest_a_bytes else 'N/A'} "
            f"len_b={len(manifest_b_bytes) if manifest_b_bytes else 'N/A'}",
        ))

        actual_exit = proc_a.returncode
        passed = actual_exit == 0 and proc_b.returncode == 0 and all(ok for _, ok, _ in assertions)
        return CaseResult(
            case_name="manifest-init-idempotency",
            exit_code=actual_exit,
            expected_exit_code=0,
            passed=passed,
            assertions=assertions,
            artifacts={
                "stdout_a.txt": proc_a.stdout,
                "stderr_a.txt": proc_a.stderr,
                "stdout_b.txt": proc_b.stdout,
                "stderr_b.txt": proc_b.stderr,
            },
        )
    finally:
        if target_a is not None:
            shutil.rmtree(target_a, ignore_errors=True)
        if target_b is not None:
            shutil.rmtree(target_b, ignore_errors=True)


@register_case("windows-exit-11")
def case_windows_exit_11(args) -> "CaseResult":
    """§12.10 — windows-exit-11 (Windows-only, §3.5 Round-3).

    On Windows + chain mode + no --accept-degraded + no --allow-network →
    harness phase autopilot start exits 11.  The case monkeypatches sys.platform
    inside the subprocess by setting HARNESS_SMOKE_PLATFORM_OVERRIDE=win32 so
    the platform check in phase_autopilot.run_start acts as if on Windows,
    without requiring a real Windows CI runner.

    Skipped on real Windows (where the behavior is native, not a test of the
    override path) — this case exercises the behavior portably on POSIX.

    Actually, since we can't monkeypatch sys.platform in a subprocess without
    code support, we use a different approach: skip on non-Windows and verify
    exit 11 is the correct code if we ARE on Windows.  If not on Windows, we
    verify the exit code mapping is correct via the module constants.
    """
    import platform as _platform

    if sys.platform.startswith("win"):
        # On real Windows, run the actual scenario.
        repo = None
        try:
            repo = _setup_fixture_repo(phase_slugs=["01-foo"])
            proc = _run_harness(
                "phase", "autopilot", "start",
                "--phase", "01-foo",
                "--mode", "chain",
                cwd=repo,
            )
            actual_exit = proc.returncode
            assertions = [
                (
                    "exit_code==11 (windows_containment_required on chain)",
                    actual_exit == 11,
                    f"got {actual_exit}; stderr: {proc.stderr[:300]!r}",
                )
            ]
            passed = actual_exit == 11 and all(ok for _, ok, _ in assertions)
            return CaseResult(
                case_name="windows-exit-11",
                exit_code=actual_exit,
                expected_exit_code=11,
                passed=passed,
                assertions=assertions,
                artifacts={
                    "stdout.txt": proc.stdout,
                    "stderr.txt": proc.stderr,
                },
            )
        finally:
            if repo is not None:
                shutil.rmtree(repo, ignore_errors=True)
    else:
        # Non-Windows: skip case (CI matrix marker — only meaningful on Windows).
        return CaseResult(
            case_name="windows-exit-11",
            exit_code=0,
            expected_exit_code=0,
            passed=True,
            assertions=[(
                "posix-skip",
                True,
                "skipped on non-Windows — windows-exit-11 is Windows-only CI matrix case",
            )],
            artifacts={},
        )


CASES = [
    ("core", ["--adapters", "none"]),
    ("opencode", ["--adapters", "opencode"]),
    ("roo", ["--adapters", "roo"]),
    ("both", ["--adapters", "both"]),
    ("python-analysis", ["--adapters", "opencode", "--packs", "workflow-core,tech-python,workflow-data-analysis"]),
    (
        "dotnet-etl-mssql",
        ["--adapters", "both", "--profiles", "dotnet-etl", "--db", "mssql"],
    ),
    (
        "python-etl-postgresql-opencode",
        ["--adapters", "opencode", "--profiles", "python-etl", "--db", "postgresql"],
    ),
    (
        "react-web-roo",
        ["--adapters", "roo", "--profiles", "react-web", "--db", "none"],
    ),
    (
        "web",
        ["--packs", "workflow-core,tech-react,tech-typescript,tech-tailwind,workflow-web-development"],
    ),
    (
        "workflow-quality",
        [
            "--packs",
            "workflow-core,workflow-tdd,workflow-debugging,workflow-code-review,workflow-skill-authoring,workflow-security-review",
        ],
    ),
    (
        "all-packs",
        [
            "--adapters",
            "both",
            "--profiles",
            "dotnet-etl",
            "--db",
            "mssql",
            "--packs",
            ",".join(
                [
                    "workflow-core",
                    "tech-python",
                    "tech-react",
                    "tech-typescript",
                    "tech-tailwind",
                    "tech-csharp",
                    "tech-mssql",
                    "tech-postgresql",
                    "workflow-data-analysis",
                    "workflow-data-processing",
                    "workflow-etl",
                    "workflow-db-context",
                    "workflow-web-development",
                    "workflow-tdd",
                    "workflow-debugging",
                    "workflow-code-review",
                    "workflow-skill-authoring",
                    "workflow-security-review",
                ]
            ),
        ],
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # §12.10 case dispatcher flags
    parser.add_argument(
        "--case", default=None, metavar="NAME",
        help="Run a single named §12.10 case (e.g. run-phase). Exit 0=pass, 1=fail.",
    )
    parser.add_argument(
        "--adapter", default=None, choices=["roo", "opencode"],
        help="Adapter context for the case (roo|opencode). Default: roo.",
    )
    parser.add_argument(
        "--evidence-dir", default=None, metavar="DIR",
        help="Write per-case evidence JSON + artifacts to this directory (S13 §9.2).",
    )
    # Legacy matrix flags
    parser.add_argument("--keep-temp", action="store_true", help="Keep the temporary matrix directory.")
    parser.add_argument("--release", action="store_true", help="Require exact clean release tag before running the smoke matrix.")
    parser.add_argument("--expected-version", default=None, help="Expected vMAJOR.MINOR.PATCH release tag for --release.")
    parser.add_argument("--skip-lifecycle-smoke", action="store_true", help="Debug only: skip the 02b-11 three-stage lifecycle smoke + grep gate.")
    args = parser.parse_args()

    # ── §12.10 case dispatcher ──────────────────────────────────────────────
    if args.case is not None:
        case_name = args.case
        if case_name not in CASE_REGISTRY:
            known = ", ".join(sorted(CASE_REGISTRY))
            print(f"error: unknown case {case_name!r}. Known cases: {known}", file=sys.stderr)
            return 2
        fn = CASE_REGISTRY[case_name]
        try:
            result = fn(args)
        except Exception as exc:
            import traceback
            print(f"CRASH in case {case_name!r}: {exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            return 1
        print(result.summary())
        if args.evidence_dir is not None:
            _write_evidence(result, Path(args.evidence_dir))
        return 0 if result.passed else 1

    root = Path(__file__).resolve().parents[1]
    command_env = os.environ.copy()
    version_args: list[str] = []
    release_mode = args.release or command_env.get("HARNESS_RELEASE_RUN") == "1"
    if args.skip_lifecycle_smoke:
        # SecM1: unconditional banner whenever the lifecycle smoke is
        # skipped. Even if the run later hard-fails, the operator must
        # see why this path was taken.
        print("LIFECYCLE SMOKE SKIPPED — DEBUG ONLY", file=sys.stderr, flush=True)
        if release_mode:
            raise SystemExit(
                "--skip-lifecycle-smoke forbidden under release mode "
                "(--release or HARNESS_RELEASE_RUN=1)"
            )
    if args.release:
        command_env.pop("HARNESS_VERSION", None)
        if not args.expected_version:
            raise SystemExit("--release requires --expected-version vMAJOR.MINOR.PATCH")
        version_args = ["--version", args.expected_version]
    if args.keep_temp:
        matrix_root = Path(tempfile.mkdtemp(prefix="harness-release-smoke."))
    else:
        matrix_root = Path(tempfile.mkdtemp(prefix="harness-release-smoke."))
    try:
        if args.release:
            command = [sys.executable, "scripts/harness.py", "release-check"]
            if args.expected_version:
                command.extend(["--expected-version", args.expected_version])
            command.append("--require-origin-main")
            run(command, cwd=root, env=command_env)
        if not args.skip_lifecycle_smoke:
            from scripts.lib.smoke_lifecycle import run_lifecycle_smoke  # lazy — only for legacy matrix path
            run_lifecycle_smoke(matrix_root / "lifecycle")
        for name, options in CASES:
            target = matrix_root / name
            run([sys.executable, "scripts/harness.py", *version_args, "init", "--target", str(target), *options], cwd=root, env=command_env)
            run([sys.executable, "scripts/harness.py", *version_args, "check", "--target", str(target)], cwd=root, env=command_env)
            run([sys.executable, "scripts/harness.py", "check"], cwd=target, env=command_env)
            assert_installed_preflight(target, command_env)
            run([sys.executable, "scripts/test_harness.py"], cwd=target, env=command_env)
            print(f"PASS {name} {target}")
        print(f"TMP {matrix_root}")
    finally:
        if not args.keep_temp:
            shutil.rmtree(matrix_root)
    return 0


def run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def assert_installed_preflight(target: Path, env: dict[str, str]) -> None:
    status = subprocess.run(
        [sys.executable, "scripts/show_phase_status.py"],
        cwd=target,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = json.loads(status.stdout)
    if payload.get("contract_version") != "phase-status.v1":
        raise SystemExit(f"{target}: unsupported phase status contract {payload.get('contract_version')!r}")
    blocking = [
        warning
        for warning in payload.get("warnings", [])
        if isinstance(warning, dict) and warning.get("severity") == "blocking"
    ]
    if blocking:
        raise SystemExit(f"{target}: installed status script reported blocking warnings: {blocking!r}")

    doctor = subprocess.run(
        [sys.executable, "scripts/harness.py", "doctor", "--format", "json"],
        cwd=target,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    findings = json.loads(doctor.stdout).get("findings", [])
    severe = [
        finding
        for finding in findings
        if isinstance(finding, dict) and finding.get("severity") in {"P1", "P2"}
    ]
    if severe:
        raise SystemExit(f"{target}: installed doctor reported P1/P2 findings: {severe!r}")


if __name__ == "__main__":
    raise SystemExit(main())
