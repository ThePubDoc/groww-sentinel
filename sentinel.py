"""Orchestrator: secrets -> config -> IST today -> broker fetch -> rules -> notify.

Wires broker.py -> rules.py -> notify.py (DATA-04, D-09/10/11/12). state.json
persists peaks/snapshots/sentiment across runs (STATE-01..04) -- loaded once
near the top, saved atomically after building the digest. `--dry-run` prints
the digest instead of sending it to Telegram. Runnable as `python -m sentinel`
or `python sentinel.py`.
"""

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import broker
import notify
import prices
import rules
import sentiment
import state as state_mod

REQUIRED_SECRETS = ["GROWW_API_KEY", "GROWW_TOTP_SEED", "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID"]


def validate_secrets(env: dict) -> list[str]:
    """Return the names of any missing required secret (DATA-04, D-12)."""
    return [name for name in REQUIRED_SECRETS if not env.get(name)]


def _redact(text: str, env: dict) -> str:
    """Strip any known secret value out of a string before it can leak (T-01-03a)."""
    for name in REQUIRED_SECRETS:
        value = env.get(name)
        if value:
            text = text.replace(value, "[REDACTED]")
    return text


def _best_effort_notify(env: dict, message: str) -> None:
    """Never let a notify-of-failure itself crash the run (T-01-03d)."""
    token, chat_id = env.get("TELEGRAM_TOKEN"), env.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        notify.send(token, chat_id, message)
    except Exception:
        pass


def _portfolio_summary(merged: list[dict], today) -> dict:
    priced = [h for h in merged if h["ltp"] is not None]
    total_value = sum(h["qty"] * h["ltp"] for h in priced)
    total_cost = sum(h["qty"] * h["avg_cost"] for h in priced)
    overall_pnl_pct = (total_value - total_cost) / total_cost if total_cost else 0.0
    return {"total_value": total_value, "overall_pnl_pct": overall_pnl_pct, "date": today}


def _telemetry(snapshots: dict, today, total_value: float, merged: list[dict]) -> dict:
    """PNL-02/03/04: day-change %, N-day trend, and intraday % -- computed
    from the LOADED (pre-write) snapshots (D-12) so a same-day rerun never
    diffs against itself. Best-effort throughout: any missing baseline or
    yfinance hiccup degrades to None rather than a 0% or a crash."""
    day_change_pct = None
    prior_value = state_mod.day_change(snapshots, today)
    if prior_value:
        day_change_pct = (total_value - prior_value) / prior_value

    trend = None
    trend_info = state_mod.n_day_trend(snapshots, today)
    if trend_info and trend_info["baseline"]:
        trend = {"days": trend_info["days"],
                  "pct": (total_value - trend_info["baseline"]) / trend_info["baseline"]}

    intraday_pct = None
    try:
        intraday = prices.get_intraday([h["symbol"] for h in merged if h["ltp"] is not None])
        priced = [
            (h["qty"], intraday[h["symbol"]]["prev_close"], intraday[h["symbol"]]["last_price"])
            for h in merged if h["ltp"] is not None and intraday.get(h["symbol"], {}).get("prev_close")
            and intraday.get(h["symbol"], {}).get("last_price")
        ]
        prev_total = sum(qty * prev for qty, prev, _ in priced)
        last_total = sum(qty * last for qty, _, last in priced)
        if prev_total:
            intraday_pct = (last_total - prev_total) / prev_total
    except Exception:
        pass

    return {"day_change_pct": day_change_pct, "trend": trend, "intraday_pct": intraday_pct}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    dry_run = "--dry-run" in argv
    env = os.environ

    missing = validate_secrets(env)
    if missing:
        message = f"Missing required secret(s): {', '.join(missing)}"
        print(message, file=sys.stderr)
        _best_effort_notify(env, f"Sentinel could not start -- {message}")
        return 2

    try:
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        state = state_mod.load()

        client = broker.get_client(env["GROWW_API_KEY"], env["GROWW_TOTP_SEED"])
        holdings = broker.get_holdings(client)
        if not holdings:
            _best_effort_notify(env, "Groww Sentinel: no holdings, nothing to check today.")
            print("No holdings.")
            return 0

        # "ltp" slot now carries the previous close (Groww live data is paid);
        # sourced from a free public quote feed. See prices.py (DATA-03).
        ltp = prices.get_prev_close([h["trading_symbol"] for h in holdings])
        merged = [
            {
                "symbol": h["trading_symbol"],
                "qty": h["quantity"],
                "avg_cost": h["average_price"],
                "ltp": ltp.get(h["trading_symbol"]),
            }
            for h in holdings
        ]

        flags, new_peaks = rules.evaluate(merged, state=state["peaks"], today=today)
        # Optional news-sentiment layer: blocks risky adds (AVERAGE -> AVOID on
        # bearish news). Best-effort -- never let it break the run; no key = skip.
        new_sentiment = state["sentiment"]
        try:
            flags, new_sentiment = sentiment.adjust(flags, env.get("GEMINI_API_KEY"), state["sentiment"], today)
        except Exception:
            pass
        portfolio = _portfolio_summary(merged, today)
        # Telemetry (PNL-02..04) reads the LOADED snapshots -- BEFORE
        # write_snapshot below overwrites today's key (D-12/Pattern 3).
        portfolio.update(_telemetry(state["snapshots"], today, portfolio["total_value"], merged))

        # Persist peaks/snapshot/sentiment BEFORE sending, using the LOADED
        # snapshots (not a post-write copy) -- plan 02-03's day-change lookup
        # depends on today's key being absent when it looks it up (D-02).
        per_symbol = {
            h["symbol"]: {"price": h["ltp"], "value": h["qty"] * h["ltp"]}
            for h in merged if h["ltp"] is not None
        }
        flags_fired = sum(1 for f in flags if f["flag"] not in ("HOLD", "NO PRICE"))
        new_snapshots = state_mod.write_snapshot(
            state["snapshots"], today, portfolio["total_value"], per_symbol, flags_fired,
        )
        state_mod.save({"peaks": new_peaks, "snapshots": new_snapshots, "sentiment": new_sentiment})

        message = notify.format_digest(flags, portfolio)

        if dry_run:
            print(message)
            return 0

        notify.send(env["TELEGRAM_TOKEN"], env["TELEGRAM_CHAT_ID"], message)
        return 0

    except Exception as exc:
        reason = _redact(str(exc), env)
        print(f"Sentinel run failed: {reason}", file=sys.stderr)
        _best_effort_notify(env, f"Groww Sentinel: fetch failed -- {reason}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
