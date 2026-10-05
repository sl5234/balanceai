import logging
import sqlite3

from balanceai_backend.bank_link.plaid_item_db import save_plaid_item
from balanceai_backend.db.bank_account_db import upsert_bank_account
from balanceai_backend.db.connection import conn as _default_conn
from balanceai_backend.models.bank_account import (
    BankAccount,
    BankAccountType,
    build_bank_account_id,
)
from balanceai_backend.models.plaid_item import PlaidItem
from balanceai_backend.services.plaid import get_accounts
from balanceai_backend.utils.journal_entry_util import (
    extract_journal_entries_from_plaid_transaction,
)

logger = logging.getLogger(__name__)

# Plaid account types we turn into BankAccounts. Anything else (e.g. "other") is skipped.
_SUPPORTED_PLAID_TYPES = {"depository", "credit", "loan", "investment", "brokerage"}

# Our type for a Plaid subtype we don't list below, per Plaid type — so an
# unfamiliar account is still kept rather than dropped.
_PLAID_TYPE_DEFAULTS = {
    "depository": BankAccountType.OTHER_DEPOSITORY,
    "credit": BankAccountType.OTHER_CREDIT,
    "loan": BankAccountType.OTHER_LOAN,
    "investment": BankAccountType.OTHER_INVESTMENT,
    "brokerage": BankAccountType.OTHER_INVESTMENT,
}

# Plaid subtypes we map to a specific BankAccountType, per Plaid type.
_PLAID_SUBTYPES: dict[str, dict[str, BankAccountType]] = {
    "depository": {
        "checking": BankAccountType.CHECKING,
        "savings": BankAccountType.SAVINGS,
        "money market": BankAccountType.MONEY_MARKET,
        "cd": BankAccountType.CD,
    },
    "credit": {
        "credit card": BankAccountType.CREDIT_CARD,
    },
    "loan": {
        "mortgage": BankAccountType.MORTGAGE,
        "home equity": BankAccountType.HOME_EQUITY,
        "home equity loan": BankAccountType.HOME_EQUITY,
        "auto": BankAccountType.AUTO_LOAN,
        "student": BankAccountType.STUDENT_LOAN,
        "consumer": BankAccountType.PERSONAL_LOAN,
        "line of credit": BankAccountType.LINE_OF_CREDIT,
    },
    "investment": {
        "brokerage": BankAccountType.BROKERAGE,
        "ira": BankAccountType.IRA,
        "roth": BankAccountType.ROTH_IRA,
        "401k": BankAccountType.RETIREMENT_401K,
        "roth 401k": BankAccountType.ROTH_401K,
        "hsa": BankAccountType.HSA,
        "529": BankAccountType.COLLEGE_529,
    },
}
_PLAID_SUBTYPES["brokerage"] = _PLAID_SUBTYPES["investment"]  # older Plaid name for investment


def bank_account_type_from_plaid(
    plaid_type: str, plaid_subtype: str | None
) -> BankAccountType | None:
    """Map a Plaid account type/subtype to our BankAccountType. Returns None for
    Plaid types we don't handle (e.g. "other"), meaning the account is skipped."""
    if plaid_type not in _SUPPORTED_PLAID_TYPES:
        return None
    return _PLAID_SUBTYPES[plaid_type].get(plaid_subtype or "", _PLAID_TYPE_DEFAULTS[plaid_type])


def sync_bank_accounts_from_plaid(
    item: PlaidItem, conn: sqlite3.Connection = _default_conn
) -> dict:
    """
    Create or update a BankAccount for every account under a linked Plaid item,
    via /accounts/get.

    Accounts that can't be saved are skipped and logged rather than failing the
    whole item: an unsupported Plaid type, a missing mask, or an id that's
    already taken by a different Plaid account.

    Returns:
        dict with "saved" (list of bank account ids) and "skipped" (list of
        {"plaid_account_id", "display_name", "reason"}).

    Raises:
        ValueError: if the item has no institution_name, since no id can be built.
    """
    if not item.institution_name:
        raise ValueError(f"Plaid item {item.item_id} has no institution_name")

    saved: list[str] = []
    skipped: list[dict] = []
    for plaid_account in get_accounts(item.access_token):
        plaid_account_id = plaid_account.account_id
        display_name = plaid_account.name
        account_type = bank_account_type_from_plaid(plaid_account.type or "", plaid_account.subtype)
        last4 = plaid_account.mask

        if account_type is None:
            reason = f"unsupported Plaid account type {plaid_account.type!r}"
        elif not last4:
            reason = "no mask (last 4 digits)"
        else:
            # TODO: if this Plaid account is already saved under an id built from
            # older values (e.g. a reissued card's last 4), the new id clashes on
            # plaid_account_id and the account is skipped instead of updated.
            # See docs/BACKLOGS.md BL-1.
            account = BankAccount(
                id=build_bank_account_id(item.institution_name, account_type, last4),
                institution_name=item.institution_name,
                account_type=account_type,
                last4=last4,
                display_name=display_name,
                plaid_institution_id=item.institution_id,
                plaid_item_id=item.item_id,
                plaid_account_id=plaid_account_id,
            )
            try:
                upsert_bank_account(account, conn=conn)
            except (ValueError, sqlite3.IntegrityError) as e:
                reason = f"could not save as {account.id}: {e}"
            else:
                saved.append(account.id)
                continue

        logger.warning("Skipping Plaid account %s: %s", plaid_account_id, reason)
        skipped.append(
            {"plaid_account_id": plaid_account_id, "display_name": display_name, "reason": reason}
        )

    return {"saved": saved, "skipped": skipped}


def save_linked_plaid_item(item: PlaidItem, conn: sqlite3.Connection = _default_conn) -> dict:
    """
    Save a newly linked Plaid item, then create its BankAccounts.

    The item is saved first, so if creating the accounts fails the link isn't
    lost — the next sync_raw_transactions_from_plaid retries it.

    Returns:
        sync_bank_accounts_from_plaid's {"saved", "skipped"} result.
    """
    save_plaid_item(item, conn=conn)
    return sync_bank_accounts_from_plaid(item, conn=conn)


def extract_journal_entries_from_transactions(transactions: dict) -> dict:
    """
    Extract journal entries from a Plaid transactions response dict.

    Iterates through added, modified, and removed transactions, running each
    through the LLM to generate journal entries. Results are grouped by whether
    the entries should be upserted or removed from the journal.

    Args:
        transactions: Plaid transactions response dict (with added, modified, removed, etc.)

    Returns:
        dict with:
            - "upsert": list of journal entry dicts for added and modified transactions
            - "remove": list of journal entry dicts for removed transactions

    # TODO: Model the input and output types.
    """
    upsert_entries = []
    remove_entries = []

    for txn in transactions.get("added", []) + transactions.get("modified", []):
        entries = extract_journal_entries_from_plaid_transaction(txn)
        upsert_entries.extend(entries)

    for txn in transactions.get("removed", []):
        entries = extract_journal_entries_from_plaid_transaction(txn)
        remove_entries.extend(entries)

    return {"upsert": upsert_entries, "remove": remove_entries}
