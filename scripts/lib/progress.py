"""Lightweight progress reporting to stderr.

Used by install/upgrade to surface activity during long-running phases.
Output is throttled to avoid noise: a tick line is emitted at
25%/50%/75%/100% boundaries, or every `step` items (whichever is sparser).

stderr-only by contract — stdout formatting must not change (existing
parsers/CI depend on stable stdout).
"""
from __future__ import annotations

import sys
from typing import TextIO


class ProgressReporter:
    def __init__(self, *, quiet: bool = False, stream: TextIO | None = None, step: int = 50) -> None:
        self.quiet = quiet
        self.stream = stream if stream is not None else sys.stderr
        self.step = max(1, step)
        self._label: str = ""
        self._total: int = 0
        self._last_emit: int = -1

    def start(self, label: str, total: int) -> None:
        self._label = label
        self._total = max(0, int(total))
        self._last_emit = -1

    def _emit(self, line: str) -> None:
        """Write one line; swallow stream errors.

        Progress output is advisory only — a closed stderr pipe, a non-writable
        stream, or any other I/O failure must never abort install/upgrade.
        """
        try:
            self.stream.write(line)
            self.stream.flush()
        except Exception:
            pass

    def tick(self, done: int) -> None:
        if self.quiet or self._total <= 0:
            return
        done = max(0, min(int(done), self._total))
        # Emit on quartile boundaries or every `step` items, but only once per value.
        quartiles = {self._total // 4, self._total // 2, (3 * self._total) // 4, self._total}
        if done == self._last_emit:
            return
        if done not in quartiles and (done % self.step) != 0 and done != self._total:
            return
        self._last_emit = done
        self._emit(f"{self._label}... [{done}/{self._total}]\n")

    def done(self, label: str | None = None) -> None:
        if self.quiet:
            return
        text = label if label is not None else self._label
        self._emit(f"{text}... done\n")

    def note(self, text: str) -> None:
        """One-shot status line (no counter)."""
        if self.quiet:
            return
        self._emit(f"{text}\n")
