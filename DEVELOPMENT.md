# Development Commands

This document lists all commands for building, linting, formatting, and testing the project. Agents should run these commands after code changes.

## Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

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
ruff check src/ tests/

# Run ruff with auto-fix
ruff check --fix src/ tests/
```

## Formatting

```bash
# Format code with black
black src/ tests/

# Check formatting without making changes
black --check src/ tests/
```

## Type Checking

```bash
# Run mypy type checker (if configured)
mypy src/
```

## Testing

```bash
# Run all tests
pytest

# Run tests with coverage
pytest --cov=src/balanceai --cov-report=html

# Run tests verbosely
pytest -v

# Run specific test file
pytest tests/test_specific.py
```

## Pre-Commit Checklist

After making code changes, run these commands in order:

```bash
# 1. Format code
black src/ tests/

# 2. Lint code
ruff check --fix src/ tests/

# 3. Run tests
pytest

# 4. Build (to ensure package structure is correct)
python -m build
```

