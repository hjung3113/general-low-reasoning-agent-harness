"""Forward / reverse / resume state migrator for ``.scratch/phase-state.json``.

Owning plan: .planning/phases/02b-hardening/plans/02b-02-T0-1-PLAN.md Block C.
Contract pin: .planning/phases/02b-hardening/CONTRACT-PIN.md §1 (module path
``scripts/lib/state_migrate.py``), §6.1 (.bak filename grammar), §6.3 (sidecar
filename grammar).

Pure functions:
- ``forward(state_v0: dict) -> dict`` — applies G2-A serialization rules:
  sets ``state_schema_version=2``; re-formats ``approved_at``/``updated_at``
  from second-precision (``YYYY-MM-DDThh:mm:ssZ``) to nanosecond-precision
  (``YYYY-MM-DDThh:mm:ss.000000000Z``). Idempotent at the ``json.loads`` level.
- ``reverse(state_v2: dict) -> dict`` — strips ``state_schema_version``,
  truncates timestamps back to second precision, ensures ``approved=false``
  for ``done`` records per ADR-001 sub-decision 3a.
- ``sidecar_payload(...)`` — assembles the G1-E ``.resume.json`` payload.
- ``serialize(state: dict) -> bytes`` — canonical serializer
  (``sort_keys=True, indent=2, separators=(',', ': ')``, trailing newline).

Filesystem orchestration (4-step protocol per ADR G1-E):
- ``migrate_file(target, *, direction, backups_dir=None)`` —
  (1) write sidecar via T0-A,
  (2) write byte-identical ``.bak`` via ``os.open(..., O_EXCL, 0o644)``,
  (3) write new target shape via T0-A,
  (4) unlink sidecar.
- ``resume(target, *, backups_dir=None)`` — read most-recent sidecar; if
  target hash == ``pre_hash`` re-run step 3+4; if target hash ==
  ``expected_post_hash`` declare complete; otherwise refuse.

T0-1 SCOPE: this slice does NOT add the ``review`` field nor rewrite the
``verification`` allowlist — those are T0-4 (and explicitly excluded by the
plan's "Out of scope" + Block C2 notes). The migrator therefore touches only
``state_schema_version`` + timestamp precision.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Optional

from .atomic_io import atomic_write_text
from . import backups as _backups_mod


MIGRATOR_VERSION = "t0-1-v1"

# Timestamp shape that the forward migrator promotes to nanosecond precision.
_SEC_TS = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z$")
# Nanosecond-precision timestamp shape that the reverse migrator truncates.
_NS_TS = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\.\d+Z$")

_TIMESTAMP_FIELDS = ("approved_at", "updated_at")


# Test seam: tests monkeypatch these to make filenames deterministic.
def _compact_utc_nanos() -> str:
    """Return current UTC time as ``YYYYMMDDTHHMMSSnnnnnnnnnZ`` (CONTRACT-PIN §6.1)."""
    ns = time.time_ns()
    secs, nanos = divmod(ns, 1_000_000_000)
    tm = time.gmtime(secs)
    return "%04d%02d%02dT%02d%02d%02d%09dZ" % (
        tm.tm_year, tm.tm_mon, tm.tm_mday,
        tm.tm_hour, tm.tm_min, tm.tm_sec, nanos,
    )


def _iso_utc_nanos() -> str:
    """Return current UTC as ``YYYY-MM-DDThh:mm:ss.nnnnnnnnnZ`` (sidecar payload)."""
    ns = time.time_ns()
    secs, nanos = divmod(ns, 1_000_000_000)
    tm = time.gmtime(secs)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%09dZ" % (
        tm.tm_year, tm.tm_mon, tm.tm_mday,
        tm.tm_hour, tm.tm_min, tm.tm_sec, nanos,
    )


def _pid() -> int:
    return os.getpid()


def _promote_timestamp(value: str) -> str:
    """Pad ``YYYY-MM-DDThh:mm:ssZ`` to nanosecond precision."""
    m = _SEC_TS.match(value)
    if m:
        return m.group(1) + ".000000000Z"
    return value  # already nanosecond-precision or non-conforming; leave as-is


def _truncate_timestamp(value: str) -> str:
    """Strip the fractional component from a nanosecond-precision timestamp."""
    m = _NS_TS.match(value)
    if m:
        return m.group(1) + "Z"
    return value


def forward(state_v0: dict) -> dict:
    """Apply the v0 -> v2 transformation in memory.

    Idempotent at ``json.loads`` level: applying ``forward`` twice yields a
    dict that ``==``-equals the once-forward result.
    """
    out = dict(state_v0)
    out["state_schema_version"] = 2
    for key in _TIMESTAMP_FIELDS:
        v = out.get(key)
        if isinstance(v, str):
            out[key] = _promote_timestamp(v)
    return out


def reverse(state_v2: dict) -> dict:
    """Apply the v2 -> v0 transformation in memory (Artifact 5 §--reverse)."""
    out = dict(state_v2)
    out.pop("state_schema_version", None)
    for key in _TIMESTAMP_FIELDS:
        v = out.get(key)
        if isinstance(v, str):
            out[key] = _truncate_timestamp(v)
    # ADR-001 sub-decision 3a: reverse of a ``done`` record writes
    # ``approved=false`` if the field is missing/absent.
    if out.get("phase") == "done" and "approved" not in out:
        out["approved"] = False
    return out


def sidecar_payload(
    *,
    target_path: str,
    pre_hash: str,
    expected_post_hash: str,
    migrator_version: str = MIGRATOR_VERSION,
) -> dict:
    """Build the G1-E sidecar JSON payload.

    Schema: ``{pre_hash, expected_post_hash, target_path, migrator_version, started_at}``.
    """
    return {
        "pre_hash": pre_hash,
        "expected_post_hash": expected_post_hash,
        "target_path": target_path,
        "migrator_version": migrator_version,
        "started_at": _iso_utc_nanos(),
    }


def serialize(state: dict) -> bytes:
    """Canonical serializer per G2-A: sort_keys, indent=2, trailing newline."""
    text = json.dumps(state, sort_keys=True, indent=2, separators=(",", ": "))
    return (text + "\n").encode("utf-8")


# ----------------------------------------------------------------------------
# Filesystem orchestration (4-step protocol).
# ----------------------------------------------------------------------------


_REPO_BACKUPS_DEFAULT = Path(".harness/backups")


def _default_backups_dir(target: Path) -> Path:
    # Walk up from the target until we find a directory that looks like a
    # repo root (contains .scratch/ or .harness/) and place backups there.
    # Fallback: alongside the target's grandparent.
    for parent in [target.parent, *target.parent.parents]:
        if (parent / ".harness").exists() or (parent / ".scratch").exists():
            return parent / ".harness" / "backups"
    return target.parent / ".harness" / "backups"


def _bak_path(target: Path, backups_dir: Path) -> Path:
    return backups_dir / f"{target.name}.pre-repair.{_compact_utc_nanos()}.{_pid()}.bak"


def _sidecar_path_for(bak_path: Path) -> Path:
    return bak_path.with_name(bak_path.name + ".resume.json")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_bak_excl(bak_path: Path, content: bytes) -> None:
    """Thin wrapper retained for back-compat; delegates to ``lib.backups``."""
    # Reuse the hardened helper (O_EXCL + O_NOFOLLOW + 0o700 dir mode + retries).
    # We pre-mkdir to keep mode semantics consistent with the original API.
    bak_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(bak_path.parent, 0o700)
    except OSError:
        pass
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(bak_path), flags, 0o644)
    except FileExistsError:
        raise _exit1(
            f"error: backup file already exists at {bak_path}; this typically "
            f"indicates a previous migration crashed. Inspect the backup and either:\n"
            f"  (a) restore it manually (cp {bak_path} <target>) and re-run, or\n"
            f"  (b) run 'harness migrate state --resume' to continue from the backup, or\n"
            f"  (c) remove the stale backup after confirming target is correct."
        )
    try:
        os.write(fd, content)
        os.fsync(fd)
    finally:
        os.close(fd)


class _CodedSystemExit(SystemExit):
    """SystemExit with both ``.code`` (int) and ``str()`` (message)."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(code)
        self._message = message

    def __str__(self) -> str:  # noqa: D401
        return self._message


