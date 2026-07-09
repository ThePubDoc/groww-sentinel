"""Orchestrator: secrets -> config -> IST today -> broker fetch -> rules -> notify.

Wires broker.py -> rules.py -> notify.py (DATA-04, D-09/10/11/12). Phase 1 has
no durable state.json -- state is always {} (STATE-05 first-run peak seed only).
`--dry-run` prints the digest instead of sending it to Telegram. Runnable as
`python -m sentinel` or `python sentinel.py`.
"""

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import yaml

import broker
import notify
import rules

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


def _load_config(path: str = "config.yaml") -> dict:
    """Flat symbol -> core|tactical map (RULES-04, D-10). Never yaml.load (T-01-03b)."""
    with open(path) as fh:
        return yaml.safe_load(fh) or {}


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
        config = _load_config()
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date()

        client = broker.get_client(env["GROWW_API_KEY"], env["GROWW_TOTP_SEED"])
        holdings = broker.get_holdings(client)
        if not holdings:
            _best_effort_notify(env, "Groww Sentinel: no holdings, nothing to check today.")
            print("No holdings.")
            return 0

        ltp = broker.get_ltp(client, [h["trading_symbol"] for h in holdings])
        merged = [
            {
                "symbol": h["trading_symbol"],
                "qty": h["quantity"],
                "avg_cost": h["average_price"],
                "ltp": ltp.get(h["trading_symbol"]),
            }
            for h in holdings
        ]

        flags, _new_state = rules.evaluate(merged, config, state={}, today=today)
        portfolio = _portfolio_summary(merged, today)
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
