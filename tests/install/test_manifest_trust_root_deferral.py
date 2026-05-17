"""P1-1 regression pin: _build_release_manifest_v2 emits trust-root deferral warning.

Pinned so the TODO(§6 trust root, deferred to S14+) cannot silently disappear.
If this test fails it means the warning was removed — the deferred security gap
must then be re-documented or the production trust root must have been wired.

Spec: §6 (trust root from signed release tarball, not local repo source tree).
Slice: S14 review-fix (honest deferral).
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


class TestTrustRootDeferralWarning:
    """_build_release_manifest_v2 must emit a UserWarning about the trust-root gap."""

    def test_build_release_manifest_v2_emits_warning(self, tmp_path: Path) -> None:
        """Calling _build_release_manifest_v2 must emit a SECURITY warning.

        Regression pin so the TODO(§6) deferral cannot silently disappear.
        """
        from lib.upgrade import _build_release_manifest_v2  # type: ignore[import]

        # Minimal fake entries list (no files to hash — that's fine for warning check)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _build_release_manifest_v2(
                root=tmp_path,
                entries=[],
                harness_version="0.0.0-test",
            )

        warning_messages = [str(w.message) for w in caught if issubclass(w.category, UserWarning)]
        assert any("trust root" in msg.lower() or "SECURITY" in msg or "deferred" in msg.lower()
                   for msg in warning_messages), (
            "Expected a SECURITY/trust-root deferral UserWarning from "
            "_build_release_manifest_v2. If this test fails it means the warning "
            "was removed — re-document the trust-root gap or wire the production fix."
        )

    def test_build_release_manifest_v2_warning_mentions_s14(self, tmp_path: Path) -> None:
        """The warning must reference S14 or the deferred TODO to aid future tracking."""
        from lib.upgrade import _build_release_manifest_v2  # type: ignore[import]

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _build_release_manifest_v2(
                root=tmp_path,
                entries=[],
                harness_version="0.0.0-test",
            )

        all_messages = " ".join(str(w.message) for w in caught)
        assert "S14" in all_messages or "deferred" in all_messages.lower() or "tarball" in all_messages.lower(), (
            "Warning must mention S14/deferred/tarball to aid future tracking of the trust-root gap."
        )

    def test_reconcile_install_docstring_has_security_note(self) -> None:
        """reconcile_install docstring must contain the SECURITY trust-root note."""
        import inspect
        from lib.manifest_reconciler import reconcile_install  # type: ignore[import]

        src = inspect.getdoc(reconcile_install) or ""
        assert "SECURITY" in src or "trust-root" in src or "trust root" in src.lower(), (
            "reconcile_install must have a SECURITY docstring note per P1-1 fix. "
            "See manifest_reconciler.py."
        )
