"""Source/target validation: structure, JSON, phase-state, manifest scopes."""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from lib.manifest import (
    ManifestEntry,
    MANIFEST_PATH,
    MANIFEST_SOURCE_VERSION,
    load_manifest,
    load_manifest_data,
    select_entries,
    source_path,
    destination_path,
    validate_managed_append_destinations,
    validate_scope_names,
)
from lib.profiles import PROFILE_MODE_OWNERS
from lib.state_diagnostics import load_state_json
from lib.roadmap_state import (
    check_roadmap_state_sync,
    roadmap_state_sync_applicable,
    normalize_path,
)
from lib.state import (
    INSTALL_STATE,
    read_install_state,
    validate_installed_scope_names,
    validate_installed_managed_append,
    required_phrase_scope,
    file_hash,
    manifest_sha256,
)
from lib.version import (
    check_readme_release_versions,
    resolve_harness_version,
)
from lib.worktree import (
    check_changed_paths,
    check_worktree_paths,
    is_text_file,
)
from lib.workflow_static_checks import (
    verification_placeholder_reason,
)
from lib.managed_block import parse_blocks
from lib.manifest_reconciler import (
    verify_install_record_integrity as _verify_install_record_integrity,
    verify_manifest_chain as _verify_manifest_chain,
)


# ---------------------------------------------------------------------------
# T8a — Import smoke (BUG-2)
# ---------------------------------------------------------------------------

