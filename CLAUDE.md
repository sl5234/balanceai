# Claude Code Instructions

Read DEVELOPMENT.md before making any code changes. It contains the setup, linting, formatting, and testing commands required for this project.

Key points:
- Always activate the venv before running any commands: `source venv/bin/activate`
- After code changes, run the pre-commit checklist in DEVELOPMENT.md (format → lint → type check → test)
- Use `pytest tests/ -v` for unit tests, `pytest integ_tests/ -v` for integration tests
