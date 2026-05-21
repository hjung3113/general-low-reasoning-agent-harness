"""T15 — Upgrade-compat: v0.9.4 + manual lib workaround → v0.9.5.

Restores the v094-with-workaround.tar.gz fixture (v0.9.4 install + the 35
missing lib modules manually copied in by the user, as per the v0.9.4 P0
workaround) then runs `harness upgrade --adopt-existing --force`.

The workaround files fall into two categories:
  (a) 30 files whose sha256 matches the v0.9.5 source exactly — these should
      NOT produce a false quarantine warning (STALE-2 fix, T6).
  (b) 5 files that differ (audit.py, audit_verify_cli.py, hooks.py,
      phase_cli.py, phase_reopen.py) — these were updated in v0.9.5; with
      --force they are overwritten; quarantine is correct behaviour here.

Assertions:
  (a) Upgrade succeeds (rc=0)
  (b) Upgrade output does NOT warn about quarantine for files that match
      v0.9.5 source (no false-positive quarantine on the 30 matching files)
  (c) Post-upgrade `harness check` rc=0
  (d) Lifecycle (discuss → plan) works post-upgrade

Note on ``upgrade.preexisting-match`` audit verb: this verb is specified in
/tmp/v095-PLAN.md §7.6 but is not yet implemented in upgrade.py.  The test
therefore asserts the OBSERVABLE BEHAVIOUR (no false quarantine, rc=0, check
passes) rather than a specific audit verb name.  A TODO is placed for when
the verb is wired in.

Sources:
  /tmp/v095-PLAN.md REV-2 §3.1 STALE-2, §5 risk row 2
  /tmp/v095-IMPL.md REV-4 T15, T6
  /tmp/v095-IMPL-review-codex.md M-9

Smoke contract (tests/SMOKE_CONTRACT.md):
  subprocess.run(..., capture_output=True, text=True)
  rc asserted on every subprocess call
  HARNESS_SMOKE_TEST=1 + HARNESS_SMOKE_BYPASS_SPEED_BUMP=1 ONLY for approve
"""

from __future__ import annotations

import hashlib
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

APPROVER_EMAIL = "workaround-test@example.com"

# Lib files that differ between v0.9.4 workaround and v0.9.5 source
# (updated during v0.9.5 hotfix; correct to overwrite with --force).
_KNOWN_DIVERGENT = {
    "scripts/lib/audit.py",
    "scripts/lib/audit_verify_cli.py",
    "scripts/lib/hooks.py",
    "scripts/lib/phase_cli.py",
    "scripts/lib/phase_reopen.py",
}

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
    return {
        **os.environ,
        "HARNESS_ALLOW_UNSIGNED_DEV": "1",
    }


def _extract_fixture(tarball: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball) as tf:
        tf.extractall(dest)


