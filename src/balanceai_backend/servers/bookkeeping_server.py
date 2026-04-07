"""
BalanceAI MCP Server

Provides tools for journal management.
"""

import calendar
import csv
import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

from balanceai_backend.dagger.aws import AWSClients
from balanceai_backend.config import settings
from balanceai_backend.models import Account, Journal
from balanceai_backend.db import conn
from balanceai_backend.journals.journal_db import save_journal, update_journal as db_update_journal, delete_journal as db_delete_journal, find_journals as db_find_journals, find_journal_entries as db_find_journal_entries
from balanceai_backend.helpers.journal_entry_helper import (
    handle_sync_journal_entries_from_receipt,
    handle_sync_journal_entries_from_transactions,
    handle_sync_journal_entries_from_bank_statement,
)
from balanceai_backend.models.journal import JournalEntry
from balanceai_backend.prompts.financial_query_prompt import financial_query_system_prompt
from balanceai_backend.services.gemini import GeminiClient, converse as gemini_converse

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
_fh = logging.FileHandler("/Users/sl5234/Workspace/BalanceAI/logs/bookkeeping_server.log", mode="a")
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
logger.addHandler(_fh)

_aws_clients = AWSClients(region_name=settings.aws_region)
if not _aws_clients.is_initialized():
    _aws_clients.initialize()
settings.set_aws_clients(_aws_clients)

mcp = FastMCP(
    "balanceai_bookkeeping",
    instructions="""
    BalanceAI is a personal finance MCP server for managing journals.

    General behavioral guidelines for the MCP client:
    - Monetary amounts are in USD unless otherwise noted.
    - For any spending, income, or financial analysis question, use
      `analyze_financial_question`. It handles double-entry bookkeeping semantics
      correctly via an internal LLM.
    - For complex questions (trends, comparisons, anomalies, burn rate), decompose
      into multiple focused sub-questions and call `analyze_financial_question`
      once per sub-question, then synthesize the results yourself.
      Example: "Am I spending more than usual?" ->
        call 1: spending by category this month
        call 2: average monthly spending by category over the prior 3 months
        synthesize: delta per category
    - For merchant spend questions, always use a two-step fuzzy lookup because
      the same merchant may appear under multiple recipient names (e.g. "Shell",
      "Shell Oil", "Shell Service Station").
      Example: "How much did I spend at Shell in October 2025?" ->
        call 1: list all DISTINCT recipients LIKE '%shell%' in that period
        call 2: sum spend across those recipients
    - Pass prior call results in the `context` argument when a follow-up query
      depends on previous results (e.g. for comparison or anomaly detection).
    """,
)


