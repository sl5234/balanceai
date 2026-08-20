# Claude Code Instructions

This is a monorepo with three self-contained packages under `src/`:
- `src/balanceai_backend/` — Python backend (MCP servers, bookkeeping logic)
- `src/balanceai_frontend/` — Expo/React Native app
- `src/balanceai_infrastructure/` — AWS CDK (TypeScript)

For backend changes: read `src/balanceai_backend/DEVELOPMENT.md` before making any code
changes. It contains the setup, linting, formatting, and testing commands required for
that package.

Key points:
- All backend commands run from within `src/balanceai_backend/`. Always activate its venv
  before running any commands: `cd src/balanceai_backend && source venv/bin/activate`
- After code changes, run the pre-commit checklist in `src/balanceai_backend/DEVELOPMENT.md`
  (format → lint → type check → test)
- Use `pytest tests/ -v` for unit tests, `pytest integ_tests/ -v` for integration tests (run
  from within `src/balanceai_backend/`)
