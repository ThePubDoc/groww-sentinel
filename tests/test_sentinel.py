"""Lightweight self-check for sentinel.py's non-trivial pure logic (Rule 2):
secrets validation (DATA-04/D-12), secret redaction (T-01-03a), and the
portfolio P&L summary. No live broker/Telegram calls.
"""

from datetime import date

import sentinel


def test_validate_secrets_returns_missing_names_in_order():
    env = {"TELEGRAM_TOKEN": "t"}
    missing = sentinel.validate_secrets(env)
    assert missing == ["GROWW_API_KEY", "GROWW_TOTP_SEED", "TELEGRAM_CHAT_ID"]


def test_validate_secrets_empty_when_all_present():
    env = {name: "x" for name in sentinel.REQUIRED_SECRETS}
    assert sentinel.validate_secrets(env) == []


def test_redact_strips_known_secret_value():
    env = {"GROWW_API_KEY": "supersecretkey"}
    text = sentinel._redact("auth failed for supersecretkey", env)
    assert "supersecretkey" not in text
    assert "[REDACTED]" in text


def test_portfolio_summary_computes_value_and_pnl_pct():
    merged = [
        {"symbol": "A", "qty": 10, "avg_cost": 100.0, "ltp": 110.0},
        {"symbol": "B", "qty": 5, "avg_cost": 200.0, "ltp": None},  # excluded, no price
    ]
    summary = sentinel._portfolio_summary(merged, date(2026, 7, 9))
    assert summary["total_value"] == 1100.0
    assert round(summary["overall_pnl_pct"], 4) == 0.10
    assert summary["date"] == date(2026, 7, 9)


def test_main_exits_2_and_prints_missing_secret_when_env_empty(monkeypatch, capsys):
    monkeypatch.setattr(sentinel.os, "environ", {})
    code = sentinel.main(["--dry-run"])
    captured = capsys.readouterr()
    assert code == 2
    assert "GROWW_API_KEY" in captured.err
