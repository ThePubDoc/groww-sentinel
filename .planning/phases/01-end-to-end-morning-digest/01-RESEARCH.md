# Phase 1: End-to-End Morning Digest - Research

**Researched:** 2026-07-09
**Domain:** Headless Python script — Groww TradeAPI auth/fetch → pure rules engine → Telegram digest. Manual invocation only (no cron this phase).
**Confidence:** HIGH (growwapi auth/holdings/LTP signatures cross-verified against official Groww docs this session; Telegram Bot API mechanics are long-stable public API; pytest mocking is standard library behavior). MEDIUM on exact rules-engine boundary operators and flag-precedence order — CONTEXT.md/spec don't state these precisely; flagged in Assumptions Log for confirmation.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Threshold values (RULES-03)**
- D-01: Lock spec's threshold numbers as v1 named constants in `rules.py`, tunable later: AVG CANDIDATE down 10/20/30% from avg cost; TRIM weight > 10% of portfolio; BOOK 50% up > 25% from avg cost (tactical); STOP HIT down > 12% from avg cost OR > 15% below tracked peak (tactical); TRAIL WATCH > 20% below tracked peak (core).
- D-02: TRIM weight denominator = total equity holdings value (sum of qty×LTP across held symbols). No cash/other assets.

**AVG CANDIDATE tiering (RULES-02)**
- D-03: 3-tier escalation, not single-fire. Fires at each of -10/-20/-30% from avg cost; message shows which tranche (e.g. `AVG CANDIDATE tier 2 (-21%)`). Deeper fall = stronger add signal.
- D-04: `weight < 10%` gate applies to ALL tiers — if a core holding is already ≥10% of portfolio, suppress AVG even at -30%.

**Digest format (NOTIFY-01..03)**
- D-05: Each flagged line shows symbol + flag + % + short action hint, e.g. `RELIANCE: STOP HIT (-13% vs avg) → review exit`.
- D-06: Header line included in Phase 1: total value + overall unrealized P&L% (both computable now from holdings + LTP). Day P&L / N-day trend / weekly are Phase 2.
- D-07: Group flagged lines into 🔴 ACTION (STOP HIT, TRIM, TRAIL WATCH) → 🟢 OPPORTUNITY (AVG CANDIDATE, BOOK 50%) → ⚠️ UNTAGGED at the bottom.
- D-08: Only non-HOLD stocks are listed; when nothing fires, send a single "all quiet" line (proof the run happened).

**Run interface & config (DATA-04, RULES-04)**
- D-09: Default invocation sends to Telegram; a `--dry-run` flag prints the formatted digest to stdout instead.
- D-10: `config.yaml` is a flat `symbol → core|tactical` map. Thresholds stay global constants in `rules.py` — no per-symbol threshold overrides in v1.
- D-11: A symbol tagged anything other than `core`/`tactical` (typo) or missing from config → UNTAGGED flag. Never guess a bucket; never hard-fail the whole run over one bad tag.
- D-12: Secrets validation (DATA-04) still hard-fails at startup naming the missing secret — distinct from D-11's bad-tag tolerance. Groww access token never written to disk (DATA-05).

### Claude's Discretion
- Exact wording of the "all quiet" line and the AVG 3-gate reminder text.
- Telegram message formatting details (Markdown vs HTML parse mode, emoji specifics) — pick what renders cleanly.
- Module/function naming within the locked 4-file split (`broker.py`, `rules.py`, `notify.py`, `sentinel.py`).
- Value-header number formatting (₹ lakhs vs plain).

### Deferred Ideas (OUT OF SCOPE)
- Per-symbol threshold overrides in `config.yaml` — deferred; global constants suffice for v1.
- Day P&L / N-day trend / weekly summary header content — Phase 2 (PNL-*).
- Peak reset-on-exit / re-seed-on-rebuy, dated snapshots — Phase 2 (STATE-01..04). Phase 1 only does first-run peak seed (STATE-05) in-memory; durable state is Phase 2.
- Corporate-action stale-avg_price warning — Phase 2 (RULES-06); verify growwapi adjustment behavior then.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DATA-01 | Headless auth: API key + runtime TOTP (pyotp) | Exact `GrowwAPI.get_access_token(api_key=, totp=)` signature verified below |
| DATA-02 | Fetch holdings (symbol, qty, avg cost) via growwapi | `get_holdings_for_user()` field list verified below |
| DATA-03 | Batched LTP for all held symbols (≤50) | `get_ltp(segment=, exchange_trading_symbols=)` signature + batching verified below |
| DATA-04 | Validate all 4 secrets at startup, fail loud naming missing one | Secrets Validation pattern below (from project ARCHITECTURE.md, reused) |
| DATA-05 | Never persist Groww access token | Confirmed: token has no expiry precisely because it's never cached — regenerate every run |
| RULES-01 | Pure `evaluate(holdings, config, state, today) -> (flags, new_state)` | Signature + fixture shapes below |
| RULES-02 | Every stock resolves to exactly one flag | Flag-precedence analysis below (structural + assumed ordering) |
| RULES-03 | Named threshold constants | Constants table below, values from D-01 |
| RULES-04 | config.yaml core/tactical tagging, UNTAGGED fallback | UNTAGGED precedence rule below |
| RULES-05 | AVG CANDIDATE + 3-gate reminder coupled | Message-shape note below |
| STATE-05 | First-run peak seed | Peak-seeding formula + Phase-1-specific "always first-run" implication below |
| NOTIFY-01 | Send digest via Telegram Bot API | `sendMessage` call + parse_mode recommendation below |
| NOTIFY-02 | Non-HOLD only, grouped action/opportunity | Grouping logic maps directly to D-07 |
| NOTIFY-03 | "All quiet" heartbeat | Message-shape note below |
| TEST-01 | rules.py boundary unit tests, AAA | Boundary test matrix below |
| TEST-02 | Mocked I/O tests for broker.py/notify.py | Mocking recipes below |
</phase_requirements>

