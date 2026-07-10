"""Lightweight self-check for sentinel.py's non-trivial pure logic (Rule 2):
secrets validation (DATA-04/D-12), secret redaction (T-01-03a), and the
portfolio P&L summary. No live broker/Telegram calls.
"""

from datetime import date, datetime

import sentinel


def _freeze_today(monkeypatch, fixed_date):
    """Monkeypatch sentinel.datetime.now() to a fixed IST datetime so
    _market_closed/main() can be tested without depending on the wall clock."""
    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(fixed_date.year, fixed_date.month, fixed_date.day, 9, 0, tzinfo=tz)

    monkeypatch.setattr(sentinel, "datetime", _Frozen)


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


# --- _telemetry (PNL-02..04, D-12) ---


def test_telemetry_computes_day_change_and_trend_from_loaded_snapshots(monkeypatch):
    snapshots = {
        "2026-07-08": {"total_value": 900.0, "symbols": {}, "flags_fired": 0},
        "2026-07-09": {"total_value": 1000.0, "symbols": {}, "flags_fired": 0},
    }
    merged = [{"symbol": "A", "qty": 1, "avg_cost": 1.0, "ltp": 10.0}]
    monkeypatch.setattr(sentinel.prices, "get_intraday", lambda symbols: {})

    result = sentinel._telemetry(snapshots, date(2026, 7, 10), 1100.0, merged)

    assert round(result["day_change_pct"], 4) == 0.1  # vs 2026-07-09 (1000 -> 1100)
    assert result["trend"]["days"] == 2
    assert round(result["trend"]["pct"], 4) == round((1100.0 - 900.0) / 900.0, 4)
    assert result["intraday_pct"] is None


def test_telemetry_omits_day_change_and_trend_on_first_run(monkeypatch):
    monkeypatch.setattr(sentinel.prices, "get_intraday", lambda symbols: {})
    result = sentinel._telemetry({}, date(2026, 7, 10), 1000.0, [])
    assert result == {"day_change_pct": None, "trend": None, "intraday_pct": None}


def test_telemetry_computes_value_weighted_intraday_pct(monkeypatch):
    merged = [
        {"symbol": "A", "qty": 10, "avg_cost": 1.0, "ltp": 100.0},
        {"symbol": "B", "qty": 5, "avg_cost": 1.0, "ltp": 200.0},
    ]
    monkeypatch.setattr(
        sentinel.prices, "get_intraday",
        lambda symbols: {
            "A": {"prev_close": 90.0, "last_price": 100.0},
            "B": {"prev_close": 200.0, "last_price": 200.0},
        },
    )
    result = sentinel._telemetry({}, date(2026, 7, 10), 2000.0, merged)
    prev_total = 10 * 90.0 + 5 * 200.0
    last_total = 10 * 100.0 + 5 * 200.0
    assert round(result["intraday_pct"], 6) == round((last_total - prev_total) / prev_total, 6)


def test_telemetry_intraday_none_when_source_lacks_prev_close(monkeypatch):
    merged = [{"symbol": "A", "qty": 10, "avg_cost": 1.0, "ltp": 100.0}]
    monkeypatch.setattr(
        sentinel.prices, "get_intraday",
        lambda symbols: {"A": {"prev_close": None, "last_price": 100.0}},
    )
    result = sentinel._telemetry({}, date(2026, 7, 10), 1000.0, merged)
    assert result["intraday_pct"] is None


def test_telemetry_never_raises_on_intraday_fetch_failure(monkeypatch):
    merged = [{"symbol": "A", "qty": 10, "avg_cost": 1.0, "ltp": 100.0}]

    def boom(symbols):
        raise Exception("yfinance hiccup")

    monkeypatch.setattr(sentinel.prices, "get_intraday", boom)
    result = sentinel._telemetry({}, date(2026, 7, 10), 1000.0, merged)
    assert result["intraday_pct"] is None


# --- _weekly_summary (PNL-05, D-08) ---


def test_weekly_summary_none_on_non_friday():
    snapshots = {
        "2026-07-06": {"total_value": 1000.0, "flags_fired": 0, "symbols": {"A": {"price": 100.0, "value": 0}}},
        "2026-07-09": {"total_value": 1100.0, "flags_fired": 0, "symbols": {"A": {"price": 110.0, "value": 0}}},
    }
    assert sentinel._weekly_summary(snapshots, date(2026, 7, 9)) is None  # Thursday


def test_weekly_summary_none_on_friday_with_thin_week():
    snapshots = {"2026-07-10": {"total_value": 1000.0, "flags_fired": 0, "symbols": {}}}
    assert sentinel._weekly_summary(snapshots, date(2026, 7, 10)) is None