@mcp.tool()
def create_journal(
    account: dict,
    description: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> dict:
    """
    Create a new journal for a bank account.

    Args:
        account: The bank account object (with id, bank, account_type, balance, categories)
        description: Description of the journal
        start_date: Start date for the journal. Defaults to today.
        end_date: End date for the journal. Defaults to end of current month.

    Returns:
        dict with the created journal
    """
    acct = Account.from_dict(account)

    today = date.today()
    if start_date is None:
        start_date = today
    if end_date is None:
        last_day = calendar.monthrange(today.year, today.month)[1]
        end_date = date(today.year, today.month, last_day)

    journal = Journal(account=acct, description=description, start_date=start_date, end_date=end_date)
    save_journal(journal, conn)
    return journal.to_dict()


@mcp.tool()
def update_journal(
    journal_id: str,
    description: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    entries: Optional[list[dict]] = None,
) -> dict:
    """
    Update a journal's properties by journal ID. Only provided fields are updated.

    Args:
        journal_id: The journal ID of the journal to update
        description: New description for the journal
        start_date: New start date for the journal
        end_date: New end date for the journal
        entries: New list of journal entry objects

    Returns:
        dict with the updated journal
    """
    results = db_find_journals(journal_id=journal_id, conn=conn)
    if not results:
        raise ValueError(f"Journal {journal_id} not found")
    journal = results[0]

    if description is not None:
        journal.description = description
    if start_date is not None:
        journal.start_date = start_date
    if end_date is not None:
        journal.end_date = end_date
    if entries is not None:
        journal.entries = [JournalEntry.from_dict(e) for e in entries]

    db_update_journal(journal, conn)

    return journal.to_dict()


@mcp.tool()
def delete_journal(journal_id: str) -> dict:
    """
    Delete a journal and all its entries.

    Args:
        journal_id: The journal ID to delete

    Returns:
        dict with the deleted journal_id
    """
    db_delete_journal(journal_id, conn)
    return {"journal_id": journal_id}


@mcp.tool()
def list_journals(account_id: Optional[str] = None) -> list[dict]:
    """
    List all journals.

    Args:
        account_id: Optional bank account ID to filter by.

    Returns:
        List of journals with account, description, start_date, end_date, and entries.
    """
    journals = db_find_journals(account_id=account_id, conn=conn)
    return [j.to_dict(redact_entries=True) for j in journals]


@mcp.tool()
def sync_journal_entries_from_receipt(
    journal_id: str,
    input_local_path: str,
) -> dict:
    """
    Create or update journal entries from a receipt image.

    Uses an LLM to perform OCR on the image and extract journal entries using
    double-entry bookkeeping.

    If a matching entry already exists (same date, account, and similar description),
    the existing entry is updated with the latest values — preserving its original ID.
    Otherwise, a new entry is created.

    Args:
        journal_id: The journal ID to add or update entries in
        input_local_path: Local path to the receipt image file

    Returns:
        dict with the updated journal
    """
    from pathlib import Path
    return handle_sync_journal_entries_from_receipt(journal_id, Path(input_local_path))


@mcp.tool()
def sync_journal_entries_from_transactions(
    journal_id: str,
    transactions: dict,
) -> dict:
    """
    Create or update journal entries from Plaid transactions.

    Uses an LLM to map structured transaction data to journal entries with appropriate
    debit/credit/account classifications using double-entry bookkeeping.

    If a matching entry already exists (same date, account, and similar description),
    the existing entry is updated with the latest values — preserving its original ID.
    Otherwise, a new entry is created.

    Args:
        journal_id: The journal ID to add or update entries in
        transactions: Plaid transactions response object (with added, modified, removed, etc.)

    Returns:
        dict with the updated journal
    """
    return handle_sync_journal_entries_from_transactions(journal_id, transactions)


@mcp.tool()
def sync_journal_entries_from_bank_statement(
    journal_id: str,
    file_path: str,
) -> dict:
    """
    Create or update journal entries from a bank statement PDF.

    Parses the PDF using the bank's statement parser, then uses an LLM to map
    each transaction to journal entries using double-entry bookkeeping. The bank
    is inferred from the journal's linked account.

    If a matching entry already exists (same date, account, and similar description),
    the existing entry is updated with the latest values — preserving its original ID.
    Otherwise, a new entry is created.

    Args:
        journal_id: The journal ID to add or update entries in
        file_path: Local path to the bank statement PDF

    Returns:
        dict with the updated journal
    """
    return handle_sync_journal_entries_from_bank_statement(journal_id, file_path)


# TODO: Add a tool that identifies recurring transactions over months.  And notifies.
# TODO: Add a tool that identifies a payment that needs to be made.  And proactively check debit account for sufficient funds.  And notifies.


@mcp.tool()
def list_journal_entries(journal_id: str, date: Optional[date] = None) -> list[dict]:
    """
    List entries for a given journal, optionally filtered by date.

    Args:
        journal_id: The journal ID to retrieve entries for
        date: Optional date to filter entries by

    Returns:
        List of journal entries
    """
    return [e.to_dict(redact=True) for e in db_find_journal_entries(journal_id, date=date, conn=conn)]


@mcp.tool()
def publish_journal(journal_id: str, output_dir: str) -> dict:
    """
    Export journal entries to a CSV file.

    The filename is derived from the journal's account bank, account type,
    start date, and end date (e.g. chase_debit_2026-01-01_2026-01-31.csv).

    Args:
        journal_id: The journal ID to export
        output_dir: Local directory path where the CSV will be written

    Returns:
        dict with output_path and number of rows written
    """
    import csv

    results = db_find_journals(journal_id=journal_id, conn=conn)
    if not results:
        raise ValueError(f"Journal {journal_id} not found")
    journal = results[0]

    filename = f"{journal.account.bank.value}_{journal.account.account_type.value}_{journal.start_date}_{journal.end_date}_{journal_id}.csv"
    out = Path(output_dir) / filename
    out.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["journal_entry_id", "date", "account", "description", "debit", "credit", "category", "tax", "recipient"]
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for entry in journal.entries:
            writer.writerow(entry.to_dict())

    return {"output_path": str(out), "rows_written": len(journal.entries)}


@mcp.tool()
def analyze_financial_question(
    question: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    account_id: Optional[str] = None,
    context: Optional[dict] = None,
) -> dict:
    """
    Answer a financial analysis question using journal data.

    An internal LLM generates the correct SQL from the question, handling
    double-entry bookkeeping semantics automatically — e.g. it always filters
    by recipient (not description) and targets the correct leg for spending vs income.

    This tool answers ONE focused question. For complex analyses (trends,
    comparisons, anomalies), the planning agent should decompose the problem
    and call this tool multiple times, passing prior results via `context`.

    Args:
        question: A focused financial question in natural language.
            Examples:
              "How much did I spend at Shell in October 2025?"
              "Top 5 spending categories in Q1 2025"
              "Total income received last month"
              "All transactions over $100 in March 2025"
              "Average monthly spend on dining over the last 6 months"
        start_date: Optional date hint (inclusive). Helps the LLM scope the query.
        end_date: Optional date hint (inclusive). Helps the LLM scope the query.
        account_id: Optional journal account ID to scope to one account.
        context: Optional dict of prior results to inform this query.
            Use for chained or comparative queries, e.g.:
            {"prior_period": "Sep 2025", "prior_total": 450.00}

    Returns:
        dict with question, description, sql, rows, row_count, and optionally total.
    """
    user_parts = [f"Question: {question}"]
    if start_date:
        user_parts.append(f"Start date hint: {start_date}")
    if end_date:
        user_parts.append(f"End date hint: {end_date}")
    if account_id:
        user_parts.append(f"Account ID filter: {account_id}")
    if context:
        user_parts.append(f"Context from prior queries: {json.dumps(context)}")

    user_message = "\n".join(user_parts)
    system_prompt = financial_query_system_prompt(date.today())
    logger.debug("analyze_financial_question | user_message: %s", user_message)
    logger.debug("analyze_financial_question | system_prompt: %s", system_prompt)

    try:
        raw = gemini_converse(
            client=GeminiClient(),
            user_message=user_message,
            system_prompt=system_prompt,
            max_tokens=1024,
        )
    except Exception as e:
        logger.error("analyze_financial_question | gemini call failed: %s", e, exc_info=True)
        raise
    logger.debug("analyze_financial_question | raw_response:\n%s", raw)

    try:
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
        json_str = json_match.group(1).strip() if json_match else raw.strip()
        parsed = json.loads(json_str)
        sql = parsed["sql"]
        description = parsed.get("description", "")
    except Exception as e:
        logger.error("analyze_financial_question | response parsing failed: %s", e, exc_info=True)
        raise
    logger.debug("analyze_financial_question | sql: %s", sql)

    rows = [dict(r) for r in conn.execute(sql).fetchall()]
    logger.debug("analyze_financial_question | row_count: %d", len(rows))

    return {
        "question": question,
        "description": description,
        "sql": sql,
        "rows": rows,
        "row_count": len(rows),
    }


if __name__ == "__main__":
    mcp.run()
