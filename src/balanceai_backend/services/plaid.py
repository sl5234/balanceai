from functools import lru_cache

import plaid
from balanceai_backend.config import settings
from plaid.api.plaid_api import PlaidApi

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
