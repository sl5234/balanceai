def transactions_sync(
    access_token: str,
    cursor: str | None = None,
    account_id: str | None = None,
) -> dict:
    """
    Fetch transaction updates for a Plaid item.

    Args:
        access_token: The Plaid access token for the item
        cursor: Cursor from a previous sync to fetch only new updates. Omit to fetch full history.
        account_id: Filter results to a specific account

    Returns:
        Plaid /transactions/sync response dict with added, modified, removed, has_more, next_cursor
    """
    return {
        "added": [
            {
                "transaction_id": "pR7k8mXnQ3",
                "account_id": "acc_12345",
                "amount": 50.00,
                "iso_currency_code": "USD",
                "date": "2026-02-27",
                "name": "SAFEWAY #1234",
                "merchant_name": "Safeway",
                "pending": False,
                "category": ["Shops", "Supermarkets and Groceries"],
                "personal_finance_category": {
                    "primary": "FOOD_AND_DRINK",
                    "detailed": "FOOD_AND_DRINK_GROCERIES",
                },
            },
            {
                "transaction_id": "qT9j2nYoR5",
                "account_id": "acc_12345",
                "amount": 15.99,
                "iso_currency_code": "USD",
                "date": "2026-02-25",
                "name": "NETFLIX.COM",
                "merchant_name": "Netflix",
                "pending": False,
                "category": ["Service", "Subscription"],
                "personal_finance_category": {
                    "primary": "ENTERTAINMENT",
                    "detailed": "ENTERTAINMENT_TV_AND_MOVIES",
                },
            },
        ],
        "modified": [],
        "removed": [],
        "has_more": False,
        "next_cursor": "eyJwYWdlX3Rva2VuIjoiMTI0In0=",
    }