def test_weekly_summary_populated_on_friday_with_week_history():
    snapshots = {
        "2026-07-06": {"total_value": 1000.0, "flags_fired": 2, "symbols": {"A": {"price": 100.0, "value": 0}}},
        "2026-07-10": {"total_value": 1100.0, "flags_fired": 1, "symbols": {"A": {"price": 110.0, "value": 0}}},
    }
    result = sentinel._weekly_summary(snapshots, date(2026, 7, 10))  # Friday
    assert result["movers"] == [("A", 0.1)]
    assert round(result["value_change"], 4) == 0.1
    assert result["flags_fired"] == 3


def test_main_exits_2_and_prints_missing_secret_when_env_empty(monkeypatch, capsys):
    monkeypatch.setattr(sentinel.os, "environ", {})
    code = sentinel.main(["--dry-run"])
    captured = capsys.readouterr()
    assert code == 2
    assert "GROWW_API_KEY" in captured.err


def test_main_wires_real_state_load_evaluate_save(monkeypatch, capsys):
    """rules.evaluate must receive the LOADED peaks (not {}), and state.save
    must persist {peaks, snapshots, sentiment} -- no live broker/Telegram/
    yfinance calls (Rule: sequential executor, mocked I/O boundaries only)."""
    env = {name: "x" for name in sentinel.REQUIRED_SECRETS}
    monkeypatch.setattr(sentinel.os, "environ", env)

    prior_peaks = {"RELIANCE": {"peak": 3000.0, "qty": 10, "avg_cost": 2500.0}}
    loaded_state = {"peaks": prior_peaks, "snapshots": {}, "sentiment": {}}
    monkeypatch.setattr(sentinel.state_mod, "load", lambda: loaded_state)

    saved = {}
    monkeypatch.setattr(sentinel.state_mod, "save", lambda new_state: saved.update(new_state))

    monkeypatch.setattr(sentinel.broker, "get_client", lambda *a, **k: object())
    monkeypatch.setattr(
        sentinel.broker, "get_holdings",
        lambda client: [{"trading_symbol": "RELIANCE", "quantity": 10, "average_price": 2500.0}],
    )
    monkeypatch.setattr(sentinel.prices, "get_prev_close", lambda symbols: {"RELIANCE": 2400.0})
    monkeypatch.setattr(sentinel.prices, "get_intraday", lambda symbols: {})

    received_peaks = {}

    def fake_evaluate(holdings, state, today):
        received_peaks.update(state)
        return [{"symbol": "RELIANCE", "flag": "HOLD", "pct": -0.04, "weight": 1.0,
                  "pct_below_peak": 0.2, "shares": 0, "value": 0.0, "reminder": False}], \
            {"RELIANCE": {"peak": 3000.0, "qty": 10, "avg_cost": 2500.0}}

    monkeypatch.setattr(sentinel.rules, "evaluate", fake_evaluate)
    monkeypatch.setattr(sentinel, "_best_effort_notify", lambda *a, **k: None)

    code = sentinel.main(["--dry-run"])
    capsys.readouterr()

    assert code == 0
    assert received_peaks == prior_peaks  # rules.evaluate got the LOADED peaks, not {}
    assert set(saved.keys()) == {"peaks", "snapshots", "sentiment"}
    assert saved["peaks"] == {"RELIANCE": {"peak": 3000.0, "qty": 10, "avg_cost": 2500.0}}
    today_key = list(saved["snapshots"].keys())[0]
    assert saved["snapshots"][today_key]["flags_fired"] == 0  # HOLD doesn't count


# --- _market_closed / holiday+weekend early-exit + healthcheck ping (RUN-02/NOTIFY-05, D-03/D-08) ---


def test_market_closed_true_for_seeded_2026_holiday():
    assert sentinel._market_closed(date(2026, 1, 26)) is True  # Republic Day


def test_market_closed_true_for_saturday():
    assert sentinel._market_closed(date(2026, 7, 11)) is True  # Saturday


def test_market_closed_false_for_ordinary_weekday():
    assert sentinel._market_closed(date(2026, 7, 10)) is False  # Friday


def _env_with_secrets(**extra):
    env = {name: "x" for name in sentinel.REQUIRED_SECRETS}
    env.update(extra)
    return env


def test_main_closed_day_returns_0_without_broker_call_and_pings_healthcheck(monkeypatch, capsys):
    env = _env_with_secrets(HEALTHCHECK_URL="https://hc-ping.com/uuid")
    monkeypatch.setattr(sentinel.os, "environ", env)
    _freeze_today(monkeypatch, date(2026, 1, 26))  # Republic Day (holiday)

    def boom(*a, **k):
        raise AssertionError("broker.get_client must not be called on a closed day")

    monkeypatch.setattr(sentinel.broker, "get_client", boom)

    pings = []
    monkeypatch.setattr(sentinel.notify, "healthcheck_ping", lambda url: pings.append(url))

    code = sentinel.main(["--dry-run"])
    capsys.readouterr()

    assert code == 0
    assert pings == ["https://hc-ping.com/uuid"]


