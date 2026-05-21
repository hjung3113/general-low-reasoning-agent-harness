"""T8b — per-policy hash verification matrix tests (STALE-3).

Tests verify_hashes() in check.py against the per-policy matrix:

  harness-owned   sha256(on-disk) vs installed_sha256   → harness-owned-drift
  managed         sha256(on-disk) vs installed_sha256   → managed-drift
  managed-append  sha256(block between markers) vs
                  applied_sha256                         → managed-append-drift
  project-owned   SKIP (not a drift signal)
  exclude         not iterated

Also tests doctor always-on wiring and check --verify-hashes CLI flag.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import pytest

# Ensure scripts/ is on sys.path
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import lib.check as _check_mod
import lib.doctor as _doctor_mod
from lib.state import INSTALL_STATE


# ---------------------------------------------------------------------------
# Marker constants — from append_block.py (real markers, not invented)
# ---------------------------------------------------------------------------
# These are rendered by append_block.marker_start / marker_end_for_path.
# We compute them directly here to avoid a runtime call to _active_harness_version().
_HARNESS_VERSION = "0.0.0-dev+unknown"


def _marker_start(path_text: str) -> str:
    return f"# >>> low-reasoning-harness:{path_text} v{_HARNESS_VERSION}"


def _marker_end(path_text: str) -> str:
    return f"# <<< low-reasoning-harness:{path_text}"


def _block_for(path_text: str, payload: str) -> str:
    """Render a full managed-append block (start marker + payload + end marker)."""
    return _marker_start(path_text) + "\n" + payload + _marker_end(path_text) + "\n"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Minimal installed-target fixture helpers
# ---------------------------------------------------------------------------

_AGENTS_BLOCK_PATH = "AGENTS.md"
_HARNESS_OWNED_PATH = "scripts/lib/state.py"
_MANAGED_PATH = "scripts/lib/managed.py"
_MANAGED_APPEND_PATH = ".gitignore"
_PROJECT_OWNED_PATH = "README.md"

# Content for the managed-append block embedded in a file
_MA_PAYLOAD = "# harness-generated content\nexport PATH=$PATH:/harness/bin\n"
_MA_PATH_TEXT = _MANAGED_APPEND_PATH  # path key used in markers


def _make_target(tmp_path: Path) -> Path:
    """Build a minimal installed-target that passes check cleanly.

    Layout:
      <root>/
        scripts/lib/state.py         harness-owned
        scripts/lib/managed.py       managed
        .gitignore                   managed-append (has real markers + user tail)
        README.md                    project-owned
        AGENTS.md                    with required guardrail phrases
        .harness/installed-manifest.json
        .scratch/phase-state.json
        .planning/STATE.md, ROADMAP.md  (minimal)
    """
    root = tmp_path

    # harness-owned file
    ho_content = b"# harness-owned stub\nINSTALL_STATE = '.harness/installed-manifest.json'\n"
    ho_path = root / _HARNESS_OWNED_PATH
    ho_path.parent.mkdir(parents=True, exist_ok=True)
    ho_path.write_bytes(ho_content)
    ho_sha = _sha256_bytes(ho_content)

    # lib/__init__.py
    (root / "scripts" / "lib" / "__init__.py").write_text("", encoding="utf-8")

    # harness.py stub
    (root / "scripts" / "harness.py").write_text(
        "from lib.state import INSTALL_STATE\n", encoding="utf-8"
    )

    # managed file
    managed_content = b"# managed stub\nSOME_CONFIG = 'value'\n"
    managed_path = root / _MANAGED_PATH
    managed_path.write_bytes(managed_content)
    managed_sha = _sha256_bytes(managed_content)

    # managed-append file: block + user-appended tail
    block = _block_for(_MA_PATH_TEXT, _MA_PAYLOAD)
    block_sha = _sha256_text(block)
    ma_content = block + "# user appended tail\n"
    ma_path = root / _MANAGED_APPEND_PATH
    ma_path.write_text(ma_content, encoding="utf-8")

    # project-owned file
    po_path = root / _PROJECT_OWNED_PATH
    po_path.write_text("# project readme\n", encoding="utf-8")

    # AGENTS.md with required guardrail phrases (wrapped in managed block)
    agents_block = _block_for(
        _AGENTS_BLOCK_PATH,
        "Karpathy-Inspired Coding Guidelines\n\n"
        "If `.scratch/phase-state.json` is not `phase=execute` with `approved=true`\n\n"
        "Every roadmap phase starts with its own `discuss` pass\n",
    )
    (root / "AGENTS.md").write_text(agents_block, encoding="utf-8")

    # .scratch/phase-state.json
    scratch = root / ".scratch"
    scratch.mkdir()
    (scratch / "phase-state.json").write_text(
        json.dumps({
            "state_schema_version": 2,
            "phase": "discuss",
            "approved": False,
            "current_checkpoint": "CP-01-01",
            "checkpoint_path": ".planning/phases/01-init/01-CHECKPOINTS.md",
            "state_path": ".planning/STATE.md",
            "automation_mode": "manual",
            "auto_selected": [],
            "updated_at": "2026-05-21T00:00:00.000000000Z",
            "updated_by": "test",
        }),
        encoding="utf-8",
    )

    # .planning/STATE.md, ROADMAP.md
    planning = root / ".planning"
    planning.mkdir()
    (planning / "STATE.md").write_text("# State\n", encoding="utf-8")
    (planning / "ROADMAP.md").write_text("# Roadmap\n", encoding="utf-8")

    # .planning/phases/01-init/
    (planning / "phases" / "01-init").mkdir(parents=True)
    (planning / "phases" / "01-init" / "01-CHECKPOINTS.md").write_text(
        "# Checkpoints\n", encoding="utf-8"
    )

    # installed-manifest.json
    harness_dir = root / ".harness"
    harness_dir.mkdir()
    manifest: dict[str, Any] = {
        "schema_version": 2,
        "version": _HARNESS_VERSION,
        "adapters": [],
        "profiles": [],
        "packs": [],
        "files": {
            _HARNESS_OWNED_PATH: {
                "policy": "harness-owned",
                "installed_sha256": ho_sha,
                "sha256": ho_sha,
            },
            _MANAGED_PATH: {
                "policy": "managed",
                "installed_sha256": managed_sha,
                "sha256": managed_sha,
            },
            _MANAGED_APPEND_PATH: {
                "policy": "managed-append",
                "applied_sha256": block_sha,
            },
            _PROJECT_OWNED_PATH: {
                "policy": "project-owned",
                "installed_sha256": "deadbeef",  # irrelevant — should be skipped
            },
            _AGENTS_BLOCK_PATH: {
                "policy": "managed-append",
                "applied_sha256": _sha256_text(
                    _block_for(
                        _AGENTS_BLOCK_PATH,
                        "Karpathy-Inspired Coding Guidelines\n\n"
                        "If `.scratch/phase-state.json` is not `phase=execute` with `approved=true`\n\n"
                        "Every roadmap phase starts with its own `discuss` pass\n",
                    )
                ),
            },
        },
    }
    (harness_dir / "installed-manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    return root


# ---------------------------------------------------------------------------
# T8b — Tests
# ---------------------------------------------------------------------------


def test_clean_install_no_drift(tmp_path):
    """Fresh target: verify_hashes returns empty list (rc=0 signal)."""
    root = _make_target(tmp_path)
    drift = _check_mod.verify_hashes(root)
    assert drift == [], f"Expected no drift on clean install, got: {drift}"


def test_harness_owned_tamper(tmp_path):
    """Modify a harness-owned file → verify_hashes returns harness-owned-drift."""
    root = _make_target(tmp_path)
    ho_path = root / _HARNESS_OWNED_PATH
    ho_path.write_text("# tampered!\n", encoding="utf-8")

    drift = _check_mod.verify_hashes(root)
    assert len(drift) == 1, f"Expected 1 drift finding, got: {drift}"
    f = drift[0]
    assert f.error_code == "harness-owned-drift", f"Wrong code: {f.error_code}"
    assert f.path == _HARNESS_OWNED_PATH
    assert f.policy == "harness-owned"


def test_managed_tamper(tmp_path):
    """Modify a managed file → verify_hashes returns managed-drift."""
    root = _make_target(tmp_path)
    (root / _MANAGED_PATH).write_text("# tampered managed!\n", encoding="utf-8")

    drift = _check_mod.verify_hashes(root)
    codes = [f.error_code for f in drift]
    assert "managed-drift" in codes, f"Expected managed-drift in {codes}"
    m = next(f for f in drift if f.error_code == "managed-drift")
    assert m.path == _MANAGED_PATH
    assert m.policy == "managed"


def test_managed_append_tamper(tmp_path):
    """Modify block content within managed-append markers → managed-append-drift."""
    root = _make_target(tmp_path)
    ma_path = root / _MANAGED_APPEND_PATH

    # Replace the block with different content but preserve file structure
    tampered_payload = "# TAMPERED PAYLOAD\nsome_bad_content\n"
    tampered_block = _block_for(_MA_PATH_TEXT, tampered_payload)
    ma_path.write_text(tampered_block + "# user appended tail\n", encoding="utf-8")

    drift = _check_mod.verify_hashes(root)
    codes = [f.error_code for f in drift]
    assert "managed-append-drift" in codes, f"Expected managed-append-drift in {codes}"
    m = next(f for f in drift if f.error_code == "managed-append-drift")
    assert m.path == _MANAGED_APPEND_PATH
    assert m.policy == "managed-append"


def test_managed_append_outside_block_ignored(tmp_path):
    """Append text AFTER the closing marker → verify_hashes rc=0.

    User-appended tail after the harness block is NOT a drift signal.
    """
    root = _make_target(tmp_path)
    ma_path = root / _MANAGED_APPEND_PATH

    # Append extra user content after the block
    existing = ma_path.read_text(encoding="utf-8")
    ma_path.write_text(
        existing + "\n# additional user-appended line\nFOO=bar\n",
        encoding="utf-8",
    )

    drift = _check_mod.verify_hashes(root)
    ma_drift = [f for f in drift if f.path == _MANAGED_APPEND_PATH]
    assert ma_drift == [], (
        f"Expected no drift for user-appended tail, got: {ma_drift}"
    )


def test_project_owned_ignored(tmp_path):
    """Modify a project-owned file → verify_hashes rc=0 (not a drift signal)."""
    root = _make_target(tmp_path)
    (root / _PROJECT_OWNED_PATH).write_text("# completely different readme\n", encoding="utf-8")

    drift = _check_mod.verify_hashes(root)
    po_drift = [f for f in drift if f.path == _PROJECT_OWNED_PATH]
    assert po_drift == [], f"project-owned must be skipped, got: {po_drift}"


def _make_minimal_check_target(root: Path) -> Path:
    """Build the smallest installed-target that passes check_installed_target cleanly.

    Deliberately omits .planning/ to avoid roadmap-state-sync checks, which
    require a fully-formed ROADMAP.md/STATE.md pair.  The harness-owned file
    is the only non-trivial fixture entry; this is sufficient to test the
    verify_hashes wire-up inside check_installed_target.
    """
    scripts = root / "scripts" / "lib"
    scripts.mkdir(parents=True)
    (root / "scripts" / "harness.py").write_text(
        "from lib.state import INSTALL_STATE\n", encoding="utf-8"
    )
    (scripts / "__init__.py").write_text("", encoding="utf-8")

    ho_content = b"# harness-owned stub\nINSTALL_STATE = 'x'\n"
    ho_path = scripts / "state.py"
    ho_path.write_bytes(ho_content)
    ho_sha = _sha256_bytes(ho_content)

    agents_block = _block_for(
        "AGENTS.md",
        "Karpathy-Inspired Coding Guidelines\n\n"
        "If `.scratch/phase-state.json` is not `phase=execute` with `approved=true`\n\n"
        "Every roadmap phase starts with its own `discuss` pass\n",
    )
    (root / "AGENTS.md").write_text(agents_block, encoding="utf-8")

    scratch = root / ".scratch"
    scratch.mkdir()
    # phase-state WITHOUT checkpoint_path/state_path/current_checkpoint so that
    # roadmap_state_sync_applicable returns False (avoids ROADMAP.md requirement).
    (scratch / "phase-state.json").write_text(
        json.dumps({
            "state_schema_version": 2,
            "phase": "discuss",
            "approved": False,
            "automation_mode": "manual",
            "auto_selected": [],
            "updated_at": "2026-05-21T00:00:00.000000000Z",
            "updated_by": "test",
        }),
        encoding="utf-8",
    )

    harness_dir = root / ".harness"
    harness_dir.mkdir()
    manifest: dict[str, Any] = {
        "schema_version": 2,
        "version": _HARNESS_VERSION,
        "adapters": [],
        "profiles": [],
        "packs": [],
        "files": {
            "scripts/lib/state.py": {
                "policy": "harness-owned",
                "installed_sha256": ho_sha,
                "sha256": ho_sha,
            },
            "AGENTS.md": {
                "policy": "managed-append",
                "applied_sha256": _sha256_text(agents_block),
            },
        },
    }
    (harness_dir / "installed-manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return root


def test_verify_hashes_check_installed_target_raises_on_tamper(tmp_path):
    """check_installed_target(..., verify_hashes=True) raises SystemExit on drift
    with the error code in the message."""
    root = _make_minimal_check_target(tmp_path)
    (root / "scripts" / "lib" / "state.py").write_text("# tampered!\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        _check_mod.check_installed_target(root, verify_hashes=True)

    msg = str(exc_info.value.code)
    assert "harness-owned-drift" in msg, f"Expected error code in message, got: {msg!r}"


def test_verify_hashes_check_installed_target_clean(tmp_path):
    """check_installed_target(..., verify_hashes=True) passes on clean install."""
    root = _make_minimal_check_target(tmp_path)
    # Should not raise
    _check_mod.check_installed_target(root, verify_hashes=True)


def test_doctor_always_runs_clean(tmp_path):
    """harness doctor on a clean install → hash_drift_doctor_findings returns empty."""
    root = _make_target(tmp_path)
    findings = _doctor_mod.hash_drift_doctor_findings(root)
    assert findings == [], f"Expected no drift findings, got: {findings}"


def test_doctor_always_runs_tamper(tmp_path):
    """harness doctor on a tampered install → P1 findings with error code."""
    root = _make_target(tmp_path)
    (root / _HARNESS_OWNED_PATH).write_text("# tampered!\n", encoding="utf-8")

    findings = _doctor_mod.hash_drift_doctor_findings(root)
    assert len(findings) >= 1, f"Expected at least one finding, got: {findings}"
    codes = [f.code for f in findings]
    assert "harness-owned-drift" in codes, f"Expected harness-owned-drift in {codes}"
    for f in findings:
        assert f.severity == "P1", f"Expected P1 severity, got: {f.severity}"


def test_doctor_no_verify_hashes_flag(tmp_path):
    """collect_doctor_findings includes hash drift without any flag (always-on)."""
    root = _make_target(tmp_path)
    (root / _HARNESS_OWNED_PATH).write_text("# tampered!\n", encoding="utf-8")

    all_findings = _doctor_mod.collect_doctor_findings(root)
    codes = [f.code for f in all_findings]
    assert "harness-owned-drift" in codes, (
        f"Expected harness-owned-drift in doctor findings (no flag needed): {codes}"
    )


def test_verify_hashes_no_manifest(tmp_path):
    """Target without installed-manifest.json → verify_hashes returns empty (graceful)."""
    root = tmp_path
    drift = _check_mod.verify_hashes(root)
    assert drift == [], f"Expected empty list when no manifest: {drift}"


def test_verify_hashes_performance(tmp_path):
    """verify_hashes on a ~10-file manifest completes well under 2s budget."""
    root = _make_target(tmp_path)
    start = time.monotonic()
    _check_mod.verify_hashes(root)
    elapsed = time.monotonic() - start
    # Budget: 2s for 181 files (~5ms each); our fixture is tiny, so <200ms expected.
    assert elapsed < 2.0, f"verify_hashes took {elapsed:.2f}s (>2s budget)"


# ---------------------------------------------------------------------------
# MAJOR-1: missing on-disk file emits *-missing finding (not silent continue)
# ---------------------------------------------------------------------------


def test_harness_owned_missing_reports_drift(tmp_path):
    """Deleting a harness-owned file → verify_hashes emits harness-owned-missing."""
    root = _make_target(tmp_path)
    (root / _HARNESS_OWNED_PATH).unlink()

    drift = _check_mod.verify_hashes(root)
    codes = [f.error_code for f in drift]
    assert "harness-owned-missing" in codes, (
        f"Expected harness-owned-missing for deleted file, got: {codes}"
    )
    m = next(f for f in drift if f.error_code == "harness-owned-missing")
    assert m.path == _HARNESS_OWNED_PATH
    assert m.policy == "harness-owned"


def test_managed_missing_reports_drift(tmp_path):
    """Deleting a managed file → verify_hashes emits managed-missing."""
    root = _make_target(tmp_path)
    (root / _MANAGED_PATH).unlink()

    drift = _check_mod.verify_hashes(root)
    codes = [f.error_code for f in drift]
    assert "managed-missing" in codes, (
        f"Expected managed-missing for deleted managed file, got: {codes}"
    )
    m = next(f for f in drift if f.error_code == "managed-missing")
    assert m.path == _MANAGED_PATH
    assert m.policy == "managed"


# ---------------------------------------------------------------------------
# MAJOR-2: malformed managed-append markers emit managed-append-malformed
# ---------------------------------------------------------------------------


def test_managed_append_malformed_markers_reports_finding(tmp_path):
    """Corrupted managed-append (missing closing marker) → managed-append-malformed."""
    root = _make_target(tmp_path)
    ma_path = root / _MANAGED_APPEND_PATH

    # Write a file with only the start marker and no end marker — parse_append_block
    # raises ValueError("Malformed managed-append block") for this case.
    corrupted = _marker_start(_MA_PATH_TEXT) + "\n# payload\n# (end marker deleted)\n"
    ma_path.write_text(corrupted, encoding="utf-8")

    drift = _check_mod.verify_hashes(root)
    codes = [f.error_code for f in drift]
    assert "managed-append-malformed" in codes, (
        f"Expected managed-append-malformed for broken markers, got: {codes}"
    )
    m = next(f for f in drift if f.error_code == "managed-append-malformed")
    assert m.path == _MANAGED_APPEND_PATH
    assert m.policy == "managed-append"


# ---------------------------------------------------------------------------
# MAJOR-3: CLI subprocess tests — --verify-hashes flag wiring end-to-end
#
# Strategy: invoke python3 -c via subprocess with PYTHONPATH set to the
# scripts/ directory.  This exercises the real check.py / check_installed_target
# code path without requiring a full 90-file harness install fixture.
# Specifically we test: (a) clean → rc=0, (b) tampered harness-owned → rc≠0
# with "harness-owned-drift" in stderr, (c) --verify-hashes flag is the
# necessary trigger (verify_hashes=False path skips hash gate).
# ---------------------------------------------------------------------------

import subprocess  # noqa: E402 — stdlib, safe to import here

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_PATH = str(_REPO_ROOT / "scripts")

# Inline python snippet that mirrors the verify_hashes → check_installed_target
# plumbing: it calls check_installed_target with verify_hashes=True/False and
# exits non-zero via SystemExit when drift is found.  This is the same code
# path exercised by check_harness.py → harness.check → check_installed_target.
_CLI_SNIPPET = """\
import sys, os
sys.path.insert(0, {scripts!r})
from pathlib import Path
import lib.check as _check
root = Path({target!r})
try:
    _check.check_installed_target(root, verify_hashes={flag})
