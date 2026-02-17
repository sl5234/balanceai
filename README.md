# BalanceAI

Automated accounting tool for receipt handling and basic bookkeeping.

## Setup

### Claude Code

Add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "balance-ai-link-bank": {
      "command": "python",
      "args": ["src/balanceai/servers/link_bank_server.py"],
      "cwd": "/Users/sl5234/Workspace/BalanceAI"
    },
    "balance-ai-bookkeeping": {
      "command": "python",
      "args": ["src/balanceai/servers/bookkeeping_server.py"],
      "cwd": "/Users/sl5234/Workspace/BalanceAI"
    }
  }
}
```

Then restart Claude Code.

## Available Tools

### balance-ai (Journals)

| Tool | Description |
|------|-------------|
| `create_journal` | Create a new journal for a bank account |
| `update_journal` | Update journal properties |
| `list_journals` | List all journals |

### balance-ai-link-bank (Bank Accounts)

| Tool | Description |
|------|-------------|
| `create_account` | Create a new bank account |
| `upload_statement` | Parse a bank statement PDF and store transactions |
| `list_accounts` | List all linked bank accounts |
| `get_balance` | Get account balances |
| `get_transactions` | Query transactions with filters |
| `list_categories` | List categories for an account |
| `update_categories` | Replace category list for an account |
| `categorize_transaction` | Manually or AI-categorize a transaction |

## Supported Banks

- Chase
