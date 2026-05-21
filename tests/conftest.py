"""Top-level conftest for the harness test suite.

Autouse fixtures that apply to ALL tests across ALL subdirectories.
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest


@pytest.fixture(autouse=True)
def _isolate_autopilot_network_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent run_start's HARNESS_AUTOPILOT_NETWORK mutation from leaking across tests.

    run_start() calls ``os.environ["HARNESS_AUTOPILOT_NETWORK"] = "deny"`` (or "allow")
    as a side effect. Without isolation this mutation persists into subsequent tests
    in the same process, causing false passes/failures depending on test ordering.

    This fixture unconditionally removes the env var before (and after, via monkeypatch
    teardown) every test so each test starts from a clean slate.
    """
    monkeypatch.delenv("HARNESS_AUTOPILOT_NETWORK", raising=False)
    yield


@pytest.fixture(scope="session")
def v094_fixtures(tmp_path_factory):
    """Session-scoped fixture: ensure v0.9.4 tarballs exist, building them if absent.

    Returns a dict with keys ``"clean"`` and ``"workaround"`` pointing to
    ``pathlib.Path`` objects for the respective ``.tar.gz`` files.

    CI always rebuilds (idempotent script); the tarballs are gitignored.
    Only the .sha256 pin files are checked-in.
    """
    out_dir = pathlib.Path(__file__).parent / "fixtures"
    clean = out_dir / "v094-clean.tar.gz"
    workaround = out_dir / "v094-with-workaround.tar.gz"
    if not (clean.exists() and workaround.exists()):
        subprocess.run(
            ["python3", "scripts/build_v094_fixture.py", "--output-dir", str(out_dir)],
            check=True,
            cwd=pathlib.Path(__file__).parent.parent,
        )
    return {"clean": clean, "workaround": workaround}
