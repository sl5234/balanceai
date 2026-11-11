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

## No real data or secrets in the repo

Never write real data (transaction ids, merchants, amounts, account numbers,
journal ids, names) or credentials into any file or commit message — docs,
prompts, tests, code. Use made-up examples, e.g. "a $12.50 charge at Blue
Bottle Coffee".

## Git workflow

- Work on a feature branch (`feature/<topic>`), never on `main`.
- When the work is done: run the pre-commit checklist in
  `src/balanceai_backend/DEVELOPMENT.md` (including the leak and security checks),
  squash the branch into a single commit, and push the feature branch.
- The user opens the PR and merges it into `main` on GitHub. `gh` can't reach
  GitHub from the sandbox, so give the PR link
  (`https://github.com/sl5234/balanceai/pull/new/<branch>`) instead.
- After the user merges: `git checkout main && git pull --rebase`, delete the
  merged branch, and create a new feature branch for the next work.
