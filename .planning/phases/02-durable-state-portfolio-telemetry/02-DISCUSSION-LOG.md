# Phase 2: Durable State & Portfolio Telemetry - Discussion Log

> **Audit trail only.** Decisions live in CONTEXT.md.

**Date:** 2026-07-09
**Phase:** 2-Durable State & Portfolio Telemetry
**Areas discussed:** State shape & cadence, P&L trend + weekly, Sentiment caching, Corp-action detection

---

## State shape & cadence

| Question | Choice |
|----------|--------|
| Run cadence | ✓ Market-hours hourly (~7 runs/weekday) — supersedes daily 08:30 (Phase-3 cron change) |
| Snapshot key | ✓ Per-day (intraday reruns overwrite; peak updates every run) |

## P&L trend + weekly

| Question | Choice |
|----------|--------|
| Trend window | ✓ 5 trading days |
| Day-change base | ✓ Prior day's snapshot (not prior run) |
| Weekly movers | ✓ % change over the trading week (from per-symbol snapshots) |

## Sentiment caching

| Question | Choice |
|----------|--------|
| Cache lifetime | ✓ Same calendar day (~1 model call/day; smooths flaky news) |

## Corp-action detection (RULES-06)

| Question | Choice |
|----------|--------|
| Response | ✓ Warn + suppress the P&L flag (quantity-jump detection → CORP-ACTION line; TRIM/TRAIL still evaluate) |

## Claude's Discretion
- Trend glyphs/wording, weekly-block layout, mover count (2–3), prune thresholds, corp-action tolerance %.

## Deferred Ideas
- state.json git commit-back → Phase 3 (RUN-03)
- hourly market-hours cron → Phase 3 (RUN-01)
- sturdier news source (Google News RSS) vs yfinance
- contribution-based weekly view (alt to %-movers)
