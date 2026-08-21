# BalanceAI

Automated accounting tool for receipt handling and basic bookkeeping.

Backend setup, MCP tool reference, and supported banks: see
[`src/balanceai_backend/README.md`](src/balanceai_backend/README.md).

## Setup

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
