"""Anthropic Haiku-4.5 model client wrapper (02b-10).

Plan: .planning/phases/02b-hardening/plans/02b-10-PHASE-E-HARNESS-PLAN.md §6.2.

Pinned: model="claude-haiku-4-5-20251001", temperature=0, max_tokens=4000.

Reads `ANTHROPIC_API_KEY` from env; raises `RuntimeError` if absent.
Falls back to `urllib.request` if the `anthropic` SDK is not installed.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from .fake_client import ModelResponse


HAIKU_MODEL_ID = "claude-haiku-4-5-20251001"
DEFAULT_TEMPERATURE = 0.0
DEFAULT_MAX_TOKENS = 4000
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

# C3 — transport retry policy.
MAX_TRANSPORT_ATTEMPTS = 3
BACKOFF_SECONDS = (1.0, 2.0, 4.0)
RETRYABLE_HTTP_CODES = frozenset({429, 500, 502, 503, 504})


class HttpTransportError(RuntimeError):
    """Raised when retryable HTTP transport (429/5xx) exhausts the retry budget.

    Distinct from the bare RuntimeError raised for non-retryable HTTP errors
    so the runner can attribute it as a transport-level trial failure rather
    than aborting the suite.
    """


@dataclass
class HaikuClient:
    model: str = HAIKU_MODEL_ID
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = DEFAULT_MAX_TOKENS
    last_call: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "HaikuClient: ANTHROPIC_API_KEY not set in environment. "
                "Run with `--live` only when the key is exported, or use "
                "--summarize-only / dry-run."
            )

    def respond(self, prompt: str) -> ModelResponse:
        api_key = os.environ["ANTHROPIC_API_KEY"]
        body = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        self.last_call = {
            "prompt": prompt,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            ANTHROPIC_URL,
            data=data,
            headers={
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            method="POST",
        )
        t0 = time.monotonic()
        last_exc: Exception | None = None
        payload = None
        for attempt in range(MAX_TRANSPORT_ATTEMPTS):
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                code = exc.code
                if code in RETRYABLE_HTTP_CODES and attempt < MAX_TRANSPORT_ATTEMPTS - 1:
                    last_exc = exc
                    time.sleep(BACKOFF_SECONDS[attempt])
                    continue
                if code in RETRYABLE_HTTP_CODES:
                    raise HttpTransportError(
                        f"HaikuClient: HTTP {code} after {MAX_TRANSPORT_ATTEMPTS} attempts"
                    ) from exc
                raise RuntimeError(
                    f"HaikuClient: HTTP {code} from Anthropic API: {exc.read()[:500]!r}"
                ) from exc
        if payload is None:
            raise HttpTransportError(
                f"HaikuClient: transport exhausted ({last_exc!r})"
            )
        wall = time.monotonic() - t0
        text_parts = []
        for block in payload.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
        text = "".join(text_parts)
        usage = payload.get("usage", {}) or {}
        return ModelResponse(
            text=text,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            wall_clock_seconds=wall,
        )
