"""Mocked-I/O tests for prices.py -- yfinance boundary patched, zero live
network calls (TEST-02)."""

from unittest.mock import patch

import numpy as np
import pandas as pd

import prices


def _download_frame(columns_data: dict) -> pd.DataFrame:
    """Build a yfinance-shaped DataFrame: MultiIndex columns (field, ticker)
    so that frame["Close"] yields a per-ticker DataFrame, matching the real
    multi-ticker yf.download response."""
    tickers = list(columns_data)
    idx = pd.date_range("2026-07-02", periods=3)
    close = pd.DataFrame({t: columns_data[t] for t in tickers}, index=idx)
    close.columns = pd.MultiIndex.from_product([["Close"], tickers])
    return close


@patch("prices.yf.download")
def test_get_prev_close_maps_last_close_per_symbol(mock_download):
    # Arrange: two priced tickers; prev close = last non-NaN row
    mock_download.return_value = _download_frame(
        {"RELIANCE.NS": [2790.0, 2800.0, 2801.25], "TCS.NS": [3400.0, 3410.0, 3450.0]}
    )

    # Act
    result = prices.get_prev_close(["RELIANCE", "TCS"])

    # Assert
    assert result == {"RELIANCE": 2801.25, "TCS": 3450.0}
    mock_download.assert_called_once()
    assert mock_download.call_args.kwargs["tickers"] == ["RELIANCE.NS", "TCS.NS"]


@patch("prices.yf.download")
def test_unpriced_or_missing_symbol_maps_to_none(mock_download):
    # Arrange: RELIANCE priced, CAPINVIT all-NaN (Yahoo has no data for it)
    mock_download.return_value = _download_frame(
        {"RELIANCE.NS": [2790.0, 2800.0, 2801.25], "CAPINVIT.NS": [np.nan] * 3}
    )

    # Act
    result = prices.get_prev_close(["RELIANCE", "CAPINVIT"])

    # Assert: unpriced symbol degrades to None, never raises
    assert result == {"RELIANCE": 2801.25, "CAPINVIT": None}


def test_empty_symbols_returns_empty_without_calling_yfinance():
    with patch("prices.yf.download") as mock_download:
        assert prices.get_prev_close([]) == {}
        mock_download.assert_not_called()
