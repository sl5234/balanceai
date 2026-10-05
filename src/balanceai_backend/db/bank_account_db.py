import sqlite3

from balanceai_backend.db.connection import conn as _default_conn
from balanceai_backend.models.bank_account import BankAccount, BankAccountType


def _build_bank_account(row) -> BankAccount:
    return BankAccount(
        id=row["id"],
        institution_name=row["institution_name"],
        account_type=BankAccountType(row["account_type"]),
        last4=row["last4"],
        display_name=row["display_name"],
        plaid_institution_id=row["plaid_institution_id"],
        plaid_item_id=row["plaid_item_id"],
        plaid_account_id=row["plaid_account_id"],
    )


def find_bank_accounts(
    id: str | None = None,
    plaid_item_id: str | None = None,
    plaid_account_id: str | None = None,
    conn: sqlite3.Connection = _default_conn,
) -> list[BankAccount]:
    """Find bank accounts, optionally filtered by id, plaid_item_id, and/or plaid_account_id."""
    query = "SELECT * FROM bank_accounts WHERE 1=1"
    params: list = []
    if id is not None:
        query += " AND id = ?"
        params.append(id)
    if plaid_item_id is not None:
        query += " AND plaid_item_id = ?"
        params.append(plaid_item_id)
    if plaid_account_id is not None:
        query += " AND plaid_account_id = ?"
        params.append(plaid_account_id)
    query += " ORDER BY id"
    rows = conn.execute(query, params).fetchall()
    return [_build_bank_account(row) for row in rows]


def upsert_bank_account(account: BankAccount, conn: sqlite3.Connection = _default_conn) -> None:
    """Insert a bank account, or update it if the id already exists.

    On update, optional fields left as None keep their stored value rather than
    being cleared — e.g. a statement upload, which knows nothing about Plaid,
    mustn't wipe the account's Plaid link.

    Raises:
        ValueError: if an account with this id is already linked to a different
            Plaid account — two Plaid accounts resolving to the same
            institution:type:last4 id, which would otherwise silently merge them.
    """
    # TODO: upserts key on id only, so an account whose id-forming fields changed
    # (last 4, type, institution) can't be updated here. See docs/BACKLOGS.md BL-1.
    existing = find_bank_accounts(id=account.id, conn=conn)
    if (
        existing
        and account.plaid_account_id is not None
        and existing[0].plaid_account_id is not None
        and existing[0].plaid_account_id != account.plaid_account_id
    ):
        raise ValueError(
            f"Bank account {account.id} is already linked to Plaid account "
            f"{existing[0].plaid_account_id}, not {account.plaid_account_id}"
        )

    with conn:
        conn.execute(
            "INSERT INTO bank_accounts"
            " (id, institution_name, account_type, last4, display_name,"
            "  plaid_institution_id, plaid_item_id, plaid_account_id)"
            " VALUES (?,?,?,?,?,?,?,?)"
            " ON CONFLICT(id) DO UPDATE SET"
            "  institution_name = excluded.institution_name,"
            "  account_type = excluded.account_type,"
            "  last4 = excluded.last4,"
            "  display_name = COALESCE(excluded.display_name, bank_accounts.display_name),"
            "  plaid_institution_id ="
            "   COALESCE(excluded.plaid_institution_id, bank_accounts.plaid_institution_id),"
            "  plaid_item_id = COALESCE(excluded.plaid_item_id, bank_accounts.plaid_item_id),"
            "  plaid_account_id ="
            "   COALESCE(excluded.plaid_account_id, bank_accounts.plaid_account_id)",
            (
                account.id,
                account.institution_name,
                account.account_type.value,
                account.last4,
                account.display_name,
                account.plaid_institution_id,
                account.plaid_item_id,
                account.plaid_account_id,
            ),
        )
