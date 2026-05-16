"""Markdown HTML-comment managed marker blocks for harness-owned regions."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

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
