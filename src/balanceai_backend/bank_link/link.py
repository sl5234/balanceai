"""One-time bank-connection setup via Plaid Hosted Link.

Run as: python -m balanceai_backend.bank_link.link
"""

import time
import webbrowser

from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.link_token_create_hosted_link import LinkTokenCreateHostedLink
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.link_token_get_request import LinkTokenGetRequest
from plaid.model.products import Products

from balanceai_backend.bank_link.plaid_item_db import save_plaid_item
from balanceai_backend.models.plaid_item import PlaidItem
from balanceai_backend.services.plaid import get_client

_DEFAULT_TIMEOUT_S = 300
_POLL_INTERVAL_S = 2


class LinkExitedError(Exception):
    """Raised when the user exits, or Plaid reports an error, before Hosted Link succeeds."""


def create_hosted_link(user_id: str = "balanceai-user") -> tuple[str, str]:
    """
    Start a Plaid Hosted Link session.

    Returns:
        (link_token, hosted_link_url) — open hosted_link_url in a browser for the
        user to authenticate with their bank.
    """
    request = LinkTokenCreateRequest(
        client_name="BalanceAI",
        language="en",
        country_codes=[CountryCode("US")],
        user=LinkTokenCreateRequestUser(client_user_id=user_id),
        products=[Products("transactions")],
        hosted_link=LinkTokenCreateHostedLink(),
    )
    response = get_client().link_token_create(request)
    return response.link_token, response.hosted_link_url


def poll_for_public_token(link_token: str, timeout_s: int = _DEFAULT_TIMEOUT_S):
    """
    Poll /link/token/get until the user completes (or exits) the Hosted Link flow.

    Success path verified against a live Plaid Sandbox response: the SDK's
    LinkTokenGetSessionsResponse model schema advertises an "on_success" field,
    but a real completed Hosted Link session never populates it — the actual
    signal is session.results.item_add_results[0], which carries public_token,
    accounts, and institution directly. The exit/error path below is not yet
    verified against a live response (no captured example of a user
    abandoning/erroring out of the flow) — best-effort from the SDK's schema only.

    Plaid's generated SDK models raise ApiAttributeError on unset optional fields
    rather than returning None, so every optional field below is read via getattr.

    Returns:
        (public_token, item_add_result) — item_add_result carries .institution
        and .accounts for the newly linked item.

    Raises:
        LinkExitedError: the user exited, or Plaid reported an error, before success.
        TimeoutError: timeout_s elapsed with no result either way.
    """
    client = get_client()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        response = client.link_token_get(LinkTokenGetRequest(link_token=link_token))
        link_sessions = getattr(response, "link_sessions", None) or []
        for session in reversed(link_sessions):
            results = getattr(session, "results", None)
            item_add_results = getattr(results, "item_add_results", None) if results else None
            if item_add_results:
                result = item_add_results[0]
                return result.public_token, result

            exit_info = getattr(session, "exit", None)
            if exit_info is not None:
                error = getattr(exit_info, "error", None)
                message = error.error_message if error is not None else "user exited Hosted Link"
                raise LinkExitedError(message)
        time.sleep(_POLL_INTERVAL_S)
    raise TimeoutError(f"Timed out after {timeout_s}s waiting for Hosted Link completion")


def complete_link(link_token: str, timeout_s: int = _DEFAULT_TIMEOUT_S) -> PlaidItem:
    """
    Wait for the Hosted Link flow to finish, exchange the resulting public_token
    for a permanent access_token, and persist the linked item.

    our_account_ids is left empty — mapping Plaid's accounts to our own Account
    records is a separate, not-yet-built piece.

    Returns:
        The saved PlaidItem.
    """
    public_token, item_add_result = poll_for_public_token(link_token, timeout_s=timeout_s)

    exchange_response = get_client().item_public_token_exchange(
        ItemPublicTokenExchangeRequest(public_token=public_token)
    )

    institution = getattr(item_add_result, "institution", None)
    accounts = getattr(item_add_result, "accounts", None) or []

    item = PlaidItem(
        item_id=exchange_response.item_id,
        access_token=exchange_response.access_token,
        institution_id=getattr(institution, "institution_id", None),
        institution_name=getattr(institution, "name", None),
        plaid_account_ids=[account.id for account in accounts],
    )
    save_plaid_item(item)
    return item


if __name__ == "__main__":
    link_token, hosted_link_url = create_hosted_link()
    print(f"Open this URL to connect your bank:\n{hosted_link_url}\n")
    try:
        webbrowser.open(hosted_link_url)
    except webbrowser.Error:
        print("(couldn't open a browser automatically — open the URL above manually)")

    print("Waiting for you to complete the connection in your browser...")
    try:
        linked_item = complete_link(link_token)
    except LinkExitedError as e:
        print(f"Link did not complete: {e}")
        raise SystemExit(2) from e
    except TimeoutError as e:
        print(str(e))
        raise SystemExit(2) from e

    print(
        f"Connected: {linked_item.institution_name or 'unknown institution'} "
        f"(item_id={linked_item.item_id})"
    )
