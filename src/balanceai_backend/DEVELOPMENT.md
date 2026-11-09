# Development Commands

This document lists all commands for building, linting, formatting, and testing the
`balanceai_backend` package. Agents should run these commands after code changes.

**All commands below are run from within this directory (`src/balanceai_backend/`).**

Secrets and local data live in `src/balanceai_backend_secrets/` (git-ignored), outside
this package so tools that scan it never touch them: `.env` (copy `.env.example`) and
`data/` (the SQLite database). Tests use a temp data folder and no `.env`.

## Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install package in editable mode with dev dependencies
pip install -e ".[dev]"
```

## Build

```bash
# Build the package
python -m build

# Clean build artifacts
rm -rf dist/ build/ *.egg-info
```

## Linting

```bash
# Run ruff linter
ruff check .

# Run ruff with auto-fix
ruff check --fix .
```

## Formatting

```bash
# Format code with black
black .

# Check formatting without making changes
black --check .
```

## Type Checking

```bash
# Run mypy type checker (excludes venv/, tests/, integ_tests/ — see pyproject.toml)
mypy .
```

## Testing

```bash
# Run all tests
pytest

# Run tests with coverage
pytest --cov=balanceai_backend --cov-report=html

# Run tests verbosely
pytest -v

# Run unit tests
pytest tests/ -v

# Run specific test file
pytest tests/test_specific.py

# Run integ tests
pytest integ_tests/ -v
```

## Pre-Commit Checklist

After making code changes, run these commands in order:

```bash
# 1. Format code
black .

# 2. Lint code
ruff check --fix .

# 3. Type check code
mypy .

# 4. Run unit tests
pytest tests/

# 4b. (Optional) Run integration tests — they call real AI APIs and cost money
pytest integ_tests/

# 5. Build
python -m build

# 6. Check for leaks in what you're committing: no credentials (API keys,
#    tokens, passwords, Plaid access tokens) and no real data from the DB or
#    logs (transaction ids, merchants, amounts, account numbers, journal ids).
#    Use made-up values in code, prompts, tests and docs. The gitleaks
#    pre-commit hook (.pre-commit-config.yaml) catches credentials, not real data.
git diff --cached

# 7. Check for new security risks: transaction data reaching the assistant or
#    an AI provider without the user's consent, consent prompts that can
#    mislead, data in error messages, SQL that isn't read-only. Run
#    /security-review for larger changes.
```
