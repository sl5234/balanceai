# Project Designs & Architecture

This document tracks the current design decisions and project structure for BalanceAI.

## Project Structure

```
BalanceAI/
├── src/
│   └── balanceai/
│       └── __init__.py
├── tests/
│   └── __init__.py
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt (optional)
├── README.md
├── DEVELOPMENT.md
├── AGENTS.md
├── DESIGNS.md
└── .gitignore
```

## Current Design Decisions

### Package Structure
- **Location**: `src/balanceai/` (src-layout pattern)
- **Rationale**: Keeps package code separate from tests and config files
- **Installation**: Editable install (`pip install -e .`) for development

### Dependencies
- **Core**: `appdevcommons` (required)
- **Build System**: `setuptools` with `pyproject.toml`
- **Dev Tools**: `pytest`, `black`, `ruff` (optional)

### Python Version
- **Minimum**: Python 3.12
- **Rationale**: Use modern Python features and performance improvements

### Code Style
- **Formatter**: Black (line length: 100)
- **Linter**: Ruff (line length: 100, target: Python 3.12)
- **Type Checking**: Not configured yet (can add mypy later)

## Design Principles

1. **Minimal MVP**: Start simple, add complexity only when needed
2. **Dependency on appdevcommons**: Leverage common utilities
3. **Modular**: Keep code organized in logical modules
4. **Testable**: Structure code to be easily testable