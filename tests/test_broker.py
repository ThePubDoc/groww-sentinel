"""Mocked-I/O tests for broker.py -- growwapi boundary patched, zero live
network calls (TEST-02). Uses pyotp's own published example seed
(JBSWY3DPEHPK3PXP), which is public documentation, not a real credential.
"""

from unittest.mock import MagicMock, patch

import broker

FAKE_TOTP_SEED = "JBSWY3DPEHPK3PXP"

# Full-shape fixture per groww.in/trade-api/docs/python-sdk/portfolio
# (verified 2026-07-09): the response wraps the list under "holdings" and
# each item carries several SDK-internal fields broker.py must drop.
FAKE_HOLDINGS_RESPONSE = {
    "holdings": [
        {
            "isin": "INE002A01018",
            "trading_symbol": "RELIANCE",
            "quantity": 10,
            "average_price": 2500.0,
            "pledge_quantity": 0,
            "demat_locked_quantity": 0,
            "groww_locked_quantity": 0,
            "repledge_quantity": 0,
            "t1_quantity": 0,
            "demat_free_quantity": 10,
            "corporate_action_additional_quantity": 0,
            "active_demat_transfer_quantity": 0,
        },
    ]
}


@patch("broker.GrowwAPI")
def test_get_client_authenticates_via_runtime_totp_without_persisting_token(mock_groww_cls):
    # Arrange
    mock_groww_cls.get_access_token.return_value = "fake-token"

    # Act
    client = broker.get_client(api_key="k", totp_seed=FAKE_TOTP_SEED)

    # Assert: auth entrypoint invoked with a fresh 6-digit TOTP code; the
    # returned token is passed straight into GrowwAPI(...), never to disk.
    mock_groww_cls.get_access_token.assert_called_once()
    _, kwargs = mock_groww_cls.get_access_token.call_args
    assert kwargs["api_key"] == "k"
    assert kwargs["totp"].isdigit() and len(kwargs["totp"]) == 6
    mock_groww_cls.assert_called_once_with("fake-token")
    assert client is mock_groww_cls.return_value


def test_get_holdings_extracts_minimal_plain_dicts():
    # Arrange: a realistic full-shape response with extra SDK fields present
    mock_client = MagicMock()
    mock_client.get_holdings_for_user.return_value = FAKE_HOLDINGS_RESPONSE

    # Act
    holdings = broker.get_holdings(mock_client)

    # Assert: only trading_symbol/quantity/average_price survive
    assert holdings == [
        {"trading_symbol": "RELIANCE", "quantity": 10, "average_price": 2500.0}
    ]
    mock_client.get_holdings_for_user.assert_called_once_with(timeout=5)
