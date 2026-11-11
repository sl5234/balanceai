"""
BalanceAI MCP Server

Provides tools for journal management.
"""

import csv
import json
import logging
import re
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP

from balanceai_backend.config import settings
from balanceai_backend.constants import FINANCIAL_QUERY_MODEL_ID
from balanceai_backend.dagger.aws import AWSClients
from balanceai_backend.db.bank_account_db import create_cash_account, find_bank_accounts
from balanceai_backend.db.connection import conn
from balanceai_backend.db.journal_db import (
    delete_journal as db_delete_journal,
)
from balanceai_backend.db.journal_db import (
    find_journal_lines as db_find_journal_lines,
)
from balanceai_backend.db.journal_db import (
    find_journals as db_find_journals,
)
from balanceai_backend.db.journal_db import (
    save_journal,
)
from balanceai_backend.db.journal_db import (
    update_journal as db_update_journal,
)
from balanceai_backend.db.readonly_journal_connection import readonly_journal_conn
from balanceai_backend.helpers.financial_query_helper import (
    check_analyze_filters,
    hide_descriptions,
)
from balanceai_backend.helpers.journal_entry_helper import (
    handle_sync_journal_entries_from_bank_statement,
    handle_sync_journal_entries_from_transactions,
)
from balanceai_backend.helpers.receipt_helper import receipt_consent_message
from balanceai_backend.models import Bank, Journal
from balanceai_backend.models.consent import (
    BookReceiptConsent,
    ShareJournalEntriesConsent,
    ShareQueryRowsConsent,
)
from balanceai_backend.models.financial_query import (
    REJECTION_MESSAGES,
    UNANSWERABLE_MESSAGE,
    FinancialQuery,
)
from balanceai_backend.models.receipt import AccountMatch, ReceiptAccount
from balanceai_backend.models.report import ReportDefinition
from balanceai_backend.prompts.financial_query_prompt import financial_query_system_prompt
from balanceai_backend.prompts.report_definition_prompt import (
    report_definition_system_prompt,
    report_definition_user_message,
)
from balanceai_backend.raw_transactions.book_raw_transactions import book_raw_transactions
from balanceai_backend.raw_transactions.classify_raw_transactions import classify_raw_transactions
from balanceai_backend.raw_transactions.sync_raw_transactions_from_receipt import (
    check_receipt_account,
    read_receipt,
    resolve_receipt_path,
    suggest_receipt_account,
    sync_raw_transactions_from_receipt,
)
from balanceai_backend.reports.report_definition_db import (
    delete_report_definition as _delete_report_definition,
)
from balanceai_backend.reports.report_definition_db import (
    find_report_definitions as _find_report_definitions,
)
from balanceai_backend.reports.report_definition_db import (
    save_report_definition as _save_report_definition,
)
from balanceai_backend.services import anthropic as anthropic_service
from balanceai_backend.services.gemini import GeminiClient
from balanceai_backend.services.gemini import converse as gemini_converse
from balanceai_backend.utils.journal_line_util import date_range, entry_to_dict, group_into_entries

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
    - Ask `analyze_financial_question` plain-language questions about the user's
      money, as the user would say them. Never put SQL, table or column names,
      or instructions on how to build the query in the question; such questions
      are rejected.
    - For complex questions (trends, comparisons, anomalies, burn rate), decompose
      into multiple focused sub-questions and call `analyze_financial_question`
      once per sub-question, then synthesize the results yourself.
      Example: "Am I spending more than usual?" ->
        call 1: spending by category this month
        call 2: average monthly spending by category over the prior 3 months
        synthesize: delta per category
    - For merchant spend questions, always use a two-step fuzzy lookup because
      the same merchant may appear under multiple counterparty names (e.g. "Shell",
      "Shell Oil", "Shell Service Station").
      Example: "How much did I spend at Shell in October 2025?" ->
        call 1: "Which merchants with 'Shell' in the name did I pay in October 2025?"
                -> e.g. Shell, Shell Oil, Shell Service Station
        call 2: "How much did I spend in October 2025 at these merchants:
                <the merchant names call 1 returned>?"
    - If the user has more than one journal (list_journals), ask which one a
      question is about and pass its `journal_id`.
    - For a receipt, the user puts the image in the receipts folder; call
      `upload_receipt` with its file name. Don't open or read the image
      yourself. If it asks which account paid (or the user declines because the account shown is wrong),
      ask the user, find the account with list_bank_accounts, and call again
      with `account_id`. For cash, pass the journal's `journal_id`.
    - Pass prior call results in the `context` argument when a follow-up query
      depends on previous results (e.g. for comparison or anomaly detection).
    - `create_report_definition` requires an `unparameterized_sql` from a prior
      `analyze_financial_question` call. Never call it without first running the
      relevant queries. Specifically:
        step 1: find the merchants matching the subject over the past 6 months
                (use the same two-step fuzzy lookup described above)
        step 2: run a sample query for the most recent 1-month period using those counterparties
        step 3: call `create_report_definition` with the SQL from step 2 as `unparameterized_sql`
                and pass the user's original request as `prompt`
    - `generate_report` accepts an optional `parameters` dict for any named parameters
      beyond :start_date/:end_date (e.g. {"category": "dining"}). Check the "parameters"
      field on the report definition to see what params it expects.
    """,
)


# ---------------------------------------------------------------------------
# Journal actions
# ---------------------------------------------------------------------------


def _raise_if_duplicate_journal_name(error: sqlite3.IntegrityError, name: str) -> None:
    """Turn the journals.name UNIQUE violation into a readable ValueError."""
    if "journals.name" in str(error):
        raise ValueError(f"A journal named {name!r} already exists") from error


@mcp.tool()
def create_journal(
    name: str, description: str = "", bank_account_ids: list[str] | None = None
) -> dict:
    """
    Create a new journal — a set of books (e.g. "Personal", "My LLC") that
    holds journal entries across all of its bank accounts and dates.

    Args:
        name: Name of the journal
        description: Optional description of the journal
        bank_account_ids: Bank accounts whose transactions belong in this journal
            (ids from the link-bank server's list_bank_accounts). A bank account
            can be in only one journal.

    Returns:
        dict with the created journal (lines are omitted — use
        list_journal_entries), plus "booking": {"booked", "transfers_paired"} for its
        bank accounts' classified transactions, which are booked right away

    Raises:
        ValueError: if a journal with this name already exists (case-insensitive),
            or a bank account doesn't exist or is already in another journal.
    """
    journal = Journal(name=name, description=description, bank_account_ids=bank_account_ids or [])
    try:
        save_journal(journal, conn)
    except sqlite3.IntegrityError as e:
        _raise_if_duplicate_journal_name(e, name)
        raise
    journal.bank_account_ids.append(create_cash_account(journal.journal_id, journal.name, conn))
    return {
        **journal.to_dict(redact_lines=True),
        "booking": book_raw_transactions(journal.journal_id, conn),
    }


@mcp.tool()
def update_journal(
    journal_id: str,
    name: str | None = None,
    description: str | None = None,
    bank_account_ids: list[str] | None = None,
) -> dict:
    """
    Update a journal's properties by journal ID. Only provided fields are
    updated. Entries can't be edited here: they're booked from bank
    transactions.

    Args:
        journal_id: The journal ID of the journal to update
        name: New name for the journal
        description: New description for the journal
        bank_account_ids: Replaces the journal's whole list of bank accounts —
            pass every account to keep, not just ones to add. [] removes all.
            The journal's cash account always stays.

    Returns:
        dict with the updated journal (lines are omitted — use
        list_journal_entries), plus "booking": {"booked", "transfers_paired"} for its
        bank accounts' classified transactions not booked yet (e.g. an account
        just added). Entries of removed accounts are deleted.

    Raises:
        ValueError: if the journal doesn't exist, the new name is already used
            by another journal (case-insensitive), or a bank account doesn't
            exist or is already in another journal.
    """
    results = db_find_journals(journal_id=journal_id, conn=conn)
    if not results:
        raise ValueError(f"Journal {journal_id} not found")
    journal = results[0]

    if name is not None:
        journal.name = name
    if description is not None:
        journal.description = description
    if bank_account_ids is not None:
        # The journal's cash account always stays; it isn't the user's to remove.
        cash = [a for a in journal.bank_account_ids if a.startswith("cash:cash:")]
        journal.bank_account_ids = list(dict.fromkeys(bank_account_ids + cash))

    try:
        db_update_journal(journal, conn)
    except sqlite3.IntegrityError as e:
        _raise_if_duplicate_journal_name(e, journal.name)
        raise

    return {
        **journal.to_dict(redact_lines=True),
        "booking": book_raw_transactions(journal.journal_id, conn),
    }


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
def list_journals() -> list[dict]:
    """
    List all journals.

    Returns:
        List of journals with journal_id, name, description, created_at, and
        bank_account_ids (lines are omitted — use list_journal_entries).
    """
    journals = db_find_journals(conn=conn)
    return [j.to_dict(redact_lines=True) for j in journals]


# ---------------------------------------------------------------------------
# Journal entry actions
# ---------------------------------------------------------------------------


@mcp.tool()
async def upload_receipt(
    ctx: Context,
    file_name: str,
    journal_id: str | None = None,
    account_id: str | None = None,
) -> dict:
    """
    Read a receipt image into a transaction and book it, after the user confirms.

    Receipts are read only from the receipts folder (balanceai_backend_secrets/
    receipts by default); pass the file's name, not a path. Don't open or read
    the receipt image yourself: its contents are shown only to the user, in the
    confirmation prompt.

    The paying account is found from the receipt: cash → the journal's cash
    account (needs journal_id); card → the account an earlier receipt with the
    same card was saved to, else the bank account with the same last 4. If it
    can't be found, this raises asking for the account: ask the user, then call
    again with account_id (from list_bank_accounts). If the user declines
    because the account is wrong, do the same.

    Args:
        file_name: The receipt image's name in the receipts folder, e.g.
            "blue_bottle.jpg" (.jpg, .png, .gif, .webp).
        journal_id: Optional; the journal the receipt is for (from list_journals).
            Needed for cash receipts unless account_id is given.
        account_id: Optional; the account that paid (from list_bank_accounts).

    Returns:
        dict with "booked" (False when the paying account isn't in a journal yet;
        add it with update_journal) and "journal_id". No receipt details.

    Raises:
        ValueError: if the file isn't in the receipts folder or can't be read, or
            the account can't be found or doesn't fit journal_id (the message
            says what to ask the user).
        PermissionError: if the user declines or cancels.
    """
    receipt = read_receipt(resolve_receipt_path(file_name))
    if account_id:
        check_receipt_account(account_id, journal_id, conn=conn)
        found = ReceiptAccount(account_id, AccountMatch.USER)
    else:
        found = suggest_receipt_account(receipt, journal_id, conn=conn)

    [account] = find_bank_accounts(id=found.account_id, conn=conn)
    journals = db_find_journals(bank_account_id=found.account_id, conn=conn)
    journal = journals[0] if journals else None

    consent = await ctx.elicit(
        message=receipt_consent_message(receipt, account, journal, found.match),
        schema=BookReceiptConsent,
    )
    if consent.action != "accept":
        raise PermissionError("User declined to book the receipt.")

    sync_raw_transactions_from_receipt(receipt, found.account_id, conn=conn)
    classify_raw_transactions(conn=conn)
    if journal:
        book_raw_transactions(journal.journal_id, conn)
    return {"booked": journal is not None, "journal_id": journal.journal_id if journal else None}


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
    bank: Bank,
) -> dict:
    """
    Create or update journal entries from a bank statement PDF.

    Parses the PDF using the bank's statement parser, then uses an LLM to map
    each transaction to journal entries using double-entry bookkeeping.

    If a matching entry already exists (same date, account, and similar description),
    the existing entry is updated with the latest values — preserving its original ID.
    Otherwise, a new entry is created.

    Args:
        journal_id: The journal ID to add or update entries in
        file_path: Local path to the bank statement PDF
        bank: The bank this statement is from (selects the statement parser)

    Returns:
        dict with the updated journal
    """
    return handle_sync_journal_entries_from_bank_statement(journal_id, file_path, bank)


# TODO: Add a tool that identifies recurring transactions over months.  And notifies.
# TODO: Add a tool that identifies a payment that needs to be made.  And proactively check debit account for sufficient funds.  And notifies.


@mcp.tool()
async def list_journal_entries(
    ctx: Context, journal_id: str, date: date | None = None
) -> list[dict]:
    """
    List a journal's entries, optionally only those with a line on a date.

    Entries are private, so the user is asked to approve sharing them before
    any are returned.

    Args:
        journal_id: The journal ID to retrieve entries for
        date: Optional date; an entry is listed if any of its lines is on it

    Returns:
        List of entries in date order, each {"journal_entry_id", "date",
        "lines": [...]}. "date" is its earliest line's. A line written by the
        old entry tools has no journal_entry_id, so it's listed as its own entry.

    Raises:
        PermissionError: if the user declines or cancels the approval prompt.
    """
    lines = db_find_journal_lines(journal_id, conn=conn)
    entries = group_into_entries(lines)
    if date is not None:
        entries = [e for e in entries if any(line.date == date for line in e)]
    if not entries:
        return []

    result = await ctx.elicit(
        message=f"Share {len(entries)} journal entries ({date_range(entries)}) with the assistant?",
        schema=ShareJournalEntriesConsent,
    )
    if result.action != "accept":
        raise PermissionError("User declined to share journal entries.")
    return [entry_to_dict(e) for e in entries]


@mcp.tool()
def publish_journal(journal_id: str, output_dir: str) -> dict:
    """
    Export journal entries to a CSV file.

    The filename is derived from the journal's name and id.

    Args:
        journal_id: The journal ID to export
        output_dir: Local directory path where the CSV will be written

    Returns:
        dict with output_path and number of rows written
    """

    results = db_find_journals(journal_id=journal_id, conn=conn)
    if not results:
        raise ValueError(f"Journal {journal_id} not found")
    journal = results[0]

    filename = f"{journal.name}_{journal_id}.csv"
    out = Path(output_dir) / filename
    out.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "journal_line_id",
        "date",
        "account",
        "description",
        "debit",
        "credit",
        "category",
        "tax",
        "counterparty",
    ]
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for entry in journal.lines:
            writer.writerow(entry.to_dict())

    return {"output_path": str(out), "rows_written": len(journal.lines)}


@mcp.tool()
async def analyze_financial_question(
    ctx: Context,
    question: str,
    start_date: date | None = None,
    end_date: date | None = None,
    account_id: str | None = None,
    journal_id: str | None = None,
    context: dict | None = None,
) -> dict:
    """
    Answer a financial analysis question using journal data.

    An internal LLM generates the correct SQL from the question, handling
    double-entry bookkeeping semantics automatically — e.g. it always filters
    by counterparty (not description) and targets the correct leg for spending vs income.
    The SQL runs read-only and can only read the journals and journal_lines tables.

    Ask in plain language, as the user would. Questions containing SQL, table or
    column names, or instructions on how to build the query are rejected.

    Rows are private, so the user is asked to approve sharing them before any
    are returned.

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
        account_id: Optional bank account id (bank_accounts.id) to scope to one account.
        journal_id: Optional journal id (from list_journals) to scope to one journal.
            With more than one journal, ask the user which one they mean.
        context: Optional dict of prior results to inform this query.
            Use for chained or comparative queries, e.g.:
            {"prior_period": "Sep 2025", "prior_total": 450.00}

    Returns:
        dict with question, description, sql, rows, row_count, and optionally total.

    Raises:
        PermissionError: if the user declines or cancels the approval prompt.
        ValueError: if a filter doesn't exist (journal, bank account), the start
            date is after the end date, or the question is rejected or can't be
            turned into a query.
        RuntimeError: if the query fails.
    """
    check_analyze_filters(start_date, end_date, account_id, journal_id, conn=conn)

    user_parts = [f"Question: {question}"]
    if start_date:
        user_parts.append(f"Start date hint: {start_date}")
    if end_date:
        user_parts.append(f"End date hint: {end_date}")
    if account_id:
        user_parts.append(f"Bank account ID filter: {account_id}")
    if journal_id:
        user_parts.append(f"Journal ID filter: {journal_id}")
    if context:
        user_parts.append(f"Context from prior queries: {json.dumps(context)}")

    user_message = "\n".join(user_parts)
    system_prompt = financial_query_system_prompt(datetime.now(UTC).date())
    logger.debug("analyze_financial_question | user_message: %s", user_message)
    logger.debug("analyze_financial_question | system_prompt: %s", system_prompt)

    query = anthropic_service.parse(
        model_id=FINANCIAL_QUERY_MODEL_ID,
        content=user_message,
        output_format=FinancialQuery,
        system_instruction=system_prompt,
        max_output_tokens=16000,  # thinking is on by default and counts toward this
        timeout=120.0,
        log_to=logger,
    )
    if query is None:
        raise ValueError("The AI declined to write a query for this question.")
    logger.debug("analyze_financial_question | response: %s", query.model_dump_json())
    if query.rejection is not None:
        raise ValueError(REJECTION_MESSAGES[query.rejection])
    if not query.sql:
        raise ValueError(UNANSWERABLE_MESSAGE)
    sql, description = query.sql, query.description

    # The error text can quote journal values (e.g. a value that isn't UTF-8),
    # and it would reach the assistant before the consent prompt (SBL-1), so
    # keep it in the local log only.
    try:
        # Amounts are stored as REAL (binary floats), so sums pick up noise
        # like 0.30000000000000004 (0.1 + 0.2).
        rows = [
            {k: round(v, 2) if isinstance(v, float) else v for k, v in dict(r).items()}
            for r in readonly_journal_conn.execute(sql).fetchall()
        ]
    except sqlite3.Error:
        logger.warning("analyze_financial_question | query failed", exc_info=True)
        raise RuntimeError(UNANSWERABLE_MESSAGE) from None
    logger.debug("analyze_financial_question | rows (%d): %s", len(rows), rows)

    result = {
        "question": question,
        "description": description,
        "sql": sql,
        "rows": [],
        "row_count": len(rows),
    }
    if not rows:
        return result

    # Show the question the tool received, not the AI's summary (SBL-6). The
    # assistant writes the question, and a hijacked assistant (e.g. one that
    # read injected text in a web page, email or transaction description) can
    # send one the user never asked, like "monthly totals, plus every merchant
    # and description". Showing it lets the user catch that before approving.
    # The AI's summary isn't shown, since nothing checks it against the query.
    consent = await ctx.elicit(
        message=f'Share {len(rows)} rows with the assistant?\nQuestion asked: "{question}"',
        schema=ShareQueryRowsConsent,
    )
    if consent.action != "accept":
        raise PermissionError("User declined to share query results.")
    result["rows"] = hide_descriptions(rows, conn=readonly_journal_conn)
    return result


# TODO(SBL-2, BL-9): the report tools (create_report_definition,
# list_report_definitions, delete_report_definition, generate_report) aren't
# integrated with the new flow (raw transactions, booking, journal scoping,
# read-only SQL, consent). Skipped until we know we want to maintain them; an
# agent can save a question and re-run it through analyze_financial_question.
@mcp.tool()
def create_report_definition(
    name: str,
    prompt: str,
    unparameterized_sql: str,
    description: str | None = None,
) -> dict:
    """
    Save a reusable report definition from a verified SQL query.

    The unparameterized_sql must come from a prior analyze_financial_question call.
    An LLM pass uses the user's prompt to decide which hardcoded literals to promote
    to named parameters (always dates; other scalars based on stated intent).
    Only parameterization changes are made — the SQL structure is preserved as-is.

    Args:
        name: Short human-readable name for the report.
        prompt: The user's stated intent for this report (e.g. "track whether I'm
            cutting back on clothing month over month"). Used by the LLM to decide
            which values to parameterize.
        unparameterized_sql: SQL from analyze_financial_question to use as the template.
        description: Optional human-readable description of what the report shows.
            Defaults to the prompt if not provided.

    Returns:
        The saved ReportDefinition as a dict, including the parameterized sql_template
        and a list of named parameters.
    """
    desc = description or prompt
    system_prompt = report_definition_system_prompt()
    user_message = report_definition_user_message(
        sample_sql=unparameterized_sql,
        name=name,
        prompt=prompt,
        description=desc,
    )
    logger.debug("create_report_definition | user_message: %s", user_message)

    try:
        raw = gemini_converse(
            client=GeminiClient(),
            user_message=user_message,
            system_prompt=system_prompt,
            max_tokens=1024,
        )
    except Exception:
        logger.exception("create_report_definition | gemini call failed")
        raise
    logger.debug("create_report_definition | raw_response:\n%s", raw)

    try:
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
        json_str = json_match.group(1).strip() if json_match else raw.strip()
        parsed = json.loads(json_str)
        sql_template = parsed["sql"]
        parameters = parsed.get("parameters", [])
    except Exception:
        logger.exception("create_report_definition | response parsing failed")
        raise

    defn = ReportDefinition(
        name=name,
        prompt=prompt,
        sql_template=sql_template,
        description=desc,
        unparameterized_sql=unparameterized_sql,
        parameters=parameters,
    )
    _save_report_definition(defn)
    logger.info("Created report definition %s: %s", defn.report_definition_id, defn.name)
    return defn.to_dict()


@mcp.tool()
def list_report_definitions() -> list[dict]:
    """
    List all saved report definitions.

    Returns:
        List of ReportDefinition dicts ordered by creation date (newest first).
    """
    return [d.to_dict() for d in _find_report_definitions()]


@mcp.tool()
def delete_report_definition(report_definition_id: str) -> dict:
    """
    Delete a saved report definition.

    Args:
        report_definition_id: ID of the report definition to delete.

    Returns:
        dict with report_definition_id of the deleted definition.
    """
    _delete_report_definition(report_definition_id)
    return {"report_definition_id": report_definition_id}


@mcp.tool()
def generate_report(
    report_definition_id: str,
    parameters: dict | None = None,
    local_path: str | None = None,
) -> dict:
    """
    Execute a saved report definition with the given parameters.

    Loads the SQL template from the report definition, substitutes all named
    parameters, and returns metadata about the run. If local_path is provided,
    the result rows are written to that path as a CSV file.

    To see which parameters a report accepts, check the "parameters" field returned
    by list_report_definitions or create_report_definition.

    Args:
        report_definition_id: ID of the report definition to run.
        parameters: Dict of named parameters matching the report definition's
            "parameters" field, e.g. {"start_date": "2025-10-01", "end_date": "2025-10-31"}.
        local_path: Optional local file path to write the result rows as CSV.

    Returns:
        dict with report_definition_id, name, description, parameters, sql, row_count,
        and local_path (only present when local_path argument is provided).
    """
    matches = _find_report_definitions(report_definition_id=report_definition_id)
    if not matches:
        raise ValueError(f"ReportDefinition '{report_definition_id}' not found")
    defn = matches[0]

    params: dict = parameters or {}
    logger.debug(
        "generate_report | id: %s | name: %s | params: %s", report_definition_id, defn.name, params
    )
    logger.debug("generate_report | sql_template: %s", defn.sql_template)

    # TODO(SBL-2): run on readonly_journal_conn and ask before writing the CSV.
    rows = [dict(r) for r in conn.execute(defn.sql_template, params).fetchall()]
    logger.debug("generate_report | row_count: %d", len(rows))

    result: dict = {
        "report_definition_id": report_definition_id,
        "name": defn.name,
        "description": defn.description,
        "parameters": params,
        "sql": defn.sql_template,
        "row_count": len(rows),
    }

    if local_path is not None:
        from balanceai_backend.utils.general_util import publish_data

        publish_data(rows, local_path)
        result["local_path"] = local_path

    return result


if __name__ == "__main__":
    mcp.run()
