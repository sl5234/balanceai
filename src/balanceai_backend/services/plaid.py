import json
from dataclasses import dataclass
from functools import lru_cache

import plaid
from balanceai_backend.config import settings
from plaid.api.plaid_api import PlaidApi
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.item_get_request import ItemGetRequest
from plaid.model.item_remove_request import ItemRemoveRequest

_ENVIRONMENTS = {
    "sandbox": plaid.Environment.Sandbox,
    "production": plaid.Environment.Production,
}


@lru_cache(maxsize=1)
def get_client() -> PlaidApi:
    """
    Build (once, lazily) and cache the Plaid API client.

    Reads settings.plaid_client_id / plaid_secret / plaid_env. Raises ValueError
    if credentials are missing or plaid_env isn't a recognized environment, rather
    than letting the SDK fail with a confusing downstream error.
    """
    if not settings.plaid_client_id or not settings.plaid_secret:
        raise ValueError(
            "Plaid credentials are not configured. Set PLAID_CLIENT_ID and PLAID_SECRET."
        )

    host = _ENVIRONMENTS.get(settings.plaid_env.lower())
    if host is None:
        raise ValueError(
            f"Unknown PLAID_ENV '{settings.plaid_env}'. Must be one of {sorted(_ENVIRONMENTS)}."
        )

    configuration = plaid.Configuration(
        host=host,
        api_key={
            "clientId": settings.plaid_client_id,
            "secret": settings.plaid_secret,
        },
    )
    api_client = plaid.ApiClient(configuration)
    return PlaidApi(api_client)


@dataclass
class PlaidAccount:
    """One account from Plaid's /accounts/get, as plain data — no Plaid SDK objects."""

    account_id: str
    name: str | None
    type: str | None  # e.g. "depository", "credit", "loan", "investment"
    subtype: str | None  # e.g. "checking", "credit card", "student"
    mask: str | None  # last 2-4 digits of the account number


def _enum_value(value) -> str | None:
    """Plaid's SDK returns AccountType/AccountSubtype wrapper objects, not plain strings."""
    if value is None:
        return None
    return getattr(value, "value", value)


def get_accounts(access_token: str) -> list[PlaidAccount]:
    """
    Call /accounts/get and return each account as plain data.

    Plaid's generated SDK models raise ApiAttributeError on unset optional
    fields rather than returning None, so optional fields are read via getattr
    — a missing field comes back as None.
    """
    response = get_client().accounts_get(AccountsGetRequest(access_token=access_token))
    return [
        PlaidAccount(
            account_id=account.account_id,
            name=getattr(account, "name", None),
            type=_enum_value(getattr(account, "type", None)),
            subtype=_enum_value(getattr(account, "subtype", None)),
            mask=getattr(account, "mask", None),
        )
        for account in getattr(response, "accounts", None) or []
    ]


def plaid_error_code(error: plaid.ApiException) -> str | None:
    """Plaid's error_code (e.g. "ITEM_LOGIN_REQUIRED") from an API error's
    JSON body, or None if it has none."""
    try:
        code = json.loads(error.body or "{}").get("error_code")
    except (TypeError, ValueError, AttributeError):
        return None
    return code if isinstance(code, str) else None


@dataclass
class PlaidItemHealth:
    """A linked item's state at Plaid (/item/get).

    found: False if Plaid no longer has it (ITEM_NOT_FOUND: removed at Plaid).
    error_code: the item's current error (e.g. "ITEM_LOGIN_REQUIRED"), or None
    if it's working.
    """

    found: bool
    error_code: str | None = None


def get_plaid_item_health(access_token: str) -> PlaidItemHealth:
    """Ask Plaid how a linked item is doing.

    Raises:
        plaid.ApiException: for Plaid errors other than ITEM_NOT_FOUND.
    """
    try:
        item = get_client().item_get(ItemGetRequest(access_token=access_token)).item
    except plaid.ApiException as e:
        if plaid_error_code(e) == "ITEM_NOT_FOUND":
            return PlaidItemHealth(found=False)
        raise
    error = getattr(item, "error", None)
    return PlaidItemHealth(
        found=True, error_code=getattr(error, "error_code", None) if error is not None else None
    )


def remove_plaid_item(access_token: str) -> None:
    """Remove an item at Plaid (/item/remove): its access token stops
    working and Plaid stops billing for it."""
    get_client().item_remove(ItemRemoveRequest(access_token=access_token))
