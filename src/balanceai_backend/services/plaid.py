from dataclasses import dataclass
from functools import lru_cache

import plaid
from balanceai_backend.config import settings
from plaid.api.plaid_api import PlaidApi
from plaid.model.accounts_get_request import AccountsGetRequest

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
