# Phase 1: End-to-End Morning Digest - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-09
**Phase:** 1-End-to-End Morning Digest
**Areas discussed:** Threshold values, AVG tiering, Digest format, Run & config shape

---

## Threshold values

| Option | Description | Selected |
|--------|-------------|----------|
| Lock spec defaults | AVG -10/-20/-30, TRIM >10%, BOOK +25%, STOP -12%/-15%-below-peak, TRAIL >20%-below-peak; named constants | ✓ |
| Tune some | Provide changed numbers | |

**User's choice:** Lock spec defaults.

| Option | Description | Selected |
|--------|-------------|----------|
| Equity holdings value | Symbol value ÷ total equity holdings value; no cash | ✓ |
| Include cash / total portfolio | Needs a cash figure not fetched | |

**User's choice:** Weight denominator = equity holdings value.

---

## AVG tiering

| Option | Description | Selected |
|--------|-------------|----------|
| 3-tier escalation | Fires at each -10/-20/-30 level; shows tranche | ✓ |
| Single fire at -10% | One flag, no tier | |

**User's choice:** 3-tier escalation.

| Option | Description | Selected |
|--------|-------------|----------|
| Gate all tiers | weight<10% required at every tier | ✓ |
| Gate tier 1 only | Deeper tiers ignore weight | |

**User's choice:** Weight gate on all tiers.

---

## Digest format

| Option | Description | Selected |
|--------|-------------|----------|
| Symbol + flag + % + hint | e.g. `RELIANCE: STOP HIT (-13% vs avg) → review exit` | ✓ |
| Symbol + flag only | Terser | |
| Verbose | Adds LTP/avg/qty/value | |

**User's choice:** Symbol + flag + % + hint.

| Option | Description | Selected |
|--------|-------------|----------|
| Value + basic P&L | Header: total value + overall unrealized P&L% | ✓ |
| Value only | Value header, no P&L | |
| No header | Flags only in Phase 1 | |

**User's choice:** Value + basic P&L header.

| Option | Description | Selected |
|--------|-------------|----------|
| Action vs Opportunity | 🔴 ACTION / 🟢 OPPORTUNITY / ⚠️ UNTAGGED sections | ✓ |
| Flat by severity | Single sorted list | |

**User's choice:** Action vs Opportunity grouping.

---

## Run & config shape

| Option | Description | Selected |
|--------|-------------|----------|
| Run + --dry-run flag | Default sends Telegram; `--dry-run` prints to stdout | ✓ |
| Plain run only | Always sends | |

**User's choice:** Run + `--dry-run`.

| Option | Description | Selected |
|--------|-------------|----------|
| Flat symbol→tag map | `RELIANCE: core` etc. | ✓ |
| Per-symbol overrides | Custom per-symbol thresholds | |

**User's choice:** Flat symbol→tag map.

| Option | Description | Selected |
|--------|-------------|----------|
| Treat as UNTAGGED | Invalid tag → UNTAGGED, surfaced | ✓ |
| Hard error | Abort run on bad tag | |

**User's choice:** Invalid tag → UNTAGGED (fails visible, not fatal).

---

## Claude's Discretion

- "All quiet" line wording and AVG 3-gate reminder text
- Telegram parse mode / emoji specifics
- Function/naming within the 4-file split
- Value-header number formatting

## Deferred Ideas

- Per-symbol threshold overrides (Phase 2+)
- Day P&L / N-day trend / weekly header content (Phase 2, PNL-*)
- Durable state, peak reset-on-exit, dated snapshots (Phase 2, STATE-01..04)
- Corporate-action stale-avg_price warning (Phase 2, RULES-06)
