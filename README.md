# BalanceAI

Automated accounting tool for receipt handling and basic bookkeeping.

## Setup

### Claude Code

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "balance-ai": {
      "command": "/Users/sl5234/Workspace/BalanceAI/.venv/bin/python",
      "args": ["-m", "balanceai.server"],
      "cwd": "/Users/sl5234/Workspace/BalanceAI"
    }
  }
}
```

Then restart Claude Code.

## Available Tools

| Tool | Description |
|------|-------------|
| `upload_statement` | Parse a bank statement PDF and store transactions |
| `list_accounts` | List all linked bank accounts |
| `get_balance` | Get account balances |
| `get_transactions` | Query transactions with filters |
| `categorize_transaction` | Manually set a transaction's category |

## Supported Banks

- Chase
