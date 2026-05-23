"""Auto-populate sections 2-4 of .planning/codebase-recon.md.

Pure functions for tech-stack detection, depth-2 dir tree generation,
and existing doc listing. The ``build_recon_doc`` orchestrator stitches
them together and performs a section-preserving merge with any existing
codebase-recon.md content.

Used by ``harness recon`` CLI subcommand.
"""

from __future__ import annotations

import re
import subprocess
from datetime import date
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEMPLATE_PATH_RELATIVE = Path("harness/skeleton/clean/.planning/codebase-recon.md")

_EXCLUDED_DIRS = {
    ".git", "node_modules", ".venv", "venv", "dist", "build",
    "__pycache__", ".pytest_cache", ".harness", ".scratch",
}
# Planning sub-directory to exclude (relative inside .planning/)
_PLANNING_EXCLUDE_SUBDIR = "phases"

# Canonical doc filenames to look for (depth 0-2)
_DOC_FILENAMES = {
    "AGENTS.md", "CLAUDE.md", "CONTEXT.md", "README.md", "MANUAL.md",
}

# Section header regex: "## N. Title"
_SECTION_RE = re.compile(r"^## \d+\.", re.MULTILINE)

# Template placeholder patterns that count as "empty / default"
_PLACEHOLDER_PATTERN = re.compile(r"<!--[^>]*-->")


# ---------------------------------------------------------------------------
# Tech-stack detection
# ---------------------------------------------------------------------------

def detect_tech_stack(root: Path, scope: Optional[list[str]] = None) -> dict[str, list[str]]:
    """Return detected tech stacks: {'languages': [...], 'test_runners': [...], 'ci': [...]}.

    ``scope`` optionally restricts glob searches to the given subdirectories.
    """
    search_roots: list[Path] = []
    if scope:
        for s in scope:
            d = root / s
            if d.is_dir():
                search_roots.append(d)
    if not search_roots:
        search_roots = [root]

    def _exists_any(*patterns: str) -> bool:
        for pattern in patterns:
            for sr in search_roots:
                if list(sr.rglob(pattern)):
                    return True
                # Also check root-level for pyproject etc.
            if list(root.glob(pattern)):
                return True
        return False

    def _glob_root(*patterns: str) -> bool:
        for pattern in patterns:
            if list(root.glob(pattern)):
                return True
        return False

    languages: list[str] = []
    test_runners: list[str] = []
    ci_systems: list[str] = []

    # --- Languages ---
    if _glob_root("pyproject.toml") or _glob_root("requirements*.txt") or _glob_root("setup.py"):
        languages.append("Python")
    if _glob_root("package.json"):
        languages.append("Node")
    if _glob_root("Cargo.toml"):
        languages.append("Rust")
    if _glob_root("go.mod"):
        languages.append("Go")
    if _glob_root("Gemfile"):
        languages.append("Ruby")
    if list(root.rglob("*.csproj")):
        languages.append("C#")
    if _glob_root("pom.xml") or _glob_root("build.gradle"):
        languages.append("Java")

    # --- Test runners ---
    if (root / "tests").is_dir():
        test_runners.append("pytest")
    pkg_json = root / "package.json"
    if pkg_json.exists():
        try:
            import json as _json
            pkg = _json.loads(pkg_json.read_text(encoding="utf-8"))
            scripts = pkg.get("scripts", {})
            combined = " ".join(scripts.values()).lower()
            if "jest" in combined:
                test_runners.append("jest")
            if "vitest" in combined:
                test_runners.append("vitest")
        except Exception:
            pass
    if _glob_root("Cargo.toml"):
        test_runners.append("cargo test")
    if _glob_root("go.mod"):
        test_runners.append("go test")

    # --- CI ---
    if (root / ".github" / "workflows").is_dir():
        ci_systems.append("GitHub Actions")
    if (root / ".gitlab-ci.yml").exists():
        ci_systems.append("GitLab CI")
    if (root / "circle.yml").exists() or (root / ".circleci").is_dir():
        ci_systems.append("CircleCI")
    if (root / "Jenkinsfile").exists():
        ci_systems.append("Jenkins")
    if (root / ".travis.yml").exists():
        ci_systems.append("Travis CI")

    return {
        "languages": languages,
        "test_runners": test_runners,
        "ci": ci_systems,
    }


