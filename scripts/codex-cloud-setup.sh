#!/usr/bin/env bash
set -euo pipefail

echo "Codex Cloud setup for hjung3113/general-low-reasoning-agent-harness"
python3 --version
python3 scripts/harness.py check

