"""Tests for state.py: atomic load/save + snapshot write/prune (STATE-04).

All I/O goes through tmp_path -- never touches the repo-root state.json.
"""

import json
import os

import state


def test_load_missing_file_returns_empty_shape(tmp_path):
    path = tmp_path / "missing.json"
    assert state.load(str(path)) == {"peaks": {}, "snapshots": {}, "sentiment": {}}


def test_load_corrupt_json_returns_empty_shape(tmp_path):
    path = tmp_path / "corrupt.json"
    path.write_text("{not valid json")
    assert state.load(str(path)) == {"peaks": {}, "snapshots": {}, "sentiment": {}}


def test_save_then_load_round_trips(tmp_path):
    path = tmp_path / "state.json"
    data = {"peaks": {"TCS": {"peak": 100.0, "qty": 5, "avg_cost": 90.0}},
            "snapshots": {}, "sentiment": {}}
    state.save(data, str(path))
    assert state.load(str(path)) == data


def test_save_is_atomic_leaves_no_temp_file(tmp_path):
    path = tmp_path / "state.json"
    state.save({"peaks": {}, "snapshots": {}, "sentiment": {}}, str(path))
    leftovers = [f for f in os.listdir(tmp_path) if f != "state.json"]
    assert leftovers == []


def test_write_snapshot_overwrites_same_day_key():
    from datetime import date
    snapshots = {}
    snapshots = state.write_snapshot(snapshots, date(2026, 7, 10), 1000.0, {"A": {"price": 10.0, "value": 100.0}}, 2)
    snapshots = state.write_snapshot(snapshots, date(2026, 7, 10), 2000.0, {"A": {"price": 20.0, "value": 200.0}}, 3)
    assert list(snapshots.keys()) == ["2026-07-10"]
    assert snapshots["2026-07-10"]["total_value"] == 2000.0
    assert snapshots["2026-07-10"]["flags_fired"] == 3


def test_write_snapshot_does_not_mutate_input():
    from datetime import date
    original = {"2026-07-09": {"total_value": 1.0, "symbols": {}, "flags_fired": 0}}
    snapshot_copy = dict(original)
    state.write_snapshot(original, date(2026, 7, 10), 5.0, {}, 1)
    assert original == snapshot_copy


def test_write_snapshot_prunes_to_keep_n():
    from datetime import date, timedelta
    snapshots = {}
    base = date(2026, 7, 1)
    for i in range(15):
        snapshots = state.write_snapshot(snapshots, base + timedelta(days=i), float(i), {}, 0, keep=10)
    assert len(snapshots) == 10
    assert list(snapshots.keys())[0] == "2026-07-06"  # oldest 5 pruned (days 0-4)
    assert list(snapshots.keys())[-1] == "2026-07-15"


# --- day_change / n_day_trend (PNL-02, PNL-03, D-12) ---


def test_day_change_picks_strictly_before_today_entry():
    from datetime import date
    snapshots = {
        "2026-07-08": {"total_value": 900.0, "symbols": {}, "flags_fired": 0},
        "2026-07-09": {"total_value": 1000.0, "symbols": {}, "flags_fired": 0},
    }
    assert state.day_change(snapshots, date(2026, 7, 10)) == 1000.0


def test_day_change_returns_none_with_only_todays_key():
    from datetime import date
    snapshots = {"2026-07-10": {"total_value": 1000.0, "symbols": {}, "flags_fired": 0}}
    assert state.day_change(snapshots, date(2026, 7, 10)) is None


def test_day_change_still_returns_yesterday_when_today_already_in_snapshots():
    """D-12 regression: 2nd+ run of the day must never diff against itself."""
    from datetime import date
    snapshots = {
        "2026-07-09": {"total_value": 1000.0, "symbols": {}, "flags_fired": 0},
        "2026-07-10": {"total_value": 1050.0, "symbols": {}, "flags_fired": 1},  # earlier run today
    }
    assert state.day_change(snapshots, date(2026, 7, 10)) == 1000.0


def test_n_day_trend_none_with_no_prior_day():
    from datetime import date
    assert state.n_day_trend({}, date(2026, 7, 10)) is None


