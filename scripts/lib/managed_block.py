"""Markdown HTML-comment managed marker blocks for harness-owned regions."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import unicodedata

BEGIN_MARKER_FMT = "<!-- HARNESS:BEGIN managed:{slug} v1 -->"
END_MARKER_FMT = "<!-- HARNESS:END managed:{slug} -->"

_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def _validate_slug(slug: str) -> None:
    if not _SLUG_RE.fullmatch(slug):
        raise ValueError(f"Invalid managed-block slug: {slug!r}")


def canonicalize(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip(" \t") for line in normalized.split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def payload_hash(payload: str) -> str:
    return hashlib.sha256(canonicalize(payload).encode("utf-8")).hexdigest()


def render_block(slug: str, payload: str) -> str:
    _validate_slug(slug)
    canonical = canonicalize(payload)
    return (
        BEGIN_MARKER_FMT.format(slug=slug)
        + "\n"
        + canonical
        + END_MARKER_FMT.format(slug=slug)
        + "\n"
    )


@dataclass(frozen=True)
class ParsedBlock:
    slug: str
    start: int   # character index of begin-marker line
    end: int     # character index just after end-marker line's trailing newline
    payload: str
    hash: str


class MissingBlockError(LookupError):
    """Raised when a requested managed-block slug is absent from the text."""


_BLOCK_RE = re.compile(
    r"^<!-- HARNESS:BEGIN managed:(?P<slug>[a-z][a-z0-9-]*) v1 -->\n"
    r"(?P<payload>.*?)"
    r"^<!-- HARNESS:END managed:(?P=slug) -->\n",
    re.MULTILINE | re.DOTALL,
)


def parse_blocks(text: str) -> dict[str, ParsedBlock]:
    result: dict[str, ParsedBlock] = {}
    for match in _BLOCK_RE.finditer(text):
        slug = match.group("slug")
        if slug in result:
            raise ValueError(f"Duplicate managed-block slug: {slug!r}")
        payload = match.group("payload")
        result[slug] = ParsedBlock(
            slug=slug,
            start=match.start(),
            end=match.end(),
            payload=payload,
            hash=payload_hash(payload),
        )

    # Detect unclosed BEGIN markers (BEGIN without matching END).
    begin_lines = re.findall(
        r"^<!-- HARNESS:BEGIN managed:([a-z][a-z0-9-]*) v1 -->$",
        text,
        re.MULTILINE,
    )
    end_lines = re.findall(
        r"^<!-- HARNESS:END managed:([a-z][a-z0-9-]*) -->$",
        text,
        re.MULTILINE,
    )
    if len(begin_lines) != len(end_lines) or sorted(begin_lines) != sorted(end_lines):
        raise ValueError("Unbalanced managed-block markers")
    if len(result) != len(begin_lines):
        raise ValueError("Malformed managed-block (begin/end mismatch)")
    return result


def replace_block(text: str, slug: str, new_payload: str) -> str:
    _validate_slug(slug)
    blocks = parse_blocks(text)
    if slug not in blocks:
        raise MissingBlockError(f"Managed block not found: managed:{slug}")
    parsed = blocks[slug]
    rendered = render_block(slug, new_payload)
    return text[: parsed.start] + rendered + text[parsed.end :]