def render_tech_stack_section(stack: dict[str, list[str]], today: Optional[str] = None) -> str:
    """Render section 2 content (excluding the ## header line)."""
    if today is None:
        today = str(date.today())

    lines: list[str] = [f"<!-- auto-detected on {today} -->"]

    langs = stack.get("languages") or []
    runners = stack.get("test_runners") or []
    ci = stack.get("ci") or []

    if langs:
        lines.append(f"- **Language(s):** {', '.join(langs)}")
    else:
        lines.append("- **Language(s):** (none detected)")

    if runners:
        lines.append(f"- **Test runner(s):** {', '.join(runners)}")
    else:
        lines.append("- **Test runner(s):** (none detected)")

    if ci:
        lines.append(f"- **CI:** {', '.join(ci)}")
    else:
        lines.append("- **CI:** (none detected)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Depth-2 directory tree
# ---------------------------------------------------------------------------

def _dir_annotation(d: Path) -> str:
    """Return a ≤5-word annotation inferred from directory name / contents."""
    name = d.name.lower()
    # Common well-known names
    known: dict[str, str] = {
        "src": "main source code",
        "lib": "library modules",
        "scripts": "automation scripts",
        "tests": "test suite",
        "test": "test suite",
        "docs": "documentation",
        "doc": "documentation",
        ".github": "GitHub Actions CI",
        ".roo": "Roo adapter files",
        ".opencode": "OpenCode adapter files",
        ".harness": "harness install state",
        ".planning": "planning documents",
        ".scratch": "scratch workspace",
        "fixtures": "test fixtures",
        "harness": "harness source tree",
        "skeleton": "project skeleton templates",
        "dist": "build output",
        "build": "build output",
        "node_modules": "npm dependencies",
        ".venv": "Python virtual environment",
        "venv": "Python virtual environment",
        "assets": "static assets",
        "public": "public web assets",
        "static": "static files",
        "config": "configuration files",
        "configs": "configuration files",
        "bin": "executable binaries",
        "cmd": "command entrypoints",
        "pkg": "package modules",
        "internal": "internal packages",
        "api": "API definitions",
        "models": "data models",
        "views": "view layer",
        "templates": "template files",
        "migrations": "database migrations",
        "data": "data files",
        "examples": "example projects",
        "demo": "demo files",
        "tools": "developer tooling",
        "util": "utility modules",
        "utils": "utility modules",
        "vendor": "vendored dependencies",
        "third_party": "third-party code",
        "site-packages": "installed packages",
    }
    if name in known:
        return known[name]
    # Fallback: return the dir name itself (max 5 words by replacing _ with space)
    label = d.name.replace("_", " ").replace("-", " ")
    words = label.split()
    return " ".join(words[:5])


def _should_exclude(d: Path, root: Path) -> bool:
    """Return True if directory should be excluded from tree output."""
    if d.name in _EXCLUDED_DIRS:
        return True
    # Exclude .planning/phases
    try:
        rel = d.relative_to(root)
        parts = rel.parts
        if len(parts) >= 2 and parts[0] == ".planning" and parts[1] == _PLANNING_EXCLUDE_SUBDIR:
            return True
    except ValueError:
        pass
    return False


def build_dir_tree(root: Path, scope: Optional[list[str]] = None) -> list[tuple[Path, str]]:
    """Return list of (abs_path, annotation) for depth-1 and depth-2 dirs.

    ``scope`` restricts the depth-1 listing to specified subdirectory names.
    """
    results: list[tuple[Path, str]] = []

    # Determine top-level dirs to include
    top_dirs: list[Path] = []
    if scope:
        for s in scope:
            d = root / s
            if d.is_dir() and not _should_exclude(d, root):
                top_dirs.append(d)
    else:
        for d in sorted(root.iterdir()):
            if d.is_dir() and not _should_exclude(d, root):
                top_dirs.append(d)

    for d in top_dirs:
        results.append((d, _dir_annotation(d)))
        for sub in sorted(d.iterdir()):
            if sub.is_dir() and not _should_exclude(sub, root):
                results.append((sub, _dir_annotation(sub)))

    return results


def render_dir_tree_section(root: Path, tree: list[tuple[Path, str]]) -> str:
    """Render section 3 content (excluding the ## header line)."""
    lines: list[str] = []
    for d, annotation in tree:
        try:
            rel = d.relative_to(root)
        except ValueError:
            rel = d
        depth = len(rel.parts)
        prefix = "  " * (depth - 1)
        lines.append(f"{prefix}- `{rel}/` — {annotation}")
    if not lines:
        lines.append("(no directories found)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Existing docs listing
# ---------------------------------------------------------------------------

def find_existing_docs(root: Path) -> list[Path]:
    """Return sorted list of doc paths relative to root (depth 0-2)."""
    found: list[Path] = []

    # Depth 0 exact names
    for name in _DOC_FILENAMES:
        p = root / name
        if p.exists():
            found.append(p.relative_to(root))

    # docs/*.md
    docs_dir = root / "docs"
    if docs_dir.is_dir():
        for p in sorted(docs_dir.glob("*.md")):
            found.append(p.relative_to(root))
        # docs/adr/*.md
        adr_dir = docs_dir / "adr"
        if adr_dir.is_dir():
            for p in sorted(adr_dir.glob("*.md")):
                found.append(p.relative_to(root))

    # Depth 1 dirs: look for the canonical filenames
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name in _EXCLUDED_DIRS:
            continue
        for name in _DOC_FILENAMES:
            p = d / name
            if p.exists():
                rel = p.relative_to(root)
                if rel not in found:
                    found.append(rel)

    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped: list[Path] = []
    for p in found:
        key = str(p)
        if key not in seen:
            seen.add(key)
            deduped.append(p)

    return deduped


def render_docs_section(docs: list[Path]) -> str:
    """Render section 4 content (excluding the ## header line)."""
    if not docs:
        return "(no documentation files found)"
    return "\n".join(f"- `{p}`" for p in docs)


# ---------------------------------------------------------------------------
# Section-preserving merge
# ---------------------------------------------------------------------------

def _split_sections(text: str) -> list[str]:
    """Split markdown text into a list of 5 section chunks.

    Each chunk begins with its '## N. ' header (or is empty string if absent).
    Returns a list of exactly 5 elements.
    """
    # Find all section header positions
    matches = list(_SECTION_RE.finditer(text))
    if not matches:
        # No sections found — return all as section 1, rest empty
        return [text, "", "", "", ""]

    chunks: list[str] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunks.append(text[start:end].rstrip())

    # Pad to 5 sections
    while len(chunks) < 5:
        chunks.append("")

    return chunks[:5]


def _is_user_owned_empty(section_body: str) -> bool:
    """Return True if a section body has only template comments / whitespace (no real user content)."""
    # Strip the header line
    lines = section_body.splitlines()
    content_lines = lines[1:] if lines else []  # skip header
    # Remove empty lines and comment-only lines
    meaningful = [
        ln for ln in content_lines
        if ln.strip() and not ln.strip().startswith("<!--")
    ]
    return len(meaningful) == 0


def _section_header_from_template(section_idx: int, template_text: str) -> str:
    """Extract a section header line from the template by section index (0-based)."""
    matches = list(_SECTION_RE.finditer(template_text))
    if section_idx < len(matches):
        m = matches[section_idx]
        end = template_text.find("\n", m.start())
        return template_text[m.start(): end if end != -1 else len(template_text)]
    # Fallback headers
    fallbacks = [
        "## 1. One-liner — what is this project?",
        "## 2. Tech stack",
        "## 3. Top-level structure (depth 2)",
        "## 4. Existing docs found",
        "## 5. Open questions",
    ]
    return fallbacks[section_idx]


_USER_PLACEHOLDER = {
    0: "<!-- User or agent: 2-3 sentences -->",
    4: "<!-- Agent-flagged unknowns for user to answer -->",
}


def build_recon_doc(
    root: Path,
    scope: Optional[list[str]] = None,
    existing_text: Optional[str] = None,
    template_text: Optional[str] = None,
    today: Optional[str] = None,
) -> str:
    """Build the full codebase-recon.md content.

    Parameters
    ----------
    root:
        Project root directory to scan.
    scope:
        Optional subdirectory names to restrict depth-2 tree scan.
    existing_text:
        Current content of .planning/codebase-recon.md (if it exists).
        Sections 1 and 5 are preserved if they contain real user content.
    template_text:
        Template file content. Used to seed section headers if not present.
    today:
        ISO date string override (for deterministic tests).
    """
    if today is None:
        today = str(date.today())

    # Resolve template
    if template_text is None:
        template_path = root / TEMPLATE_PATH_RELATIVE
        if not template_path.exists():
            # Fallback minimal template
            template_text = (
                "# Codebase Recon\n\n"
                "## 1. One-liner — what is this project?\n"
                "<!-- User or agent: 2-3 sentences -->\n\n"
                "## 2. Tech stack\n"
                "<!-- Auto-detected: language, build tool, test runner, CI -->\n\n"
                "## 3. Top-level structure (depth 2)\n"
                "<!-- Tree, 5 words per dir -->\n\n"
                "## 4. Existing docs found\n"
                "<!-- Paths to AGENTS.md, CONTEXT.md, README.md, docs/, etc. -->\n\n"
                "## 5. Open questions\n"
                "<!-- Agent-flagged unknowns for user to answer -->\n"
            )
        else:
            template_text = template_path.read_text(encoding="utf-8")

    # Parse existing sections (or use template as baseline)
    base_text = existing_text if existing_text is not None else template_text
    sections = _split_sections(base_text)

    # Generate auto-detected content
    stack = detect_tech_stack(root, scope=scope)
    tree = build_dir_tree(root, scope=scope)
    docs = find_existing_docs(root)

    sec2_body = render_tech_stack_section(stack, today=today)
    sec3_body = render_dir_tree_section(root, tree)
    sec4_body = render_docs_section(docs)

    # Rebuild each section
    def _header(idx: int) -> str:
        # Try to get header from existing section first
        existing_sec = sections[idx] if idx < len(sections) else ""
        if existing_sec:
            first_line = existing_sec.splitlines()[0]
            if first_line.startswith("## "):
                return first_line
        return _section_header_from_template(idx, template_text)

    def _build_section(idx: int, auto_body: str) -> str:
        return f"{_header(idx)}\n{auto_body}"

    def _build_user_section(idx: int) -> str:
        existing_sec = sections[idx] if idx < len(sections) else ""
        if existing_sec and not _is_user_owned_empty(existing_sec):
            # User has written real content — preserve it
            return existing_sec
        # Insert placeholder
        placeholder = _USER_PLACEHOLDER.get(idx, "<!-- (empty) -->")
        return f"{_header(idx)}\n{placeholder}"

    # Extract the preamble (everything before first ## section)
    preamble = ""
    first_match = _SECTION_RE.search(base_text)
    if first_match and first_match.start() > 0:
        preamble = base_text[: first_match.start()].rstrip()
    elif template_text:
        tm = _SECTION_RE.search(template_text)
        if tm and tm.start() > 0:
            preamble = template_text[: tm.start()].rstrip()

    parts: list[str] = []
    if preamble:
        parts.append(preamble)
    parts.append(_build_user_section(0))   # section 1: user-owned
    parts.append(_build_section(1, sec2_body))  # section 2: auto
    parts.append(_build_section(2, sec3_body))  # section 3: auto
    parts.append(_build_section(3, sec4_body))  # section 4: auto
    parts.append(_build_user_section(4))   # section 5: user-owned

    return "\n\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# Dry-run diff helper
# ---------------------------------------------------------------------------

def compute_unified_diff(old_text: str, new_text: str, path: str = ".planning/codebase-recon.md") -> str:
    """Return a unified diff string between old_text and new_text."""
    import difflib
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    return "".join(diff)