## Summary

Phase 1 is a thin, verified vertical slice: authenticate to Groww via TOTP, pull holdings + one batched LTP call, run them through a pure `rules.py`, and push one Telegram message. All three external integration points (`growwapi` auth/holdings/LTP, Telegram `sendMessage`) were cross-checked against Groww's official docs and confirmed to match the project-level `STACK.md`/`ARCHITECTURE.md` research already on file — no corrections needed there, only precision added for exact call signatures and edge-case behavior an executor needs.

The one thing worth calling out before planning starts: **in Phase 1, `state` is always `{}`** (no durable `state.json` yet — that's Phase 2's STATE-01..04). This means every run is a "first run" for peak-seeding purposes (STATE-05), and it has a direct consequence for TRAIL WATCH / STOP HIT's "below-peak" clause: since peak is re-seeded fresh every single run as `max(ltp, avg_cost)`, the trailing-stop math will rarely produce a meaningful non-zero `pct_below_peak` in Phase 1 testing — that's expected, not a bug, and should be called out explicitly in test fixtures so nobody chases a phantom issue.

The second thing worth flagging: RULES-02 requires exactly one flag per stock, but the flags aren't naturally mutually exclusive (e.g., a stock can simultaneously qualify for STOP HIT and TRIM). D-04's weight-gate coupling structurally rules out AVG-vs-TRIM collisions, but STOP HIT/TRAIL WATCH/BOOK 50% can each still co-occur with TRIM. CONTEXT.md doesn't lock a precedence order — this research proposes one (below, Assumptions Log #A1) that the planner should carry into task definitions and TEST-01's boundary matrix should explicitly test.

**Primary recommendation:** Build `rules.py` first and fully boundary-test it (per Suggested Build Order in project ARCHITECTURE.md) using the exact fixture shapes and threshold table below; then `broker.py` against the verified growwapi signatures; then `notify.py` + `sentinel.py` wiring with plain-text Telegram messages (no parse_mode) to sidestep the entire Markdown/HTML escaping failure class.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Groww auth (TOTP) | Broker / I/O boundary (`broker.py`) | — | Talks to an external API; must never leak into pure logic |
| Holdings + LTP fetch | Broker / I/O boundary (`broker.py`) | — | Same — network I/O, returns plain dicts only |
| Flag evaluation (thresholds, tiers, weight) | Pure core (`rules.py`) | — | Money-path decision logic; must be side-effect-free and unit-testable without mocks |
| Peak seeding (STATE-05) | Pure core (`rules.py`) | Orchestrator (`sentinel.py` supplies `state={}`) | Computation is pure; the "always empty state" fact is a Phase-1 orchestration decision, not a rules decision |
| Digest formatting | Pure core (`notify.py::format_digest`) | — | Deliberately split from `send()` so message text is snapshot-testable without HTTP mocking |
| Telegram send | I/O boundary (`notify.py::send`) | — | Thin wrapper, one HTTP call, no retry/backoff needed at 1 msg/run |
| Secrets validation | Orchestrator (`sentinel.py`) | — | Must run before any network call touches any module |
| `--dry-run` short-circuit | Orchestrator (`sentinel.py`) | — | Decides whether to call `notify.send()` or `print()`; not `notify.py`'s concern |
| Config loading (`config.yaml`) | Orchestrator (`sentinel.py`) | Pure core consumes result | Loading is I/O; the resulting dict is handed to `rules.py` as plain data |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|---------------|
| `growwapi` | 1.5.0 `[VERIFIED: PyPI + groww.in official docs]` | Official Groww TradeAPI SDK | Sole sanctioned access path per project constraints (no scraping) |
| `pyotp` | 2.10.0 `[VERIFIED: PyPI]` | Runtime TOTP generation from stored seed | Purpose-built RFC 6238 implementation; exactly what Groww's own docs show for headless auth |
| `requests` | 2.32.3 `[VERIFIED: pip show — already installed locally]` | Telegram `sendMessage` HTTP call | Already a transitive dep of `growwapi`; no bot framework needed for one fire-and-forget message |
| `PyYAML` | 6.0.3 latest / 6.0.2 acceptable `[VERIFIED: PyPI]` | Parse `config.yaml` | De facto standard; stdlib has no YAML support |
| `pytest` | 8.4.2 pinned (9.1.1 is current latest on PyPI as of this research — no known compat blocker, but 8.4.2 matches the already-committed project-level STACK.md pin) `[VERIFIED: PyPI]` | Unit tests for `rules.py`; mocked-I/O tests for `broker.py`/`notify.py` | Project requirement; ecosystem standard |

### Supporting