def test_n_day_trend_reports_actual_window_length_under_n():
    from datetime import date
    snapshots = {
        "2026-07-08": {"total_value": 900.0, "symbols": {}, "flags_fired": 0},
        "2026-07-09": {"total_value": 950.0, "symbols": {}, "flags_fired": 0},
    }
    trend = state.n_day_trend(snapshots, date(2026, 7, 10), n=5)
    assert trend == {"days": 2, "baseline": 900.0}


def test_n_day_trend_caps_window_at_n_over_longer_history():
    from datetime import date, timedelta
    base = date(2026, 7, 1)
    snapshots = {}
    for i in range(7):
        d = base + timedelta(days=i)
        snapshots[d.isoformat()] = {"total_value": float(i), "symbols": {}, "flags_fired": 0}
    trend = state.n_day_trend(snapshots, base + timedelta(days=7), n=5)
    assert trend["days"] == 5
    assert trend["baseline"] == 2.0  # 2026-07-03, the 5th-most-recent prior day


# --- weekly helpers (PNL-05, D-08) ---


def test_week_start_returns_monday_for_mid_week_date():
    from datetime import date
    assert state.week_start(date(2026, 7, 9)) == date(2026, 7, 6)  # Thu -> Mon


def test_week_start_returns_monday_for_friday_date():
    from datetime import date
    assert state.week_start(date(2026, 7, 10)) == date(2026, 7, 6)  # Fri -> same Mon


def test_weekly_movers_empty_on_thin_week():
    from datetime import date
    snapshots = {"2026-07-10": {"total_value": 1000.0, "flags_fired": 0,
                                 "symbols": {"A": {"price": 10.0, "value": 100.0}}}}
    assert state.weekly_movers(snapshots, date(2026, 7, 10)) == []


def test_weekly_movers_ranks_best_and_worst_over_the_week():
    from datetime import date
    snapshots = {
        "2026-07-06": {"total_value": 1000.0, "flags_fired": 0, "symbols": {
            "A": {"price": 100.0, "value": 0}, "B": {"price": 100.0, "value": 0},
            "C": {"price": 100.0, "value": 0},
        }},
        "2026-07-10": {"total_value": 1050.0, "flags_fired": 0, "symbols": {
            "A": {"price": 120.0, "value": 0},  # +20%
            "B": {"price": 100.0, "value": 0},  # 0%
            "C": {"price": 80.0, "value": 0},   # -20%
        }},
    }
    movers = state.weekly_movers(snapshots, date(2026, 7, 10), top_n=1)
    assert movers[0] == ("A", 0.2)
    assert movers[-1] == ("C", -0.2)


def test_weekly_movers_ignores_a_symbol_missing_from_baseline():
    from datetime import date
    snapshots = {
        "2026-07-06": {"total_value": 1000.0, "flags_fired": 0, "symbols": {
            "A": {"price": 100.0, "value": 0},
        }},
        "2026-07-10": {"total_value": 1000.0, "flags_fired": 0, "symbols": {
            "A": {"price": 110.0, "value": 0},
            "NEW": {"price": 50.0, "value": 0},  # started mid-week -- no baseline, skipped
        }},
    }
    movers = state.weekly_movers(snapshots, date(2026, 7, 10))
    assert movers == [("A", 0.1)]


def test_week_value_change_none_on_thin_week():
    from datetime import date
    snapshots = {"2026-07-10": {"total_value": 1000.0, "flags_fired": 0, "symbols": {}}}
    assert state.week_value_change(snapshots, date(2026, 7, 10)) is None


def test_week_value_change_computes_pct_over_the_week():
    from datetime import date
    snapshots = {
        "2026-07-06": {"total_value": 1000.0, "flags_fired": 0, "symbols": {}},
        "2026-07-10": {"total_value": 1100.0, "flags_fired": 0, "symbols": {}},
    }
    assert round(state.week_value_change(snapshots, date(2026, 7, 10)), 4) == 0.1


def test_flags_fired_this_week_sums_in_week_snapshots_only():
    from datetime import date
    snapshots = {
        "2026-06-29": {"total_value": 1.0, "flags_fired": 99, "symbols": {}},  # prior week
        "2026-07-06": {"total_value": 1.0, "flags_fired": 2, "symbols": {}},
        "2026-07-08": {"total_value": 1.0, "flags_fired": 1, "symbols": {}},
        "2026-07-10": {"total_value": 1.0, "flags_fired": 3, "symbols": {}},
    }
    assert state.flags_fired_this_week(snapshots, date(2026, 7, 10)) == 6
