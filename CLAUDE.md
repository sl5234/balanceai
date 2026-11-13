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
- After the user says it's merged, prepare for the next work:
  1. `git checkout main`
  2. `git pull --rebase`
  3. `git branch -d <merged branch>` (and `git push origin --delete <merged branch>`
     if GitHub didn't delete it)
  4. `git checkout -b feature/<next topic>`

## Subtask lists

When asked for a subtask list, use this format:

- A one-line intro naming the scope (e.g. "for this PR: one PR, one DB wipe at
  the end").
- One bold heading per step: `**Step N: <what it achieves>**`, in the order
  they'll be done.
- Under each step, Markdown checkboxes (`- [ ]`), one per concrete change,
  naming the file, function or column, and a short note after a semicolon or
  colon (e.g. "`upsert_source_transaction`: a new row creates its transaction; an
  update keeps it").
- End each step with a `Tests:` checkbox listing what the tests cover.
- Mark undecided items inline in bold (e.g. "**Not decided yet.**").
- A final "docs, checks" step (docs, DEVELOPMENT.md checklist, audit, squash,
  push) and any steps for the user (e.g. "You: wipe the DB…").
- A "Later, separate PRs" section for follow-ups.
- Close with one line on what to do first.
