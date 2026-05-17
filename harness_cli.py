"""Entry point for the `harness` console script.

Wraps ``scripts/harness.py:run`` so that ``pip install -e .`` produces a
cross-platform ``harness`` (POSIX) / ``harness.exe`` (Windows) launcher on the
user's PATH.

The existing ``scripts/harness.py`` module uses bare ``from lib.X import ...``
imports (i.e. it assumes ``scripts/`` is on ``sys.path``). We honor that
convention here instead of rewriting the imports; this keeps backward
compatibility with direct ``python3 scripts/harness.py`` invocations used by
tests, CI, and existing tooling while letting installs use the console script.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
SCRIPTS_DIR = REPO_ROOT / "scripts"


def main() -> int:
    scripts_path = str(SCRIPTS_DIR)
    if scripts_path not in sys.path:
        sys.path.insert(0, scripts_path)
    import harness as _harness  # noqa: E402  (path prep must precede import)

    return _harness.run()


if __name__ == "__main__":
    raise SystemExit(main())
