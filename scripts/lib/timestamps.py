"""Nanosecond-precision ISO-8601 UTC timestamp helpers.

Owning plan: .planning/milestones/02b-hardening/plans/02b-04-T0-3-PLAN.md
Contract pin: .planning/milestones/02b-hardening/CONTRACT-PIN.md §1 (Timestamps).

Extracted out of `session.py` + `phase_cli.py` per T0-3 amendment #5 so
both callers route through a single implementation. Format:
``YYYY-MM-DDTHH:MM:SS.nnnnnnnnnZ`` (always UTC, always 9 fractional digits).

``parse_iso_nanos`` is the complementary parser used by ``--at`` validation
in `phase_cli.py`. It tolerates the nanosecond-precision form by truncating
to microseconds (the resolution Python's ``datetime`` exposes); the test
suite documents this precision loss.
"""

from __future__ import annotations

import datetime
import re
import time


_NANOS_RE = re.compile(
    r"^(?P<base>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\.(?P<frac>\d{1,9})Z$"
)


def now_iso_nanos() -> str:
    """Return the current UTC time as ``YYYY-MM-DDTHH:MM:SS.nnnnnnnnnZ``."""
    ns = time.time_ns()
    secs, rem = divmod(ns, 1_000_000_000)
    base = datetime.datetime.fromtimestamp(
        secs, tz=datetime.timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{rem:09d}Z"


def parse_iso_nanos(s: str) -> datetime.datetime:
    """Parse a nanosecond-precision ISO-8601 UTC string.

    Truncates to microseconds (datetime's native resolution). Raises
    ``ValueError`` on any input that does not match the canonical shape.
    """
    if not isinstance(s, str):
        raise ValueError(f"parse_iso_nanos: expected str, got {type(s).__name__}")
    m = _NANOS_RE.match(s)
    if m is None:
        # Fall back to fromisoformat to accept the looser ISO-8601 forms
        # produced by older callers; explicit Z handling needed.
        try:
            dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"parse_iso_nanos: could not parse {s!r}: {exc}") from exc
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt
    base = m.group("base")
    frac = m.group("frac").ljust(9, "0")
    micros = int(frac[:6])
    dt = datetime.datetime.strptime(base, "%Y-%m-%dT%H:%M:%S").replace(
        microsecond=micros, tzinfo=datetime.timezone.utc
    )
    return dt


__all__ = ["now_iso_nanos", "parse_iso_nanos"]
