#!/usr/bin/env python3
"""Verify the `harness` console-script launcher works on the current platform.

Required by S00.5-launcher slice. Builds a throwaway virtual environment,
installs the repo via ``pip install -e .``, and confirms the installed
``harness`` entry point resolves and dispatches to ``scripts/harness.py:run``.

Strategy:
  - Create a tmpdir venv (``venv.create(..., with_pip=True)``).
  - Run ``<venv>/bin/pip install -e <repo_root>`` (or ``Scripts\\pip.exe`` on
    Windows).
  - Locate the installed ``harness`` launcher (POSIX ``<venv>/bin/harness``;
    Windows ``<venv>\\Scripts\\harness.exe``).
  - Invoke ``harness --help``; require exit 0 and stdout that mentions every
    known top-level subcommand declared in ``scripts/harness.py``.

The venv is destroyed after the test. CI matrix rows (design doc §7.1) run
this once per (OS, Python, launcher, shell) tuple.

Exit codes:
  0  launcher resolves and dispatches correctly
  1  install failed or launcher missing / dispatch failed
  2  unsupported platform (no POSIX bin/ and no Windows Scripts/)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Top-level subcommands declared by scripts/harness.py — keep in sync with the
# argparse subparsers in scripts/harness.py:run. If any of these stops being
# emitted by `harness --help`, the launcher is not dispatching correctly.
REQUIRED_SUBCOMMANDS = {
    "install",
    "init",
    "upgrade",
    "check",
    "doctor",
    "uninstall",
    "release-check",
    "state",
    "migrate",
    "phase",
    "session",
}


def venv_launcher(venv_dir: Path) -> Path | None:
    """Return the path of the installed `harness` launcher inside *venv_dir*."""
    if os.name == "nt":
        candidate = venv_dir / "Scripts" / "harness.exe"
    else:
        candidate = venv_dir / "bin" / "harness"
    return candidate if candidate.exists() else None


def venv_pip(venv_dir: Path) -> Path | None:
    """Return the path of pip inside *venv_dir*."""
    if os.name == "nt":
        candidate = venv_dir / "Scripts" / "pip.exe"
    else:
        candidate = venv_dir / "bin" / "pip"
    return candidate if candidate.exists() else None


MIN_PYTHON = (3, 11)


def main() -> int:
    if sys.version_info < MIN_PYTHON:
        major, minor = MIN_PYTHON
        sys.stderr.write(
            f"this verifier requires Python >= {major}.{minor}; "
            f"got {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} "
            f"at {sys.executable}.\n"
            "Fix: re-run with a Python that matches pyproject.toml's "
            "`requires-python` (release matrix §7.1 ships 3.11 and 3.12), e.g.\n"
            "  /opt/homebrew/bin/python3.12 scripts/smoke/verify_launcher_matrix.py\n"
            "  py -3.12 scripts\\smoke\\verify_launcher_matrix.py\n"
        )
        return 2

    if not (REPO_ROOT / "pyproject.toml").is_file():
        sys.stderr.write(
            f"pyproject.toml not found at {REPO_ROOT}; cannot verify launcher.\n"
            "Fix: run from the harness repo root.\n"
        )
        return 1

    if os.name not in {"nt", "posix"}:
        sys.stderr.write(f"unsupported platform: os.name={os.name!r}\n")
        return 2

    with tempfile.TemporaryDirectory(prefix="harness-launcher-verify-") as tmp_str:
        tmp = Path(tmp_str)
        venv_dir = tmp / "venv"
        sys.stdout.write(f"creating venv at {venv_dir} ...\n")
        venv.create(venv_dir, with_pip=True, clear=True)

        pip = venv_pip(venv_dir)
        if pip is None:
            sys.stderr.write(f"pip not found in venv {venv_dir}\n")
            return 1

        sys.stdout.write(f"installing {REPO_ROOT} via pip install -e ...\n")
        install = subprocess.run(
            [str(pip), "install", "-e", str(REPO_ROOT), "--quiet"],
            capture_output=True,
            text=True,
        )
        if install.returncode != 0:
            sys.stderr.write("pip install -e failed:\n")
            sys.stderr.write(install.stdout)
            sys.stderr.write(install.stderr)
            sys.stderr.write(
                "Fix: ensure pyproject.toml [project.scripts] entry points "
                "are valid and dependencies install on this Python.\n"
            )
            return 1

        launcher = venv_launcher(venv_dir)
        if launcher is None:
            sys.stderr.write(
                f"`harness` launcher not found in venv {venv_dir}.\n"
                "Fix: confirm pyproject.toml [project.scripts] declares "
                "`harness = \"harness_cli:main\"`.\n"
            )
            return 1

        sys.stdout.write(f"invoking {launcher} --help ...\n")
        helped = subprocess.run(
            [str(launcher), "--help"],
            capture_output=True,
            text=True,
        )
        if helped.returncode != 0:
            sys.stderr.write(
                f"`harness --help` exited {helped.returncode}; expected 0.\n"
            )
            sys.stderr.write(helped.stdout)
            sys.stderr.write(helped.stderr)
            return 1

        missing = sorted(cmd for cmd in REQUIRED_SUBCOMMANDS if cmd not in helped.stdout)
        if missing:
            sys.stderr.write(
                "`harness --help` is missing expected subcommands: "
                f"{missing}.\n"
                "Fix: ensure scripts/harness.py:run registers every "
                "subcommand listed in REQUIRED_SUBCOMMANDS.\n"
            )
            sys.stderr.write("--- stdout ---\n")
            sys.stderr.write(helped.stdout)
            return 1

        sys.stdout.write(
            f"OK launcher={launcher} python={sys.executable} platform={os.name}\n"
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())