None beyond the core set for Phase 1 — `pandas_market_calendars` (holiday calendar) and `stefanzweifel/git-auto-commit-action` (state commit-back) are Phase 3 concerns; do not install/wire them this phase.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Raw `requests.post` for Telegram | `python-telegram-bot` / `aiogram` | Only justified if this becomes an interactive multi-chat bot — not this project's shape. Adds an async event loop for a once-a-day fire-and-forget message. |
| Plain-text Telegram message | `HTML` parse_mode with `<b>` bold flags | Only if bold emphasis is explicitly wanted later; introduces an escaping failure class (Pitfall 10) for zero requirement-driven benefit this phase |
| Hand-pinned `requirements.txt` | `pip-tools` / `poetry` | Overkill for 5 packages |

**Installation:**
```bash
pip install growwapi==1.5.0 pyotp==2.10.0 requests==2.32.3 PyYAML==6.0.3 pytest==8.4.2
```

**Version verification:** confirmed live against PyPI this session via `pip index versions <pkg>` (correct ecosystem — Python/PyPI, not npm) for `growwapi`, `pyotp`, `PyYAML`, `pytest`; `requests` confirmed via local `pip show` (already installed at 2.32.3, matching pin).

## Package Legitimacy Audit

> Automated `gsd-tools query package-legitimacy check` seam was unavailable in this environment (command not registered in the installed gsd-sdk build). Fell back to manual verification: `pip index versions` against the correct ecosystem registry (PyPI) for every package, plus a PyPI project-page fetch for the one package with no multi-year track record (`growwapi`).

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| `growwapi` | PyPI | First release 2025-04-11, latest 1.5.0 on 2025-12-06 (~9 months old at research date) | Not independently checked (no PyPIStats query run) | None published on PyPI page; docs at `groww.in/trade-api/docs/python-sdk` | OK | Approved — official vendor SDK, maintainer `growwapi@groww.in`, MIT license, is the *only* officially sanctioned access path per project constraints (no viable alternative exists or should be sought) |
| `pyotp` | PyPI | Long-established (multi-year, RFC 6238 reference impl) | High, ubiquitous | github.com/pyauth/pyotp | OK | Approved |
| `PyYAML` | PyPI | Long-established (since 2006) | Very high, ubiquitous | github.com/yaml/pyyaml | OK | Approved |
| `pytest` | PyPI | Long-established | Very high, ubiquitous | github.com/pytest-dev/pytest | OK | Approved |
| `requests` | PyPI | Long-established | Very high, ubiquitous | github.com/psf/requests | OK | Approved — already installed locally, matches pinned version |

**Packages removed due to [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** none. `growwapi`'s relative youth (~9 months) would normally warrant a `[SUS]` flag under a generic "new package" heuristic, but it is downgraded to `OK` here because (a) it is published directly by Groww (`growwapi@groww.in`, matching the vendor's own domain), (b) it is explicitly and exclusively the project's chosen integration path per `PROJECT.md`'s constraints, and (c) there is no alternative package to substitute — flagging it `SUS` would only produce a checkpoint with no actionable alternative. The planner should still not skip verifying the installed package's `setup.py`/`pyproject.toml` has no unexpected `postinstall`-equivalent behavior (Python packages don't have npm-style postinstall scripts, but do check for unusual `setup.py` code execution) — low risk for a vendor-published SDK, near-zero effort to confirm.

## Architecture Patterns

### System Architecture Diagram

```
Manual invocation: `python sentinel.py` (or `python sentinel.py --dry-run`)
        │
        ▼
sentinel.py: validate_secrets(env) → missing? → print to stderr, exit 2
        │ all present
        ▼
sentinel.py: load config.yaml (symbol→bucket map, read-only)
        │
        ▼
broker.py: pyotp.TOTP(seed).now() → GrowwAPI.get_access_token(api_key, totp) → GrowwAPI(token)
        │                                                     │ auth failure → raise GrowwAPIException
        ▼                                                     ▼
broker.py: get_holdings_for_user() → list[dict]        sentinel.py catches → notify "fetch failed: <reason>" → exit 1
        │ empty? → notify "no holdings", exit 0
        ▼
broker.py: build ("NSE_"+trading_symbol) list → get_ltp(segment=SEGMENT_CASH, exchange_trading_symbols=tuple) → {symbol: price}
        │ per-symbol missing price → carry ltp=None for that symbol (not fatal)
        ▼
sentinel.py: merge holdings + ltp → list[dict] {symbol, qty, avg_cost, ltp}
        │
        ▼
rules.py: evaluate(holdings, config, state={}, today) → (flags: list[dict], new_state: dict)
        │  (pure — no network, no clock, no file I/O inside)
        ▼
notify.py: format_digest(flags, portfolio_summary) → str   [pure, testable without HTTP]
        │
        ▼
   --dry-run?  ──yes──▶ print(message) to stdout, exit 0
        │no
        ▼
notify.py: send(token, chat_id, message) → requests.post(...) → raise_for_status()
        │ send failure → sentinel.py catches → log to stderr, exit 1
        ▼
   exit 0
```

### Recommended Project Structure

```
groww-sentinel/
├── sentinel.py          # orchestrator + top-level error handling + --dry-run flag
├── broker.py            # Groww auth (TOTP) + get_holdings + get_ltp — I/O, thin, no persistence
├── rules.py             # pure evaluate() + named threshold constants
├── notify.py            # format_digest() [pure] + send() [I/O]
├── config.yaml          # user-owned: symbol -> core/tactical tags
├── requirements.txt     # pinned: growwapi==1.5.0, pyotp==2.10.0, requests==2.32.3, PyYAML==6.0.3, pytest==8.4.2
├── tests/
│   ├── test_rules.py    # AAA, boundary matrix per threshold constant — the money path
│   ├── test_broker.py   # mocked growwapi SDK, no live calls
│   └── test_notify.py   # format_digest snapshot tests (pure) + mocked requests.post tests
└── .gitignore            # excludes any local .env / secrets file
```

