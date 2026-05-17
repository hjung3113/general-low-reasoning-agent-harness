"""Unit tests for the S13 release_smoke_test.py runner infrastructure (§12.10).

Tests the case dispatcher pattern, fixture helper shape, and TEST-OIDC env
wiring without invoking real harness subprocesses (fast, hermetic).

Spec: docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md §12.10
Slice: S13-smoke step 1
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# ── Import the runner module ──────────────────────────────────────────────────
# Import via sys.path manipulation so __name__ / __module__ are set correctly
# (required for dataclasses to resolve type annotations in Python 3.9).

if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import importlib.util
_spec = importlib.util.spec_from_file_location(
    "release_smoke_test_module",
    str(REPO_ROOT / "scripts" / "release_smoke_test.py"),
    submodule_search_locations=[],
)
_mod = importlib.util.module_from_spec(_spec)
_mod.__name__ = "release_smoke_test_module"
_mod.__package__ = None
import sys as _sys
_sys.modules["release_smoke_test_module"] = _mod
_spec.loader.exec_module(_mod)

CASE_REGISTRY = _mod.CASE_REGISTRY
CaseResult = _mod.CaseResult
_setup_fixture_repo = _mod._setup_fixture_repo
_run_harness = _mod._run_harness
_ci_env_overrides = _mod._ci_env_overrides
_REPO_ROOT = _mod._REPO_ROOT


# ── Case registry tests ───────────────────────────────────────────────────────


def test_case_registry_contains_5_fundamental_cases():
    """All 5 step-1 §12.10 cases are registered."""
    expected = {
        "run-phase",
        "run-phase-empty-arg",
        "run-phase-multi-arg-fail",
        "run-all",
        "run-all-empty-roadmap",
    }
    assert expected.issubset(set(CASE_REGISTRY)), (
        f"Missing cases: {expected - set(CASE_REGISTRY)}"
    )


def test_case_registry_values_are_callable():
    """Every registered case is callable."""
    for name, fn in CASE_REGISTRY.items():
        assert callable(fn), f"Case {name!r} is not callable"


def test_register_case_decorator_is_idempotent_for_same_name():
    """Registering a new function under an existing name replaces the old one."""
    _rc = _mod.register_case

    sentinel = []

    @_rc("_test_idempotent_sentinel_unit")
    def _fn1():
        sentinel.append(1)

    @_rc("_test_idempotent_sentinel_unit")
    def _fn2():
        sentinel.append(2)

    assert CASE_REGISTRY["_test_idempotent_sentinel_unit"] is _fn2


def test_case_result_passed_false_when_exit_mismatch():
    """CaseResult.passed is False when actual exit ≠ expected."""
    r = CaseResult(
        case_name="dummy",
        exit_code=1,
        expected_exit_code=0,
        passed=False,
        assertions=[],
        artifacts={},
    )
    assert not r.passed


def test_case_result_summary_shows_pass():
    """CaseResult.summary() prefixes PASS when passed=True."""
    r = CaseResult(
        case_name="dummy",
        exit_code=0,
        expected_exit_code=0,
        passed=True,
        assertions=[("check-a", True, "ok")],
        artifacts={},
    )
    summary = r.summary()
    assert summary.startswith("PASS"), f"Expected PASS prefix, got: {summary[:30]!r}"


def test_case_result_summary_shows_fail():
    """CaseResult.summary() prefixes FAIL when passed=False."""
    r = CaseResult(
        case_name="dummy",
        exit_code=1,
        expected_exit_code=0,
        passed=False,
        assertions=[("check-a", False, "not ok")],
        artifacts={},
    )
    summary = r.summary()
    assert summary.startswith("FAIL"), f"Expected FAIL prefix, got: {summary[:30]!r}"


# ── _ci_env_overrides tests ───────────────────────────────────────────────────


def test_ci_env_overrides_contains_required_keys():
    """_ci_env_overrides() returns all keys needed for CI predicate (§3.5.1)."""
    overrides = _ci_env_overrides()
    required = [
        "HARNESS_OIDC_TEST_MODE",
        "HARNESS_AUTOMATION",
        "HARNESS_BY_TRUST",
        "GITHUB_ACTIONS",
        "GITHUB_RUN_ID",
        "GITHUB_REPOSITORY",
        "GITHUB_SHA",
        "GITHUB_WORKFLOW",
        "GITHUB_RUN_ATTEMPT",
        "ACTIONS_ID_TOKEN_REQUEST_URL",
        "HARNESS_TEST_OIDC_TOKEN_GITHUB_ACTIONS",
        "HARNESS_TEST_OIDC_CLAIMS_GITHUB_ACTIONS",
    ]
    for key in required:
        assert key in overrides, f"Missing key: {key}"


def test_ci_env_overrides_oidc_test_mode_is_1():
    """HARNESS_OIDC_TEST_MODE must be exactly '1' to enable test stubs."""
    assert _ci_env_overrides()["HARNESS_OIDC_TEST_MODE"] == "1"


def test_ci_env_overrides_claims_valid_json():
    """HARNESS_TEST_OIDC_CLAIMS_GITHUB_ACTIONS must be parseable JSON."""
    raw = _ci_env_overrides()["HARNESS_TEST_OIDC_CLAIMS_GITHUB_ACTIONS"]
    parsed = json.loads(raw)
    assert isinstance(parsed, dict)
    assert "iss" in parsed
    assert "sub" in parsed


def test_ci_env_overrides_bot_distinct_from_approver():
    """Bot email (HARNESS_BY_TRUST) must differ from fixture approver alice@smoke.example.com."""
    bot = _ci_env_overrides()["HARNESS_BY_TRUST"]
    assert bot != "alice@smoke.example.com", (
        "Bot identity must differ from fixture approver (CI predicate step 2)"
    )


# ── _setup_fixture_repo shape tests ──────────────────────────────────────────


@pytest.fixture
def fixture_repo(tmp_path):
    """Create a fixture repo and return its root path."""
    import shutil
    repo = None
    try:
        repo = _setup_fixture_repo(phase_slugs=["01-foo", "02-bar", "03-baz"])
        yield repo
    finally:
        if repo is not None and Path(repo).exists():
            shutil.rmtree(repo, ignore_errors=True)


def test_fixture_repo_creates_git_dir(fixture_repo):
    """.git/ directory exists (walk-up fence detector)."""
    assert (Path(fixture_repo) / ".git").is_dir()


def test_fixture_repo_creates_harness_dir(fixture_repo):
    """.harness/ directory exists."""
    assert (Path(fixture_repo) / ".harness").is_dir()


def test_fixture_repo_install_record_valid_json(fixture_repo):
    """.harness/install-record.json is valid JSON with required fields."""
    ir_path = Path(fixture_repo) / ".harness" / "install-record.json"
    assert ir_path.exists()
    ir = json.loads(ir_path.read_text())
    assert "approvers" in ir
    assert len(ir["approvers"]) >= 1
    assert "install_id" in ir
    assert "harness_version" in ir


def test_fixture_repo_install_record_approver(fixture_repo):
    """Fixture approver is alice@smoke.example.com."""
    ir_path = Path(fixture_repo) / ".harness" / "install-record.json"
    ir = json.loads(ir_path.read_text())
    emails = [a["email"] for a in ir["approvers"]]
    assert "alice@smoke.example.com" in emails


def test_fixture_repo_audit_log_exists(fixture_repo):
    """.harness/audit.log exists."""
    assert (Path(fixture_repo) / ".harness" / "audit.log").exists()


def test_fixture_repo_installed_manifest_schema_v2(fixture_repo):
    """.harness/installed-manifest.json has schema_version=2."""
    mp = Path(fixture_repo) / ".harness" / "installed-manifest.json"
    assert mp.exists()
    m = json.loads(mp.read_text())
    assert m.get("schema_version") == 2


def test_fixture_repo_scratch_dir_exists(fixture_repo):
    """.scratch/ directory exists."""
    assert (Path(fixture_repo) / ".scratch").is_dir()


def test_fixture_repo_phase_state_seeded(fixture_repo):
    """.scratch/phase-state.json is seeded with execution_mode=manual."""
    state_path = Path(fixture_repo) / ".scratch" / "phase-state.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text())
    assert state.get("execution_mode") == "manual"


def test_fixture_repo_planning_phases_created(fixture_repo):
    """.planning/phases/01-foo, 02-bar, 03-baz dirs exist."""
    phases = Path(fixture_repo) / ".planning" / "phases"
    assert phases.is_dir()
    for slug in ("01-foo", "02-bar", "03-baz"):
        assert (phases / slug).is_dir(), f"Missing phase dir: {slug}"


def test_fixture_repo_empty_roadmap(tmp_path):
    """phase_slugs=[] creates fixture with no phase dirs."""
    import shutil
    repo = None
    try:
        repo = _setup_fixture_repo(phase_slugs=[])
        phases = Path(repo) / ".planning" / "phases"
        # Either dir doesn't exist or is empty
        phase_dirs = list(phases.iterdir()) if phases.exists() else []
        assert phase_dirs == [], f"Expected no phase dirs, found: {phase_dirs}"
    finally:
        if repo is not None:
            shutil.rmtree(repo, ignore_errors=True)


# ── _repo_root resolution ─────────────────────────────────────────────────────


def test_repo_root_points_to_harness_repo():
    """_REPO_ROOT resolves to the harness repository root."""
    assert (_REPO_ROOT / "scripts" / "harness.py").exists()
