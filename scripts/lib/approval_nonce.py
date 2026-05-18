"""Out-of-project approval nonce store (design §3.1.1).

The harness's default human-presence proof is a single-use nonce written
by `harness approve-nonce mint` into a directory OUTSIDE any project
root (POSIX: ``~/.harness/approval-nonces/``; Windows:
``%LOCALAPPDATA%/Harness/approval-nonces/``). The nonce is consumed by
`harness phase approve` and other TTY-only verbs; project-scoped agent
file tools cannot read it.

This module exposes the in-process primitives — file paths and store
location are passed in by callers so tests inject a `tmp_path`-rooted
fixture directory rather than touching the real `~/.harness`.

Public surface
--------------
    Nonce                  -- dataclass(nonce_id, audience, minter_tty,
                                       minted_at, expires_at)
    ConsumeResult          -- dataclass(outcome, nonce|None)
                              outcome ∈ {"consumed", "missing", "expired",
                                         "same_tty", "audience_mismatch",
                                         "signature_invalid"}
    mint(nonce_dir, *, audience, minter_tty, ttl_seconds,
         secret_key) -> Nonce
    consume_newest_valid(nonce_dir, *, audience, consumer_tty,
                         secret_key) -> ConsumeResult
    default_nonce_dir() -> Path
    default_secret_key_path() -> Path
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from typing import Optional

# Conditionally import platform-specific locking primitives.
if os.name == "posix":
    import fcntl as _fcntl
else:
    try:
        import msvcrt as _msvcrt  # type: ignore[import]
    except ImportError:
        _msvcrt = None  # type: ignore[assignment]


@dataclasses.dataclass(frozen=True)
class Nonce:
    nonce_id: str
    audience: str
    minter_tty: str
    minted_at: float
    expires_at: float


@dataclasses.dataclass(frozen=True)
class ConsumeResult:
    outcome: str  # "consumed" | "missing" | "expired" | "same_tty" | "audience_mismatch" | "signature_invalid"
    nonce: Optional[Nonce] = None


_OUTCOMES = (
    "consumed",
    "missing",
    "expired",
    "same_tty",
    "audience_mismatch",
    "signature_invalid",
)

# Sentinel returned by _load_one to indicate HMAC failure (distinct from None = parse error).
_SIG_INVALID = object()


def _windows_base_dir(context: str) -> Path:
    """B3-Fix-6: resolve Windows base dir for nonce/key state.

    Priority: HARNESS_NONCE_DIR env > LOCALAPPDATA env > hard failure.
    If LOCALAPPDATA is unset on Windows, we WARN and do NOT silently relocate
    state to $HOME (diverging sessions). Operators must set LOCALAPPDATA or
    HARNESS_NONCE_DIR explicitly.
    """
    import sys as _sys
    harness_dir = os.environ.get("HARNESS_NONCE_DIR", "")
    if harness_dir:
        return Path(harness_dir)
    localappdata = os.environ.get("LOCALAPPDATA", "")
    if localappdata:
        return Path(localappdata)
    # LOCALAPPDATA unset — warn loudly; do NOT silently fall back to home.
    _sys.stderr.write(
        f"WARNING: LOCALAPPDATA is unset on Windows ({context}); "
        "falling back to home directory — nonce mint/consume may diverge "
        "across sessions. Set LOCALAPPDATA or HARNESS_NONCE_DIR to suppress.\n"
    )
    return Path(os.path.expanduser("~"))


def default_nonce_dir() -> Path:
    """Resolve the canonical OS-specific nonce directory.

    POSIX: ``~/.harness/approval-nonces/``
    Windows: ``%LOCALAPPDATA%/Harness/approval-nonces/``

    Caller is responsible for creating the directory if missing.
    """
    if os.name == "nt":
        base = _windows_base_dir("default_nonce_dir")
        return base / "Harness" / "approval-nonces"
    return Path.home() / ".harness" / "approval-nonces"


def default_secret_key_path() -> Path:
    """Resolve the canonical OS-specific secret key path.

    POSIX: ``~/.harness/secret.key``
    Windows: ``%LOCALAPPDATA%/Harness/secret.key``
    """
    if os.name == "nt":
        base = _windows_base_dir("default_secret_key_path")
        return base / "Harness" / "secret.key"
    return Path.home() / ".harness" / "secret.key"


def _load_or_create_secret_key(
    secret_path: Path,
    *,
    audit_path: Optional[Path] = None,
) -> bytes:
    """Return the 32-byte HMAC key from *secret_path*, creating it if absent.

    Uses O_WRONLY|O_CREAT|O_EXCL for atomic create (race-safe).  File
    permissions 0600 set on POSIX (best-effort).

    B3-Fix-7: if the file exists with wrong length (corrupt) OR is unreadable,
    rotate the corrupt file aside to a timestamped backup and create a fresh key.
    This prevents the deadlock where O_EXCL fails (file exists), re-read returns
    the same corrupt data, and processes diverge by using locally-generated keys.
    Emits 'audit.secret_key.rotated' real audit row after successful rotation.

    A-1 (Cycle-2): the entire read → detect → rotate → create path runs under an
    exclusive fcntl.flock (POSIX) / msvcrt.locking (Windows) on a sidecar
    ``secret.key.lock`` file.  This prevents two concurrent processes from both
    detecting corruption and creating divergent keys.
    """
    import sys as _sys

    # Create parent directory before acquiring the lock (mkdir is idempotent and
    # safe to call outside the lock).
    secret_path.parent.mkdir(parents=True, exist_ok=True)

    lock_path = secret_path.with_suffix(".lock")
    lock_fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        # Acquire exclusive lock covering: read → detect → rotate → create.
        if os.name == "posix":
            _fcntl.flock(lock_fd, _fcntl.LOCK_EX)
        elif _msvcrt is not None:
            try:
                _msvcrt.locking(lock_fd, _msvcrt.LK_LOCK, 1)
            except OSError:
                pass  # best-effort on Windows

        return _load_or_create_secret_key_locked(
            secret_path, audit_path=audit_path
        )
    finally:
        os.close(lock_fd)


def _load_or_create_secret_key_locked(
    secret_path: Path,
    *,
    audit_path: Optional[Path] = None,
) -> bytes:
    """Inner implementation — called while the sidecar lock is held.

    B3-Fix-9: add permissions check (POSIX only) — delegates to secret_key module
    guard to inherit the same 0600 enforcement that secret_key.load_secret_key uses.
    """
    import sys as _sys

    corrupt_data: bytes | None = None
    corrupt_reason: str = "corrupt_length"
    try:
        data = secret_path.read_bytes()
        if len(data) == 32:
            # Permissions guard: reject group/other readable bits on POSIX.
            if os.name == "posix":
                import stat as _stat
                mode = secret_path.stat().st_mode
                if mode & (_stat.S_IRWXG | _stat.S_IRWXO):
                    raise RuntimeError(
                        f"secret.key at {secret_path} has insecure permissions "
                        f"(mode={oct(mode & 0o777)}). Fix: chmod 600 {secret_path}"
                    )
            return data
        # Wrong length — mark as corrupt for rotation below.
        corrupt_data = data
        corrupt_reason = "corrupt_length"
    except FileNotFoundError:
        pass
    except OSError:
        corrupt_data = b""  # unreadable — also rotate
        corrupt_reason = "corrupt_unreadable"

    # Rotate corrupt file aside (B3-Fix-7).
    backup_path: Optional[Path] = None
    if corrupt_data is not None and secret_path.exists():
        import shutil as _shutil
        # Use time_ns + token_hex(4) suffix to prevent collision (A-1 P2-conc P2-4).
        suffix = f".corrupt-{time.time_ns()}-{secrets.token_hex(4)}"
        backup = secret_path.with_suffix(suffix)
        backup_path = backup
        try:
            _shutil.move(str(secret_path), str(backup))
            _sys.stderr.write(
                f"WARNING: secret.key at {secret_path} had wrong length "
                f"({len(corrupt_data)} bytes); rotated to {backup}. "
                "A fresh key will be created.\n"
            )
        except OSError as _e:
            backup_path = None
            _sys.stderr.write(
                f"WARNING: could not rotate corrupt secret.key {secret_path}: {_e}. "
                "Proceeding with fresh key generation.\n"
            )

    # Create parent directory if needed (may have been absent before).
    secret_path.parent.mkdir(parents=True, exist_ok=True)

    key = secrets.token_bytes(32)
    try:
        fd = os.open(str(secret_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, key)
            os.fsync(fd)
        finally:
            os.close(fd)
    except FileExistsError:
        # Another process created the file between our read and create — read it.
        data = secret_path.read_bytes()
        if len(data) == 32:
            return data
        # Still corrupt after concurrent create — return what we generated.
        return key

    # Best-effort chmod on POSIX (handles umask edge cases).
    if os.name == "posix":
        try:
            os.chmod(str(secret_path), 0o600)
        except OSError:
            pass

    # A-2 (Cycle-2): emit real audit row after successful rotation (not just stderr).
    if backup_path is not None:
        _emit_secret_key_rotated_audit(
            backup_path=backup_path,
            reason=corrupt_reason,
            audit_path=audit_path,
        )

    return key


def _emit_secret_key_rotated_audit(
    *,
    backup_path: Path,
    reason: str,
    audit_path: Optional[Path] = None,
) -> None:
    """Emit an audit.secret_key.rotated audit row (A-2, Cycle-2).

    Uses a default audit path derived from the user's ~/.harness/ directory if
    none is supplied.  Failure is best-effort (audit must not block security-
    critical key creation).
    """
    if audit_path is None:
        try:
            audit_path = Path.home() / ".harness" / "audit.log"
        except Exception:
            return
    try:
        from . import audit as _audit  # local import to avoid circular deps
        _audit.audit_append(
            {
                "verb": "audit.secret_key.rotated",
                "reason": reason,
                "backup_path": str(backup_path),
            },
            audit_path=audit_path,
        )
    except Exception:
        pass  # audit failure must not block key creation


def _gen_id() -> str:
    """8-char base32 code from a 64-bit random token (design §3.1.1)."""
    # 5 bytes → 40 bits → 8 base32 chars (no padding); collision-safe at
    # nonce volumes (~/min).
    raw = secrets.token_bytes(5)
    return base64.b32encode(raw).decode("ascii").rstrip("=").lower()


def _ensure_windows_tty_path(tty_path: str) -> str:
    """Defense-in-depth: on Windows, replace an empty tty_path with a unique
    session identifier so that mint and consume in different processes always
    produce *distinct* values, preserving the cross-TTY guard (§3.1.1).

    On POSIX the OS-assigned tty device path is already unique per session, so
    this function is a no-op there.

    NOTE on same-process scenario: if the mint and consume calls run inside the
    *same* process (same pid), they will produce the same identifier.  That is
    intentional — a same-process mint+consume is exactly the self-approval spoof
    the cross-TTY guard is designed to block.

    TODO(v0.8): the approve-nonce mint CLI (P2-A5 carryover) should STORE its
    session identifier alongside the nonce so the consume side can read its OWN
    session id rather than computing it on the fly.
    """
    if not tty_path and os.name != "posix":
        tty_path = f"win:{os.getpid()}:{secrets.token_hex(4)}"
    return tty_path


def _compute_sig(body_without_sig: dict, key: bytes) -> str:
    """Return HMAC-SHA256 hex digest over JSON-canonical *body_without_sig*."""
    payload = json.dumps(body_without_sig, sort_keys=True).encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def mint(
    nonce_dir: Path,
    *,
    audience: str,
    minter_tty: str,
    ttl_seconds: int = 120,
    secret_key: Optional[bytes] = None,
) -> Nonce:
    """Write a single-use nonce file. Returns the in-memory Nonce.

    The file is HMAC-SHA256 signed (§12.1).  *secret_key* is the raw 32-byte
    key; if None the key is loaded/created from ``default_secret_key_path()``.
    """
    # §3.1.1 defense-in-depth: on Windows os.ttyname is unavailable and callers
    # pass minter_tty="" — replace with a unique per-process session identifier
    # so cross-TTY guard does not collapse to no-op when both sides use "".
    minter_tty = _ensure_windows_tty_path(minter_tty)

    if secret_key is None:
        secret_key = _load_or_create_secret_key(default_secret_key_path())

    nonce_dir = Path(nonce_dir)
    nonce_dir.mkdir(parents=True, exist_ok=True)
    # Tighten dir perms on POSIX (best-effort).
    if os.name == "posix":
        try:
            os.chmod(nonce_dir, 0o700)
        except OSError:
            pass

    minted_at = time.time()
    expires_at = minted_at + float(ttl_seconds)
    nonce_id = _gen_id()
    body = {
        "nonce_id": nonce_id,
        "audience": audience,
        "minter_tty": minter_tty,
        "minted_at": minted_at,
        "expires_at": expires_at,
    }
    # §12.1: HMAC-SHA256 sign the body (sort_keys=True for canonical form).
    sig = _compute_sig(body, secret_key)
    body["sig_version"] = 1
    body["signature"] = sig

    path = nonce_dir / f"{nonce_id}.json"
    # O_EXCL guards against rare ID collision.
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, (json.dumps(body, sort_keys=True) + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    return Nonce(
        nonce_id=nonce_id,
        audience=audience,
        minter_tty=minter_tty,
        minted_at=minted_at,
        expires_at=expires_at,
    )


def _load_one(path: Path, secret_key: Optional[bytes] = None):
    """Parse a nonce file.

    Returns:
        Nonce      — valid and signature OK (or no key provided)
        _SIG_INVALID — parsed OK but HMAC check failed
        None       — parse error (malformed file)
    """
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    try:
        nonce = Nonce(
            nonce_id=str(body["nonce_id"]),
            audience=str(body["audience"]),
            minter_tty=str(body["minter_tty"]),
            minted_at=float(body["minted_at"]),
            expires_at=float(body["expires_at"]),
        )
    except (KeyError, TypeError, ValueError):
        return None

    # §12.1: verify HMAC-SHA256 if a key is provided.
    if secret_key is not None:
        stored_sig = body.get("signature")
        if stored_sig is None:
            # Unsigned nonce — reject as signature_invalid.
            return _SIG_INVALID
        # Recompute over body minus {signature, sig_version}.
        body_to_verify = {
            k: v for k, v in body.items() if k not in ("signature", "sig_version")
        }
        expected_sig = _compute_sig(body_to_verify, secret_key)
        if not hmac.compare_digest(stored_sig, expected_sig):
            return _SIG_INVALID

    return nonce


def consume_newest_valid(
    nonce_dir: Path,
    *,
    audience: str,
    consumer_tty: str,
    secret_key: Optional[bytes] = None,
) -> ConsumeResult:
    """Find the newest nonce for *audience*, validate freshness and TTY
    distinctness, delete the file, return the consumed Nonce.

    Outcome priority (when there ARE candidates for *audience*):
      signature_invalid > same_tty > expired > consumed
    If no candidate at all (no files OR only wrong-audience files):
      → ``missing``.

    *secret_key* is the raw 32-byte HMAC key; if None the key is loaded
    from ``default_secret_key_path()``.  Pass ``secret_key=b""`` to skip
    signature verification (test-only escape hatch — not recommended).
    """
    if secret_key is None:
        secret_key = _load_or_create_secret_key(default_secret_key_path())

    nonce_dir = Path(nonce_dir)
    if not nonce_dir.exists():
        return ConsumeResult(outcome="missing")

    now = time.time()
    candidates: list[tuple[float, Path, object]] = []
    for p in nonce_dir.glob("*.json"):
        result = _load_one(p, secret_key=secret_key)
        if result is None:
            continue
        if result is _SIG_INVALID:
            # We still need the audience to filter; peek without sig check.
            try:
                body = json.loads(p.read_text(encoding="utf-8"))
                if str(body.get("audience", "")) != audience:
                    continue
                minted_at = float(body.get("minted_at", 0))
            except Exception:
                continue
            candidates.append((minted_at, p, _SIG_INVALID))
            continue
        n: Nonce = result  # type: ignore[assignment]
        if n.audience != audience:
            continue
        candidates.append((n.minted_at, p, n))

    if not candidates:
        return ConsumeResult(outcome="missing")

    # Newest first.
    candidates.sort(key=lambda t: t[0], reverse=True)

    # Inspect the newest candidate's failure modes deterministically.
    # Priority: signature_invalid > same_tty > expired > consumed.
    _, path, n_or_sentinel = candidates[0]

    if n_or_sentinel is _SIG_INVALID:
        # Build a minimal Nonce-like stub for the result; we only have
        # what we can parse from the file (audience at least).
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
            stub = Nonce(
                nonce_id=str(body.get("nonce_id", "")),
                audience=str(body.get("audience", audience)),
                minter_tty=str(body.get("minter_tty", "")),
                minted_at=float(body.get("minted_at", 0)),
                expires_at=float(body.get("expires_at", 0)),
            )
        except Exception:
            stub = None
        return ConsumeResult(outcome="signature_invalid", nonce=stub)

    n: Nonce = n_or_sentinel  # type: ignore[assignment]
    if n.minter_tty == consumer_tty:
        return ConsumeResult(outcome="same_tty", nonce=n)
    if n.expires_at < now:
        return ConsumeResult(outcome="expired", nonce=n)

    # Consume — delete the file (single-use). Best-effort unlink; if a
    # racer beat us, treat as missing.
    try:
        path.unlink()
    except FileNotFoundError:
        return ConsumeResult(outcome="missing")
    return ConsumeResult(outcome="consumed", nonce=n)


__all__ = [
    "Nonce",
    "ConsumeResult",
    "mint",
    "consume_newest_valid",
    "default_nonce_dir",
    "default_secret_key_path",
    "_load_or_create_secret_key",
]