def test_main_pings_healthcheck_on_successful_dry_run(monkeypatch, capsys):
    env = _env_with_secrets(HEALTHCHECK_URL="https://hc-ping.com/uuid")
    monkeypatch.setattr(sentinel.os, "environ", env)
    _freeze_today(monkeypatch, date(2026, 7, 10))  # ordinary Friday

    monkeypatch.setattr(sentinel.state_mod, "load", lambda: {"peaks": {}, "snapshots": {}, "sentiment": {}})
    monkeypatch.setattr(sentinel.state_mod, "save", lambda new_state: None)
    monkeypatch.setattr(sentinel.broker, "get_client", lambda *a, **k: object())
    monkeypatch.setattr(
        sentinel.broker, "get_holdings",
        lambda client: [{"trading_symbol": "RELIANCE", "quantity": 10, "average_price": 2500.0}],
    )
    monkeypatch.setattr(sentinel.prices, "get_prev_close", lambda symbols: {"RELIANCE": 2400.0})
    monkeypatch.setattr(sentinel.prices, "get_intraday", lambda symbols: {})
    monkeypatch.setattr(
        sentinel.rules, "evaluate",
        lambda holdings, state, today: (
            [{"symbol": "RELIANCE", "flag": "HOLD", "pct": -0.04, "weight": 1.0,
              "pct_below_peak": 0.2, "shares": 0, "value": 0.0, "reminder": False}],
            {},
        ),
    )

    pings = []
    monkeypatch.setattr(sentinel.notify, "healthcheck_ping", lambda url: pings.append(url))

    code = sentinel.main(["--dry-run"])
    capsys.readouterr()

    assert code == 0
    assert pings == ["https://hc-ping.com/uuid"]


def test_main_pings_healthcheck_on_no_holdings_exit(monkeypatch, capsys):
    env = _env_with_secrets(HEALTHCHECK_URL="https://hc-ping.com/uuid")
    monkeypatch.setattr(sentinel.os, "environ", env)
    _freeze_today(monkeypatch, date(2026, 7, 10))  # ordinary Friday

    monkeypatch.setattr(sentinel.state_mod, "load", lambda: {"peaks": {}, "snapshots": {}, "sentiment": {}})
    monkeypatch.setattr(sentinel.broker, "get_client", lambda *a, **k: object())
    monkeypatch.setattr(sentinel.broker, "get_holdings", lambda client: [])
    monkeypatch.setattr(sentinel, "_best_effort_notify", lambda *a, **k: None)

    pings = []
    monkeypatch.setattr(sentinel.notify, "healthcheck_ping", lambda url: pings.append(url))

    code = sentinel.main(["--dry-run"])
    capsys.readouterr()

    assert code == 0
    assert pings == ["https://hc-ping.com/uuid"]


def test_main_does_not_ping_healthcheck_on_exception_path(monkeypatch, capsys):
    env = _env_with_secrets(HEALTHCHECK_URL="https://hc-ping.com/uuid")
    monkeypatch.setattr(sentinel.os, "environ", env)
    _freeze_today(monkeypatch, date(2026, 7, 10))  # ordinary Friday

    def boom():
        raise Exception("state load failed")

    monkeypatch.setattr(sentinel.state_mod, "load", boom)
    monkeypatch.setattr(sentinel, "_best_effort_notify", lambda *a, **k: None)

    pings = []
    monkeypatch.setattr(sentinel.notify, "healthcheck_ping", lambda url: pings.append(url))

    code = sentinel.main(["--dry-run"])
    capsys.readouterr()

    assert code == 1
    assert pings == []


def test_main_past_seeded_year_warns_but_still_proceeds(monkeypatch, capsys):
    env = _env_with_secrets()
    monkeypatch.setattr(sentinel.os, "environ", env)
    _freeze_today(monkeypatch, date(2028, 1, 1))  # past LAST_SEEDED_YEAR

    monkeypatch.setattr(sentinel.state_mod, "load", lambda: {"peaks": {}, "snapshots": {}, "sentiment": {}})
    monkeypatch.setattr(sentinel.broker, "get_client", lambda *a, **k: object())
    monkeypatch.setattr(sentinel.broker, "get_holdings", lambda client: [])
    monkeypatch.setattr(sentinel, "_best_effort_notify", lambda *a, **k: None)
    monkeypatch.setattr(sentinel.notify, "healthcheck_ping", lambda url: None)

    code = sentinel.main(["--dry-run"])
    captured = capsys.readouterr()

    assert code == 0  # did not early-exit on the warning alone
    assert "2028" in captured.err
