# BalanceAI

Automated accounting tool for receipt handling and basic bookkeeping.

Backend setup, MCP tool reference, and supported banks: see
[`src/balanceai_backend/README.md`](src/balanceai_backend/README.md).

## Setup

### Secret scanning (whole repo)

A [gitleaks](https://github.com/gitleaks/gitleaks) pre-commit hook
(`.pre-commit-config.yaml`) blocks commits that contain credentials (API keys,
tokens, passwords). It doesn't catch real transaction data; see the pre-commit
checklist in `src/balanceai_backend/DEVELOPMENT.md`. One-time setup, from the
repo root:

```bash
brew install gitleaks pre-commit
gitleaks git --redact -v      # scan the existing git history once (secrets masked)
pre-commit install            # install the hook into .git/hooks
pre-commit run --all-files    # check all tracked files now
```

### Frontend

The Expo project lives in `src/balanceai_frontend/` (its own `package.json`) — run commands from there:

```bash
cd src/balanceai_frontend
npm install            # first time / after pulling dependency changes
npx expo start          # start dev server (then press i, a, or w)
npx expo start --ios
npx expo start --android
npx expo start --web
```
