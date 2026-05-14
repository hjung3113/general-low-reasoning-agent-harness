---
name: tech-python
description: Use when repository evidence confirms Python is in scope. Keeps Python commands, packaging, typing, and test assumptions evidence-based.
---

# Tech Python

Use only after Python is confirmed by repository evidence or user direction.

## Evidence

Look for `pyproject.toml`, `requirements.txt`, `environment.yml`, `uv.lock`, `poetry.lock`, Python source files, tests, notebooks, or scripts.

## Rules

- Do not assume `pip`, `uv`, Poetry, Conda, pytest, unittest, pandas, or notebooks.
- Record the actual package manager and test command before execute.
- Prefer importable modules for durable logic.
- Keep generated files and data artifacts out of source unless the plan approves them.

## Verification

Use only commands present in the target project, such as `python -m pytest`, `python -m unittest`, `uv run pytest`, or a repository script.