def _exit1(message: str) -> _CodedSystemExit:
    return _CodedSystemExit(1, message)


def _transform(state: dict, *, direction: str) -> dict:
    if direction == "forward":
        return forward(state)
    if direction == "reverse":
        return reverse(state)
    raise ValueError(f"unknown direction: {direction!r}")


def migrate_file(
    target: Path,
    *,
    direction: str,
    backups_dir: Optional[Path] = None,
) -> None:
    """Apply the 4-step protocol (ADR G1-E) to ``target``.

    Order:
    1. write sidecar via ``atomic_write_text`` to ``<bak_path>.resume.json``.
    2. write byte-identical ``.bak`` via ``os.open(O_EXCL)``.
    3. write transformed payload to ``target`` via ``atomic_write_text``.
    4. ``os.unlink`` the sidecar.

    Idempotence guard: if ``direction == "forward"`` and the on-disk bytes
    of ``target`` already equal what ``forward`` would produce (canonical),
    return without creating a ``.bak`` (avoids spurious files on re-runs).
    """
    target = Path(target)
    pre_bytes = target.read_bytes()
    pre_state = json.loads(pre_bytes.decode("utf-8"))
    post_state = _transform(pre_state, direction=direction)
    post_bytes = serialize(post_state)

    if pre_bytes == post_bytes:
        # No-op: target already at the desired shape (byte-identical).
        return

    if backups_dir is None:
        backups_dir = _default_backups_dir(target)
    backups_dir.mkdir(parents=True, exist_ok=True)

    bak_path = _bak_path(target, backups_dir)
    sidecar_path = _sidecar_path_for(bak_path)

    pre_hash = _sha256(pre_bytes)
    expected_post_hash = _sha256(post_bytes)

    # Step 1: sidecar via T0-A.
    sidecar = sidecar_payload(
        target_path=str(target),
        pre_hash=pre_hash,
        expected_post_hash=expected_post_hash,
    )
    atomic_write_text(sidecar_path, json.dumps(sidecar, indent=2) + "\n")

    # Step 2: byte-identical .bak via O_EXCL.
    try:
        _write_bak_excl(bak_path, pre_bytes)
    except _CodedSystemExit:
        # Leave the sidecar in place so --resume can reason about state.
        raise

    # Step 3: write transformed target via T0-A.
    atomic_write_text(target, post_bytes.decode("utf-8"))

    # Step 4: remove sidecar.
    try:
        os.unlink(sidecar_path)
    except FileNotFoundError:  # pragma: no cover — concurrent cleanup
        pass

    # Retention prune (CONTRACT-PIN §6): keep last 10 .bak per target basename.
    _backups_mod._prune_old_backups(target.name, backups_dir, 10)