def _collect_lib_imports_from_file(path: Path) -> list[str]:
    """AST-walk *path*; return unique dotted lib module names referenced.

    Collects:
      - ``from lib.X import ...``  → ``lib.X``
      - ``from lib.X.Y import ...`` → ``lib.X.Y``
      - ``import lib.X``            → ``lib.X``
      - ``from lib import X``       → ``lib.X``  (T8a broadening: catches sub-module
        imports like ``from lib import install_recovery``; each alias name is
        recorded as ``lib.<name>`` so the manifest-completeness check can
        verify the corresponding file exists)

    Skips:
      - Relative imports (``from . import ...``)
    """
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(path))
    except (OSError, SyntaxError):
        return []

    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # relative import — skip
            mod = node.module or ""
            if mod.startswith("lib."):
                modules.add(mod)
            elif mod == "lib":
                # ``from lib import X`` — treat each alias as lib.X
                for alias in node.names:
                    modules.add(f"lib.{alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("lib."):
                    modules.add(alias.name)
    return sorted(modules)


def _module_to_path(scripts_dir: Path, module: str) -> Path:
    """Convert a dotted module name to the expected .py path under scripts_dir.

    Examples::

        lib.state          → scripts_dir/lib/state.py
        lib.project_dashboard.core → scripts_dir/lib/project_dashboard/core.py
    """
    parts = module.split(".")
    return scripts_dir / Path(*parts).with_suffix(".py")


def run_import_smoke(scripts_dir: Path) -> list[str]:
    """Check that every ``lib.*`` module referenced in *scripts_dir* is present.

    Scans ``scripts_dir/harness.py`` and ``scripts_dir/lib/**/*.py`` via AST
    to collect all ``from lib.X`` / ``import lib.X`` references, then verifies
    that the corresponding ``lib/X.py`` (or ``lib/X/__init__.py``) exists inside
    *scripts_dir*.

    This file-existence check (rather than a live import) is correct because:
    - The caller is an INSTALLED TARGET whose ``scripts/`` dir is separate from
      the harness source repo.
    - ``sys.modules`` may already contain harness-source copies of the same
      modules; a live import would silently succeed even if the target file is
      absent (exactly the BUG-2 class we are catching).

    Returns a sorted list of dotted module names whose file is missing.
    Empty list means success.
    """
    scripts_dir = scripts_dir.resolve()

    # Collect all .py files to scan
    source_files: list[Path] = []
    harness_py = scripts_dir / "harness.py"
    if harness_py.is_file():
        source_files.append(harness_py)
    lib_root = scripts_dir / "lib"
    if lib_root.is_dir():
        for py_file in sorted(lib_root.rglob("*.py")):
            if "__pycache__" in py_file.parts:
                continue
            source_files.append(py_file)

    # Collect unique module names across all scanned files
    all_modules: set[str] = set()
    for sf in source_files:
        all_modules.update(_collect_lib_imports_from_file(sf))

    if not all_modules:
        return []

    failures: list[str] = []
    for mod in sorted(all_modules):
        # Accept either lib/X.py  OR  lib/X/__init__.py (package form)
        mod_file = _module_to_path(scripts_dir, mod)
        init_file = scripts_dir / Path(*mod.split(".")) / "__init__.py"
        if not mod_file.is_file() and not init_file.is_file():
            failures.append(mod)

    return failures


# ---------------------------------------------------------------------------
# End T8a
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# T8b — Per-policy hash verification matrix (STALE-3)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HashDriftFinding:
    """One per-file hash mismatch from verify_hashes()."""

    path: str          # relative path as stored in installed-manifest.json
    policy: str        # harness-owned | managed | managed-append
    error_code: str    # harness-owned-drift | managed-drift | managed-append-drift
    expected: str      # hash recorded in installed-manifest.json
    found: str         # hash computed from on-disk file


def _sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_hashes(target: Path) -> list[HashDriftFinding]:
    """Iterate installed-manifest.json:files[] and detect per-policy hash drift.

    Per-policy matrix
    -----------------
    ``harness-owned``   : sha256(on-disk) vs ``installed_sha256``  → ``harness-owned-drift``
    ``managed``         : sha256(on-disk) vs ``installed_sha256``  → ``managed-drift``
    ``managed-append``  : sha256 of managed block (between markers) vs
                          ``applied_sha256``                        → ``managed-append-drift``
    ``project-owned``   : SKIP — not a drift signal
    ``exclude``         : not iterated

    Returns a (possibly empty) list of HashDriftFinding.  Does NOT raise on
    mismatch; callers decide whether to exit.
    """
    from lib.append_block import parse_append_block, sha256_text  # local import: avoids cycle

    installed_path = target / INSTALL_STATE
    if not installed_path.exists():
        return []
    try:
        installed = json.loads(installed_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    files: dict = installed.get("files", {}) or {}
    findings: list[HashDriftFinding] = []

    for path_text, info in files.items():
        if not isinstance(info, dict):
            continue
        policy = info.get("policy", "")
        if policy in ("project-owned", "exclude", ""):
            continue

        on_disk = target / normalize_path(path_text)
        if not on_disk.exists():
            # File listed in installed-manifest but absent on disk: emit a
            # *-missing finding so that deleted harness-owned/managed files
            # surface in verify_hashes (incl. the doctor path which calls
            # verify_hashes directly without going through check_installed_target).
            error_code = f"{policy}-missing"
            expected = info.get("installed_sha256", "") or info.get("applied_sha256", "")
            findings.append(
                HashDriftFinding(
                    path=path_text,
                    policy=policy,
                    error_code=error_code,
                    expected=expected,
                    found="(missing)",
                )
            )
            continue

        if policy in ("harness-owned", "managed"):
            expected = info.get("installed_sha256", "")
            if not expected:
                continue
            found = _sha256_file(on_disk)
            if found != expected:
                error_code = (
                    "harness-owned-drift" if policy == "harness-owned" else "managed-drift"
                )
                findings.append(
                    HashDriftFinding(
                        path=path_text,
                        policy=policy,
                        error_code=error_code,
                        expected=expected,
                        found=found,
                    )
                )

        elif policy == "managed-append":
            expected = info.get("applied_sha256", "")
            if not expected:
                continue
            try:
                text = on_disk.read_text(encoding="utf-8")
                parsed = parse_append_block(text, path_text)
            except OSError:
                continue
            except ValueError as exc:
                # Malformed managed-append markers (duplicate start/end, inverted
                # order, missing end marker) prevent hash verification and are
                # themselves a signal of corruption or tampering.
                findings.append(
                    HashDriftFinding(
                        path=path_text,
                        policy=policy,
                        error_code="managed-append-malformed",
                        expected=expected,
                        found=f"(malformed: {exc})",
                    )
                )
                continue
            if parsed is None:
                # Block absent — validate_installed_managed_append already reports this.
                continue
            found = sha256_text(parsed.text)
            if found != expected:
                findings.append(
                    HashDriftFinding(
                        path=path_text,
                        policy=policy,
                        error_code="managed-append-drift",
                        expected=expected,
                        found=found,
                    )
                )

    return findings


def format_hash_drift_errors(findings: list[HashDriftFinding]) -> str:
    """Return a human-readable multi-line summary of drift findings."""
    lines = []
    for f in findings:
        lines.append(
            f"error: {f.error_code}: {f.path} "
            f"(expected {f.expected[:12]}… found {f.found[:12]}…)"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# End T8b
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ManagedBlockWarning:
    code: str
    path: str
    message: str


def _is_trivial_phase_state(state_path: Path) -> bool:
    """Return True when ``state_path`` matches the clean-skeleton init signature.

    The fresh-repo state has ``updated_by == "harness-init"`` AND
    ``updated_at == "1970-01-01T00:00:00Z"`` (per
    ``harness/skeleton/clean/.scratch/phase-state.json``). Either field
    diverging means the file has been touched and drift detection should
    not be silently suppressed when audit.log is absent.
    """
    if not state_path.exists():
        return True
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return (
        isinstance(data, dict)
        and data.get("updated_by") == "harness-init"
        and data.get("updated_at") == "1970-01-01T00:00:00Z"
    )


def check_drift(root: Path, *, stderr=None) -> None:
    """Emit a drift warning if state SHA-256 diverges from last audit entry.

    Per ADR-003a G2-D (T0-3 Task 8): compares the live
    ``.scratch/phase-state.json`` SHA-256 against the last audit entry's
    ``after_sha256`` in ``.harness/audit.log``. Drift never fails the check
    — only stderr is touched.

    Missing/empty audit.log handling (C1 amendment):

    - audit.log absent/empty AND state is trivial (clean-skeleton init
      signature) → silent return (legitimate first-use).
    - audit.log absent/empty AND state has been edited → WARNING that drift
      detection is disabled.

    The warning template MUST NOT reference any future verbs such as
    ``harness phase audit`` (deferred to 02c).
    """
    if stderr is None:
        stderr = sys.stderr
    audit_path = root / ".harness" / "audit.log"
    state_path = root / ".scratch" / "phase-state.json"
    if not audit_path.exists() or audit_path.stat().st_size == 0:
        if _is_trivial_phase_state(state_path):
            return  # G1-A first-write suppression on fresh repo
        print(
            "warning: audit log missing — drift detection disabled. "
            "Run 'harness phase set <phase>' to re-establish baseline.",
            file=stderr,
        )
        return
    if not state_path.exists():
        return
    try:
        from lib.audit import read_last_entry, compute_state_hash
    except Exception:
        return
    last = read_last_entry(audit_path)
    if last is None:
        return
    expected = last.get("after_sha256")
    if not expected:
        return
    actual = compute_state_hash(state_path)
    if expected == actual:
        return
    try:
        current_phase = json.loads(state_path.read_text(encoding="utf-8")).get(
            "phase", "<unknown>"
        )
    except Exception:
        current_phase = "<unknown>"
    print(
        f"warning: .scratch/phase-state.json sha256 ({actual}) does not match "
        f"the last audit entry's after_sha256 ({expected}) at index "
        f"{last.get('index')}. Drift detected. To restore audit baseline, "
        f"re-run the last CLI verb that should have produced this state "
        f"(typically 'harness phase set {current_phase}' or "
        f"'harness phase approve'). Manual edits are not currently tracked.",
        file=stderr,
    )


_REQUIRED_MARKERS = (
    (".planning/ROADMAP.md", "roadmap-phases"),
    (".planning/STATE.md", "state-current"),
)


def managed_block_warnings(root: Path) -> list[ManagedBlockWarning]:
    findings: list[ManagedBlockWarning] = []
    for rel_path, slug in _REQUIRED_MARKERS:
        path = root / rel_path
        if not path.exists():
            continue
        try:
            blocks = parse_blocks(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            findings.append(
                ManagedBlockWarning(
                    code="malformed_managed_block",
                    path=rel_path,
                    message=str(exc),
                )
            )
            continue
        if slug not in blocks:
            findings.append(
                ManagedBlockWarning(
                    code="missing_managed_block",
                    path=rel_path,
                    message=(
                        f"managed:{slug} block missing in {rel_path}; "
                        f"run `python3 scripts/harness.py state repair` to add it."
                    ),
                )
            )
    return findings


CLEAN_SKELETON = Path("harness/skeleton/clean")
UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
#
# T0-4 (ADR-004 / G4-A): the verification allowlist is the canonical 7-verb
# tuple. The previous soft prefixes (Confirm/Review/Inspect/Validate/Roo/
# core-only/OpenCode-only) AND `bash ` (D-G4) are intentionally rejected.
# The core checker (this module) NEVER executes a verification string —
# the field is a developer-trusted manifest consumed by external runners
# (e.g., scripts/release_smoke_test.py). See ADR-004 G4-B + L19 in
# CHANGELOG.md `### Breaking`.
VERIFICATION_PREFIXES = (
    "python3 ",
    "git ",
    "jq ",
    "npx ",
    "pytest ",
    "harness ",
    "make ",
)
VERIFICATION_VERBS_INLINE = "python3, git, jq, npx, pytest, harness, make"
REQUIRED_TARGET_PHRASES = {
    "AGENTS.md": (
        "Karpathy-Inspired Coding Guidelines",
        "If `.scratch/phase-state.json` is not `phase=execute` with `approved=true`",
        "Every roadmap phase starts with its own `discuss` pass",
    ),
}
CONTAMINATION_PATTERNS = (
    re.compile(r"\bPR\s*#\d+\b", re.IGNORECASE),
    re.compile(r"\bDB context snapshot\b", re.IGNORECASE),
    re.compile(r"\bhjung3113/new-project\b", re.IGNORECASE),
    re.compile(r"\bPhase\s+[0-9]+.*(?:implemented|complete|완료)", re.IGNORECASE),
    re.compile(r"\bunder PR review\b", re.IGNORECASE),
)


def check(
    *,
    root: Path,
    target: Path | None = None,
    base: str | None = None,
    worktree: bool = False,
    adapter: str | None = None,
    harness_version: str = "0.0.0-dev+unknown",
    verify_hashes: bool = False,
) -> None:
    root = root.resolve()
    if not (root / MANIFEST_PATH).exists() or should_check_as_installed_target(root, harness_version=harness_version):
        check_installed_target(root, verify_hashes=verify_hashes)
        if base:
            check_changed_paths(root, base)
        if worktree:
            check_worktree_paths(root)
        check_drift(root)
        _check_planning_drift(root)
        return

    manifest = load_manifest_data(root)
    if manifest.get("version") != harness_version:
        raise SystemExit(f"Manifest version mismatch: expected {harness_version}")

    all_entries = load_manifest(root)
    entries = all_entries
    missing = [str(entry.source) for entry in entries if entry.policy != "exclude" and not source_path(root, entry).exists()]
    if missing:
        raise SystemExit(f"Manifest sources missing: {', '.join(missing)}. Fix: run `harness upgrade --target <target>` (or restore missing source files in the harness checkout)")

    check_clean_skeleton(root)
    if (root / ".roomodes").exists():
        check_json(root / ".roomodes")
    check_json(root / ".scratch/phase-state.schema.json")
    check_json(root / ".scratch/phase-state.example.json")
    check_json(root / ".scratch/phase-state.json")
    check_phase_state_semantics(root / ".scratch/phase-state.json")
    check_phase_state_semantics(root / ".scratch/phase-state.example.json")
    if (root / ".roo").exists() and (root / ".roomodes").exists():
        check_command_modes(root)
    check_phase_state_paths(root)
    check_roadmap_state_sync(root)
    check_phase_reference_drift(root)

    check_target = (target or root).resolve()
    if target:
        installed = read_install_state(check_target)
        adapters = set(installed.get("adapters", ["roo"]))
        profiles = set(installed.get("profiles", ["generic"]))
        packs = set(installed.get("packs", []))
        if adapter:
            adapters.add(adapter)
        validate_scope_names(all_entries, adapters=adapters, profiles=profiles, packs=packs)
        expected = select_entries(all_entries, adapters=adapters, profiles=profiles, packs=packs)
        check_installed_target(check_target, expected_entries=expected)
    if base:
        check_changed_paths(check_target, base)
    if worktree:
        check_worktree_paths(check_target)
    # G2-D drift detection (T0-3 Task 8) — always non-fatal.
    check_drift(root)
    _check_planning_drift(root)


def _check_planning_drift(root: Path) -> None:
    """Sub-check: call dashboard --check in-process and propagate blocking warnings as SystemExit.

    Non-blocking dashboard warnings (severity="warning") do not fail harness check;
    only blocking warnings (EXIT_PLANNING_DRIFT) are propagated.
    If the .planning directory does not exist, skip silently (not a planning repo).
    """
    if not (root / ".planning").exists():
        return
    # Skip if canonical planning files are absent — fixture or partial install.
    if not (root / ".planning" / "STATE.md").exists() or not (root / ".planning" / "ROADMAP.md").exists():
        return
    # Skip if no installed-manifest (not an installed harness target — fixture or dev environment).
    if not (root / INSTALL_STATE).exists():
        return
    # Lazy dual import to avoid module-level circular import risk.
    try:
        from scripts.lib.project_dashboard.core import run as _dashboard_run
        from scripts.lib.exitcodes import EXIT_OK
    except ModuleNotFoundError:
        from lib.project_dashboard.core import run as _dashboard_run  # type: ignore[no-redef]
        from lib.exitcodes import EXIT_OK  # type: ignore[no-redef]
    import contextlib
    import io
    # Capture dashboard JSON output so it doesn't pollute harness check stdout.
    # On failure, print a single-line summary pointing to the dedicated command.
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        drift_exit = _dashboard_run(["--check", "--root", str(root)])
    if drift_exit != EXIT_OK:
        raise SystemExit(
            "planning-drift: dashboard --check detected blocking drift; "
            "run `python3 scripts/project_dashboard.py --check` for details"
        )


def should_check_as_installed_target(root: Path, *, harness_version: str = "0.0.0-dev+unknown") -> bool:
    if not (root / INSTALL_STATE).exists() or not (root / MANIFEST_PATH).exists():
        return False
    try:
        manifest = json.loads((root / MANIFEST_PATH).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return True
    version = manifest.get("version") if isinstance(manifest, dict) else None
    return version not in {MANIFEST_SOURCE_VERSION, harness_version}


def _scan_stale_staging_dirs(
    target: Path,
) -> list[tuple[Path, str, float | None]]:
    """Return stale staging dirs as list of (path, runid, age_secs) tuples.

    A staging dir is stale when:
    - It has a sibling ``.staging-<name>.journal.jsonl`` file, AND
    - ``install_recovery._is_stale(staging_dir)`` is True (age >= 600s OR .aborted marker).

    This avoids false-positives on live install operations (fresh dirs < 600s old).
    Per-task one warning row per stale dir (LRR M-3).
    """
    import fnmatch as _fnmatch
    import time as _time
    try:
        from lib.install_recovery import _is_stale as _ir_is_stale
    except ImportError:
        return []

    harness = target / ".harness"
    if not harness.is_dir():
        return []

    results: list[tuple[Path, str, float | None]] = []
    try:
        import os as _os
        with _os.scandir(str(harness)) as it:
            for entry in it:
                if not (
                    _fnmatch.fnmatchcase(entry.name, ".staging-*")
                    and entry.is_dir(follow_symlinks=False)
                ):
                    continue
                staging_dir = Path(entry.path)
                runid = entry.name[len(".staging-"):]
                journal = harness / (entry.name + ".journal.jsonl")
                if not journal.exists():
                    continue  # no journal = not a harness install staging dir
                if not _ir_is_stale(staging_dir):
                    continue  # not stale yet (live install, < 600s)
                try:
                    import time as _t
                    mtime = staging_dir.stat().st_mtime
                    age_secs: float | None = _t.time() - mtime
                except OSError:
                    age_secs = None
                results.append((staging_dir, runid, age_secs))
    except OSError:
        pass
    return results


def _print_stale_staging_warnings(target: Path) -> int:
    """Print warning(s) for stale aborted-install staging dirs.

    N == 1: single-line "중단된 설치 감지 (runid=..., age=...s)".
    N >= 2: single summary line "{N}개 중단된 설치 감지 (oldest runid=..., age=...s)".
    Returns the number of stale dirs found.
    """
    _stale = list(_scan_stale_staging_dirs(target))
    if len(_stale) == 1:
        _path, _runid, _age = _stale[0]
        _age_str = f"{int(_age)}" if _age is not None else "?"
        print(
            f"warning: 중단된 설치 감지 (runid={_runid}, age={_age_str}s). "
            f"복구: python3 scripts/harness.py state repair "
            f"[Aborted install detected; recover with state repair]"
        )
    elif len(_stale) >= 2:
        # Sort so that entries with known ages come first, oldest age first;
        # entries with unknown age sort last (None age cannot be claimed "oldest").
        def _age_key(t):
            age = t[2]
            return (0, -float(age)) if age is not None else (1, 0)
        _stale_sorted = sorted(_stale, key=_age_key)
        _oldest_path, _oldest_runid, _oldest_age = _stale_sorted[0]
        if _oldest_age is not None:
            _oldest_label = f"oldest runid={_oldest_runid}, age={int(_oldest_age)}s"
            _oldest_label_en = f"oldest runid={_oldest_runid}, age={int(_oldest_age)}s"
        else:
            _oldest_label = f"oldest known runid=?, age=?"
            _oldest_label_en = f"oldest known runid=?, age=?"
        _all_runids = ", ".join(t[1] for t in _stale_sorted)
        print(
            f"warning: {len(_stale)}개 중단된 설치 감지 "
            f"({_oldest_label}; all runids: {_all_runids}). "
            f"복구: python3 scripts/harness.py state repair "
            f"[{len(_stale)} aborted installs detected ({_oldest_label_en}); "
            f"recover with state repair]"
        )
    return len(_stale)


def check_installed_target(
    target: Path,
    expected_entries: list[ManifestEntry] | None = None,
    *,
    verify_hashes: bool = False,
) -> None:
    # T8a early gate: smoke-check that every lib.* referenced in the target's
    # scripts/ directory actually exists as a file there.  Must run before any
    # other check so a broken install (BUG-2: manifest-gap) surfaces immediately
    # with an actionable error instead of a confusing ModuleNotFoundError later.
    _scripts_dir = target / "scripts"
    if _scripts_dir.is_dir():
        _smoke_failures = run_import_smoke(_scripts_dir)
        if _smoke_failures:
            missing_names = ", ".join(
                mod.split(".", 1)[1] if mod.startswith("lib.") else mod
                for mod in _smoke_failures
            )
            raise SystemExit(
                f"error: import smoke detected missing module(s): {missing_names}. "
                f"Fix: run `harness upgrade --target {target}` to restore missing lib files."
            )

    installed_path = target / INSTALL_STATE
    if not installed_path.exists():
        raise SystemExit(f"Target is missing {INSTALL_STATE}")
    # P5-P1-3: verify installed-manifest chain hash on read (§6 integrity).
    # Chain mismatch is logged as a WARNING to avoid masking other check
    # failures (policy mismatch, retired files, etc.) that are reported via
    # their own specific error messages.  The warning is printed to stderr so
    # operators are alerted; BOM / parse errors still raise exit 5 (hard stop).
    from lib.manifest_reconciler import ManifestChainTamperedError as _MCTE
    try:
        _verify_install_record_integrity(target)
    except _MCTE as _ce:
        import sys as _sys
        _sys.stderr.write(
            f"WARNING: installed-manifest chain hash mismatch "
            f"(possible tampering or legacy record). {_ce}\n"
        )
    # Returns False for fresh installs (no manifest → skip chain check).
    installed = load_state_json(installed_path)
    if installed.get("version") is None:
        raise SystemExit("Target install state is missing version.")
    validate_installed_scope_names(installed)
    profile_sync_errs = _check_roomodes_profile_sync(target, installed)
    if profile_sync_errs:
        raise SystemExit("Profile-mode sync errors: " + "; ".join(profile_sync_errs) + ". Fix: run `harness upgrade --target <target> --profiles <profile>` to re-sync .roomodes with the installed profile set")
    missing = []
    for path_text in installed.get("files", {}):
        from lib.adoption import is_optional_project_owned_path
        destination = target / normalize_path(path_text)
        if not destination.exists():
            info = installed.get("files", {}).get(path_text)
            if (
                isinstance(info, dict)
                and info.get("policy") == "project-owned"
                and is_optional_project_owned_path(path_text)
            ):
                continue
            missing.append(path_text)
            continue
        info = installed.get("files", {}).get(path_text)
        if isinstance(info, dict) and info.get("policy") == "managed-append":
            validate_installed_managed_append(destination=destination, path_text=path_text, info=info)
    if missing:
        raise SystemExit("Installed target is missing files: " + ", ".join(missing) + ". Fix: run `harness upgrade --target <target>`")
    if expected_entries is not None:
        expected_by_path = {str(entry.path): entry for entry in expected_entries if entry.policy != "exclude"}
        policy_mismatches = []
        for path_text, entry in expected_by_path.items():
            info = installed.get("files", {}).get(path_text)
            if not isinstance(info, dict):
                continue
            if info.get("policy") != entry.policy:
                policy_mismatches.append(f"{path_text}: installed {info.get('policy')} != current {entry.policy}")
                continue
            if entry.policy == "managed-append":
                destination = target / normalize_path(path_text)
                if destination.exists():
                    validate_installed_managed_append(destination=destination, path_text=path_text, info=info)
        if policy_mismatches:
            raise SystemExit("Installed policy mismatch: " + "; ".join(policy_mismatches) + ". Fix: run `harness upgrade --target <target>` to realign installed policy with the current manifest")
        expected_paths = {
            str(entry.path) for entry in expected_entries if entry.policy not in {"exclude", "project-owned"}
        }
        missing_current = [
            path_text for path_text in sorted(expected_paths) if not (target / normalize_path(path_text)).exists()
        ]
        if missing_current:
            raise SystemExit("Current harness files missing from target: " + ", ".join(missing_current) + ". Fix: run `harness upgrade --target <target>`")
        retired = [
            path_text
            for path_text, info in sorted(installed.get("files", {}).items())
            if path_text not in expected_paths
            and isinstance(info, dict)
            and info.get("policy") != "project-owned"
        ]
        if retired:
            raise SystemExit("Retired harness files remain installed: " + ", ".join(retired) + ". Fix: run `harness upgrade --target <target> --force` to overwrite, or delete the listed files manually")
    missing_phrases = []
    for relative, phrases in REQUIRED_TARGET_PHRASES.items():
        path = target / relative
        if not path.exists():
            missing_phrases.append(f"{relative}: missing file")
            continue
        text = required_phrase_scope(path=path, relative=relative)
        for phrase in phrases:
            if phrase not in text:
                missing_phrases.append(f"{relative}: {phrase}")
    if missing_phrases:
        raise SystemExit("Required guardrail phrases missing: " + "; ".join(missing_phrases) + ". Fix: run `harness upgrade --target <target>` to restore guardrail phrases in AGENTS.md / .roomodes")
    for relative in (
        ".roomodes",
        ".scratch/phase-state.schema.json",
        ".scratch/phase-state.example.json",
        ".scratch/phase-state.json",
    ):
        path = target / relative
        if path.exists():
            check_json(path)
    for relative in (".scratch/phase-state.json", ".scratch/phase-state.example.json"):
        path = target / relative
        if path.exists():
            check_phase_state_semantics(path)
    if roadmap_state_sync_applicable(target):
        check_roadmap_state_sync(target)
    # T5: detect stale aborted-install staging directories.
    _print_stale_staging_warnings(target)

    for warning in managed_block_warnings(target):
        print(f"warning: {warning.code} in {warning.path}: {warning.message}")
    if verify_hashes:
        import lib.check as _self
        drift = _self.verify_hashes(target)
        if drift:
            msg = format_hash_drift_errors(drift)
            raise SystemExit(msg)


def _check_roomodes_profile_sync(target: Path, installed: dict) -> list[str]:
    roomodes_path = target / ".roomodes"
    if not roomodes_path.exists():
        return []
    try:
        from lib import roomodes_writer
        profile_modes = roomodes_writer.read(roomodes_path).profile_modes
    except ImportError:
        # roomodes_writer is not installed to targets; parse directly using the
        # same slug-based classification as the writer.
        _BASE_SLUGS = {
            "orchestrator", "architect", "tdd-code", "diagnose", "review",
            "docs-issues", "ops-observability", "harness-maintainer",
        }
        _KNOWN_PROFILE_SLUGS = frozenset(PROFILE_MODE_OWNERS.keys())
        data = json.loads(roomodes_path.read_text(encoding="utf-8"))
        profile_modes = [
            m for m in data.get("customModes", [])
            if m.get("slug") not in _BASE_SLUGS and m.get("slug") in _KNOWN_PROFILE_SLUGS
        ]
    installed_profiles = set((installed.get("init_options") or {}).get("profiles") or [])
    errs: list[str] = []
    for mode in profile_modes:
        slug = mode.get("slug")
        owner = PROFILE_MODE_OWNERS.get(slug)
        if owner and owner not in installed_profiles:
            errs.append(
                f".roomodes contains profile-contributed mode {slug!r} but "
                f"owning profile {owner!r} is not installed"
            )
    return errs


def check_clean_skeleton(root: Path) -> None:
    skeleton = root / CLEAN_SKELETON
    if not skeleton.exists():
        raise SystemExit(f"Missing clean skeleton: {CLEAN_SKELETON}")
    offenders: list[str] = []
    for path in skeleton.rglob("*"):
        if path.is_file() and is_text_file(path):
            text = path.read_text(encoding="utf-8")
            if any(pattern.search(text) for pattern in CONTAMINATION_PATTERNS):
                offenders.append(str(path.relative_to(root)))
    if offenders:
        raise SystemExit("Clean skeleton contamination detected: " + ", ".join(offenders) + ". Fix: revert or remove project-specific content from the listed paths under harness/skeleton/clean/ (skeleton must stay generic)")


def check_json(path: Path) -> None:
    json.loads(path.read_text(encoding="utf-8"))


def check_phase_state_semantics(path: Path) -> None:
    state = load_state_json(path)
    # ADR-001: state_schema_version is required (v2 = post-T0-1 shape). A
    # record without this field is a pre-slice (v0) record and must be
    # migrated forward before the rest of the checker runs.
    if state.get("state_schema_version") != 2:
        raise SystemExit(
            f"{path} missing or stale state_schema_version (expected 2). "
            f"Run: python3 scripts/harness.py migrate state --forward"
        )
    for key in ("updated_at",):
        if not UTC_TIMESTAMP.fullmatch(str(state.get(key, ""))):
            raise SystemExit(f"{path} {key} must be an ISO-8601 UTC timestamp. Fix: re-run `harness phase set <phase> --stdin-json` with a corrected {key} (e.g. \"2026-05-18T12:34:56Z\") in the JSON payload")
    if not isinstance(state.get("updated_by"), str) or not state.get("updated_by"):
        raise SystemExit(f"{path} updated_by is required. Fix: re-run `harness phase set <phase> --stdin-json` with \"updated_by\": \"<agent-or-user-id>\" in the JSON payload")
    automation_mode = state.get("automation_mode")
    if automation_mode not in {"manual", "auto", "chain"}:
        raise SystemExit(f"{path} automation_mode must be manual, auto, or chain. Fix: re-run `harness phase set <phase> --stdin-json` with \"automation_mode\": \"manual\" (or \"auto\"/\"chain\") in the JSON payload")
    # S01-A.2: execution_mode is the v0.7 canonical replacement for the
    # legacy automation_mode alias (design §1.1). It is optional on
    # legacy state_schema_version=2 records that pre-date the S01 slice;
    # `harness migrate state --forward` is what upgrades them. When
    # present, it MUST be inside the enum — fail closed to defeat
    # hand-edited or forged values (state-trust preflight lands in S01-E).
    if "execution_mode" in state:
        from lib.phase_state import EXECUTION_MODES  # local import: avoids cycle
        execution_mode = state["execution_mode"]
        if execution_mode not in EXECUTION_MODES:
            raise SystemExit(
                f"{path} execution_mode must be one of "
                f"{sorted(EXECUTION_MODES)}; got {execution_mode!r}."
            )
    auto_selected = state.get("auto_selected")
    if not isinstance(auto_selected, list):
        raise SystemExit(f"{path} auto_selected must be an array. Fix: re-run `harness phase set <phase> --stdin-json` with \"auto_selected\": [] (empty list is valid for automation_mode=manual)")
    if automation_mode in {"auto", "chain"} and not auto_selected:
        raise SystemExit(f"{path} auto_selected must record choices when automation_mode={automation_mode}. Fix: switch to automation_mode=manual via `harness phase set <phase> --stdin-json`, or re-run the autopilot decision so harness records auto_selected entries")
    required = {
        "choice": str,
        "selected_value": str,
        "reason": str,
        "evidence_path": str,
        "risk_level": str,
        "reversible": bool,
        "inside_allowed_paths": bool,
        "stop_conditions_checked": list,
    }
    for index, item in enumerate(auto_selected):
        if not isinstance(item, dict):
            raise SystemExit(f"{path} auto_selected[{index}] must be an object. Fix: replace the entry at index {index} via `harness phase set <phase> --stdin-json` — each item must be a JSON object with choice, selected_value, reason, evidence_path, risk_level, reversible, inside_allowed_paths, stop_conditions_checked")
        for key, expected_type in required.items():
            if key not in item or not isinstance(item[key], expected_type):
                raise SystemExit(f"{path} auto_selected[{index}].{key} is required. Fix: add the missing {key} to auto_selected[{index}] via `harness phase set <phase> --stdin-json`")
        if item["risk_level"] not in {"low", "medium", "high"}:
            raise SystemExit(f"{path} auto_selected[{index}].risk_level must be low, medium, or high. Fix: set auto_selected[{index}].risk_level to one of low|medium|high via `harness phase set <phase> --stdin-json`")
        if not item["stop_conditions_checked"]:
            raise SystemExit(f"{path} auto_selected[{index}].stop_conditions_checked must be non-empty. Fix: add at least one stop-condition string to auto_selected[{index}].stop_conditions_checked via `harness phase set <phase> --stdin-json`")
    phase = state.get("phase")
    if phase not in {"discuss", "plan", "execute", "done"}:
        raise SystemExit(f"{path} phase must be discuss, plan, execute, or done. Fix: run `harness phase set discuss` (or plan/execute/done) to reset to a valid phase value")
    # SM5: `approved`, when present, MUST be a bool. Reject string truthy
    # values like "yes"/"true" across all phases. (Note: isinstance(x, bool)
    # is the only correct test in Python; bool is a subclass of int so the
    # ordering matters but `int` is not an accepted approval type either.)
    if "approved" in state and not isinstance(state["approved"], bool):
        raise SystemExit(
            f"{path} approved must be a JSON boolean (true/false); got "
            f"{type(state['approved']).__name__}={state['approved']!r}."
        )
    if phase == "discuss" and state.get("approved") is not False:
        raise SystemExit(f"{path} discuss phase requires approved=false. Fix: run `harness phase set discuss --reset-approval`")
    if phase == "plan":
        required_plan = (
            "plan_id",
            "summary",
            "plan_path",
            "state_path",
            "checkpoint_path",
            "current_checkpoint",
            "next_action",
            "acceptance_criteria",
            "verification",
        )
        missing = [key for key in required_plan if not state.get(key)]
        if state.get("approved") is not False:
            missing.append("approved=false")
        if missing:
            raise SystemExit(f"{path} plan phase requires {', '.join(missing)}.")
    if phase == "execute":
        required_execute = (
            "plan_id",
            "allowed_paths",
            "verification",
            "state_path",
            "plan_path",
            "checkpoint_path",
            "current_checkpoint",
            "next_action",
            "approved_by",
            "approved_at",
        )
        missing = [key for key in required_execute if not state.get(key)]
        if state.get("approved") is not True:
            missing.append("approved=true")
        if missing:
            raise SystemExit(f"{path} execute approval requires {', '.join(missing)}.")
        if not UTC_TIMESTAMP.fullmatch(str(state.get("approved_at", ""))):
            raise SystemExit(f"{path} approved_at must be an ISO-8601 UTC timestamp.")
    if phase == "done":
        required_done = (
            "plan_id",
            "state_path",
            "plan_path",
            "checkpoint_path",
            "current_checkpoint",
            "next_action",
        )
        # T0-4 (ADR-004): verification may be empty when `review` carries
        # the closure evidence. The "verification OR review non-empty"
        # constraint is enforced below, after both have been validated.
        missing = [key for key in required_done if not state.get(key)]
        # ADR-001 option 3: the schema constraint on ``approved`` is dropped
        # from the ``done`` branch — both ``approved=true`` and ``approved=false``
        # are valid. See docs/adr/2026-05-16-hardening-bundle.md ADR-001.
        if missing:
            raise SystemExit(f"{path} done phase requires {', '.join(missing)}.")
    verification = state.get("verification", [])
    if verification is None:
        verification = []
    if not isinstance(verification, list):
        raise SystemExit(f"{path} verification must be an array.")
    for index, command in enumerate(verification):
        if not isinstance(command, str) or not command.strip():
            raise SystemExit(f"{path} verification[{index}] must be a non-empty string.")
        placeholder_reason = verification_placeholder_reason(command)
        if placeholder_reason:
            raise SystemExit(f"{path} verification[{index}] is a {placeholder_reason}.")
        if not command.startswith(VERIFICATION_PREFIXES):
            raise SystemExit(
                f"{path} verification[{index}] = {command!r} does not start with an allowed verb.\n"
                f"Allowed verbs: {VERIFICATION_VERBS_INLINE}.\n"
                f"See docs/protocol-spec.md#verification-allowlist "
                f"(source: scripts/lib/check.py VERIFICATION_PREFIXES)."
            )
    # T0-4 (ADR-004) review evidence validator.
    review = state.get("review", [])
    if review is None:
        review = []
    if not isinstance(review, list):
        raise SystemExit(f"{path} review must be an array.")
    for index, entry in enumerate(review):
        if not isinstance(entry, dict):
            raise SystemExit(f"{path} review[{index}] must be an object.")
        # Reject extra properties (mirror schema additionalProperties: false).
        allowed_keys = {"actor", "at", "evidence_path", "summary"}
        extra = set(entry.keys()) - allowed_keys
        if extra:
            raise SystemExit(
                f"{path} review[{index}] has unexpected keys: {sorted(extra)}."
            )
        for key in ("actor", "at", "evidence_path", "summary"):
            if key not in entry:
                raise SystemExit(f"{path} review[{index}].{key} is required.")
            if not isinstance(entry[key], str):
                raise SystemExit(
                    f"{path} review[{index}].{key} must be a string; got "
                    f"{type(entry[key]).__name__}."
                )
        # Non-empty constraints (evidence_path may be empty; doctor warns).
        if not entry["actor"]:
            raise SystemExit(f"{path} review[{index}].actor must be non-empty.")
        if not entry["summary"]:
            raise SystemExit(f"{path} review[{index}].summary must be non-empty.")
        if not UTC_TIMESTAMP.fullmatch(entry["at"]):
            raise SystemExit(
                f"{path} review[{index}].at must be an ISO-8601 UTC timestamp; "
                f"got {entry['at']!r}."
            )
        # T0-4 SecM4: when evidence_path is non-empty, reject traversal
        # segments, absolute paths, and URL schemes. The empty string is
        # accepted as a migration sentinel (see state_migrate_t04).
        ev = entry["evidence_path"]
        if ev:
            ev_segments = ev.replace("\\", "/").split("/")
            if (
                ".." in ev_segments
                or os.path.isabs(ev)
                or "://" in ev
            ):
                raise SystemExit(
                    f"{path} review[{index}].evidence_path: traversal or "
                    f"absolute path not allowed (got: {ev})"
                )
    # T0-4 (ADR-004): a closed (done) phase requires verification OR review
    # non-empty — at least one form of evidence must be present.
    if state.get("phase") == "done" and not verification and not review:
        raise SystemExit(
            f"{path} done phase requires non-empty verification OR review "
            f"(at least one form of evidence)."
        )


from .roo_modes import ROO_BUILTIN_MODES as _ROO_BUILTIN_MODES  # single source of truth


def check_command_modes(root: Path) -> None:
    modes = json.loads((root / ".roomodes").read_text(encoding="utf-8"))
    known = {mode["slug"] for mode in modes.get("customModes", [])} | _ROO_BUILTIN_MODES
    unknown: list[str] = []
    for command in (root / ".roo/commands").glob("*.md"):
        text = command.read_text(encoding="utf-8")
        match = re.search(r"^mode:\s*([A-Za-z0-9_-]+)\s*$", text, re.MULTILINE)
        if match and match.group(1) not in known:
            unknown.append(f"{command.relative_to(root)} -> {match.group(1)}")
    if unknown:
        raise SystemExit("Commands reference unknown Roo modes: " + ", ".join(unknown))


def check_phase_reference_drift(root: Path) -> None:
    stale = (
        "Phase 2 should add mechanical",
        "Future mechanical enforcement belongs to Phase 2",
        "Phase 3 for consumer onboarding",
        "Phase 4 is reserved for a project-specific example slice",
    )
    offenders = []
    for path in (root / ".planning").rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        for phrase in stale:
            if phrase in text:
                offenders.append(f"{path.relative_to(root)}: {phrase}")
    if offenders:
        raise SystemExit("Stale phase reference detected: " + "; ".join(offenders) + ". Fix: search-and-replace the listed phrases in the named files, or rephrase the stale text")


def check_phase_state_paths(root: Path) -> None:
    state_path = root / ".scratch/phase-state.json"
    state = load_state_json(state_path)
    missing = []
    for key in ("state_path", "plan_path", "checkpoint_path"):
        value = state.get(key)
        if isinstance(value, str) and value and not (root / normalize_path(value)).exists():
            missing.append(f"{key}={value}")
    if missing:
        raise SystemExit("Phase-state paths are missing: " + ", ".join(missing) + ". Fix: create the listed file(s), or update phase-state.json's state_path/plan_path/checkpoint_path via `harness phase set <phase> --stdin-json`")
