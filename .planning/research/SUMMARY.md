# Project Research Summary

**Project:** Groww Sentinel  
**Domain:** Personal brokerage advisory bot (Groww TradeAPI → rules engine → Telegram digest)  
**Researched:** 2026-07-09  
**Confidence:** MEDIUM-HIGH (stack and architecture well-documented; Groww corporate-action behavior and GitHub org policy are the primary unknowns)

## Executive Summary

Groww Sentinel is a deterministic, daily advisory bot that fetches your portfolio holdings from Groww's official TradeAPI, evaluates them against seven simple flag rules (buy averaging, loss-exit signals, concentration warnings, profit-booking thresholds), and sends a low-noise, human-gated Telegram digest every weekday morning. The design is intentionally non-automated — it alerts, you verify, you decide.

The recommended approach is a 5-file Python script (no web server, no database) orchestrated by GitHub Actions' free cron, persisting mutable state (price peaks, daily snapshots) as a simple JSON file committed back to the repo each run. The tech stack is minimal and low-risk: the official Groww Python SDK (`growwapi`), standard libraries (`pyotp` for headless TOTP, `requests` for raw Telegram calls, `pytest` for testing), and GitHub's built-in secrets + workflow permissions.

Two technical risks require explicit decisions during implementation: (1) **corporate actions** — Groww's API doesn't document whether `average_price` is retroactively adjusted for stock splits/bonuses, so the default assumption is unsafe for money-path calculations; and (2) **GitHub org policy** — the `ThePubDoc` org may restrict workflow token permissions, causing silent state-commit failures that look like "all quiet" but are actually data loss. Both risks are mitigatable but require verification/fallbacks planned upfront, not discovered at runtime.

## Key Findings

### Recommended Stack

**Core technologies** (all pinned to exact versions in `requirements.txt`):

- **Python 3.11+** (SDK supports 3.9–3.13) — Only language with official Groww SDK; GitHub Actions cache tier includes 3.12 by default
- **`growwapi` 1.5.0** (PyPI) — Official Groww TradeAPI SDK; TOTP-based headless auth, rate limits documented (20 req/sec non-trading); exception hierarchy includes rate-limit handling
- **`pyotp` 2.10.0** (PyPI) — Minimal TOTP generation from stored seed; zero dependencies; matches Groww's own TOTP flow documentation
- **`requests` 2.32.3** (already transitive from `growwapi`) — Raw HTTP POST for Telegram `sendMessage` API; no bot framework needed for a fire-and-exit daily message
- **`PyYAML` 6.0.3** (PyPI) — YAML parser for `config.yaml` (symbol → core/tactical tags); de facto standard
- **`pytest` 8.4.2** (PyPI) — Test runner, required by design spec; standard ecosystem choice

### Expected Features

**Must have at launch (v1):**

| Feature | Why |
|---------|-----|
| 7-flag rules engine (HOLD, UNTAGGED, STOP HIT, AVG CANDIDATE, TRIM, TRAIL WATCH, BOOK 50%) | The entire decision set |
| Peak price tracking with reset-on-exit, re-seed-on-rebuy | Required for TRAIL WATCH and STOP HIT peak-based logic |
| Manual-gate reminder on AVG CANDIDATE | Keeps bot "advisory" not "auto-pilot" |
| Non-HOLD-only filtering + "all quiet" heartbeat | Prevents alert fatigue; proves job ran |
| Overall P&L + day snapshot delta | Minimum "how am I doing today" telemetry |
| Holiday-aware skip | Running pre-market against stale holiday prices produces wrong flags |
| Fetch-failure notification + secret validation | "Never silently skip a day" + "fail loud naming missing secret" |

**Should have soon (v1.x):**

