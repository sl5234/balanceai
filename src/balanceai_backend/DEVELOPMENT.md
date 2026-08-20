# Development Commands

This document lists all commands for building, linting, formatting, and testing the
`balanceai_backend` package. Agents should run these commands after code changes.

**All commands below are run from within this directory (`src/balanceai_backend/`).**

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

# 4. Run tests
pytest

# 5. Build
python -m build
```