Flat, no `src/` package — 4 files of substance, matches project ARCHITECTURE.md. `state.json` and `.github/workflows/` are explicitly out of scope this phase (no durable state, no cron — manual `python sentinel.py` invocation only).

### Pattern 1: TOTP-based headless auth (no token persistence)

**What:** Regenerate a fresh TOTP code and a fresh access token on every single invocation. Never write the token anywhere.
**When to use:** Always, for this project — this is DATA-05 and also the only auth path compatible with an unattended/manual headless run (the alternative API-key+secret flow requires daily manual dashboard re-approval, per project STACK.md).
**Example:**
```python
# broker.py
# Source: groww.in/trade-api/docs/python-sdk (verified via WebSearch cross-check, 2026-07-09)
from growwapi import GrowwAPI
import pyotp

def get_client(api_key: str, totp_seed: str) -> GrowwAPI:
    """api_key here is the TOTP-flow key ('TOTP token' on Groww's dashboard),
    NOT the separate key+secret non-headless flow's API key — same param name,
    different credential, generated together when TOTP auth is selected."""
    totp_code = pyotp.TOTP(totp_seed).now()
    access_token = GrowwAPI.get_access_token(api_key=api_key, totp=totp_code)
    return GrowwAPI(access_token)   # never persist access_token
```

**Note on secret naming:** Groww's dashboard, when you select TOTP-based auth, issues two values: a "TOTP token" (passed as the `api_key` parameter above) and a "TOTP Secret" (the seed passed to `pyotp.TOTP(...)`). This maps directly onto the project's existing `GROWW_API_KEY` (= TOTP token) and `GROWW_TOTP_SEED` (= TOTP secret) env var names — no renaming needed, but the executor should know these are the TOTP-flow-specific credential pair, not the separate non-headless API key+secret pair, which uses different values from the same dashboard.

### Pattern 2: Holdings fetch — exact shape

**Example:**
```python
# Source: groww.in/trade-api/docs/python-sdk/portfolio (verified 2026-07-09)
holdings_response = groww.get_holdings_for_user(timeout=5)
# Each holding dict includes at minimum:
#   trading_symbol, quantity, average_price, isin,
#   pledge_quantity, demat_locked_quantity, groww_locked_quantity,
#   repledge_quantity, t1_quantity, demat_free_quantity,
#   corporate_action_additional_quantity, active_demat_transfer_quantity
# broker.py should extract and return ONLY: {trading_symbol, quantity, average_price}
# per component boundary rule (broker.py returns plain, minimal dicts — no SDK objects).
```
No LTP field present — confirms LTP must be fetched separately (Pattern 3).

### Pattern 3: Batched LTP fetch — exact shape

**Example:**
```python
# Source: groww.in/trade-api/docs/python-sdk/live-data (verified 2026-07-09)
symbols = tuple(f"NSE_{h['trading_symbol']}" for h in holdings)   # up to 50 per call
ltp_response = groww.get_ltp(
    segment=groww.SEGMENT_CASH,
    exchange_trading_symbols=symbols,
)
# -> {"NSE_RELIANCE": 2500.5, "NSE_TCS": 3450.0, ...}
# Map back to a holding: ltp_response.get(f"NSE_{holding['trading_symbol']}")
```
- A personal portfolio (well under 50 holdings) needs exactly **one** `get_ltp` call per run — confirmed no per-symbol looping is required, which sidesteps PITFALLS.md Pitfall 6 (per-symbol rate-limit exposure) almost entirely for this phase.
- Live Data rate limit: 10/sec, 300/min `[CITED: groww.in/trade-api/docs/python-sdk/exceptions]` — at 1 call/run this is a non-issue; no throttle/backoff logic needed, just a defensive `except GrowwAPIException` around the call.
- If a symbol's key is absent from the response dict (shouldn't normally happen with a valid batch call, but treat defensively), `broker.py` should return `ltp=None` for that symbol rather than raising — `rules.py` then represents "unknown LTP" explicitly (see Anti-Patterns).

### Pattern 4: Pure rules engine signature and fixture shape