- N-day trend direction (trivial once daily snapshots proven)
- Weekly summary block (Friday-only append)
- Corporate-action adjustment awareness (only if verification shows Groww's `average_price` is NOT already adjusted)

### Architecture Approach

**Pattern:** Pure-core / imperative-shell. All decision logic lives in one pure `evaluate()` function with no I/O, no clock calls, no file access. I/O lives at the edges (broker fetches, notify sends, sentinel orchestrates), each returning plain dicts/lists.

**Major components:**

1. **`sentinel.py`** (orchestrator) — Validate secrets → check holiday → call broker → evaluate rules → format digest → send → persist state
2. **`broker.py`** (Groww I/O) — Auth via TOTP, fetch holdings, fetch LTPs
3. **`rules.py`** (pure evaluation) — `evaluate(holdings, config, state, today) → (flags, new_state)` with named threshold constants
4. **`notify.py`** (Telegram I/O) — Format digest (pure) + send (thin HTTP wrapper)
5. **`config.yaml`** (user input) — Symbol → bucket mappings
6. **`state.json`** (mutable state) — Peak prices + date-keyed snapshots, rebuilt-not-merged each run
7. **GitHub Actions workflow** — Cron at 03:00 UTC (08:30 IST weekdays) with state.json commit

### Critical Pitfalls & Mitigations

1. **Corporate actions silently corrupt `avg_price` and peak** — Groww docs don't confirm adjustment. Verify empirically at impl time; add quantity-delta detection as backstop.

2. **Peak tracking has three distinct bugs** — Never decays (alert fatigue), seed wrong on first-seen, survives sell then lies on rebuy. Unit test all three scenarios explicitly.

3. **GitHub `contents: write` fails silently due to org policy or branch protection** — Order job as fetch → compute → **persist first** → notify; test with real `workflow_dispatch` before cron; have PAT fallback ready.

4. **Concurrent/double runs corrupt same-day snapshot** — Use `concurrency: {group, cancel-in-progress: false}` in workflow; make per-day write an explicit merge, not blind overwrite.

5. **Alerter has no watcher — silent failure is invisible** — Implement independent dead-man's-switch (heartbeat ping, GitHub status email, third-party monitoring) that does NOT depend on sentinel job itself.

## Implications for Roadmap

### Phase 1: Data Model & Foundation Testing
**Rationale:** State schema and rules must be correct first; they're the ground truth.  
**Delivers:** `state.json` schema, `config.yaml` shape, full `rules.py` with boundary tests for every threshold constant.  
**Avoids:** Pitfall #11 (false test confidence), Pitfall #2 (peak tracking bugs).

### Phase 2: Broker & Auth Integration
**Rationale:** Verify Groww SDK surface early; most external uncertainty lives here.  
**Delivers:** `broker.py` with growwapi integration, auth verification against real sandbox, rate-limit behavior, LTP batch performance.  
**Research flags:** Verify Groww corporate-action behavior on `average_price` (undocumented); characterize LTP rate limits in sandbox.

### Phase 3: Rules Engine & State Model
**Rationale:** Depends on Phases 1-2; transforms raw holdings into actionable flags.  
**Delivers:** Corporate-action detection, state rebuild-not-merge, peak reset/re-seed with explicit holding-period tracking, snapshot pruning.  
**Avoids:** Pitfall #1 (corporate actions), Pitfall #2 (peak tracking), Pitfall #4 (concurrent runs).

### Phase 4: Notification & Formatting
**Rationale:** Depends on Rules Engine; pure formatting, high-signal for UX.  
**Delivers:** Telegram `send()` via raw requests, grouped/triaged layout, reason/number inline, explicit `⚠️ LTP unavailable` lines, adversarial input tests.  
**Avoids:** Pitfall #10 (message length/escaping), Pitfall #6 (silent omission).

### Phase 5: Scheduling & CI Wiring
**Rationale:** Brings all pieces into GitHub Actions; where external unknowns must be validated.  
**Delivers:** `.github/workflows/sentinel.yml` with correct UTC cron, `permissions: contents: write`, static NSE holiday list, secret validation, state persistence, concurrency guards, real `workflow_dispatch` test.  
**Research flags:** Verify ThePubDoc org policy on `permissions: contents: write` (is it org-restricted?). Have PAT fallback ready if blocked.

### Phase 6: Integration, Hardening & Dead-Man's-Switch
**Rationale:** End-to-end validation, resilience checks, meta-safeguard that the alerter itself is alive.  
**Delivers:** Full end-to-end sandbox run, boundary tests for pitfall #11, dead-man's-switch implementation (explicitly called out as required), double-trigger integration test, security audit.  
**Avoids:** Pitfall #9 (silent system death), Pitfall #11 (false test confidence), Pitfall #12 (secrets leak).

## NSE Holiday Calendar Decision: Static (v1) with Upgrade Path

**Reconciliation:** STACK.md recommends `pandas_market_calendars` (XNSE); ARCHITECTURE.md recommends static list. Recommendation: **static for v1 launch, with planned upgrade path to `pandas_market_calendars` after validation.**

**v1 approach (launch with this):**
- `holidays.py` contains static `set[date]` of NSE holidays, refreshed once per calendar year from NSE's published list
- Manual update: ~5 min/year, deterministic, fails loud if forgotten (wrong flag = immediate detection)
- Zero dependencies, zero runtime surprises

**v1.x upgrade path (only pursue if manual edit becomes a burden):**
- Switch to `pandas_market_calendars` (community-maintained, actively used in quant trading, direct incentive to keep calendars current)
- Before switching: verify XNSE output against NSE's published list for 1-2 years
- Gain: yearly update becomes automatic; Loss: adds dependency, requires ongoing trust

**Why this reconciliation:** Start simple under your control (matches ARCHITECTURE's pragmatism for personal projects), but explicitly plan upgrade path contingent on (a) manual edit becoming demonstrably burdensome, and (b) successful validation of package's NSE data against real schedules.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Groww SDK, pyotp, GitHub Actions all have official current documentation; dependencies pinned; no version mismatch risk |
| Features | HIGH | Design spec already approved; thresholds validated against market conventions |
| Architecture | HIGH | Pure-core/imperative-shell is established pattern; GitHub Actions cron + state-commit mechanics documented |
| Pitfalls | MEDIUM-HIGH | GitHub org token policy is known unknown (must verify Phase 5); Groww corporate-action behavior undocumented (must verify Phase 2). All other pitfalls have known mitigations |

### Gaps to Address

1. **Groww `average_price` corporate-action adjustment:** Undocumented. Verify empirically at Phase 2 against known bonus/split holding. Does not block launch but must be checked before relying on P&L.

2. **Groww LTP rate-limit specifics:** Undocumented. Characterize in sandbox at Phase 2. For personal portfolios <50 holdings, not expected to be an issue.

3. **GitHub org policy on workflow token permissions:** May restrict `permissions: contents: write`. Test with real `workflow_dispatch` at Phase 5. Have fine-grained-PAT fallback ready.

4. **Dead-man's-switch service selection:** Multiple options (GitHub status email, third-party heartbeat, self-hosted check). Decide at Phase 6 based on latency tolerance and setup cost.

## Sources

### Primary (HIGH confidence)

- Groww Trade API Python SDK: https://groww.in/trade-api/docs/python-sdk — auth, holdings schema, LTP methods, rate limits
- growwapi on PyPI: https://pypi.org/project/growwapi/ — version 1.5.0, Python 3.9–3.13
- pyotp on PyPI: https://pypi.org/project/PyOTP/ — TOTP generation
- GitHub Docs — Controlling GITHUB_TOKEN permissions: https://docs.github.com/en/actions/
- GitHub Community — Org override of workflow permissions, scheduled workflow delays
- Telegram Bot API — sendMessage 4096-char limit, parse-mode escaping

### Secondary (MEDIUM confidence)

- Project design spec: `.planning/docs/superpowers/specs/2026-07-09-groww-sentinel-design.md` — approved thresholds, requirements
- Trading-education sources: TradingWithRayner, TickerDaily — trailing-stop conventions (5–15%), used to validate thresholds
- pandas_market_calendars: https://pandas-market-calendars.readthedocs.io/ — XNSE existence (note: no explicit accuracy audit published)
- NSE official holiday calendar: https://www.nseindia.com/trade/market-timings.html — used for validation reference

### Tertiary (flagged LOW — need impl-time verification)

- Groww corporate-action adjustment: Not in official docs; verify empirically Phase 2
- Groww LTP rate limits: Specific caps not published; characterize in sandbox Phase 2
- `pandas_market_calendars` XNSE accuracy: Validate against official NSE schedules for 1-2 years before upgrading from static list

---

*Research completed: 2026-07-09*  
*Synthesized by: GSD Research Synthesizer*  
*Ready for roadmap planning: yes*
