"""In-memory model client doubles for unit-testing the smoke runner (02b-10).

`FakeClient` implements the same `respond(prompt)` interface as `HaikuClient`
but returns scripted responses with no network call. Tests use it to drive
the runner deterministically and to verify temperature/model pinning.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class ModelResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    wall_clock_seconds: float = 0.0


@dataclass
class FakeClient:
    """Deterministic test double.

    Args:
      scripted_responses: list of strings; each call to respond() pops one.
      scripted_token_counts: optional list of (input_tokens, output_tokens) tuples.
      scripted_wall_seconds: optional list of float wall-clock seconds per call.
      model: pinned model id (default matches the production pin).
      temperature: pinned temperature (default 0).
    """

    scripted_responses: list[str] = field(default_factory=list)
    scripted_token_counts: list[tuple[int, int]] | None = None
    scripted_wall_seconds: list[float] | None = None
    # If True, actually sleep so the runner's real monotonic clock (post-C2
    # honesty fix) observes the delay. Kept off by default to keep unit tests
    # fast — tests that want to exercise the budget cap should monkey-patch
    # `scripts.smoke.runner.time.monotonic` instead of relying on real sleep.
    sleep_for_scripted_wall: bool = False
    model: str = "claude-haiku-4-5-20251001"
    temperature: float = 0.0
    max_tokens: int = 4000

    calls: list[dict] = field(default_factory=list)
    last_call: dict = field(default_factory=dict)
    _index: int = 0

    def respond(self, prompt: str) -> ModelResponse:
        idx = self._index
        if idx >= len(self.scripted_responses):
            raise RuntimeError(
                f"FakeClient: scripted_responses exhausted (index={idx}, "
                f"len={len(self.scripted_responses)})"
            )
        text = self.scripted_responses[idx]
        if self.scripted_token_counts and idx < len(self.scripted_token_counts):
            in_tok, out_tok = self.scripted_token_counts[idx]
        else:
            in_tok, out_tok = (len(prompt) // 4, len(text) // 4)
        if self.scripted_wall_seconds and idx < len(self.scripted_wall_seconds):
            wall = self.scripted_wall_seconds[idx]
        else:
            wall = 0.01
        if self.sleep_for_scripted_wall and wall > 0:
            time.sleep(wall)
        self.last_call = {
            "prompt": prompt,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        self.calls.append(dict(self.last_call))
        self._index += 1
        return ModelResponse(
            text=text,
            input_tokens=in_tok,
            output_tokens=out_tok,
            wall_clock_seconds=wall,
        )
