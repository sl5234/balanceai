"""Match the two sides of one transfer among classified raw transactions; see
docs/BACKEND_IMPLEMENTATION_DECISIONS.md #5 and #12."""

from balanceai_backend.models.bank_account import BankAccountType
from balanceai_backend.models.raw_transaction import RawTransaction
from balanceai_backend.raw_transactions.generate_journal_entry import bank_side_account

_MAX_DAYS_APART = 5

Match = tuple[RawTransaction, RawTransaction]  # (money-out side, money-in side)


def _is_candidate(
    out_side: RawTransaction, in_side: RawTransaction, account_types: dict[str, BankAccountType]
) -> bool:
    """Decision #5: different bank accounts, the same amount with opposite signs,
    at most _MAX_DAYS_APART days apart, and each side's counter account is the
    other side's bank-side account."""
    assert out_side.classification is not None and in_side.classification is not None
    return (
        out_side.account_id != in_side.account_id
        and out_side.amount == -in_side.amount
        and abs((out_side.posting_date - in_side.posting_date).days) <= _MAX_DAYS_APART
        and out_side.classification.counter_account
        == bank_side_account(account_types[in_side.account_id])
        and in_side.classification.counter_account
        == bank_side_account(account_types[out_side.account_id])
    )


def find_matched_transfers(
    txns: list[RawTransaction], account_types: dict[str, BankAccountType]
) -> list[Match]:
    """
    Matched transfers: (money-out side, money-in side) that are the two sides
    of one transfer. Each transaction matches at most once, with the candidate
    closest in date. A transaction whose closest candidates are on more than
    one bank account doesn't match, and neither do those candidates
    (decision #12).
    Unclassified transactions, zero amounts, and bank accounts missing from
    account_types are skipped.
    """
    usable = [
        t
        for t in txns
        if t.classification is not None and t.amount != 0 and t.account_id in account_types
    ]
    outs = [t for t in usable if t.amount < 0]
    ins = [t for t in usable if t.amount > 0]
    candidates = [
        (abs((o.posting_date - i.posting_date).days), o, i)
        for o in outs
        for i in ins
        if _is_candidate(o, i, account_types)
    ]

    # Each transaction's candidates, to spot true ties.
    options: dict[str, list[tuple[int, RawTransaction]]] = {}
    for days, o, i in candidates:
        options.setdefault(o.raw_transaction_id, []).append((days, i))
        options.setdefault(i.raw_transaction_id, []).append((days, o))
    tied: set[str] = set()
    for txn_id, txn_options in options.items():
        closest = min(days for days, _ in txn_options)
        nearest = [other for days, other in txn_options if days == closest]
        if len({other.account_id for other in nearest}) > 1:
            tied.add(txn_id)
            tied.update(other.raw_transaction_id for other in nearest)

    # Closest first; ids break exact ties so the result doesn't depend on input order.
    matches: list[Match] = []
    used: set[str] = set()
    for _, o, i in sorted(
        candidates,
        key=lambda c: (c[0], c[1].posting_date, c[1].raw_transaction_id, c[2].raw_transaction_id),
    ):
        if {o.raw_transaction_id, i.raw_transaction_id} & (used | tied):
            continue
        matches.append((o, i))
        used.update((o.raw_transaction_id, i.raw_transaction_id))
    return matches
