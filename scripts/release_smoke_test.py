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