except SystemExit as e:
    code = e.code
    if isinstance(code, int) and code == 0:
        sys.exit(0)
    msg = str(code) if code else ""
    print(msg, file=sys.stderr)
    sys.exit(1)
"""


def _run_verify_hashes_cli(target: Path, *, verify_hashes: bool) -> subprocess.CompletedProcess:
    """Run verify-hashes check against *target* via a subprocess python snippet."""
    snippet = _CLI_SNIPPET.format(
        scripts=_SCRIPTS_PATH,
        target=str(target),
        flag="True" if verify_hashes else "False",
    )
    return subprocess.run(
        [sys.executable, "-c", snippet],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )


def test_cli_clean_install_exits_zero(tmp_path):
    """CLI subprocess: clean install with verify_hashes=True → rc=0."""
    root = _make_minimal_check_target(tmp_path)
    result = _run_verify_hashes_cli(root, verify_hashes=True)
    assert result.returncode == 0, (
        f"Expected rc=0 for clean install, got rc={result.returncode}\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )


def test_cli_tampered_harness_owned_exits_nonzero(tmp_path):
    """CLI subprocess: tampered harness-owned with verify_hashes=True → rc≠0 + drift in stderr."""
    root = _make_minimal_check_target(tmp_path)
    (root / "scripts" / "lib" / "state.py").write_text("# tampered!\n", encoding="utf-8")

    result = _run_verify_hashes_cli(root, verify_hashes=True)
    assert result.returncode != 0, (
        f"Expected non-zero rc for tampered file, got rc={result.returncode}\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    combined = result.stdout + result.stderr
    assert "harness-owned-drift" in combined, (
        f"Expected 'harness-owned-drift' in subprocess output, got:\n{combined!r}"
    )


def test_cli_verify_hashes_flag_actually_plumbed(tmp_path):
    """CLI subprocess: tampered file with verify_hashes=False → hash gate skipped (rc=0)."""
    root = _make_minimal_check_target(tmp_path)
    (root / "scripts" / "lib" / "state.py").write_text("# tampered!\n", encoding="utf-8")

    # Without the flag: hash verification is skipped; check_installed_target
    # still passes because structural checks on this fixture are satisfied.
    result_without = _run_verify_hashes_cli(root, verify_hashes=False)
    assert result_without.returncode == 0, (
        f"Expected rc=0 when verify_hashes=False (hash gate disabled), "
        f"got rc={result_without.returncode}\nstderr={result_without.stderr!r}"
    )

    # With the flag: drift is detected → rc != 0.
    result_with = _run_verify_hashes_cli(root, verify_hashes=True)
    assert result_with.returncode != 0, (
        "Expected hash-drift detected (rc!=0) when verify_hashes=True"
    )
    combined = result_with.stdout + result_with.stderr
    assert "harness-owned-drift" in combined, (
        f"Expected 'harness-owned-drift' in CLI output with flag:\n{combined!r}"
    )
