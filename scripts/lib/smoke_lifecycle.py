"""Adapter-neutral lifecycle smoke driver (02b-11).

Implements the three-stage release-gate smoke per
`docs/superpowers/specs/2026-05-16-hardening-slice-design.md` §10.2 and
`.planning/phases/02b-hardening/plans/02b-11-SMOKE-EXT-PLAN.md`.

Stages:
  - Stage 1: core-only CLI (`harness phase set/approve`).
  - Stage 2: Roo lifecycle (.roo/commands/{phase-discuss,phase-plan,phase-execute,done}.md).
  - Stage 3: OpenCode lifecycle (.opencode/commands/{discuss,plan,execute,done}.md).

The golden file `scripts/smoke/golden/cli-contract-lifecycle.json` is
hand-derived from ADR Artifact 1 (see spec §10.3 invariant). It is
NOT regenerated from runtime output.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE_GOLDEN_PATH = REPO_ROOT / "scripts" / "smoke" / "golden" / "cli-contract-lifecycle.json"
GOLDEN_HEADER = "// DERIVED FROM ADR Artifact 1 — DO NOT REGENERATE FROM RUNTIME"

# The shared invocation contract (spec §10.4 semantic symmetry). Each
# adapter dispatcher (Roo, OpenCode) MUST resolve to the same argv that
# stage 1 invokes directly. Each step maps to a single lifecycle markdown
# command file in the adapter.
STAGE1_INVOCATIONS: list[dict] = [
    {"argv": ["phase", "set", "discuss"], "roo": "phase-discuss.md", "opencode": "discuss.md"},
    {"argv": ["phase", "set", "plan"], "roo": "phase-plan.md", "opencode": "plan.md"},
    {"argv": ["phase", "approve", "--by", "smoke"], "roo": "phase-plan.md", "opencode": "plan.md"},
    {"argv": ["phase", "set", "execute"], "roo": "phase-execute.md", "opencode": "execute.md"},
    {"argv": ["phase", "approve", "--by", "smoke"], "roo": "phase-execute.md", "opencode": "execute.md"},
    {"argv": ["phase", "set", "done"], "roo": "done.md", "opencode": "done.md"},
]

QUARANTINED_ROO_COMMANDS: frozenset[str] = frozenset({
    "adr.md", "bugfix.md", "feature.md", "doctor.md", "issues.md",
    "ops.md", "fsd-phase.md", "review.md", "simple.md",
})

LIFECYCLE_GREP_GATE_ALLOWLIST: frozenset[str] = frozenset({
    ".roo/commands/phase-discuss.md",
    ".roo/commands/phase-plan.md",
    ".roo/commands/phase-execute.md",
    ".roo/commands/done.md",
    ".opencode/commands/discuss.md",
    ".opencode/commands/plan.md",
    ".opencode/commands/execute.md",
    ".opencode/commands/done.md",
})

_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6,9}Z$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_REDACTED_KEYS = {"pid", "index", "audit_entry_index"}
_ACTOR_KEYS = {"by", "updated_by", "approved_by"}


@dataclass(frozen=True)
class Violation:
    file: str
    line_number: int
    line_text: str


def canonicalize_capture(obj, *, tmp_prefix: str | None = None):
    """Recursively normalize timestamps, sha256, pids, paths, actors.

    Returns a JSON-serializable structure equivalent in shape to ``obj``
    with non-deterministic fields replaced by canonical sentinels.
    """
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            if key in _REDACTED_KEYS:
                if key == "index" or key == "audit_entry_index":
                    out[key] = "<MONOTONIC>"
                else:
                    out[key] = "<PID>"
            elif key in _ACTOR_KEYS:
                if value is None:
                    out[key] = None
                else:
                    out[key] = "<ACTOR>"
            else:
                out[key] = canonicalize_capture(value, tmp_prefix=tmp_prefix)
        return out
    if isinstance(obj, list):
        return [canonicalize_capture(v, tmp_prefix=tmp_prefix) for v in obj]
    if isinstance(obj, str):
        if _TIMESTAMP_RE.match(obj):
            return "<TIMESTAMP>"
        if _SHA256_RE.match(obj):
            return "<SHA256>"
        if _EMAIL_RE.match(obj):
            return "<ACTOR>"
        if tmp_prefix and obj.startswith(tmp_prefix):
            return "<TMP>" + obj[len(tmp_prefix):]
        sys_tmp = tempfile.gettempdir()
        if obj.startswith(sys_tmp):
            return "<TMP>" + obj[len(sys_tmp):]
        return obj
    return obj


def canonical_json_bytes(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def load_golden() -> dict:
    text = LIFECYCLE_GOLDEN_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or "DERIVED FROM ADR" not in lines[0]:
        raise RuntimeError(
            f"golden file missing required 'DERIVED FROM ADR' header marker: {LIFECYCLE_GOLDEN_PATH}"
        )
    if "DO NOT REGENERATE" not in lines[0]:
        raise RuntimeError(
            f"golden file missing required 'DO NOT REGENERATE' header marker: {LIFECYCLE_GOLDEN_PATH}"
        )
    body = "\n".join(lines[1:])
    return json.loads(body)


def copy_fixture(dest: Path) -> None:
    src = REPO_ROOT / "scripts" / "fixtures" / "smoke" / "lifecycle-base"
    if src.exists():
        shutil.copytree(src, dest, dirs_exist_ok=True)
    else:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / ".harness").mkdir(exist_ok=True)
        (dest / ".scratch").mkdir(exist_ok=True)


def _pinned_smoke_env(cwd: Path) -> dict[str, str]:
    """M4: build a minimal pinned env so the smoke is insensitive to
    the host's git config and shell environment.

    Only PATH, HOME (set to the fixture so any rc-file reads stay
    local), HARNESS_USER, and the GIT_{AUTHOR,COMMITTER}_{NAME,EMAIL}
    quartet are passed through. PYTHONPATH is forwarded when set so
    that pytest/unittest runners can still locate `scripts` as a
    package (the harness CLI itself is invoked by absolute path).
    """
    env: dict[str, str] = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(cwd),
        "HARNESS_USER": "smoke",
        "GIT_AUTHOR_NAME": "smoke",
        "GIT_AUTHOR_EMAIL": "smoke@local",
        "GIT_COMMITTER_NAME": "smoke",
        "GIT_COMMITTER_EMAIL": "smoke@local",
    }
    if "PYTHONPATH" in os.environ:
        env["PYTHONPATH"] = os.environ["PYTHONPATH"]
    return env


def _run_harness(argv: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "harness.py"), *argv],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env=_pinned_smoke_env(cwd),
    )


def _state_sha(fixture_root: Path) -> str:
    state = fixture_root / ".scratch" / "phase-state.json"
    if not state.exists():
        return ""
    return hashlib.sha256(state.read_bytes()).hexdigest()


def _parse_json_text(text: str) -> dict | list:
    return json.loads(text)


def _read_audit(fixture_root: Path) -> list[dict]:
    log = fixture_root / ".harness" / "audit.log"
    if not log.exists():
        return []
    return [_parse_json_text(line) for line in log.read_text().splitlines() if line.strip()]


def _read_state(fixture_root: Path) -> dict:
    state = fixture_root / ".scratch" / "phase-state.json"
    if not state.exists():
        return {}
    return _parse_json_text(state.read_text())


def _capture(fixture_root: Path, results: list[dict]) -> dict:
    return {
        "audit_entries": _read_audit(fixture_root),
        "final_state": _read_state(fixture_root),
        "exit_codes": [r["returncode"] for r in results],
    }


def _run_lifecycle_argv_sequence(fixture_root: Path, sequence: Iterable[list[str]]) -> dict:
    results = []
    for argv in sequence:
        cp = _run_harness(argv, cwd=fixture_root)
        results.append({"argv": argv, "returncode": cp.returncode, "stderr": cp.stderr})
        if cp.returncode != 0:
            raise RuntimeError(
                f"harness {' '.join(argv)} exited {cp.returncode} in {fixture_root}: {cp.stderr}"
            )
        # SHA invariant: last audit after_sha must exist AND match state sha.
        # M1: FAIL (not skip) when after_sha256 is missing — silent skip
        # would hide a contract violation in the runtime audit writer.
        entries = _read_audit(fixture_root)
        if entries:
            last = entries[-1]
            after = last.get("after_sha256")
            if not after:
                raise RuntimeError(
                    f"audit after_sha256 missing/empty for entry after {argv}; "
                    f"runtime audit writer contract violation"
                )
            actual = _state_sha(fixture_root)
            if actual and after != actual:
                raise RuntimeError(
                    f"drift: audit after_sha256 {after} != state sha {actual} after {argv}"
                )
    return _capture(fixture_root, results)


def _run_stage1_core(matrix_root: Path) -> dict:
    fixture = matrix_root / "stage1-core"
    copy_fixture(fixture)
    sequence = [inv["argv"] for inv in STAGE1_INVOCATIONS]
    capture = _run_lifecycle_argv_sequence(fixture, sequence)
    return canonicalize_capture(capture, tmp_prefix=str(matrix_root))


_HARNESS_INVOCATION_RE = re.compile(
    # Match either:
    #   `python3 scripts/harness.py <verb> <args...>`
    #   `harness <verb> <args...>`     (short form in docs)
    # We capture everything after the binary up to a comment marker (#)
    # or end of line. Backticks and code-fence whitespace are stripped
    # by the caller. We deliberately do NOT match the bare word
    # `harness.py` without `scripts/` so as to avoid false positives in
    # narrative prose.
    r"(?:python3\s+scripts/harness\.py|harness)\s+(phase\s+\S+(?:\s+(?!#)\S+)*?)(?=\s*(?:#|$))",
    re.MULTILINE,
)


def _extract_argv_from_markdown(path: Path) -> list[list[str]]:
    """Return all `harness <argv>` invocations found in a command markdown file.

    Parses both the short form (`harness phase set plan`) and the long
    form (`python3 scripts/harness.py phase set plan`). Trailing inline
    comments (`# ...`) are stripped. Backticks and code-fence noise are
    stripped before regex match. Returned argvs include only the
    arguments AFTER `harness`/`harness.py`.
    """
    text = path.read_text(encoding="utf-8")
    # Strip backticks so inline-code-wrapped invocations match.
    scrubbed = text.replace("`", " ")
    found: list[list[str]] = []
    for match in _HARNESS_INVOCATION_RE.finditer(scrubbed):
        argv = match.group(1).split()
        if argv:
            found.append(argv)
    return found


def _argv_prefix_matches(extracted: list[str], wanted: list[str]) -> bool:
    """True iff `extracted` argv starts with `wanted` (prefix match).

    Allows the markdown to embed extra optional flags after the verb
    while still being recognized as a dispatch for `wanted`.
    """
    if len(extracted) < len(wanted):
        return False
    return extracted[: len(wanted)] == wanted


def _execute_adapter_command_real(
    adapter_file: Path,
    wanted_argv: list[str],
    fixture_root: Path,
) -> subprocess.CompletedProcess:
    """C2: parse the adapter markdown file and execute the wanted verb
    via real subprocess against `fixture_root`.

    The markdown file MUST contain at least one `harness ...` invocation
    whose first two tokens match `wanted_argv` (i.e., the same verb
    *domain* — `phase set` or `phase approve`). This verifies the
    adapter actually advertises the verb being dispatched, without
    requiring per-token equality (lifecycle command files may list the
    *next* transition rather than the current entry verb; e.g.
    `phase-discuss.md` documents `phase set plan` as the leave-discuss
    step).

    Once the verb domain is confirmed, we dispatch `wanted_argv`
    verbatim (semantic-symmetry rule per spec §10.4: stages 2 and 3
    must produce the same audit log shape as stage 1).
    """
    if not adapter_file.exists():
        raise SystemExit(f"adapter command file missing: {adapter_file}")
    extracted = _extract_argv_from_markdown(adapter_file)
    if not extracted:
        raise RuntimeError(
            f"adapter file {adapter_file} contains no `harness ...` invocations; "
            f"cannot dispatch {wanted_argv!r}"
        )
    domain = wanted_argv[:2]  # e.g. ['phase', 'set'] or ['phase', 'approve']
    has_domain = any(_argv_prefix_matches(argv, domain) for argv in extracted)
    if not has_domain:
        raise RuntimeError(
            f"adapter file {adapter_file} has no invocation in domain {domain!r}; "
            f"extracted: {extracted!r}"
        )
    return _run_harness(wanted_argv, cwd=fixture_root)


def _assert_command_file_references_verb(path: Path, expected_verb_words: list[str]) -> None:
    """Ensure the adapter command file mentions the expected harness verb."""
    if not path.exists():
        raise RuntimeError(f"adapter command missing: {path}")
    text = path.read_text(encoding="utf-8")
    # All expected_verb_words must appear together in the file as a phrase.
    phrase = " ".join(expected_verb_words[:2])  # e.g., "phase set" or "phase approve"
    if phrase not in text:
        raise RuntimeError(
            f"adapter command {path} does not reference expected verb '{phrase}'"
        )


def _run_adapter_stage(
    matrix_root: Path,
    *,
    stage_name: str,
    adapter_dir: Path,
    adapter_key: str,
    open_tracker: list | None = None,
) -> dict:
    """C2: each lifecycle step dispatches via _execute_adapter_command_real,
    which parses the adapter markdown and runs the matching `harness ...`
    invocation as a real subprocess. The open_tracker (if provided) is
    appended with every adapter file path actually opened so quarantine
    assertions can be made by callers.
    """
    fixture = matrix_root / stage_name
    copy_fixture(fixture)
    results = []
    for inv in STAGE1_INVOCATIONS:
        cmd_file = adapter_dir / inv[adapter_key]
        if not cmd_file.exists():
            raise SystemExit(
                f"{stage_name}: adapter command file missing: {cmd_file}. "
                f"For Roo stage, see CONTRACT-PIN.md §5.2 (T1-S owns done.md)."
            )
        # Symmetry check: the command file MUST reference the expected verb.
        _assert_command_file_references_verb(cmd_file, inv["argv"])
        if open_tracker is not None:
            open_tracker.append(str(cmd_file))
        # Real dispatcher: parse markdown, extract argv, execute subprocess.
        cp = _execute_adapter_command_real(cmd_file, inv["argv"], fixture)
        results.append({"argv": inv["argv"], "returncode": cp.returncode, "stderr": cp.stderr})
        if cp.returncode != 0:
            raise RuntimeError(
                f"{stage_name}: harness {' '.join(inv['argv'])} exited {cp.returncode}: {cp.stderr}"
            )
    capture = _capture(fixture, results)
    return canonicalize_capture(capture, tmp_prefix=str(matrix_root))


def _run_stage2_roo(matrix_root: Path) -> dict:
    done = REPO_ROOT / ".roo" / "commands" / "done.md"
    if not done.exists():
        raise SystemExit(
            "T1-S has not landed yet; cannot run stage 2 (Roo lifecycle smoke). "
            "See CONTRACT-PIN.md §5.2."
        )
    return _run_adapter_stage(
        matrix_root,
        stage_name="stage2-roo",
        adapter_dir=REPO_ROOT / ".roo" / "commands",
        adapter_key="roo",
    )


def _run_stage3_opencode(matrix_root: Path) -> dict:
    # Spec text says `.opencode/commands/*.md`; both singular and plural are
    # accepted for forward compat. On-disk currently uses plural.
    plural = REPO_ROOT / ".opencode" / "commands"
    singular = REPO_ROOT / ".opencode" / "command"
    adapter_dir = plural if plural.exists() else singular
    return _run_adapter_stage(
        matrix_root,
        stage_name="stage3-opencode",
        adapter_dir=adapter_dir,
        adapter_key="opencode",
    )


_STATE_PATH_LITERAL = ".scratch/phase-state.json"

# Substring/literal write tokens (always matched as substrings; safe
# from boundary issues since they contain non-word characters).
_WRITE_LITERAL_TOKENS = (
    " > ", ">>", "dd of=", "printf >", "exec >", "cat <<",
)

# Word-boundary write verbs. Matched with \b<verb>\b so `write` does NOT
# match `rewrite`/`overwrite`. `sed -i` and `python -c` and `install`
# and `awk` etc. each have a distinct word so they match as single
# tokens. `tee`, `cp`, `mv`, `replace` likewise.
_WRITE_WORD_VERBS = (
    "write", "replace", "tee", "cp", "mv", "install", "awk",
)

# Multi-word verb patterns: anchored on the leading word boundary and
# then required to be followed by the specific tail (e.g., `sed` alone
# is too broad — only `sed -i` rewrites in place).
_WRITE_MULTIWORD_PATTERNS = (
    re.compile(r"\bsed\s+-i\b"),
    re.compile(r"\bpython\s+-c\b"),
)

# Back-compat alias (some external callers may import this).
_WRITE_VERBS = tuple(_WRITE_LITERAL_TOKENS) + tuple(f" {v} " for v in _WRITE_WORD_VERBS)


def _line_has_write_verb(line: str) -> bool:
    for tok in _WRITE_LITERAL_TOKENS:
        if tok in line:
            return True
    for verb in _WRITE_WORD_VERBS:
        if re.search(rf"\b{re.escape(verb)}\b", line):
            return True
    for pat in _WRITE_MULTIWORD_PATTERNS:
        if pat.search(line):
            return True
    return False


def run_grep_gate(*, root: Path | None = None) -> list[Violation]:
    """Static gate per spec §10.2: no quarantined command file may
    co-locate a write verb with the state file path on the same line.

    Design note (conservative-by-design): this is a substring-only gate.
    It does NOT parse markdown or strip comments, so a write verb
    embedded inside an HTML comment such as
    ``<!-- echo > .scratch/phase-state.json -->`` WILL be flagged. This
    is intentional: low-reasoning agents have been observed using
    "documentation" comments as a smuggling channel. Operators who need
    to mention the state path in a comment must phrase it without any
    of the tokens in ``_WRITE_LITERAL_TOKENS`` / ``_WRITE_WORD_VERBS`` /
    ``_WRITE_MULTIWORD_PATTERNS``. Treat this gate as defense-in-depth,
    not authoritative parsing.

    Limitation: this is a static grep gate; it is not exhaustive. Novel
    shell idioms (custom binaries, Python f-string redirection helpers,
    base64-decoded payloads) can still evade it. The verb table is
    intentionally pessimistic on common idioms and word-boundary-strict
    on `write` (so `rewrite`/`overwrite` in prose do NOT false-positive).
    """
    root = root or REPO_ROOT
    violations: list[Violation] = []
    for name in QUARANTINED_ROO_COMMANDS:
        path = root / ".roo" / "commands" / name
        if not path.exists():
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if _STATE_PATH_LITERAL not in line:
                continue
            if _line_has_write_verb(line):
                violations.append(Violation(file=str(path), line_number=i, line_text=line))
    return violations


def run_lifecycle_smoke(matrix_root: Path) -> None:
    """Orchestrate the three new stages plus static grep gate.

    Raises SystemExit on any failure; prints `STAGE n PASS` per stage.
    """
    matrix_root.mkdir(parents=True, exist_ok=True)
    violations = run_grep_gate()
    if violations:
        raise SystemExit(f"grep gate violations: {violations!r}")
    print("GREP GATE PASS")

    golden = load_golden()

    for stage_no, runner in [
        (1, _run_stage1_core),
        (2, _run_stage2_roo),
        (3, _run_stage3_opencode),
    ]:
        try:
            capture = runner(matrix_root)
        except SystemExit:
            raise
        except Exception as exc:
            print(f"STAGE {stage_no} FAILED: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        # Compare to golden (audit_entries shape + final_state shape).
        diff = _compare_to_golden(capture, golden, stage_no)
        if diff:
            print(f"STAGE {stage_no} FAILED: {diff}", file=sys.stderr)
            raise SystemExit(1)
        print(f"STAGE {stage_no} PASS")


_ARGS_REDACTED_KEYS = _REDACTED_KEYS | _ACTOR_KEYS


def _compare_args_canonical(golden_args: dict | None, capture_args: dict | None) -> str | None:
    """Compare audit-entry `args` payloads canonically.

    Redacted-key values (PID, MONOTONIC, ACTOR sentinels) are compared by
    key presence only, since their runtime values are non-deterministic.
    All other keys must match exactly after canonicalization.
    """
    g = canonicalize_capture(golden_args or {})
    c = canonicalize_capture(capture_args or {})
    g_keys = set(g.keys())
    c_keys = set(c.keys())
    if g_keys != c_keys:
        return f"args key set {sorted(c_keys)} != golden {sorted(g_keys)}"
    for key in g_keys:
        if key in _ARGS_REDACTED_KEYS:
            continue
        if g[key] != c[key]:
            return f"args[{key!r}] {c[key]!r} != golden {g[key]!r}"
    return None


def _compare_to_golden(capture: dict, golden: dict, stage_no: int) -> str | None:
    """Structural compare against the hand-authored golden.

    The golden encodes the EXPECTED SHAPE — verb names, args, final
    phase/approved/schema_version — not byte-by-byte runtime equality,
    which would force regeneration. We assert:
      - audit_entries length matches
      - each entry's `verb` matches in order
      - each entry's `args` matches canonically
      - each entry has both `before_sha256` and `after_sha256` keys (presence only)
      - final_state.phase matches
      - final_state.approved matches
      - final_state.state_schema_version matches
      - all exit codes are within the pinned table (0..8).
    """
    g_entries = golden.get("audit_entries", [])
    c_entries = capture.get("audit_entries", [])
    if len(c_entries) != len(g_entries):
        return f"audit_entries length {len(c_entries)} != golden {len(g_entries)}"
    for idx, (g, c) in enumerate(zip(g_entries, c_entries)):
        if g.get("verb") != c.get("verb"):
            return f"audit_entries[{idx}].verb {c.get('verb')!r} != golden {g.get('verb')!r}"
        args_diff = _compare_args_canonical(g.get("args"), c.get("args"))
        if args_diff:
            return f"audit_entries[{idx}].{args_diff}"
        for sha_key in ("before_sha256", "after_sha256"):
            if sha_key in g and sha_key not in c:
                return f"audit_entries[{idx}] missing {sha_key} key"
    g_final = golden.get("final_state") or {}
    c_final = capture.get("final_state") or {}
    if g_final.get("phase") != c_final.get("phase"):
        return f"final_state.phase {c_final.get('phase')!r} != golden {g_final.get('phase')!r}"
    if "approved" in g_final and g_final.get("approved") != "<ANY>" and g_final.get("approved") != c_final.get("approved"):
        return f"final_state.approved {c_final.get('approved')!r} != golden {g_final.get('approved')!r}"
    # T0-3 follow-up: state_schema_version is contractually pinned to 2 on
    # every write (phase set / phase approve both stamp it). The <ANY>
    # sentinel handling for THIS field was a workaround for the gap that
    # the follow-up closes; the golden now carries the literal 2 and the
    # comparator enforces it strictly. (The <ANY> sentinel remains valid
    # for approved/approved_at/approved_by per ADR-001.)
    if "state_schema_version" in g_final and g_final.get("state_schema_version") != c_final.get("state_schema_version"):
        return (
            f"final_state.state_schema_version {c_final.get('state_schema_version')!r} "
            f"!= golden {g_final.get('state_schema_version')!r}"
        )
    for ec in capture.get("exit_codes", []):
        if ec not in {0, 1, 2, 3, 4, 5, 6, 7, 8}:
            return f"exit_code {ec} outside CONTRACT-PIN §4 table"
    return None
