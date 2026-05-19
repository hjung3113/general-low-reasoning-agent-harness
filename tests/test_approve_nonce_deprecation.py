"""approve-nonce mint --audience phase.approve must be a deprecation no-op."""
from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts.lib import approve_nonce_cli


def _make_args(audience: str, ttl: int = 120):
    return SimpleNamespace(audience=audience, ttl=ttl)


def test_phase_approve_audience_is_deprecated_noop(tmp_path):
    args = _make_args("phase.approve")
    stdout = io.StringIO()
    stderr = io.StringIO()

    with mock.patch.object(
        __import__("sys").stdin, "isatty", return_value=True
    ):
        rc = approve_nonce_cli.run_mint(
            args,
            nonce_dir=tmp_path,
            stdout=stdout,
            stderr=stderr,
        )

    assert rc == 0
    assert "deprecated" in stderr.getvalue().lower()
    # No nonce file written for phase.approve audience
    assert list(tmp_path.iterdir()) == []


def test_phase_approve_audience_deprecation_fires_even_without_tty(tmp_path):
    """Deprecation no-op must fire BEFORE the TTY guard so CI scripts get the right message (X6/Codex-Finding-2)."""
    args = SimpleNamespace(audience="phase.approve", ttl=120)
    stdout = io.StringIO()
    stderr = io.StringIO()
    # No TTY mock — simulate non-TTY environment (sys.stdin.isatty() returns False)
    rc = approve_nonce_cli.run_mint(
        args,
        nonce_dir=tmp_path,
        stdout=stdout,
        stderr=stderr,
    )
    assert rc == 0
    assert "deprecated" in stderr.getvalue().lower()
    assert "interactive tty" not in stderr.getvalue().lower()


def test_release_audience_still_writes_nonce(tmp_path):
    args = _make_args("release.publish")
    stdout = io.StringIO()
    stderr = io.StringIO()

    with mock.patch.object(
        __import__("sys").stdin, "isatty", return_value=True
    ):
        rc = approve_nonce_cli.run_mint(
            args,
            nonce_dir=tmp_path,
            stdout=stdout,
            stderr=stderr,
        )

    assert rc == 0
    assert "deprecated" not in stderr.getvalue().lower()
    assert len(list(tmp_path.iterdir())) >= 1
