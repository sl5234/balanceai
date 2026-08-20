# balanceai_backend

## Setup

### Claude Code

```bash
cd src/balanceai_backend
claude mcp add balanceai_bookkeeping -- venv/bin/python -m balanceai_backend.servers.bookkeeping_server
claude mcp add balanceai_link_bank -- venv/bin/python -m balanceai_backend.servers.link_bank_server
```

Or add directly to `~/.claude.json`:

```json
{
  "mcpServers": {
    "balanceai_bookkeeping": {
      "command": "/Users/sl5234/Workspace/BalanceAI/src/balanceai_backend/venv/bin/python",
      "args": ["-m", "balanceai_backend.servers.bookkeeping_server"]
    },
    "balanceai_link_bank": {
      "command": "/Users/sl5234/Workspace/BalanceAI/src/balanceai_backend/venv/bin/python",
      "args": ["-m", "balanceai_backend.servers.link_bank_server"]
    }
  }
}
```

Then restart Claude Code.

See `DEVELOPMENT.md` for setup, linting, formatting, and testing commands.

## Available Tools

### balanceai_bookkeeping (Journals)

| Tool | Description |
|------|-------------|
| `create_journal` | Create a new journal for a bank account |
| `update_journal` | Update journal properties |
| `list_journals` | List all journals |

### balanceai_link_bank (Bank Accounts)

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
