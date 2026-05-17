"""Top-level conftest for the harness test suite.

Autouse fixtures that apply to ALL tests across ALL subdirectories.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_autopilot_network_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent run_start's HARNESS_AUTOPILOT_NETWORK mutation from leaking across tests.

    run_start() calls ``os.environ["HARNESS_AUTOPILOT_NETWORK"] = "deny"`` (or "allow")
    as a side effect. Without isolation this mutation persists into subsequent tests
    in the same process, causing false passes/failures depending on test ordering.

    This fixture unconditionally removes the env var before (and after, via monkeypatch
    teardown) every test so each test starts from a clean slate.
    """
    monkeypatch.delenv("HARNESS_AUTOPILOT_NETWORK", raising=False)
    yield
