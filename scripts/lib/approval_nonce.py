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
                                         "same_tty", "audience_mismatch"}
    mint(nonce_dir, *, audience, minter_tty, ttl_seconds) -> Nonce
    consume_newest_valid(nonce_dir, *, audience, consumer_tty)
                                       -> ConsumeResult
    default_nonce_dir() -> Path
"""

from __future__ import annotations

import dataclasses
import json
import os
import secrets
import time
from pathlib import Path
from typing import Optional


@dataclasses.dataclass(frozen=True)
class Nonce:
    nonce_id: str
    audience: str
    minter_tty: str
    minted_at: float
    expires_at: float


@dataclasses.dataclass(frozen=True)
class ConsumeResult:
    outcome: str  # "consumed" | "missing" | "expired" | "same_tty" | "audience_mismatch"
    nonce: Optional[Nonce] = None


_OUTCOMES = (
    "consumed",
    "missing",
    "expired",
    "same_tty",
    "audience_mismatch",
)


def default_nonce_dir() -> Path:
    """Resolve the canonical OS-specific nonce directory.

    POSIX: ``~/.harness/approval-nonces/``
    Windows: ``%LOCALAPPDATA%/Harness/approval-nonces/``

    Caller is responsible for creating the directory if missing.
    """
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(base) / "Harness" / "approval-nonces"
    return Path.home() / ".harness" / "approval-nonces"


def _gen_id() -> str:
    """8-char base32 code from a 64-bit random token (design §3.1.1)."""
    # 5 bytes → 40 bits → 8 base32 chars (no padding); collision-safe at
    # nonce volumes (~/min).
    raw = secrets.token_bytes(5)
    import base64

    return base64.b32encode(raw).decode("ascii").rstrip("=").lower()


def mint(
    nonce_dir: Path,
    *,
    audience: str,
    minter_tty: str,
    ttl_seconds: int = 120,
) -> Nonce:
    """Write a single-use nonce file. Returns the in-memory Nonce."""
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


def _load_one(path: Path) -> Optional[Nonce]:
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    try:
        return Nonce(
            nonce_id=str(body["nonce_id"]),
            audience=str(body["audience"]),
            minter_tty=str(body["minter_tty"]),
            minted_at=float(body["minted_at"]),
            expires_at=float(body["expires_at"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def consume_newest_valid(
    nonce_dir: Path,
    *,
    audience: str,
    consumer_tty: str,
) -> ConsumeResult:
    """Find the newest nonce for *audience*, validate freshness and TTY
    distinctness, delete the file, return the consumed Nonce.

    Outcome priority (when there ARE candidates for *audience*):
      same_tty > expired > consumed
    If no candidate at all (no files OR only wrong-audience files):
      → ``missing``.
    """
    nonce_dir = Path(nonce_dir)
    if not nonce_dir.exists():
        return ConsumeResult(outcome="missing")

    now = time.time()
    candidates: list[tuple[float, Path, Nonce]] = []
    for p in nonce_dir.glob("*.json"):
        n = _load_one(p)
        if n is None:
            continue
        if n.audience != audience:
            continue
        candidates.append((n.minted_at, p, n))

    if not candidates:
        return ConsumeResult(outcome="missing")

    # Newest first.
    candidates.sort(key=lambda t: t[0], reverse=True)

    # Inspect the newest candidate's failure modes deterministically.
    _, path, n = candidates[0]
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
]
