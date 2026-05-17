"""Tests for scripts.lib.secret_key (S00.7-A)."""

from __future__ import annotations

import os
import stat

import pytest

from lib import secret_key


def test_ensure_mints_and_is_idempotent(isolated_home):
    path1 = secret_key.ensure_secret_key()
    key1 = path1.read_bytes()
    assert path1.exists()
    assert len(key1) == secret_key.KEY_BYTES

    path2 = secret_key.ensure_secret_key()
    key2 = path2.read_bytes()
    assert path2 == path1
    # Idempotent: existing key is reused, not regenerated.
    assert key1 == key2


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics only")
def test_secret_key_is_0600(isolated_home):
    path = secret_key.ensure_secret_key()
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics only")
def test_loose_permissions_are_rejected(isolated_home):
    path = secret_key.ensure_secret_key()
    os.chmod(path, 0o644)
    with pytest.raises(secret_key.SecretKeyError):
        secret_key.ensure_secret_key()


def test_mint_disabled_raises_when_missing(isolated_home):
    with pytest.raises(secret_key.SecretKeyError):
        secret_key.ensure_secret_key(mint_if_missing=False)


def test_load_secret_key_returns_bytes(isolated_home):
    key = secret_key.load_secret_key()
    assert isinstance(key, bytes)
    assert len(key) == secret_key.KEY_BYTES


def test_corrupted_key_length_raises(isolated_home):
    path = secret_key.ensure_secret_key()
    path.write_bytes(b"too short")
    with pytest.raises(secret_key.SecretKeyError):
        secret_key.load_secret_key()