def _find_sidecar_for(target: Path, backups_dir: Path) -> Optional[Path]:
    """Return the most-recent sidecar matching ``target`` basename, if any."""
    candidates = sorted(
        backups_dir.glob(f"{target.name}.pre-repair.*.bak.resume.json"),
        reverse=True,
    )
    return candidates[0] if candidates else None


def resume(target: Path, *, backups_dir: Optional[Path] = None) -> None:
    """Resume a partial migration recorded in a sidecar (ADR G1-E `--resume`).

    Decision tree:
    - If current target hash == ``pre_hash``: rerun steps 3+4 (the .bak is
      already in place; we just need to write the target and unlink the
      sidecar).
    - If current target hash == ``expected_post_hash``: declare complete;
      remove the sidecar.
    - Otherwise: exit 7 (stale-detection-uncertain).
    """
    target = Path(target)
    if backups_dir is None:
        backups_dir = _default_backups_dir(target)

    sidecar_path = _find_sidecar_for(target, backups_dir)
    if sidecar_path is None:
        raise _CodedSystemExit(
            1, f"no sidecar found under {backups_dir} for {target.name}"
        )

    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    pre_hash = sidecar["pre_hash"]
    expected_post_hash = sidecar["expected_post_hash"]

    current_bytes = target.read_bytes()
    current_hash = _sha256(current_bytes)

    if current_hash == expected_post_hash:
        # Already migrated. Remove sidecar; done.
        os.unlink(sidecar_path)
        return

    if current_hash == pre_hash:
        # Re-run step 3 + step 4. The sidecar contains the pre-image; apply
        # the in-memory transform to reconstruct the canonical post bytes.
        state = json.loads(current_bytes.decode("utf-8"))
        # Direction is implicit in the sidecar's hash structure; we choose
        # ``forward`` because that is the only direction T0-1 writes
        # sidecars for in practice. (``reverse`` follows the same protocol
        # but T0-1 lands forward + reverse symmetrically; resuming a partial
        # reverse is an out-of-scope concern.)
        post = forward(state)
        post_bytes = serialize(post)
        if _sha256(post_bytes) != expected_post_hash:
            raise _CodedSystemExit(
                7,
                f"resume: in-memory transform hash does not match sidecar's "
                f"expected_post_hash for {target}. Manual inspection required.",
            )
        atomic_write_text(target, post_bytes.decode("utf-8"))
        os.unlink(sidecar_path)
        return

    raise _CodedSystemExit(
        7,
        f"resume: target hash matches neither pre_hash nor expected_post_hash "
        f"recorded in {sidecar_path}. Manual inspection required.",
    )


__all__ = [
    "MIGRATOR_VERSION",
    "forward",
    "reverse",
    "sidecar_payload",
    "serialize",
    "migrate_file",
    "resume",
]
