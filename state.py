"""Durable state.json I/O shell (STATE-01..04). Stdlib only, no new dependency.

Schema (D-03): {"peaks": {SYM: {peak, qty, avg_cost}},
"snapshots": {"YYYY-MM-DD": {total_value, symbols, flags_fired}},
"sentiment": {SYM: {date, label, reason}}}.

load()/save() are the only impure functions here; write_snapshot is a pure
helper (no disk access) so it stays unit-testable without touching a file.
Committing state.json back to the repo is Phase 3 (RUN-03) -- out of scope.
"""

import json
import os
import tempfile

_EMPTY_STATE = {"peaks": {}, "snapshots": {}, "sentiment": {}}


def load(path: str = "state.json") -> dict:
    """Read state.json; missing or corrupt file falls back to the empty shape
    (V5 defense-in-depth -- the atomic save() below already prevents partial
    writes, this guards a truncated file from some other cause)."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(_EMPTY_STATE)


def save(state: dict, path: str = "state.json") -> None:
    """Atomic write: temp file in the same directory, then os.replace (T-02-02).
    The file on disk is always the old-complete or new-complete version."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2, default=str)
        os.replace(tmp_path, path)
    except Exception:
        os.unlink(tmp_path)
        raise


def write_snapshot(snapshots: dict, today, total_value: float, per_symbol: dict,
                    flags_fired: int, keep: int = 10) -> dict:
    """Pure: date-keyed overwrite (STATE-04/D-02, idempotent same-day rerun),
    bounded to the most recent `keep` dated entries (D-05). Never mutates
    `snapshots` -- returns a new dict."""
    key = today.isoformat()
    updated = {**snapshots, key: {
        "total_value": total_value, "symbols": per_symbol, "flags_fired": flags_fired,
    }}
    return dict(sorted(updated.items())[-keep:])


def _prior_dates(snapshots: dict, today) -> list[str]:
    """Dates strictly before today, sorted ascending (D-12 off-by-one guard:
    never `sorted(keys)[-2]`, which wrongly grabs today's own earlier value
    once today's key exists from an earlier run this same day)."""
    key = today.isoformat()
    return sorted(d for d in snapshots if d < key)


def day_change(snapshots: dict, today) -> float | None:
    """PNL-02: total_value of the most recent snapshot strictly before today,
    or None on the first run ever (no prior day exists). Caller computes
    (today_value - prior_value) / prior_value. Call this on the LOADED
    (pre-write) snapshots -- see 02-RESEARCH Pattern 3."""
    prior_dates = _prior_dates(snapshots, today)
    if not prior_dates:
        return None
    return snapshots[prior_dates[-1]]["total_value"]


def n_day_trend(snapshots: dict, today, n: int = 5) -> dict | None:
    """PNL-03: up to n most recent prior-day snapshots as a trend baseline.
    Returns {"days": <actual window length>, "baseline": <total_value>}, or
    None with no prior day. `days` reflects the real window (never a
    hardcoded "5d") so week-one degrades gracefully to a 1-4 day trend."""
    prior_dates = _prior_dates(snapshots, today)
    if not prior_dates:
        return None
    window = prior_dates[-n:]
    return {"days": len(window), "baseline": snapshots[window[0]]["total_value"]}
