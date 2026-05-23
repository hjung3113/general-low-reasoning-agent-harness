"""v0.7.1 P0 — runtime-dep import-guard contract.

`scripts/lib/phase_lock.py` MUST surface a SystemExit with an actionable
install instruction when the declared runtime dependency (`psutil`) is
missing, instead of letting a bare ``ModuleNotFoundError`` traceback escape.

The guard has ``# pragma: no cover`` in source because the import path
is environment-dependent — this test covers the contract by running a
fresh interpreter with the target module blocked, so future refactors
cannot silently revert the guard.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_with_blocked_module(blocked: str, target_import: str) -> subprocess.CompletedProcess:
    """Spawn a fresh Python that blocks ``blocked`` then attempts ``target_import``."""
    program = textwrap.dedent(
        f"""
        import sys
        # Install a finder that refuses imports of the blocked module BEFORE
        # the target module is imported. We use sys.modules sentinel so even
        # cached imports inside the test runner cannot leak through.
        sys.modules.pop({blocked!r}, None)
        class _Block:
            def find_spec(self, name, path=None, target=None):
                if name == {blocked!r}:
                    raise ImportError("No module named {blocked!r}")
                return None
        sys.meta_path.insert(0, _Block())
        sys.path.insert(0, {str(REPO_ROOT / "scripts")!r})
        {target_import}
        """
    )
    return subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


@pytest.mark.parametrize(
    ("blocked", "target_import"),
    [
        ("psutil", "from lib import phase_lock  # noqa: F401"),
    ],
    ids=["phase_lock-missing-psutil"],
)
def test_missing_runtime_dep_surfaces_actionable_systemexit(
    blocked: str, target_import: str
) -> None:
    result = _run_with_blocked_module(blocked, target_import)

    # SystemExit(str) → exit code 1, message on stderr (per CPython).
    assert result.returncode == 1, (
        f"expected exit 1 (SystemExit), got {result.returncode}.\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    # Contract: name the missing module, name the install command, point to README.
    assert f"missing runtime dependency '{blocked}'" in result.stderr, result.stderr
    assert "pip install -e ." in result.stderr, result.stderr
    assert "README" in result.stderr, result.stderr
    # Source-checkout breadcrumb (matches LOW-1 follow-up — same explanatory
    # line lives in both guards for consistency).
    assert "Source-checkout users" in result.stderr, result.stderr
    # Ensure we DID NOT leak the raw ModuleNotFoundError traceback as the
    # primary surface — the SystemExit message must be present at the top
    # of the error path. (The chained-cause ImportError name may still
    # appear inside the message; that's fine — we just don't want it to
    # be the ONLY thing the user sees.)
    assert "ModuleNotFoundError: No module named" not in result.stderr.splitlines()[0], (
        "first stderr line must be the actionable SystemExit message, "
        "not the raw ModuleNotFoundError traceback"
    )
