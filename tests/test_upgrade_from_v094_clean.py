"""T15 — Upgrade-compat: clean v0.9.4 → v0.9.5.

Restores the v094-clean.tar.gz fixture (vanilla v0.9.4 install, 35 lib
modules absent from manifest per BUG-1) into a scratch directory, then runs
`harness upgrade --adopt-existing --force` from current (v0.9.5) source.

Assertions:
  (a) Upgrade succeeds (rc=0)
  (b) `release.trust.rechained` audit row present (T16) with
      cause=v094_manifest_gap_remediation when a prior manifest existed
  (c) Post-upgrade `harness check` rc=0
  (d) Post-upgrade `harness check --verify-hashes` rc=0
  (e) Lifecycle single transition (discuss → plan) works post-upgrade
  (f) Audit chain hash chains (each row's previous_entry_hash references prior)

Sources:
  /tmp/v095-PLAN.md REV-2 §2 success criteria + §5 risk table
  /tmp/v095-IMPL.md REV-4 T15, T16
  /tmp/v095-IMPL-review-codex.md M-9

Smoke contract (tests/SMOKE_CONTRACT.md):
  subprocess.run(..., capture_output=True, text=True)
  rc asserted on every subprocess call
  HARNESS_SMOKE_TEST=1 + HARNESS_SMOKE_BYPASS_SPEED_BUMP=1 ONLY for approve
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
HARNESS_PY = str(SCRIPTS_DIR / "harness.py")
_PYTHON = sys.executable

APPROVER_EMAIL = "upgrade-test@example.com"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(
    *args: str,
    cwd: str | None = None,
    env: dict | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = [_PYTHON, HARNESS_PY, *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd or str(REPO_ROOT),
        env=env if env is not None else dict(os.environ),
    )


def _approve_env() -> dict:
    """Env for phase approve subprocess only (codex M-9)."""
    return {
        **os.environ,
        "HARNESS_SMOKE_TEST": "1",
        "HARNESS_SMOKE_BYPASS_SPEED_BUMP": "1",
    }


def _upgrade_env() -> dict:
    """Env for upgrade subprocess — unsigned dev allowed for local tests."""
    return {
        **os.environ,
        "HARNESS_ALLOW_UNSIGNED_DEV": "1",
    }


def _extract_fixture(tarball: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball) as tf:
        tf.extractall(dest)


def _read_audit_rows(target: Path) -> list[dict[str, Any]]:
    audit_path = target / ".harness" / "audit.log"
    if not audit_path.exists():
        return []
    rows = []
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


# ===========================================================================
# Fixture
# ===========================================================================


@pytest.fixture
def v094_clean_target(tmp_path: Path, v094_fixtures) -> Path:
    """Extracted v094-clean fixture; includes real .harness/installed-manifest.json from tarball."""
    extract_dir = tmp_path / "target"
    _extract_fixture(v094_fixtures["clean"], extract_dir)
    # T8: assert the real manifest is present (no synthetic seed needed)
    assert (extract_dir / ".harness" / "installed-manifest.json").exists(), (
        "v094-clean.tar.gz must contain .harness/installed-manifest.json; "
        "regenerate with scripts/build_v094_fixture.py"
    )
    return extract_dir


# ===========================================================================
# Tests
# ===========================================================================


class TestUpgradeFromV094Clean:
    def test_upgrade_succeeds_rc0(self, v094_clean_target: Path) -> None:
        """Upgrade from v0.9.4 clean fixture succeeds with rc=0."""
        result = _run(
            "upgrade",
            "--target", str(v094_clean_target),
            "--adopt-existing",
            "--force",
            env=_upgrade_env(),
        )
        assert result.returncode == 0, (
            f"upgrade must exit 0.\nstdout={result.stdout}\nstderr={result.stderr}"
        )

    def test_release_trust_rechained_audit_row_present(
        self, v094_clean_target: Path
    ) -> None:
        """release.trust.rechained audit row present after upgrade from v0.9.4."""
        result = _run(
            "upgrade",
            "--target", str(v094_clean_target),
            "--adopt-existing",
            "--force",
            env=_upgrade_env(),
        )
        assert result.returncode == 0, (
            f"upgrade must exit 0.\nstdout={result.stdout}\nstderr={result.stderr}"
        )

        rows = _read_audit_rows(v094_clean_target)
        rechain_rows = [r for r in rows if r.get("verb") == "release.trust.rechained"]
        assert len(rechain_rows) >= 1, (
            f"Expected release.trust.rechained audit row after v0.9.4 → v0.9.5 upgrade.\n"
            f"Audit verbs: {[r.get('verb') for r in rows]}"
        )

        row = rechain_rows[0]
        args = row.get("args", {})
        assert "cause" in args, f"rechain row must have cause field: {row}"
        # cause MUST be v094_manifest_gap_remediation (35 lib modules added).
        # Plan §2 success criterion 10 mandates this classification when the
        # v0.9.4 manifest gap is detected.  Accepting manifest_evolution would
        # allow a silent regression where the upgrade misclassifies the
        # v0.9.4 → v0.9.5 transition (MAJOR-1 adversarial-review fix).
        assert args["cause"] == "v094_manifest_gap_remediation", (
            f"Expected cause=v094_manifest_gap_remediation (35 lib modules "
            f"added in v0.9.5); got {args['cause']!r}"
        )

    def test_rechained_row_has_chain_fields(self, v094_clean_target: Path) -> None:
        """release.trust.rechained row has standard chain fields (T16 contract)."""
        result = _run(
            "upgrade",
            "--target", str(v094_clean_target),
            "--adopt-existing",
            "--force",
            env=_upgrade_env(),
        )
        assert result.returncode == 0, (
            f"upgrade must exit 0.\nstdout={result.stdout}\nstderr={result.stderr}"
        )

        rows = _read_audit_rows(v094_clean_target)
        rechain_rows = [r for r in rows if r.get("verb") == "release.trust.rechained"]
        assert len(rechain_rows) >= 1, "Expected rechain row"

        row = rechain_rows[0]
        args = row.get("args", {})
        assert "previous_chain_hash" in args, f"Missing previous_chain_hash: {row}"
        assert "new_chain_hash" in args, f"Missing new_chain_hash: {row}"
        assert args["previous_chain_hash"] != args["new_chain_hash"], (
            "previous and new chain hashes must differ"
        )

    def test_post_upgrade_check_rc0(self, v094_clean_target: Path) -> None:
        """harness check rc=0 after v0.9.4 → v0.9.5 upgrade."""
        rc = _run(
            "upgrade",
            "--target", str(v094_clean_target),
            "--adopt-existing",
            "--force",
            env=_upgrade_env(),
        ).returncode
        assert rc == 0, "upgrade must exit 0"

        result = _run("check", cwd=str(v094_clean_target))
        assert result.returncode == 0, (
            f"harness check must exit 0 post-upgrade.\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )

    def test_post_upgrade_check_verify_hashes_rc0(
        self, v094_clean_target: Path
    ) -> None:
        """harness check --verify-hashes rc=0 after upgrade."""
        rc = _run(
            "upgrade",
            "--target", str(v094_clean_target),
            "--adopt-existing",
            "--force",
            env=_upgrade_env(),
        ).returncode
        assert rc == 0, "upgrade must exit 0"

        result = _run("check", "--verify-hashes", cwd=str(v094_clean_target))
        assert result.returncode == 0, (
            f"harness check --verify-hashes must exit 0 post-upgrade.\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )

    def test_lifecycle_works_post_upgrade(self, v094_clean_target: Path) -> None:
        """Single lifecycle transition (discuss → plan) works after upgrade."""
        rc = _run(
            "upgrade",
            "--target", str(v094_clean_target),
            "--adopt-existing",
            "--force",
            env=_upgrade_env(),
        ).returncode
        assert rc == 0, "upgrade must exit 0"

        # Add an install-record so phase approve works
        harness_dir = v094_clean_target / ".harness"
        install_record = {
            "harness_version": "v0.9.5",
            "installed_at": "2026-05-21T00:00:00Z",
            "approvers": [
                {
                    "email": APPROVER_EMAIL,
                    "added_at": "2026-05-21T00:00:00Z",
                    "source": "test_fixture",
                }
            ],
            "schema_version": 1,
        }
        (harness_dir / "install-record.json").write_text(
            json.dumps(install_record, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        result = _run(
            "phase", "set", "plan",
            "--plan-id", "post-upgrade-smoke",
            cwd=str(v094_clean_target),
        )
        assert result.returncode == 0, (
            f"phase set plan must exit 0 post-upgrade.\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )

        state_path = v094_clean_target / ".scratch" / "phase-state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert state["phase"] == "plan", (
            f"Expected plan phase post-upgrade, got {state['phase']}"
        )

    def test_audit_chain_continues_post_upgrade(
        self, v094_clean_target: Path
    ) -> None:
        """Audit rows after upgrade chain correctly (previous_entry_hash linkage)."""
        result = _run(
            "upgrade",
            "--target", str(v094_clean_target),
            "--adopt-existing",
            "--force",
            env=_upgrade_env(),
        )
        assert result.returncode == 0, (
            f"upgrade must exit 0.\nstdout={result.stdout}\nstderr={result.stderr}"
        )

        rows = _read_audit_rows(v094_clean_target)
        # MAJOR-3 fix: early-return silently passed on broken state.
        # Replace the guard with an explicit failure so missing rows are
        # never hidden.  The upgrade emits at minimum a release.trust.rechained
        # row; if the audit log is empty the implementation has regressed.
        assert len(rows) >= 1, (
            f"Expected ≥1 audit rows post-upgrade (at minimum release.trust.rechained), "
            f"got 0 — audit log is missing entirely"
        )
        # Chain linkage verification is only possible with ≥2 rows.
        # Assert the condition explicitly so a regression that drops to 0 rows
        # is caught by the assertion above, not silently skipped here.
        if len(rows) < 2:
            # Only 1 row present (release.trust.rechained) — chain linkage
            # cannot be verified but the row's existence is already asserted.
            verbs = [r.get("verb") for r in rows]
            assert "release.trust.rechained" in verbs, (
                f"Only 1 audit row but it is not release.trust.rechained: {verbs}"
            )
            return

        # Verify chain: each row's previous_entry_hash should match prior row's entry_hash
        for i in range(1, len(rows)):
            prev_row = rows[i - 1]
            curr_row = rows[i]
            prev_hash = prev_row.get("entry_hash")
            curr_prev_hash = curr_row.get("previous_entry_hash")
            if prev_hash and curr_prev_hash:
                assert prev_hash == curr_prev_hash, (
                    f"Audit chain broken at row {i}: "
                    f"row[{i-1}].entry_hash={prev_hash} != "
                    f"row[{i}].previous_entry_hash={curr_prev_hash}"
                )
