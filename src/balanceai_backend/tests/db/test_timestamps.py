"""BL-18: every table records created_at and updated_at. A new row gets both; an
update changes only updated_at."""

import datetime
import itertools
import sqlite3
from decimal import Decimal
from unittest.mock import patch

import pytest
from balanceai_backend.bank_link.plaid_item_db import find_plaid_items, save_plaid_item
from balanceai_backend.bank_link.plaid_sync_cursor_db import update_plaid_sync_cursor
from balanceai_backend.db.bank_account_db import find_bank_accounts, upsert_bank_account
from balanceai_backend.db.connection import create_schema
from balanceai_backend.db.journal_db import (
    add_journal_entry,
    find_journals,
    save_journal,
    update_journal,
)
from balanceai_backend.models.bank_account import BankAccount, BankAccountType
from balanceai_backend.models.journal import Journal, JournalAccount, JournalLine
from balanceai_backend.models.plaid_item import PlaidItem
from balanceai_backend.models.plaid_sync_cursor import PlaidSyncCursor
from balanceai_backend.models.report import ReportDefinition
from balanceai_backend.reports.report_definition_db import (
    find_report_definitions,
    save_report_definition,
    update_report_definition,
)

_MODULES = [
    "balanceai_backend.db.journal_db",
    "balanceai_backend.db.bank_account_db",
    "balanceai_backend.bank_link.plaid_sync_cursor_db",
    "balanceai_backend.reports.report_definition_db",
]


@pytest.fixture
def clock():
    """utc_now_iso returns 2026-01-01T00:00:01, then :02, ... in every module."""
    ticks = (f"2026-01-01T00:00:{n:02d}+00:00" for n in itertools.count(1))
    patches = [patch(f"{m}.utc_now_iso", side_effect=lambda: next(ticks)) for m in _MODULES]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


@pytest.fixture
def db(clock):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    yield conn
    conn.close()


def _account(display_name=None) -> BankAccount:
    return BankAccount(
        id="test_bank:checking:0000",
        institution_name="Test Bank",
        account_type=BankAccountType.CHECKING,
        last4="0000",
        display_name=display_name,
    )


def _line() -> JournalLine:
    return JournalLine(
        journal_line_id="line-1",
        date=datetime.date(2026, 1, 1),
        account=JournalAccount.CASH,
        description="Coffee",
        debit=Decimal(0),
        credit=Decimal("4.50"),
    )


def test_bank_account_update_keeps_created_at(db):
    upsert_bank_account(_account(), conn=db)
    upsert_bank_account(_account(display_name="Checking"), conn=db)
    [account] = find_bank_accounts(conn=db)
    assert account.created_at == "2026-01-01T00:00:01+00:00"
    assert account.updated_at == "2026-01-01T00:00:02+00:00"


def test_renaming_a_journal_keeps_every_created_at(db):
    upsert_bank_account(_account(), conn=db)
    journal = Journal(
        name="Personal",
        created_at="2026-01-01T00:00:00+00:00",
        bank_account_ids=["test_bank:checking:0000"],
    )
    save_journal(journal, conn=db)
    with db:
        add_journal_entry(journal.journal_id, [_line()], conn=db)
    [saved] = find_journals(conn=db)
    line_created = saved.lines[0].created_at
    link_created = db.execute("SELECT created_at FROM journal_bank_accounts").fetchone()[0]

    saved.name = "Home"
    update_journal(saved, conn=db)

    [renamed] = find_journals(conn=db)
    assert renamed.created_at == "2026-01-01T00:00:00+00:00"
    assert renamed.updated_at > renamed.created_at
    assert renamed.lines[0].created_at == line_created  # lines are re-inserted (BL-9)
    assert db.execute("SELECT created_at FROM journal_bank_accounts").fetchone()[0] == (
        link_created
    )


def test_sync_cursor_update_keeps_created_at(db):
    save_plaid_item(PlaidItem(item_id="item-1", access_token="access-sandbox-abc"), conn=db)
    update_plaid_sync_cursor(PlaidSyncCursor(item_id="item-1", cursor="c1"), conn=db)
    update_plaid_sync_cursor(PlaidSyncCursor(item_id="item-1", cursor="c2"), conn=db)
    row = db.execute("SELECT cursor, created_at, updated_at FROM plaid_sync_cursors").fetchone()
    assert row["cursor"] == "c2"
    assert row["created_at"] == "2026-01-01T00:00:01+00:00"
    assert row["updated_at"] == "2026-01-01T00:00:02+00:00"


def test_plaid_item_gets_both(db):
    save_plaid_item(PlaidItem(item_id="item-1", access_token="access-sandbox-abc"), conn=db)
    [item] = find_plaid_items(conn=db)
    assert item.created_at and item.updated_at == item.created_at


def test_report_definition_update_sets_updated_at(db):
    defn = ReportDefinition(
        name="Dining",
        prompt="p",
        sql_template="SELECT 1",
        description="d",
        created_at="2026-01-01T00:00:00+00:00",
    )
    save_report_definition(defn, conn=db)
    defn.name = "Dining out"
    update_report_definition(defn, conn=db)
    [saved] = find_report_definitions(conn=db)
    assert saved.created_at == "2026-01-01T00:00:00+00:00"
    assert saved.updated_at == "2026-01-01T00:00:01+00:00"
