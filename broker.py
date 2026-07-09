"""I/O boundary to the Groww TradeAPI SDK (DATA-01, DATA-02, DATA-05).

Every call here talks to the network; nothing here is pure. Returns only
plain dicts -- no growwapi SDK objects ever leak past this module, so the
rest of the pipeline (rules.py, tests) never depends on SDK internals.

The access token is never written to disk (DATA-05): it lives only as a
local variable inside get_client() and is regenerated fresh on every call.
GrowwAPIException is intentionally left uncaught -- broker raises, the
orchestrator (sentinel.py) decides how to respond.
"""

import pyotp
from growwapi import GrowwAPI


def get_client(api_key: str, totp_seed: str) -> GrowwAPI:
    """Authenticate headlessly via a runtime-generated TOTP (DATA-01).

    api_key is the TOTP-flow "TOTP token"; totp_seed is the "TOTP Secret" --
    both from Groww's dashboard. The resulting access_token is a local
    variable only, never persisted anywhere (DATA-05).
    """
    totp_code = pyotp.TOTP(totp_seed).now()
    access_token = GrowwAPI.get_access_token(api_key=api_key, totp=totp_code)
    return GrowwAPI(access_token)


def get_holdings(client: GrowwAPI) -> list[dict]:
    """Fetch holdings and return ONLY minimal plain dicts (DATA-02).

    The live API wraps the list under a "holdings" key -- verified against
    groww.in/trade-api/docs/python-sdk/portfolio (2026-07-09); each item
    carries several other SDK-internal fields (isin, pledge_quantity, ...)
    that are intentionally dropped here.
    """
    response = client.get_holdings_for_user(timeout=5)
    return [
        {
            "trading_symbol": h["trading_symbol"],
            "quantity": h["quantity"],
            "average_price": h["average_price"],
        }
        for h in response.get("holdings", [])
    ]
