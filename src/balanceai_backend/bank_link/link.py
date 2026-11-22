"""One-time bank-connection setup via Plaid Hosted Link.

Run as: python -m balanceai_backend.bank_link.link
"""

import logging
import time
import webbrowser

from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.link_token_create_hosted_link import LinkTokenCreateHostedLink
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_update import LinkTokenCreateRequestUpdate
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.link_token_get_request import LinkTokenGetRequest
from plaid.model.products import Products

from balanceai_backend.helpers.plaid_helper import save_linked_plaid_item
from balanceai_backend.models.plaid_item import PlaidItem
from balanceai_backend.services.plaid import get_client

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_S = 300
_POLL_INTERVAL_S = 5


class LinkExitedError(Exception):
    """Raised when the user exits, or Plaid reports an error, before Hosted Link succeeds."""


def create_hosted_link(
    user_id: str = "balanceai-user", item: PlaidItem | None = None, add_accounts: bool = False
) -> tuple[str, str]:
    """Start a Plaid Hosted Link session: a first link if item is None, else
    update mode for that item (see run_plaid_link_flow).

    Returns:
        (link_token, hosted_link_url)
    """
    is_initial_link = item is None
    kwargs: dict = {}
    if is_initial_link:
        kwargs["products"] = [Products("transactions")]
    else:
        assert item is not None
        # Update mode: Plaid requires products to be left out.
        kwargs["access_token"] = item.access_token
        if add_accounts:
            kwargs["update"] = LinkTokenCreateRequestUpdate(account_selection_enabled=True)
    request = LinkTokenCreateRequest(
        client_name="BalanceAI",
        language="en",
        country_codes=[CountryCode("US")],
        user=LinkTokenCreateRequestUser(client_user_id=user_id),
        hosted_link=LinkTokenCreateHostedLink(),
        **kwargs,
    )
    response = get_client().link_token_create(request)
    return response.link_token, response.hosted_link_url


def run_plaid_link_flow(
    item: PlaidItem | None = None,
    add_accounts: bool = False,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
) -> PlaidItem:
    """Open Plaid Hosted Link in the browser and wait for the user to finish.

    No item: a first link. The resulting public_token is exchanged for a new
    item (not saved; callers save it with save_linked_plaid_item).

    An item: update mode for that link. The user logs in or approves at the
    bank again, and with add_accounts picks which accounts it covers. Nothing
    to exchange: the same item comes back, with the same access token,
    account ids, transaction ids and sync cursor.

    Raises:
        LinkExitedError: the user exited, Plaid reported an error, or a first
            link finished without linking a bank.
        TimeoutError: the user didn't finish within timeout_s.
    """
    is_initial_link = item is None
    link_token, hosted_link_url = create_hosted_link(item=item, add_accounts=add_accounts)
    try:
        webbrowser.open(hosted_link_url)
    except webbrowser.Error:
        logger.warning("Could not open a browser automatically for %s", hosted_link_url)

    session = _wait_for_finished_session(link_token, timeout_s)
    if not is_initial_link:
        # A finished update-mode session with no exit is success (seen live in
        # Sandbox). It also carries an item_add_result, which isn't needed.
        assert item is not None
        return item
    return _exchange_public_token_for_item(_get_item_add_result(link_token, session))


def _get_item_add_result(link_token: str, session):
    """A finished first-link session's result. In Sandbox the result arrives
    before the session is marked finished; as a safety net, if it's missing,
    look at the same session once more (`session` is a snapshot; by id, since
    the user may have opened the URL again).

    Raises:
        LinkExitedError: still no result: Plaid finished without linking a bank.
    """
    result = _read_item_add_result(session)
    if result is None:
        time.sleep(_POLL_INTERVAL_S)
        result = _read_item_add_result(
            _find_session(link_token, getattr(session, "link_session_id", None))
        )
    if result is None:
        raise LinkExitedError("Plaid finished without linking a bank")
    return result


def _read_item_add_result(session):
    """session.results.item_add_results[0] (public_token, institution,
    accounts; seen live in Sandbox, session.on_success is never filled for
    Hosted Link), or None. One session adds one item."""
    results = getattr(session, "results", None) if session is not None else None
    added = getattr(results, "item_add_results", None) if results is not None else None
    return added[0] if added else None


def _exchange_public_token_for_item(result) -> PlaidItem:
    """Swap a first link's temporary public_token for the new item: its
    item_id and permanent access_token (not saved here)."""
    exchange = get_client().item_public_token_exchange(
        ItemPublicTokenExchangeRequest(public_token=result.public_token)
    )
    institution = getattr(result, "institution", None)
    return PlaidItem(
        item_id=exchange.item_id,
        access_token=exchange.access_token,
        institution_id=getattr(institution, "institution_id", None),
        institution_name=getattr(institution, "name", None),
    )


def _sessions(link_token: str) -> list:
    """The link token's sessions, oldest first (the user may open the URL more
    than once); empty before the user opens it."""
    response = get_client().link_token_get(LinkTokenGetRequest(link_token=link_token))
    return getattr(response, "link_sessions", None) or []


def _find_session(link_token: str, link_session_id: str | None):
    """The session with this id, or None."""
    return next(
        (
            s
            for s in _sessions(link_token)
            if getattr(s, "link_session_id", None) == link_session_id
        ),
        None,
    )


def _wait_for_finished_session(link_token: str, timeout_s: int):
    """Poll every _POLL_INTERVAL_S until the newest session finishes
    (finished_at set). Only the newest counts: an earlier session the user
    exited doesn't end a later one still in progress.

    Plaid's SDK models raise on unset optional fields, so they're read via
    getattr. Seen live in Sandbox: an exited session has both exit and
    finished_at set, so exit is checked first.

    Returns:
        The finished session.

    Raises:
        LinkExitedError: the newest session exited (user quit or Plaid error).
        TimeoutError: it didn't finish within timeout_s.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        sessions = _sessions(link_token)
        session = sessions[-1] if sessions else None
        exit_info = getattr(session, "exit", None) if session is not None else None
        if exit_info is not None:
            error = getattr(exit_info, "error", None)
            raise LinkExitedError(
                error.error_message if error is not None else "user exited Hosted Link"
            )
        if session is not None and getattr(session, "finished_at", None):
            return session
        time.sleep(_POLL_INTERVAL_S)
    raise TimeoutError(f"Timed out after {timeout_s}s waiting for Hosted Link completion")


if __name__ == "__main__":
    print("Opening Plaid in your browser to connect your bank...")
    try:
        linked_item = run_plaid_link_flow()
    except LinkExitedError as e:
        print(f"Link did not complete: {e}")
        raise SystemExit(2) from e
    except TimeoutError as e:
        print(str(e))
        raise SystemExit(2) from e

    save_linked_plaid_item(linked_item)
    print(
        f"Connected: {linked_item.institution_name or 'unknown institution'} "
        f"(item_id={linked_item.item_id})"
    )
