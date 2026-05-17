"""User-home secret key minting and loading.

ADR ``docs/adr/2026-05-17-audit-canonicalization-locking-and-state-trust.md``
D-7. The key is a 256-bit random value used to:

  - Sign the out-of-repo audit-tip anchor (§12.1).
  - HMAC the human-presence nonce files (§3.1.1 / §12.6).

Storage:

  - POSIX: ``~/.harness/secret.key``, mode ``0o600``.
  - Windows: ``%LOCALAPPDATA%/Harness/secret.key``.

The key is NEVER written into the repo, never logged, never echoed to stdout
or stderr. ``ensure_secret_key()`` is idempotent: a key that already exists
is reused; only missing keys are minted.

If an attacker has user-account access, the key file is reachable; this is
documented out-of-scope in the design (matches the broader OS-trust
assumption). Adapter ``permissions.deny`` globs MUST cover
``~/.harness/**`` to claim ``approval_proof=supported``.
"""

from __future__ import annotations

import os
import secrets
import stat
import sys
from pathlib import Path


KEY_BYTES = 32  # 256-bit


class SecretKeyError(RuntimeError):
    """Raised when the secret key cannot be loaded or minted."""


def home_dir() -> Path:
    """Return the platform-appropriate harness home directory."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            base = str(Path.home() / "AppData" / "Local")
        return Path(base) / "Harness"
    return Path.home() / ".harness"


def secret_key_path() -> Path:
    return home_dir() / "secret.key"


def ensure_secret_key(*, mint_if_missing: bool = True) -> Path:
    """Return the path of the secret key, minting it if missing.

    Idempotent. If a key already exists, return its path without modification.

    Raises:
        SecretKeyError: if minting is disabled and the key is missing, or if
            the key exists with insecure permissions on POSIX.
    """
    path = secret_key_path()
    if path.exists():
        _check_permissions(path)
        return path

    if not mint_if_missing:
        raise SecretKeyError(
            f"secret key not found at {path}. "
            "Fix: run `harness anchor repair` to mint it."
        )

    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        # Best-effort restrict directory to user.
        try:
            os.chmod(parent, 0o700)
        except OSError:
            pass

    key = secrets.token_bytes(KEY_BYTES)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        if os.name == "nt":
            tmp.write_bytes(key)
        else:
            # O_EXCL to refuse if tmp already exists (concurrent minter race).
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            fd = os.open(str(tmp), flags, 0o600)
            try:
                os.write(fd, key)
                os.fsync(fd)
            finally:
                os.close(fd)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass

    if os.name != "nt":
        os.chmod(path, 0o600)

    return path


def load_secret_key() -> bytes:
    """Return the raw secret key bytes. Mints if missing."""
    path = ensure_secret_key()
    data = path.read_bytes()
    if len(data) != KEY_BYTES:
        raise SecretKeyError(
            f"secret key at {path} has {len(data)} bytes; expected {KEY_BYTES}. "
            "Fix: delete the file and run `harness anchor repair` (this invalidates "
            "every anchor signed with the old key)."
        )
    return data


def _check_permissions(path: Path) -> None:
    if os.name == "nt":
        return
    mode = path.stat().st_mode
    # Reject group/other readable bits.
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise SecretKeyError(
            f"secret key at {path} has insecure permissions (mode={oct(mode & 0o777)}). "
            "Fix: chmod 600 the file or delete and re-run `harness anchor repair`."
        )