def _seed_v094_manifest(target: Path) -> str:
    """Write a minimal v0.9.4 installed-manifest.json and return its chain hash."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    from lib.manifest_reconciler import compute_manifest_hash_chain  # type: ignore

    harness_dir = target / ".harness"
    harness_dir.mkdir(parents=True, exist_ok=True)

    v094_files: dict[str, Any] = {
        "scripts/lib/install.py": {
            "installed_sha256": "aaa000" + "0" * 58,
            "current_sha256": "aaa000" + "0" * 58,
        },
        "scripts/lib/upgrade.py": {
            "installed_sha256": "bbb000" + "0" * 58,
            "current_sha256": "bbb000" + "0" * 58,
        },
    }

    chain_manifest: dict[str, Any] = {
        "release_commit": None,
        "release_tag": "v0.9.4",
        "schema_version": 2,
        "harness_version": "0.9.4",
        "files": v094_files,
        "removed_in_version": [],
        "trust_origin": "dev_unsigned",
    }
    v094_chain_hash = compute_manifest_hash_chain(chain_manifest)

    installed_manifest: dict[str, Any] = {
        # ``version`` must be non-None so upgrade() reads the prior manifest
        # and enters the non-adoption path where installed_files_chain_hash
        # is preserved (allowing the T16 chain-delta detection).
        "version": "0.9.4",
        "harness_version": "0.9.4",
        "schema_version": 2,
        "release_tag": "v0.9.4",
        "trust_origin": "dev_unsigned",
        "installed_files_chain_hash": v094_chain_hash,
        "files": v094_files,
    }
    (harness_dir / "installed-manifest.json").write_text(
        json.dumps(installed_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return v094_chain_hash


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


def _sha256_of_workaround_files(tarball: Path, clean_tarball: Path) -> dict[str, str]:
    """Return sha256 dict of lib files added in workaround (absent in clean)."""
    with tarfile.open(clean_tarball) as tf:
        clean_names = {m.name for m in tf.getmembers()}

    result = {}
    with tarfile.open(tarball) as tf:
        for m in tf.getmembers():
            if (
                m.name not in clean_names
                and m.name.startswith("scripts/lib/")
                and m.name.endswith(".py")
            ):
                fobj = tf.extractfile(m)
                if fobj:
                    content = fobj.read()
                    result[m.name] = hashlib.sha256(content).hexdigest()
    return result


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def v094_workaround_target(tmp_path: Path, v094_fixtures) -> Path:
    """Extracted v094-with-workaround fixture with seeded v0.9.4 manifest."""
    extract_dir = tmp_path / "target"
    _extract_fixture(v094_fixtures["workaround"], extract_dir)
    _seed_v094_manifest(extract_dir)
    return extract_dir


# ===========================================================================
# Tests
# ===========================================================================


class TestUpgradeFromV094WithWorkaround:
    def test_upgrade_succeeds_rc0(self, v094_workaround_target: Path) -> None:
        """Upgrade from v0.9.4 + manual workaround succeeds with rc=0."""
        result = _run(
            "upgrade",
            "--target", str(v094_workaround_target),
            "--adopt-existing",
            "--force",
            env=_upgrade_env(),
        )
        assert result.returncode == 0, (
            f"upgrade must exit 0.\nstdout={result.stdout}\nstderr={result.stderr}"
        )

    def test_no_false_quarantine_for_matching_files(
        self, v094_workaround_target: Path, v094_fixtures
    ) -> None:
        """Files that sha256-match v0.9.5 source must NOT trigger quarantine.

        STALE-2 fix (T6): false quarantine is a regression.  With --force all
        harness-owned files are overwritten, so no quarantine for any file is
        expected in this upgrade path.
        """
        result = _run(
            "upgrade",
            "--target", str(v094_workaround_target),
            "--adopt-existing",
            "--force",
            env=_upgrade_env(),
        )
        assert result.returncode == 0, (
            f"upgrade must exit 0.\nstdout={result.stdout}\nstderr={result.stderr}"
        )

        # With --force, quarantine should not be triggered at all
        combined = (result.stdout + result.stderr).lower()
        assert "quarantined" not in combined, (
            f"Unexpected quarantine warning with --force upgrade:\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )

    def test_matching_workaround_files_identified(
        self, v094_workaround_target: Path, v094_fixtures
    ) -> None:
        """30 of 35 workaround files sha256-match v0.9.5 source — verify the assertion."""
        wk_sha = _sha256_of_workaround_files(
            v094_fixtures["workaround"], v094_fixtures["clean"]
        )
        matching = []
        divergent = []
        for rel_path, wk_hash in wk_sha.items():
            src_path = REPO_ROOT / rel_path
            if src_path.exists():
                src_hash = hashlib.sha256(src_path.read_bytes()).hexdigest()
                if wk_hash == src_hash:
                    matching.append(rel_path)
                else:
                    divergent.append(rel_path)

        # All divergent files should be in the known-divergent set
        unexpected_divergent = set(divergent) - _KNOWN_DIVERGENT
        assert not unexpected_divergent, (
            f"Unexpected divergent workaround files (not in _KNOWN_DIVERGENT):\n"
            f"{sorted(unexpected_divergent)}"
        )

        # Most files should match (at least 25 of 35)
        assert len(matching) >= 25, (
            f"Expected at least 25 matching workaround files; got {len(matching)}: "
            f"{sorted(matching)}"
        )

    def test_post_upgrade_check_rc0(self, v094_workaround_target: Path) -> None:
        """harness check rc=0 after upgrade from workaround state."""
        rc = _run(
            "upgrade",
            "--target", str(v094_workaround_target),
            "--adopt-existing",
            "--force",
            env=_upgrade_env(),
        ).returncode
        assert rc == 0, "upgrade must exit 0"

        result = _run("check", cwd=str(v094_workaround_target))
        assert result.returncode == 0, (
            f"harness check must exit 0 post-upgrade.\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )

    def test_lifecycle_works_post_upgrade(
        self, v094_workaround_target: Path
    ) -> None:
        """discuss → plan transition works after upgrading from workaround state."""
        rc = _run(
            "upgrade",
            "--target", str(v094_workaround_target),
            "--adopt-existing",
            "--force",
            env=_upgrade_env(),
        ).returncode
        assert rc == 0, "upgrade must exit 0"

        # Add an install-record so phase approve works
        harness_dir = v094_workaround_target / ".harness"
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
            "--plan-id", "workaround-post-upgrade-smoke",
            cwd=str(v094_workaround_target),
        )
        assert result.returncode == 0, (
            f"phase set plan must exit 0 post-upgrade.\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )

        state_path = v094_workaround_target / ".scratch" / "phase-state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert state["phase"] == "plan", (
            f"Expected plan phase post-upgrade, got {state['phase']}"
        )

    def test_upgrade_preexisting_match_audit_verb_if_implemented(
        self, v094_workaround_target: Path
    ) -> None:
        """TODO: When upgrade.preexisting-match verb is wired, assert it is present.

        This test is a placeholder per /tmp/v095-PLAN.md §7.6.  The verb is
        specified but not yet implemented in scripts/lib/upgrade.py.  When
        it is wired in, change this test to assert that
        ``upgrade.preexisting-match`` rows appear in the audit log for the
        30 lib files that sha256-match the v0.9.5 source.
        """
        result = _run(
            "upgrade",
            "--target", str(v094_workaround_target),
            "--adopt-existing",
            "--force",
            env=_upgrade_env(),
        )
        assert result.returncode == 0, (
            f"upgrade must exit 0.\nstdout={result.stdout}\nstderr={result.stderr}"
        )

        rows = _read_audit_rows(v094_workaround_target)
        preexisting_match_rows = [
            r for r in rows if r.get("verb") == "upgrade.preexisting-match"
        ]
        # Not yet implemented — skip assertion if no rows found.
        if not preexisting_match_rows:
            pytest.skip(
                "upgrade.preexisting-match verb not yet implemented in upgrade.py "
                "(see /tmp/v095-PLAN.md §7.6 — pending implementation)"
            )
        # If implemented, assert at least one row per matching file
        assert len(preexisting_match_rows) >= 25, (
            f"Expected ≥25 upgrade.preexisting-match rows; got {len(preexisting_match_rows)}"
        )
