"""I/O boundary for previous-close prices (DATA-03).

Groww's live-data endpoints (get_ltp/get_ohlc/get_quote/historical) are all a
paid subscription; the free API returns cost basis but no price. Sentinel runs
pre-market (~08:30 IST), so it only ever needs the *previous close*, which is
freely available from Yahoo Finance via yfinance. This keeps the Groww account
on the official API (holdings) while sourcing read-only public quotes elsewhere.

A symbol Yahoo can't price (e.g. some InvITs/REITs whose ticker isn't
`<symbol>.NS`) maps to None -- defensive, not fatal; rules.py surfaces it as a
NO PRICE flag. Network I/O only; nothing here is pure.
"""

import logging
import warnings

import yfinance as yf

# yfinance logs unpriced/delisted tickers to stderr; we handle missing prices
# explicitly (-> None -> NO PRICE flag), so silence the noise for clean CI logs.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)


def _extract(close, ticker: str) -> float | None:
    """Last non-NaN close for one ticker, or None. Handles the yfinance
    single-vs-multi-ticker shape difference (Series vs DataFrame column)."""
    try:
        series = close[ticker] if hasattr(close, "columns") else close
        series = series.dropna()
        return float(series.iloc[-1]) if len(series) else None
    except (KeyError, IndexError, ValueError, TypeError):
        return None


def get_prev_close(symbols: list[str]) -> dict[str, float | None]:
    """Previous close per NSE symbol via one batched yfinance download (DATA-03).

    Maps each Groww trading_symbol to Yahoo's `<symbol>.NS` ticker. Missing or
    unpriced symbols map to None.
    """
    if not symbols:
        return {}
    tickers = [f"{s}.NS" for s in symbols]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        data = yf.download(
            tickers=tickers, period="5d", progress=False, auto_adjust=False
        )
    close = data["Close"]
    return {s: _extract(close, f"{s}.NS") for s in symbols}


def get_intraday(symbols: list[str]) -> dict[str, dict[str, float | None]]:
    """Previous close + last price per NSE symbol via yfinance fast_info
    (PNL-04) -- the purpose-built lightweight quote path, preferred over the
    slower `.info` dict (02-RESEARCH State of the Art). A symbol whose lookup
    fails or lacks an attribute degrades to {prev_close: None, last_price:
    None}, never fatal -- additive helper, does not touch get_prev_close.
    """
    if not symbols:
        return {}
    result = {}
    for s in symbols:
        try:
            fast_info = yf.Ticker(f"{s}.NS").fast_info
            result[s] = {
                "prev_close": fast_info.previous_close,
                "last_price": fast_info.last_price,
            }
        except Exception:
            result[s] = {"prev_close": None, "last_price": None}
    return result
