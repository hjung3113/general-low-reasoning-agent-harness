#!/usr/bin/env python3
"""Run the release install/check smoke matrix for the harness source tree.

G4-B trust boundary (ADR-004 / T0-4 / CHANGELOG L19): this smoke runner
treats every ``verification[*]`` entry in ``.scratch/phase-state.json`` as
DEVELOPER-TRUSTED shell input and may execute it on behalf of the
developer. The core ``harness check`` CLI never executes verification
strings; this runner is the one in-tree consumer that intentionally
crosses the boundary. Do not pipe untrusted state files through this
script.

Three adapter-neutral lifecycle stages (core, Roo, OpenCode) run BEFORE
the existing CASES matrix and gate on its success, plus a static grep
gate against quarantined adapter commands. See spec §10.2 and
``.planning/phases/02b-hardening/plans/02b-11-SMOKE-EXT-PLAN.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

# Allow direct invocation (`python3 scripts/release_smoke_test.py`) as
# well as module-style import (`python3 -m scripts.release_smoke_test`).
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.lib.smoke_lifecycle import run_lifecycle_smoke  # noqa: E402


CASES = [
    ("core", ["--adapters", "none"]),
    ("opencode", ["--adapters", "opencode"]),
    ("roo", ["--adapters", "roo"]),
    ("both", ["--adapters", "both"]),
    ("python-analysis", ["--adapters", "opencode", "--packs", "workflow-core,tech-python,workflow-data-analysis"]),
    (
        "dotnet-etl-mssql",
        ["--adapters", "both", "--profiles", "dotnet-etl", "--db", "mssql"],
    ),
    (
        "python-etl-postgresql-opencode",
        ["--adapters", "opencode", "--profiles", "python-etl", "--db", "postgresql"],
    ),
    (
        "react-web-roo",
        ["--adapters", "roo", "--profiles", "react-web", "--db", "none"],
    ),
    (
        "web",
        ["--packs", "workflow-core,tech-react,tech-typescript,tech-tailwind,workflow-web-development"],
    ),
    (
        "workflow-quality",
        [
            "--packs",
            "workflow-core,workflow-tdd,workflow-debugging,workflow-code-review,workflow-skill-authoring,workflow-security-review",
        ],
    ),
    (
        "all-packs",
        [
            "--adapters",
            "both",
            "--profiles",
            "dotnet-etl",
            "--db",
            "mssql",
            "--packs",
            ",".join(
                [
                    "workflow-core",
                    "tech-python",
                    "tech-react",
                    "tech-typescript",
                    "tech-tailwind",
                    "tech-csharp",
                    "tech-mssql",
                    "tech-postgresql",
                    "workflow-data-analysis",
                    "workflow-data-processing",
                    "workflow-etl",
                    "workflow-db-context",
                    "workflow-web-development",
                    "workflow-tdd",
                    "workflow-debugging",
                    "workflow-code-review",
                    "workflow-skill-authoring",
                    "workflow-security-review",
                ]
            ),
        ],
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-temp", action="store_true", help="Keep the temporary matrix directory.")
    parser.add_argument("--release", action="store_true", help="Require exact clean release tag before running the smoke matrix.")
    parser.add_argument("--expected-version", default=None, help="Expected vMAJOR.MINOR.PATCH release tag for --release.")
    parser.add_argument("--skip-lifecycle-smoke", action="store_true", help="Debug only: skip the 02b-11 three-stage lifecycle smoke + grep gate.")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    command_env = os.environ.copy()
    version_args: list[str] = []
    release_mode = args.release or command_env.get("HARNESS_RELEASE_RUN") == "1"
    if args.skip_lifecycle_smoke:
        # SecM1: unconditional banner whenever the lifecycle smoke is
        # skipped. Even if the run later hard-fails, the operator must
        # see why this path was taken.
        print("LIFECYCLE SMOKE SKIPPED — DEBUG ONLY", file=sys.stderr, flush=True)
        if release_mode:
            raise SystemExit(
                "--skip-lifecycle-smoke forbidden under release mode "
                "(--release or HARNESS_RELEASE_RUN=1)"
            )
    if args.release:
        command_env.pop("HARNESS_VERSION", None)
        if not args.expected_version:
            raise SystemExit("--release requires --expected-version vMAJOR.MINOR.PATCH")
        version_args = ["--version", args.expected_version]
    if args.keep_temp:
        matrix_root = Path(tempfile.mkdtemp(prefix="harness-release-smoke."))
    else:
        matrix_root = Path(tempfile.mkdtemp(prefix="harness-release-smoke."))
    try:
        if args.release:
            command = [sys.executable, "scripts/harness.py", "release-check"]
            if args.expected_version:
                command.extend(["--expected-version", args.expected_version])
            command.append("--require-origin-main")
            run(command, cwd=root, env=command_env)
        if not args.skip_lifecycle_smoke:
            run_lifecycle_smoke(matrix_root / "lifecycle")
        for name, options in CASES:
            target = matrix_root / name
            run([sys.executable, "scripts/harness.py", *version_args, "init", "--target", str(target), *options], cwd=root, env=command_env)
            run([sys.executable, "scripts/harness.py", *version_args, "check", "--target", str(target)], cwd=root, env=command_env)
            run([sys.executable, "scripts/harness.py", "check"], cwd=target, env=command_env)
            assert_installed_preflight(target, command_env)
            run([sys.executable, "scripts/test_harness.py"], cwd=target, env=command_env)
            print(f"PASS {name} {target}")
        print(f"TMP {matrix_root}")
    finally:
        if not args.keep_temp:
            shutil.rmtree(matrix_root)
    return 0


def run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def assert_installed_preflight(target: Path, env: dict[str, str]) -> None:
    status = subprocess.run(
        [sys.executable, "scripts/show_phase_status.py"],
        cwd=target,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = json.loads(status.stdout)
    if payload.get("contract_version") != "phase-status.v1":
        raise SystemExit(f"{target}: unsupported phase status contract {payload.get('contract_version')!r}")
    blocking = [
        warning
        for warning in payload.get("warnings", [])
        if isinstance(warning, dict) and warning.get("severity") == "blocking"
    ]
    if blocking:
        raise SystemExit(f"{target}: installed status script reported blocking warnings: {blocking!r}")

    doctor = subprocess.run(
        [sys.executable, "scripts/harness.py", "doctor", "--format", "json"],
        cwd=target,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    findings = json.loads(doctor.stdout).get("findings", [])
    severe = [
        finding
        for finding in findings
        if isinstance(finding, dict) and finding.get("severity") in {"P1", "P2"}
    ]
    if severe:
        raise SystemExit(f"{target}: installed doctor reported P1/P2 findings: {severe!r}")


if __name__ == "__main__":
    raise SystemExit(main())
