"""Banks that are already linked: finding one by name, updating its link, and
what link_bank does when the user links one again."""

import re
import sqlite3

from balanceai_backend.bank_link.link import run_plaid_link_flow
from balanceai_backend.bank_link.plaid_item_db import find_plaid_items
from balanceai_backend.db.bank_account_db import find_bank_accounts
from balanceai_backend.db.connection import conn as _default_conn
from balanceai_backend.helpers.plaid_helper import (
    bank_account_type_from_plaid,
    sync_bank_accounts_from_plaid,
)
from balanceai_backend.models.bank_account import build_bank_account_id
from balanceai_backend.models.plaid_item import PlaidItem
from balanceai_backend.services.plaid import (
    get_accounts,
    get_plaid_item_health,
    remove_plaid_item,
)

# Plaid item errors that logging in again in update mode fixes.
_ITEM_ERRORS_FIXABLE_BY_UPDATE = {"ITEM_LOGIN_REQUIRED"}


def update_link(
    item: PlaidItem, add_accounts: bool = False, conn: sqlite3.Connection = _default_conn
) -> dict:
    """Run update mode on a linked item (log in again; with add_accounts,
    pick which accounts it covers), then refresh its bank accounts.

    Returns:
        {"item_id", "institution_name", "bank_accounts": {"saved", "skipped"}}
    """
    run_plaid_link_flow(item, add_accounts=add_accounts)
    return {
        "item_id": item.item_id,
        "institution_name": item.institution_name,
        "bank_accounts": sync_bank_accounts_from_plaid(item, conn=conn),
    }


def handle_already_linked_bank(
    linked: PlaidItem, conn: sqlite3.Connection = _default_conn
) -> dict | None:
    """link_bank's response for a bank that's already linked:
    - its login needs fixing: update mode on it, plus "updated": True;
    - otherwise nothing opens: {"already_linked": True, "item_id",
      "institution_name", "error_code"} (error_code None if it works, else a
      problem logging in again won't fix, e.g. the bank is down).
    None if Plaid no longer has it (removed at Plaid): link it anew
    (re-linking such a bank is docs/BACKLOGS.md BL-5, edge case 1).
    """
    health = get_plaid_item_health(linked.access_token)
    if not health.found:
        return None
    if health.error_code in _ITEM_ERRORS_FIXABLE_BY_UPDATE:
        return {**update_link(linked, conn=conn), "updated": True}
    return {
        "already_linked": True,
        "item_id": linked.item_id,
        "institution_name": linked.institution_name,
        "error_code": health.error_code,
    }


def resolve_duplicate_link(
    new_item: PlaidItem, conn: sqlite3.Connection = _default_conn
) -> dict | None:
    """After a first link, before it's saved: if any of its accounts is
    already linked through another item, it's a duplicate. The new item is
    removed at Plaid (nothing saved, nothing billed) and link_bank returns
    this instead. None if it isn't a duplicate (a new bank, or a different
    login at the same bank).

    If the existing item is still at Plaid: {"duplicate_removed": True,
    "item_id", "institution_name", "message"}, plus "login_required": True
    if it needs fixing (update_bank_link; not opened here, so the assistant
    can explain first), or "error_code" for a problem logging in again won't
    fix.

    If Plaid no longer has the existing item (removed at Plaid), the new one
    can't take over yet: it's removed too, with a message saying so.
    TODO(BL-5): take the accounts over and cut over instead (edge case 1).
    """
    existing = find_item_with_same_accounts(new_item, conn=conn)
    if existing is None:
        return None
    remove_plaid_item(new_item.access_token)
    health = get_plaid_item_health(existing.access_token)
    old_item_exists = health.found
    old_item_needs_fixing = old_item_exists and health.error_code in _ITEM_ERRORS_FIXABLE_BY_UPDATE
    summary = {
        "duplicate_removed": True,
        "item_id": existing.item_id,
        "institution_name": existing.institution_name,
    }
    if not old_item_exists:
        return {
            **summary,
            "message": (
                "This bank was connected before, but that connection was removed at "
                "Plaid. Reconnecting it isn't supported yet, so the new connection "
                "wasn't kept."
            ),
        }
    if old_item_needs_fixing:
        return {
            **summary,
            "login_required": True,
            "message": (
                "This bank was already connected, so the new connection wasn't kept "
                "(it would have counted everything twice). The existing connection "
                "needs you to log in again: run update_bank_link to restore it."
            ),
        }
    return {
        **summary,
        "error_code": health.error_code,
        "message": (
            "This bank was already connected, so the new connection wasn't kept "
            "(it would have counted everything twice)."
        ),
    }


def find_item_with_same_accounts(
    new_item: PlaidItem, conn: sqlite3.Connection = _default_conn
) -> PlaidItem | None:
    """The linked item that already has one of new_item's accounts: same
    bank account id (bank, type, last 4; the rule account sync uses), linked
    through a different item. None if there's none. Accounts account sync
    skips (unsupported type, no last 4) can't be stored, so they're skipped
    here too."""
    if not new_item.institution_name:
        return None
    for account in get_accounts(new_item.access_token):
        account_type = bank_account_type_from_plaid(account.type or "", account.subtype)
        if account_type is None or not account.mask:
            continue
        account_id = build_bank_account_id(new_item.institution_name, account_type, account.mask)
        found = find_bank_accounts(id=account_id, conn=conn)
        if found and found[0].plaid_item_id and found[0].plaid_item_id != new_item.item_id:
            items = find_plaid_items(item_id=found[0].plaid_item_id, conn=conn)
            if items:
                return items[0]
    return None


def find_linked_bank(bank_name: str, conn: sqlite3.Connection = _default_conn) -> PlaidItem | None:
    """The one linked item whose bank name matches bank_name: compared
    ignoring case, spaces and punctuation, either containing the other, so
    "acme" matches "Acme Bank". None if none match, or more than one
    (e.g. two logins at the same bank): then a normal link runs, and the
    check after Link catches a true duplicate."""
    wanted = _bank_name_key(bank_name)
    if not wanted:
        return None
    matches = []
    for item in find_plaid_items(conn=conn):
        have = _bank_name_key(item.institution_name or "")
        if have and (wanted in have or have in wanted):
            matches.append(item)
    return matches[0] if len(matches) == 1 else None


def _bank_name_key(name: str) -> str:
    """Lowercase letters and digits only: "Acme Bank & Co." -> "acmebankco"."""
    return re.sub(r"[^a-z0-9]", "", name.lower())