**Example:**
```python
# rules.py
from datetime import date

def evaluate(
    holdings: list[dict],   # [{"symbol": "RELIANCE", "qty": 10, "avg_cost": 2500.0, "ltp": 2801.25}, ...]
    config: dict,           # {"RELIANCE": "core", "ZOMATO": "bogus-typo"}  — missing/bad key -> UNTAGGED
    state: dict,            # {} always, in Phase 1 (no durable state.json yet)
    today: date,            # caller-supplied, IST calendar date — never date.today() inside this module
) -> tuple[list[dict], dict]:
    ...
    return flags, new_state
```
- `holdings` entries MUST already have `ltp` merged in by `sentinel.py` — `rules.py` never reaches into a separate LTP dict itself (keeps the pure function's input fully self-contained and trivially fixture-able).
- `ltp=None` for a symbol (LTP fetch failed for just that one) is a valid, representable input — `rules.py` must emit an explicit "LTP unavailable" note for that symbol rather than silently treating it as HOLD (PITFALLS.md Pitfall 6).

### Pattern 5: Telegram send — plain text, no parse_mode

**Example:**
```python
# notify.py
# Source: core.telegram.org/bots/api#sendmessage (well-established, stable public API)
import requests

TELEGRAM_MAX_LEN = 4096

def send(token: str, chat_id: str, text: str) -> None:
    if len(text) > TELEGRAM_MAX_LEN:
        text = text[:TELEGRAM_MAX_LEN - 20].rsplit("\n", 1)[0] + "\n…truncated, see logs"
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text},   # no parse_mode key at all
        timeout=10,
    )
    resp.raise_for_status()   # non-2xx raises — caller (sentinel.py) treats as send failure
```
- **No `parse_mode`** (defaults to Telegram's plain-text rendering): the design spec's message shape (`docs/superpowers/specs/2026-07-09-groww-sentinel-design.md`) uses only emoji + plain bullet lines, no bold/italic — plain text renders every raw emoji correctly with zero escaping risk. This sidesteps the entire `MarkdownV2`/`HTML` escaping failure class (PITFALLS.md Pitfall 10) for a feature the message shape doesn't actually need. If bold emphasis is wanted later, revisit with `HTML` (fewer escape-required characters than `MarkdownV2`) and a centralized escaping helper — not needed this phase.
- **4096-char limit `[CITED: Telegram Bot API docs]`:** at realistic personal-portfolio scale (non-HOLD-only lines, D-08) this won't be hit, but the truncate-and-note fallback above is the minimal defensible handling — do not build multi-message pagination (YAGNI; revisit only if truncation is observed in practice).
- **Check the actual response**, not just "didn't throw" (PITFALLS.md Pitfall 9): `raise_for_status()` covers non-2xx; `sentinel.py` must treat a raised exception from `notify.send()` as a hard failure (log to stderr, exit non-zero) — a silently-swallowed Telegram failure is the single highest-leverage pitfall named in project research.

### Anti-Patterns to Avoid

- **Rules engine reading the clock or environment directly:** `date.today()` or `os.environ` inside `rules.py` kills unit-testability and hides timezone bugs. `sentinel.py` computes `today` once (IST) and passes it in.
- **Treating a per-symbol LTP fetch failure as silent HOLD:** must surface as an explicit "LTP unavailable" note in the digest, never an unflagged omission.
- **Caching the Groww access token "to save an API call":** guaranteed to break once the token's (undocumented but real) expiry window passes, indistinguishable from a broker outage. Regenerate every run — this is DATA-05, non-negotiable.
- **Passing the raw growwapi/Telegram exception string verbatim into the digest or logs:** library exception reprs can include request headers/payload containing the API key or token. Validate secret *presence* only; never echo secret *values*; redact known secret substrings from any string headed to Telegram or stderr.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| TOTP code generation | A manual RFC 6238 HMAC-SHA1 implementation | `pyotp.TOTP(seed).now()` | Purpose-built, correct, zero-dependency; hand-rolling a time-based OTP is a security-adjacent problem with subtle off-by-one/clock-skew bugs |
| YAML parsing | A hand-written `symbol: bucket` line parser | `PyYAML` (`yaml.safe_load`) | Config files quote, comment, and nest in ways a hand parser will mishandle eventually |
| Telegram markdown escaping | A custom escaper function for `MarkdownV2`/`HTML` special characters | Plain text (no `parse_mode`) | The message shape doesn't need bold/italic; avoiding the format entirely removes the whole escaping-bug class rather than requiring a hand-tested escaper |
| Retry/backoff for Groww calls | A custom exponential-backoff wrapper | Nothing — at ≤2 calls/run against a 300/min quota, retry logic is defensive theatre; catch `GrowwAPIException` once and let `sentinel.py` decide (notify + exit) | The volume genuinely doesn't warrant it this phase; revisit only if Phase 3's cron surfaces real rate-limit hits |

**Key insight:** every "don't hand-roll" item above is also a place where a from-scratch implementation would look correct in a demo (TOTP happens to generate *a* code; a line parser happens to parse this week's `config.yaml`) and only fail once, unpredictably, later — exactly the failure shape this project's own error-handling philosophy ("never silently skip a day") exists to prevent.

## Runtime State Inventory

Not applicable — this is a greenfield phase (no existing code, no rename/refactor/migration). Skipped per template guidance.

## Common Pitfalls

### Pitfall 1: TRAIL WATCH / STOP HIT's "below-peak" clause is structurally inert in Phase 1

**What goes wrong:** Because `state` is always `{}` this phase (no durable `state.json` until Phase 2), every run re-seeds every symbol's peak fresh. If peak seeding is `max(ltp, avg_cost)`, then on any given run `pct_below_peak` will be at most the gap between `ltp` and `avg_cost` — it can never reflect a genuine multi-day drawdown from a real historical high, because there is no history. A developer testing TRAIL WATCH (`>20% below peak`) manually against real live data may see it never fire and incorrectly conclude the logic is broken.
**Why it happens:** STATE-05 (first-run peak seed) is correctly scoped to Phase 1, but its interaction with "state is always empty this phase" (a Phase 1 boundary decision, not a rules bug) is easy to miss when reading the rules table in isolation.
**How to avoid:** Document this explicitly in `rules.py`'s docstring and in the Phase 1 test fixtures (a test with `state={}` and a peak-seeded scenario should assert `pct_below_peak` behaves as "always same-run seeded", not attempt to simulate multi-day drawdown — that belongs in Phase 2's `test_state.py`). STOP HIT's *other* clause (`down > 12% from avg cost`) is unaffected and will fire normally.
**Warning signs:** TRAIL WATCH never appears in manual `--dry-run` testing even for a stock the user knows is well below its real historical peak.

### Pitfall 2: Exactly-one-flag requirement collides with non-exclusive flag conditions

**What goes wrong:** RULES-02 requires every stock to resolve to exactly one flag, but TRIM (weight-based) is not mutually exclusive with STOP HIT, TRAIL WATCH, or BOOK 50% (all price-based). D-04's weight-gate coupling structurally prevents an AVG/TRIM collision (see Summary), but TRIM can still co-occur with the other three. Without an explicit precedence rule, two developers implementing `rules.py` independently could pick a different flag for the same input, and no test would catch the ambiguity because CONTEXT.md doesn't specify one.
**Why it happens:** The design spec's rules table lists conditions per-flag, not a decision tree — it's easy to translate a table into an unordered set of `if` checks without noticing two can both be true.
**How to avoid:** Implement flag resolution as an explicit ordered chain (see Assumptions Log #A1 for the proposed order), not independent `if` branches that could each "win" nondeterministically depending on dict-insertion order or similar incidental behavior. Add a boundary test that constructs a stock qualifying for two flags simultaneously and asserts the expected single output.
**Warning signs:** Flake y test results where the same fixture produces a different flag on different runs; two code reviewers disagreeing on "which flag should show" for a hand-traced example.

### Pitfall 3: Mocking `growwapi` at the wrong layer gives false test confidence

**What goes wrong:** Patching the entire `GrowwAPI` class with an unconfigured `Mock()` means `holdings_response.<anything>` silently returns another `Mock()` instead of raising `AttributeError` — tests pass while the real SDK's actual dict-shaped response would break the same code.
**How to avoid:** Mock at the boundary `broker.py` actually calls, and configure the mock's return value to a realistic fixture dict shaped exactly like the verified response above (`trading_symbol`, `quantity`, `average_price`, etc.), not an ad-hoc shorthand dict. See the pytest recipe below.
**Warning signs:** A test suite with high "assertion count" that never had to change when a real field name was verified/corrected.

## Code Examples

### pytest: mocking `broker.py`'s growwapi boundary (TEST-02)

```python
# tests/test_broker.py
from unittest.mock import patch, MagicMock
import broker

FAKE_HOLDINGS = [
    {"trading_symbol": "RELIANCE", "quantity": 10, "average_price": 2500.0,
     "isin": "INE002A01018", "pledge_quantity": 0, "demat_locked_quantity": 0,
     "groww_locked_quantity": 0, "repledge_quantity": 0, "t1_quantity": 0,
     "demat_free_quantity": 10, "corporate_action_additional_quantity": 0,
     "active_demat_transfer_quantity": 0},
]

@patch("broker.GrowwAPI")
def test_get_holdings_returns_plain_dicts(mock_groww_cls):
    mock_instance = MagicMock()
    mock_instance.get_holdings_for_user.return_value = FAKE_HOLDINGS
    mock_groww_cls.return_value = mock_instance
    mock_groww_cls.get_access_token.return_value = "fake-token"

    client = broker.get_client(api_key="k", totp_seed="JBSWY3DPEHPK3PXP")
    holdings = broker.get_holdings(client)

    assert holdings == [{"trading_symbol": "RELIANCE", "quantity": 10, "average_price": 2500.0}]
    mock_groww_cls.get_access_token.assert_called_once()   # token generated, never cached/read from disk


@patch("broker.GrowwAPI")
def test_get_ltp_batches_all_symbols_in_one_call(mock_groww_cls):
    mock_instance = MagicMock()
    mock_instance.get_ltp.return_value = {"NSE_RELIANCE": 2801.25}
    mock_instance.SEGMENT_CASH = "CASH"
    mock_groww_cls.return_value = mock_instance

    result = broker.get_ltp(mock_instance, ["RELIANCE"])

    mock_instance.get_ltp.assert_called_once_with(
        segment="CASH", exchange_trading_symbols=("NSE_RELIANCE",)
    )
    assert result == {"RELIANCE": 2801.25}
```
*(`JBSWY3DPEHPK3PXP` above is `pyotp`'s own published example seed used in its README/tests — safe to use in test fixtures, not a real credential.)*

### pytest: mocking `notify.py`'s Telegram boundary (TEST-02)

```python
# tests/test_notify.py
from unittest.mock import patch, Mock
import notify

@patch("notify.requests.post")
def test_send_success_posts_expected_payload(mock_post):
    mock_post.return_value = Mock(status_code=200, raise_for_status=Mock())

    notify.send(token="T", chat_id="C", text="all quiet")

    mock_post.assert_called_once_with(
        "https://api.telegram.org/botT/sendMessage",
        json={"chat_id": "C", "text": "all quiet"},
        timeout=10,
    )

@patch("notify.requests.post")
def test_send_failure_propagates(mock_post):
    mock_post.return_value = Mock(status_code=401)
    mock_post.return_value.raise_for_status.side_effect = Exception("401 Unauthorized")

    import pytest
    with pytest.raises(Exception):
        notify.send(token="bad", chat_id="C", text="msg")
```

### pytest: rules.py fixtures (TEST-01, no mocks needed — pure function)

```python
# tests/test_rules.py
from datetime import date
import rules

def holding(symbol="TCS", qty=10, avg_cost=1000.0, ltp=1000.0):
    return {"symbol": symbol, "qty": qty, "avg_cost": avg_cost, "ltp": ltp}

def test_stop_hit_fires_exactly_above_boundary():
    # Arrange: tactical stock down exactly 12.01% from avg cost
    h = holding(avg_cost=1000.0, ltp=879.9)   # -12.01%
    config = {"TCS": "tactical"}
    # Act
    flags, _ = rules.evaluate([h], config, state={}, today=date(2026, 7, 9))
    # Assert
    assert flags[0]["flag"] == "STOP HIT"

def test_stop_hit_does_not_fire_at_exactly_boundary():
    # Arrange: exactly -12.00% — boundary is exclusive per spec's ">" wording
    h = holding(avg_cost=1000.0, ltp=880.0)   # exactly -12%
    config = {"TCS": "tactical"}
    flags, _ = rules.evaluate([h], config, state={}, today=date(2026, 7, 9))
    assert flags[0]["flag"] != "STOP HIT"
```

## State of the Art

Not applicable — no prior version of this system exists to compare against (greenfield project). The one "old approach" worth naming: the design spec's original open item ("confirm exact growwapi live-data method name") is now closed — it's `get_ltp()`, not `get_live_price()`, confirmed against current official docs this session.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Flag precedence when a stock qualifies for more than one flag: UNTAGGED (hard override, skips all bucket-specific rules) > STOP HIT > TRIM > BOOK 50% > TRAIL WATCH > AVG CANDIDATE (deepest applicable tier) > HOLD. AVG-vs-TRIM never actually collide (D-04's weight gate structurally prevents it). | Architecture Patterns / Pitfall 2 | If the user's mental model differs (e.g., they'd expect TRIM to always win over a price-action flag since concentration risk is more urgent), the digest surfaces a different — but still singular and defensible — flag than expected. Low financial risk (advisory only, human reviews before acting) but should be confirmed in discuss-phase or plan-review before locking into `rules.py`. |
| A2 | Threshold boundary operators are strict `>` for TRIM (>10%), BOOK 50% (>25%), STOP HIT (>12% / >15% below peak), TRAIL WATCH (>20% below peak) — matching the spec table's literal wording — and AVG CANDIDATE's tiers use the same strict-`>` convention (down >10/>20/>30%) for consistency, even though the spec table's AVG row omits the ">" character that the other four rows include. | Standard Stack / Code Examples (boundary tests) | If AVG's thresholds were actually meant to be inclusive (`>=`) or the whole table meant `>=` throughout, the boundary tests in TEST-01 would need their expected values flipped at the exact threshold value. Low risk (a single-cent misclassification at an exact round-number price is rare in practice) but worth a one-line confirmation before writing the full boundary matrix. |
| A3 | Peak seeding formula for STATE-05 is `peak = max(ltp, average_price)` on first-seen (per project PITFALLS.md's own recommendation), not blind `ltp`-only seeding. | Common Pitfalls / Pattern 4 | If a plain `ltp`-only seed is used instead, a stock that's already run up significantly from cost on its very first `state.json`-less run (i.e., every run in Phase 1) would show `pct_below_peak = 0%` regardless — functionally near-identical outcome in Phase 1 specifically (since state is always empty either way, see Pitfall 1), so the risk is contained to Phase 2 once persistence exists. |
| A4 | `pyotp`'s published example seed `JBSWY3DPEHPK3PXP` is safe to embed directly in test fixtures (it is a widely-published, non-secret example value from `pyotp`'s own documentation, not a real credential). | Code Examples | Negligible — this is a publicly documented library example, not project-specific secret material. |

**If this table is empty:** N/A — see rows above for the two genuine open decisions (A1, A2) the planner should either lock via a quick discuss-phase follow-up or explicitly accept as this research's best-effort default before `rules.py` is written.

## Open Questions

1. **Flag precedence order (A1) and AVG boundary operator (A2)**
   - What we know: CONTEXT.md locks the threshold *values* and the AVG tiering *behavior* (deepest tier wins, weight gate applies to all tiers) but not the operator at each exact boundary, nor precedence when multiple non-AVG flags qualify simultaneously.
   - What's unclear: whether `>` vs `>=` is intended per-flag, and whether TRIM should outrank a price-action flag or vice versa.
   - Recommendation: Proceed with this research's proposed defaults (A1, A2) for the first `rules.py` implementation; surface both as a single confirmation question in plan-review or the next discuss-phase touchpoint rather than blocking Phase 1 kickoff on it — both are cheap to adjust (named constants, one ordering function) if the user's intent differs.

2. **`average_price` corporate-action adjustment status**
   - What we know: Groww's docs don't state whether `average_price` is retroactively adjusted for splits/bonuses (per project STACK.md/PITFALLS.md, already flagged and explicitly deferred to Phase 2 as RULES-06).
   - What's unclear: whether any of the user's *current* Phase 1 test holdings have had a real corporate action, which would make this an immediate (not just future) concern.
   - Recommendation: Confirmed out of scope per CONTEXT.md's Deferred Ideas — no action needed this phase beyond being aware a wrong flag on an affected symbol during manual dry-runs isn't a `rules.py` bug.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.x | Runtime | ✓ | 3.13.0 (local) — SDK supports 3.9–3.13 | — |
| pip | Package install | ✓ | 24.2 (local) | — |
| `growwapi` | DATA-01/02/03 | ✗ (not yet installed) | target 1.5.0 | Install via `requirements.txt` — no fallback exists (sole sanctioned SDK) |
| `pyotp` | DATA-01 | ✗ (not yet installed) | target 2.10.0 | Install via `requirements.txt` — no viable alternative |
| `requests` | NOTIFY-01 | ✓ | 2.32.3 (local) | — |
| `PyYAML` | RULES-04 | ✓ | 6.0.2 (local; target 6.0.3) | — |
| `pytest` | TEST-01/02 | ✗ (not yet installed) | target 8.4.2 | — |
| Groww API key + TOTP seed (user secret) | DATA-01 | Not verifiable from this environment | — | Hard-fails at startup per DATA-04/D-12 if missing — expected behavior, not a gap to fix |
| Telegram bot token + chat ID (user secret) | NOTIFY-01 | Not verifiable from this environment | — | Same as above |

**Missing dependencies with no fallback:** `growwapi`, `pyotp` are not yet installed in this environment but have a trivial fallback (install from `requirements.txt` before running/testing) — not a blocker, just an implementation-time setup step for whichever plan implements `broker.py`.

**Missing dependencies with fallback:** none beyond the install step above.

## Security Domain

> `security_enforcement` is absent from `.planning/config.json` (treated as enabled per template default). This is a single-user CLI script with no web-facing surface — most ASVS web categories are structurally not applicable; the relevant categories are input validation and secret/credential handling.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | Partially — outbound auth *to* Groww only, no auth *of* Sentinel's own users (none exist) | TOTP via `pyotp` (never hand-roll RFC 6238); credential is the stored seed, treated as a secret |
| V3 Session Management | No — single-shot script, no session concept | N/A; DATA-05 (never persist access token) is the closest analog and is already locked |
| V4 Access Control | No — single user, no roles | N/A |
| V5 Input Validation | Yes | `config.yaml` values validated against the `{core, tactical}` enum (D-11: anything else → UNTAGGED, never guessed); growwapi/Telegram responses treated as untrusted external data — defensive `.get()` with `None` handling before any arithmetic, never assume a key is present |
| V6 Cryptography | Yes, narrowly | TOTP generation exclusively via `pyotp` (never hand-rolled HMAC/SHA1); no other cryptographic operations exist in this phase |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|----------------------|
| Secret leakage via exception message echoed to Telegram/logs | Information Disclosure | Validate secret *presence* only (`if not env.get(...)`), never echo *value*; redact any string headed to Telegram/stderr that contains a known secret substring before sending (Common Pitfalls / PITFALLS.md Pitfall 12) |
| Config injection via malformed `config.yaml` | Tampering (low severity — user-owned local file, not attacker-controlled input) | `yaml.safe_load` (never `yaml.load` with default `Loader`, which permits arbitrary Python object construction) — this is a one-line, no-cost mitigation to bake in from the start |
| Untrusted/partial API response crashing the pipeline (e.g., missing LTP key, unexpected None field) | Denial of Service (of this one-shot job — a crash means no digest that day) | Defensive `.get()` access on every external dict field before arithmetic; represent "unknown" explicitly (`ltp=None`) rather than letting a `KeyError`/`TypeError` propagate uncaught |
| Credential exposure via git history | Information Disclosure | `.gitignore` must exclude any local `.env`/secrets file before the first commit that touches secrets — verify before writing any local test-run script that reads real credentials |

## Sources

### Primary (HIGH confidence)
- `groww.in/trade-api/docs/python-sdk` (auth flow, TOTP vs key+secret) — cross-verified via WebSearch this session, matches project STACK.md exactly
- `groww.in/trade-api/docs/python-sdk/portfolio` (`get_holdings_for_user()` field list) — matches project STACK.md exactly
- `groww.in/trade-api/docs/python-sdk/live-data` (`get_ltp()` signature, 50-symbol batch limit, `SEGMENT_CASH` constant) — cross-verified via WebSearch this session, matches project STACK.md exactly
- `groww.in/trade-api/docs/python-sdk/exceptions` (rate limit table, exception hierarchy) — per project STACK.md, not re-fetched this session (no change expected)
- PyPI `pip index versions` output for `growwapi`, `pyotp`, `PyYAML`, `pytest` (live registry check, this session, 2026-07-09)
- Local `pip show requests` (already-installed version confirmation, this session)
- Telegram Bot API `sendMessage` 4096-char limit and parse_mode escaping behavior — long-stable, well-documented public API surface (project PITFALLS.md, unchanged)

### Secondary (MEDIUM confidence)
- This phase's flag-precedence and AVG-boundary-operator recommendations (Assumptions Log A1/A2) — reasoned from CONTEXT.md/spec text, not independently confirmed with the user this session

### Tertiary (LOW confidence)
- None — the one genuinely unresolved external fact (`average_price` corporate-action adjustment) is correctly deferred to Phase 2 per CONTEXT.md and not re-investigated here.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every version pinned and verified live against PyPI this session
- Architecture: HIGH — directly inherits and adds executor precision to already-verified project-level STACK.md/ARCHITECTURE.md, no contradictions found
- Pitfalls: HIGH for the growwapi/Telegram mechanics; MEDIUM for the two rules-engine ambiguities (A1, A2) explicitly flagged rather than silently resolved

**Research date:** 2026-07-09
**Valid until:** 30 days for the Python package pins (stable ecosystem); growwapi-specific signatures should be re-verified if `broker.py` implementation surfaces any discrepancy against the live SDK, since it's the newest and least battle-tested dependency in the stack.
