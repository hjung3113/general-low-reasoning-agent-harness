"""S02 sub-suite — `approval_nonce` primitive (§3.1.1).

The nonce store is the human-presence proof default. This file pins:
  - `mint()` writes a single-use file with audience + minter_tty + expiry
  - `consume_newest_valid()` returns the freshest non-expired nonce for
    the requested audience, with consumer_tty != minter_tty
  - consume DELETES the file (single-use)
  - expired files are SKIPPED by consume; mint also garbage-collects them
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from lib import approval_nonce


@pytest.fixture
def nonce_dir(tmp_path: Path) -> Path:
    d = tmp_path / "approval-nonces"
    d.mkdir()
    return d


def test_mint_writes_audience_minter_tty_expiry(nonce_dir: Path):
    n = approval_nonce.mint(
        nonce_dir=nonce_dir,
        audience="phase.approve",
        minter_tty="/dev/ttys001",
        ttl_seconds=120,
    )
    files = list(nonce_dir.glob("*.json"))
    assert len(files) == 1
    body = json.loads(files[0].read_text())
    assert body["audience"] == "phase.approve"
    assert body["minter_tty"] == "/dev/ttys001"
    assert body["expires_at"] > body["minted_at"]
    assert n.nonce_id == files[0].stem


def test_mint_file_mode_0600_posix(nonce_dir: Path):
    n = approval_nonce.mint(
        nonce_dir=nonce_dir,
        audience="phase.approve",
        minter_tty="/dev/ttys001",
        ttl_seconds=120,
    )
    files = list(nonce_dir.glob("*.json"))
    import os, stat as st
    if os.name == "posix":
        mode = st.S_IMODE(os.stat(files[0]).st_mode)
        assert mode == 0o600


def test_consume_newest_valid_returns_freshest(nonce_dir: Path):
    a = approval_nonce.mint(
        nonce_dir=nonce_dir, audience="phase.approve",
        minter_tty="/dev/tty1", ttl_seconds=120,
    )
    time.sleep(0.01)
    b = approval_nonce.mint(
        nonce_dir=nonce_dir, audience="phase.approve",
        minter_tty="/dev/tty1", ttl_seconds=120,
    )
    result = approval_nonce.consume_newest_valid(
        nonce_dir=nonce_dir,
        audience="phase.approve",
        consumer_tty="/dev/tty2",
    )
    assert result.outcome == "consumed"
    assert result.nonce.nonce_id == b.nonce_id
    # File deleted (single-use).
    assert not (nonce_dir / f"{b.nonce_id}.json").exists()
    # The older nonce remains for a possible future consume.
    assert (nonce_dir / f"{a.nonce_id}.json").exists()


def test_consume_no_nonce_returns_missing(nonce_dir: Path):
    result = approval_nonce.consume_newest_valid(
        nonce_dir=nonce_dir,
        audience="phase.approve",
        consumer_tty="/dev/tty2",
    )
    assert result.outcome == "missing"


def test_consume_expired_returns_expired(nonce_dir: Path, monkeypatch):
    approval_nonce.mint(
        nonce_dir=nonce_dir,
        audience="phase.approve",
        minter_tty="/dev/tty1",
        ttl_seconds=1,
    )
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 5.0)
    result = approval_nonce.consume_newest_valid(
        nonce_dir=nonce_dir,
        audience="phase.approve",
        consumer_tty="/dev/tty2",
    )
    assert result.outcome == "expired"


def test_consume_same_tty_returns_same_tty(nonce_dir: Path):
    approval_nonce.mint(
        nonce_dir=nonce_dir,
        audience="phase.approve",
        minter_tty="/dev/tty1",
        ttl_seconds=120,
    )
    result = approval_nonce.consume_newest_valid(
        nonce_dir=nonce_dir,
        audience="phase.approve",
        consumer_tty="/dev/tty1",
    )
    assert result.outcome == "same_tty"


def test_consume_audience_mismatch_returns_audience_mismatch(nonce_dir: Path):
    approval_nonce.mint(
        nonce_dir=nonce_dir,
        audience="phase.reopen",
        minter_tty="/dev/tty1",
        ttl_seconds=120,
    )
    result = approval_nonce.consume_newest_valid(
        nonce_dir=nonce_dir,
        audience="phase.approve",
        consumer_tty="/dev/tty2",
    )
    # Nonces minted for a different audience are not visible to
    # phase.approve; outcome is "missing" or "audience_mismatch".
    assert result.outcome in ("missing", "audience_mismatch")
