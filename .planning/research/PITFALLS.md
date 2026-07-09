# Pitfalls Research

**Domain:** Personal brokerage-API advisory bot — scheduled GitHub Actions job, Groww TradeAPI, Telegram alerting, git-committed state
**Researched:** 2026-07-09
**Confidence:** MEDIUM-HIGH (GitHub Actions scheduling/token behavior and Telegram API limits are well-documented HIGH confidence; Groww-specific corporate-action adjustment behavior and exact rate limits are unconfirmed by public docs — flagged LOW and marked as "verify at impl" per the design spec's own open item)

## Critical Pitfalls

### Pitfall 1: Corporate actions silently poison `avg_price` and `peak` math

**What goes wrong:**
A bonus issue, stock split, or (less commonly) a special dividend changes the economically-correct average cost and share count without any trade happening. If `growwapi`'s `average_price` is *not* retroactively adjusted for a split/bonus that happened after your last buy, every rule that compares `ltp` to `average_price` (STOP HIT, BOOK 50%, AVG CANDIDATE) computes a `pnl_pct` that's wrong by roughly the split/bonus ratio — e.g., a 1:1 bonus makes a stock look like it crashed 50% overnight, firing a false STOP HIT. Your own `state.json` peak is *also* now wrong: it was seeded/updated against the pre-split price, so `pct_below_peak` is nonsense too. Neither failure throws an error — the bot just confidently sends a wrong flag.

**Why it happens:**
Corporate actions are metadata events, not trades. Brokerage APIs vary wildly in whether `get_holdings_for_user()` reflects a post-action-adjusted `average_price` or the raw historical cost basis. The design spec already flags this as unconfirmed ("Confirm `average_price` is post-corporate-action adjusted; if not, note the limitation") — that's the right instinct, but "note the limitation" isn't sufficient if it's silently wrong, because a note nobody reads at 8:30am doesn't stop a false STOP HIT from firing.

**How to avoid:**
- Detect the event indirectly rather than trusting the API to self-correct: each run, compare `quantity` for a symbol against the prior day's `quantity` in `state.json`. A jump in quantity with no corresponding cash-flow-implying price drop is the signature of a bonus/split.
- On detected quantity change without a matching `avg_price` proportional change, treat it as a corporate-action event: reset that symbol's `peak` to the current LTP (don't carry a pre-split peak forward) and suppress STOP/BOOK/AVG flags for that symbol for one run, emitting a `⚠️ CORP ACTION?` flag instead so you can eyeball it manually.
- Never assume; verify once against a known real bonus/split in your own holdings (or Groww's sandbox/paper data if available) before trusting the field in production.

**Warning signs:** A STOP HIT or BOOK 50% flag with a `pnl_pct` magnitude that doesn't match what you remember paying; a sudden quantity change in the digest with no buy/sell you made.

**Phase to address:** Rules Engine & State Model (the quantity-delta detection must live in `rules.py` since it needs both current and prior state) — flag as a phase needing deeper research per the design spec's own open item.

---

### Pitfall 2: Peak-price tracking has three distinct, easy-to-conflate bugs

**What goes wrong:**
"Track the peak, alert when price falls far enough below it" sounds like one feature; it's actually three independent failure modes that each look fine in isolation:

1. **Peak never decays.** `peak = max(stored_peak, today_ltp)` is monotonically non-decreasing by design — that's correct for *a stock you still hold*. But if you never reset it, a stock that's been in slow permanent decline for a year sits in perpetual TRAIL WATCH every single day, forever. The flag becomes wallpaper you stop reading, which defeats the entire point of a daily digest (alert fatigue → the one day it matters, you skip it).
2. **Peak seeded wrong on first-seen.** If a symbol enters `state.json` for the first time *not* at its true peak (e.g., you bought after a run-up and it's already down from ATH, or the bot's first run happens to catch a dip day), the seed becomes an artificially low ceiling, and `pct_below_peak` will always understate real drawdown from the stock's actual high.
3. **Peak surviving after a sell, then lying on rebuy.** The design spec correctly calls for "reset peak on exit, re-seed on rebuy" — but this is easy to get subtly wrong: if the reset logic keys off "symbol not in current holdings" but the state write happens *before* checking for holdings closure (e.g., using stale state from two runs ago because of pitfall #4 below), a sold-and-rebought stock can inherit a peak from the previous ownership period, producing a TRAIL WATCH on day one of a fresh position that has no peak history yet.

**Why it happens:** Peak tracking is stateful logic threaded through multiple runs with no single source of truth for "is this the same continuous holding period." Developers write the happy path (accumulate max) and treat exit/re-entry as an edge case to "handle later."

**How to avoid:**
- Model peak state explicitly as `{symbol: {peak, since_date, holding_id}}` rather than a bare float — increment `holding_id` (or just delete-and-recreate the key) every time a symbol transitions from absent → present in holdings. This makes "is this a fresh holding period" a structural fact, not an inferred one.
- On the seeding edge case: seed peak to `max(ltp, average_price)` on first-seen, not just `ltp` — since if you're already up from cost, cost is a better floor-estimate than a possibly-already-dipped LTP; document this as a known approximation (it will still be wrong for anyone who bought exactly at a peak, but it's less wrong than blind `ltp`-only seeding).
- Add an explicit decay/staleness rule to TRAIL WATCH: only fire it for N consecutive trading days max, or require the drawdown to have *widened* since last run, not just "still > 20% below peak" — otherwise it's a permanent flag on any stock that never recovers, not a trailing-stop signal.
- Unit test all three scenarios explicitly with hand-built state fixtures: (a) held 30 days no new peak, (b) first-seen day, (c) sold-then-rebought same symbol.

**Warning signs:** The same symbol shows TRAIL WATCH every single day for weeks; a freshly-rebought stock shows TRAIL WATCH on day 1; `pct_below_peak` looks smaller than you know the real drawdown from its all-time high to be.

**Phase to address:** Rules Engine & State Model.

---

### Pitfall 3: `contents: write` fails under org policy, and the failure mode is "silent state loss," not a crash

**What goes wrong:** GitHub Actions' default `GITHUB_TOKEN` needs `permissions: contents: write` at the workflow or job level to push a commit. Two separate things can block this even after you set that permission: (a) the *organization* can force a more restrictive default and disable repos from ever escalating token permissions ("Workflow permissions" locked to read-only org-wide), and (b) branch protection rules on the default branch (required reviews, required status checks) can reject a direct push from the Actions bot even with a writable token. Either failure means `state.json` never gets committed — but because the digest send usually happens *before* the commit step in a naive script ordering, you still get your Telegram message that day and have zero visual signal that persistence quietly failed. The next run then computes peaks/snapshots against day-old (or original) state, silently degrading every downstream flag.

**Why it happens:** `PROJECT.md` already flags this ("under the ThePubDoc org this may be restricted") — it's a known unknown, correctly identified, but the risk isn't just "the push fails," it's that a failed push is easy to leave unhandled because the workflow step order puts notify before persist, so a `git push` failure doesn't feel urgent to catch.

**How to avoid:**
- Order the job: fetch → compute → **persist attempt** → notify, and make the notify step *include* commit-success/failure status ("⚠️ state.json commit failed — investigate before tomorrow"), not the other way around.
- Set `permissions: contents: write` explicitly at the job level in the workflow YAML (don't rely on repo defaults) and verify by running the workflow once manually (`workflow_dispatch`) before enabling the cron.
- If org policy blocks token escalation, the fallback is a fine-grained PAT (with only `contents: write` on this one repo) stored as a secret and used for the push step specifically — decide this at implementation time rather than discovering it at 8:30am on day one.
- Turn off/allow-list branch protection for the bot's push path (e.g., push directly to `main` with no required review for this automated commit), or push to a dedicated `state` branch instead of `main` to avoid ever touching a protected branch.

**Warning signs:** Workflow run shows green (job "succeeded") but `git log` on `state.json` doesn't show a new commit for today; two consecutive days' Telegram digests both look like day-1 seeding behavior.

**Phase to address:** Scheduling & CI Wiring — verify this concretely (not just "resolve at impl time") before relying on the cron unattended.

---

### Pitfall 4: Concurrent or re-triggered runs corrupt the same-day snapshot

**What goes wrong:** GitHub Actions scheduled workflows are documented as *best-effort* — they can be delayed, and under some conditions a manual re-run, a retry, or a second dispatch (e.g., you manually re-ran the job to debug a Telegram formatting issue) can execute against the same date key in `state.json` while a prior run's commit is still landing. If `state.json` is keyed by date and the write logic does `state[today] = new_snapshot` without checking `state[today]` already exists, a debug re-run silently overwrites the morning's real snapshot with an afternoon LTP snapshot, corrupting the "day P&L" delta for every future day that diffs against it. Two runs racing to `git push` at once also risks a rejected push (non-fast-forward) that a naive script doesn't retry-with-rebase, again landing you back in pitfall #3's silent-loss mode.
Note: while `PROJECT.md` claims "date-keying makes double-runs idempotent," date-keying alone does not give idempotency — it only prevents cross-day collisions. Same-day double-runs (retry, manual dispatch, GHA occasionally firing a schedule twice) still collide on the *same* key unless the write is itself guarded.

**Why it happens:** "Idempotent" is being used loosely to mean "keyed by date" when it actually requires "safe to apply twice with the same result." A same-day re-run with fresher LTPs is a legitimate use case (you want the numbers to update), but a same-day re-run that also re-appends to weekly-movers logic, or that recomputes peaks against an already-updated peak, is not.

**How to avoid:**
- Make the per-day write an explicit merge/upsert, not a blind overwrite: recompute peaks from the max of `(existing_peak_for_today, new_ltp)`, and only append to weekly-summary aggregation once per calendar day (guard with a "did I already summarize this Friday" check keyed off the date, not just "is it Friday").
- On git push, catch the non-fast-forward rejection and retry once with a fresh `git pull --rebase` before giving up and alerting.
- Prefer `concurrency:` group in the GHA workflow (`concurrency: { group: sentinel-run, cancel-in-progress: false }`) so a second trigger queues rather than races the first.

**Warning signs:** Two commits to `state.json` on the same calendar date with different LTP values; Friday's weekly summary appears twice or with doubled "flags-fired count."

**Phase to address:** Scheduling & CI Wiring, in coordination with Rules Engine & State Model (the merge-not-overwrite logic is a state-model contract, the concurrency guard is a workflow contract).

---

### Pitfall 5: Groww auth token/session and TOTP have narrow validity windows that CI can miss

**What goes wrong:** Groww's TOTP-based login flow uses an epoch timestamp valid for a short window (documented as ~10 minutes) and issues an access token with daily expiry. Two separate CI-specific failure modes follow: (a) if the GitHub Actions runner's clock is skewed from Groww's server clock (rare on GHA-hosted runners, but real on self-hosted runners or if `pyotp` computes the code from a mis-parsed seed), TOTP validation fails intermittently and unpredictably; (b) because the token expires daily, any code path that tries to *cache and reuse* a token across runs (e.g., committing a session token into `state.json` "to save an API call") will work for a while and then fail exactly once a day in a way that looks like a broker outage rather than an expected refresh.

**Why it happens:** TOTP and session-token expiry are "worked once, assumed forever" pitfalls — they pass in local testing (same machine, same run) and only surface once fired unattended, daily, from a different environment (GHA runner) over enough days to hit the edge.

**How to avoid:**
- Never persist the access token; regenerate a fresh TOTP and fresh login on every single run — this is already implied by the design ("generate the code at runtime with pyotp"), just make sure no code path accidentally short-circuits it by reading a cached token from `state.json`.
- GHA-hosted runners sync NTP reliably; this is a non-issue there, but explicitly avoid self-hosted runners for this job to keep that guarantee.
- On auth failure, do not treat it as generic "fetch failed" — surface the specific step (TOTP generation vs. login call vs. holdings call) in the Telegram error message so you can tell "seed rotated/invalid" apart from "Groww API is down" apart from "network blip," since the fix for each is completely different (re-issue TOTP seed vs. wait vs. nothing).

**Warning signs:** Auth failures that recur at roughly the same time of day; a token that "used to work" and now doesn't despite no code change.

**Phase to address:** Broker & Auth.

---

### Pitfall 6: Per-symbol LTP fetch hits rate limits or partial failures that get silently absorbed

**What goes wrong:** `get_holdings_for_user()` gives no LTP; the design already requires an LTP call per held symbol per run. Retail brokerage APIs (Groww's documented public limits don't specify an exact per-second cap for this endpoint) commonly throttle rapid sequential calls. With enough holdings, a naive loop that fetches LTP one symbol at a time with no backoff can (a) get intermittently rate-limited on some subset of symbols, and (b) if that failure is caught with a broad `try/except` that just skips the symbol, the rules engine silently evaluates that symbol as HOLD-by-omission rather than surfacing "we don't actually know" — meaning a STOP HIT could be sitting unflagged today because its LTP call happened to 429 while looping.

**Why it happens:** Rate-limit handling is usually added reactively, after the first time it's hit — and the "fetch failed, skip that symbol" branch is exactly the kind of thing that satisfies "never crash" without satisfying "never silently lie."

**How to avoid:**
- Batch/throttle LTP fetches with a small fixed delay between calls (or use a bulk quote endpoint if one exists in the SDK — check before looping per-symbol) and retry once on a 429/5xx before giving up on a symbol.
- When a symbol's LTP genuinely can't be fetched after retry, the design spec already calls for this correctly: "skip that symbol's peak/flag calc, note it in message" — implement the "note it in message" part literally as a visible line in the digest (e.g., `⚠️ LTP unavailable: XYZ — flags skipped`), never as a silent omission. This turns pitfall #6 into a visible degraded-mode signal rather than a hidden gap.
- Log (to workflow run logs, not Telegram) which symbols were retried and how many times, so a persistent single-symbol failure pattern is diagnosable later.

**Warning signs:** A symbol occasionally missing from the digest with no flag at all (not even HOLD) on days its price clearly should have triggered something; workflow logs showing repeated 429s from the same call.

**Phase to address:** Broker & Auth (fetch resilience) with a contract into Rules Engine & State Model ("missing LTP" must be a representable state, not an absence).

---

### Pitfall 7: GitHub Actions cron is best-effort — "08:30 IST" can silently mean 08:55 or "didn't run"

**What goes wrong:** GitHub's own scheduling is documented as best-effort with no SLA; delays of 5–30 minutes are routine, and worse delays or drops are more likely at high-contention times (notably top-of-the-hour UTC, and Monday mornings UTC). A `0 3 * * 1-5` (08:30 IST) cron landing at 08:55 or 09:10 isn't catastrophic for a morning digest, but if it lands *after* market open (09:15 IST) the "pre-market day P&L" framing in the message becomes misleading — the LTP you fetch is no longer pre-market, it's 20 minutes into a live session, but the message still reads as if it's the calm pre-market snapshot. Worse, on a sufficiently loaded day the run can be skipped entirely with zero notification, and a repo with low general commit activity (exactly this kind of personal-project repo) is specifically called out as more likely to have scheduled runs throttled.

**Why it happens:** Developers treat GHA cron like a real scheduler (systemd timer, cloud scheduler) with guaranteed firing, when GitHub explicitly documents it as opportunistic.

**How to avoid:**
- Pick a schedule minute that avoids top-of-hour contention (e.g., `17 3 * * 1-5` rather than `0 3 * * 1-5`).
- Add a lightweight dead-man's-switch check (see Pitfall 9) that alerts you if *no* run happened by some cutoff time — this is the only reliable way to detect "GitHub silently didn't fire the cron" since there's no error to catch from inside a run that never started.
- Word the digest's timestamp/freshness explicitly ("as of HH:MM IST") rather than assuming "always pre-market," so a late-firing run is self-evidently late rather than silently misleading.

**Warning signs:** Digest arrival time drifting later over weeks; occasional days with no digest at all and no error — check the Actions tab's run history, not just your inbox, to catch complete misses.

**Phase to address:** Scheduling & CI Wiring.

---

### Pitfall 8: Timezone handling — UTC↔IST conversion bugs and stale "day P&L" semantics

**What goes wrong:** Two distinct bugs live under "timezone," and they're easy to conflate:
1. **The cron expression itself.** GHA cron is always UTC. IST is UTC+5:30 with no DST, so the math is simple, but a common real mistake is writing the workflow YAML cron in local-IST intuition (`30 8 * * 1-5`) instead of converting to UTC (`0 3 * * 1-5`) — this fires at 08:30 UTC (2:00pm IST) instead of the intended pre-market time, and because the job still "succeeds" (holdings exist, LTP exists, message sends), nothing looks broken; you just get an afternoon message you interpret as a morning one.
2. **"Day P&L" semantics when the run is pre-market.** If the run genuinely fires at 08:30 IST (before the 09:15 IST market open), the LTP returned is the *previous close* (or last traded price from the prior session), not "today's price." A message that says "Day P&L +1.2%" at 8:30am is actually reporting yesterday-vs-day-before-yesterday's close delta, not today's movement — today hasn't traded yet. This is a semantics bug, not a code bug, but it's exactly the kind of thing that quietly erodes trust in the digest once you notice the numbers don't match what the market actually does that day.

**How to avoid:**
- Always write and comment the cron in UTC with the IST-equivalent as an inline comment (`# 03:00 UTC = 08:30 IST`), and verify once by watching an actual run's timestamp in the Actions log, not by reasoning about it.
- Rename or reframe the pre-market message to be explicit about what it's measuring: "vs. yesterday's close" rather than "Day P&L," or gate any true "intraday %" language behind actually having a same-session LTP-vs-prev-close field from the API (the design already scopes this correctly as an *if the broker exposes prev close* enhancement — just make sure the default framing is honest until that's confirmed).
- Never use `datetime.now()` without an explicit timezone anywhere date-keying happens for `state.json` — GHA runners run in UTC, so an implicit "today" computed as `date.today()` on the runner is UTC's today, which can be a different calendar date than IST's today for runs near midnight UTC (5:30am IST) — irrelevant at 08:30 IST specifically, but a landmine if the schedule ever shifts.

**Warning signs:** Digest timestamp doesn't match intended send time by a fixed, wrong offset (5:30h is the signature of a UTC/IST mixup); "Day P&L" language triggering questions like "why does this not match what I see in the app."

**Phase to address:** Scheduling & CI Wiring (cron correctness) and Notification Layer (message framing honesty).

---

### Pitfall 9: The alerter has no watcher — total failure is invisible

**What goes wrong:** This is the meta-risk named directly in the question, and it's the single highest-leverage pitfall for a one-person, unattended, financially-relevant automation: every failure mode above (cron didn't fire, `contents: write` blocked, Groww auth broke, Telegram API changed/rate-limited/blocked the bot) has one thing in common — the *absence* of a message. A system whose only success signal is "a message arrived" has no way to distinguish "everything is fine, HOLD everywhere" from "the entire pipeline silently died three days ago." Telegram Bot API calls can themselves fail silently in application code that doesn't check the HTTP response (bot blocked by user, chat_id wrong after a Telegram account change, bot token revoked, transient Telegram outage) — and if the failure happens *after* the state.json commit but *before* a successful send confirmation, you get correct-but-invisible state and zero visible symptom until you happen to open Groww yourself and notice a STOP HIT you never got.

**Why it happens:** "Send a Telegram message" reads as the terminal, low-risk step of the pipeline, so it gets the least defensive code — but it's actually the only step whose failure is externally undetectable by definition, because the entire point of the system is to replace you checking manually.

**How to avoid:**
- Check the Telegram send call's actual HTTP response/return value, not just "didn't throw" — a bot blocked by the user or an invalid `chat_id` typically returns a clean error response, not a Python exception, if the wrapper library doesn't raise on non-2xx.
- Add a genuinely independent dead-man's-switch: a separate, trivially simple mechanism that alerts you if the *expected* daily message didn't arrive by a fixed cutoff — options in rough order of setup cost: (a) a GitHub Actions status-check subscription/webhook to your email for job failures (catches crash-and-exit-nonzero, not silent success-with-no-send), (b) a third-party heartbeat/dead-man's-switch service (e.g., a cron-monitoring ping the job must hit on success — if the ping doesn't arrive, the service itself emails you), or (c) at minimum, GitHub's own email-on-workflow-failure notifications enabled for this repo, which catches exit-non-zero failures (already required by the design) but *not* the "ran clean, sent nothing" failure mode — which is why (b) or a self-check step matters.
- Treat "Telegram send succeeded" as a checkable postcondition of the run, not a fire-and-forget final step: fail the workflow (exit non-zero) if the send call didn't confirm success, so at minimum GitHub's own failure-notification path (which the design already requires) catches it.

**Warning signs:** No warning signs from inside the system by construction — this is precisely why it needs an external check. The only detection is either an independent heartbeat monitor or you personally noticing "I haven't gotten a message in N days."

**Phase to address:** Notification Layer, and this should be treated as its own late-stage hardening concern (a dedicated dead-man's-switch step) rather than folded silently into "error handling" — call it out explicitly as a phase deliverable, not an assumed side effect of "robust error handling."

---

### Pitfall 10: Telegram message construction fails at the API boundary in ways that only show up with real data

**What goes wrong:** Telegram's `sendMessage` has a 4096-character limit per message and, if using `MarkdownV2` or `HTML` parse modes for formatting (bold flags, emoji headers), any unescaped special character in dynamically-inserted content (a stock symbol with a period, a negative percentage with a `-` next to markdown-significant characters, etc.) causes the *entire send to fail* with a 400 error — not a partial render. A portfolio that temporarily has many simultaneous non-HOLD flags (a bad market day, exactly the day you most need the digest) is also exactly the day most likely to produce a message near or over the 4096-char limit, meaning the failure mode correlates with the days the alert matters most.

**Why it happens:** Development and testing happens against a small, clean holdings list with no adversarial characters and few simultaneous flags, so both the length limit and the escaping requirement go untested until a real bad-market day produces both a long message and, coincidentally, a symbol/percentage combination that trips markdown escaping.

**How to avoid:**
- Prefer plain text over `MarkdownV2`/`HTML` parse modes unless you specifically need bold/formatting — it removes the entire escaping failure class for a personal single-user bot where formatting is a nice-to-have, not a requirement.
- If formatting is kept, centralize all dynamic-value insertion through one escaping helper and unit test it against known-adversarial inputs (symbols with dots, negative numbers, parentheses).
- Defensively cap/truncate message construction with an explicit length check and a "…and N more, see logs" fallback rather than trusting it'll always be short enough, and unit test the digest formatter against a synthetic worst-case holdings list (every symbol flagged) as a boundary case, not just the happy-path few-flags case.

**Warning signs:** A Telegram send failure specifically on a volatile market day; a 400 error in workflow logs referencing markdown parsing.

**Phase to address:** Notification Layer.

---

### Pitfall 11: Mocking the SDK wrong gives false test confidence while real boundary bugs in the rules engine go uncaught

**What goes wrong:** Two independent testing failure modes compound each other. First, mocking `growwapi` incorrectly — e.g., mocking at the wrong layer (stubbing the whole `GrowwAPI` class with a `Mock()` that returns whatever `Mock()` returns for unconfigured attributes, rather than mocking the specific SDK call with a realistic response shape) means tests pass while the actual integration would break on a real (differently-shaped) SDK response — a classic case of testing your mock, not your code. Second, and more dangerous for a *money-decision* system: because `rules.py` is a pure function, it's tempting to write a handful of "one assertion per flag" tests that each hit the *middle* of a threshold band (e.g., "-15% triggers STOP HIT") and call coverage done — while the actual bugs in threshold logic live at the *boundaries* (exactly -12.0% vs -12.01%, off-by-one in `>` vs `>=`, a stock at exactly 10% portfolio weight that should or shouldn't TRIM depending on which side of the boundary the spec intends).

**Why it happens:** Mocking the SDK class wholesale is the path of least resistance and "just works" in a quick test; boundary-value testing requires deliberately thinking about the *edges* of each named constant, which is easy to skip once the obvious middle-of-range cases pass.

**How to avoid:**
- Mock at the function-call boundary with realistic fixture data shaped exactly like a real (or documented) SDK response — capture one real anonymized response during manual testing and use it as the fixture shape, rather than an ad-hoc dict.
- For `rules.py`, write boundary tests explicitly for every named threshold constant: value exactly at the threshold, one unit above, one unit below — for each of STOP HIT (-12%), BOOK 50% (+25%), TRIM (10% weight), AVG CANDIDATE (10/20/30% down), and TRAIL WATCH (20% below peak). This is a small, fixed, enumerable test list, not open-ended — do it once, completely, rather than incrementally.
- Also test flag *precedence* explicitly: a stock that qualifies for both STOP HIT and TRIM simultaneously — the rules table implies flags aren't mutually exclusive per bucket, so the digest formatting/precedence logic needs its own boundary tests, not just the rule-evaluation logic.

**Warning signs:** High "test count" but bugs still found manually near threshold values in production; a test suite that never had to be updated when threshold constants changed (suggests tests aren't actually threshold-sensitive).

**Phase to address:** Testing & Hardening, but the boundary-test list should be written *alongside* Rules Engine & State Model as that phase's own definition of done, not deferred to a separate later phase.

---

### Pitfall 12: Secrets leak into logs, error messages, or committed files

**What goes wrong:** This system has four secrets (`GROWW_API_KEY`, `GROWW_TOTP_SEED`, `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`) flowing through error handling paths that, by design, are supposed to be verbose and Telegram-visible ("fail loud naming the missing secret"). Two concrete leak vectors follow directly from that good instinct if implemented carelessly: (a) an exception's string representation from the `growwapi` SDK or an HTTP client can include the request headers or payload (which contain the API key/token) — if a broad `except Exception as e: send_telegram(f"failed: {e}")` is used, a library that includes auth headers in its exception repr sends your own API key to yourself over Telegram, and Telegram messages aren't a secure secret store; (b) GitHub Actions' own log masking only redacts secrets it can see used *verbatim* as `secrets.X` in the workflow YAML or literally matched in stdout — a TOTP *code* (the 6-digit value derived from the seed via `pyotp`, not the seed itself) is not a registered secret, so if it's ever printed for debugging, it's not masked, and while an individual TOTP code is short-lived and low-value alone, printing it habitually during development is a bad habit that risks the seed itself leaking via a stray `print(seed)` left in during debugging.

**Why it happens:** "Validate secrets present, fail loud naming which one is missing" (a good, explicitly required practice here) is easy to conflate with "print the exception verbatim" during implementation — the former only needs to name the *variable*, never its *value*, but broad exception handlers make that distinction easy to blur.

**How to avoid:**
- The "fail loud" requirement should validate *presence* only (`if not os.environ.get("GROWW_API_KEY"): raise ...("GROWW_API_KEY missing")`) — never echo the value, and never pass a raw caught exception's `str(e)` into a Telegram message without first checking it doesn't contain a known secret substring (a simple guard: redact any exact match of the four secret values from any string headed to Telegram or logs, since GHA's own env is available to do that substring check in-process).
- Never `print()` or log the TOTP seed or derived code, even temporarily "just to debug" — use a separate local-only debug script outside the CI workflow if you need to eyeball TOTP generation.
- Confirm `.gitignore` excludes any local `.env`/secrets file before the first commit, and grep the git history once after initial setup for any of the four secret variable *values* (not just names) to catch an accidental early commit before the repo goes further.

**Warning signs:** A Telegram error message that includes anything that looks like a token/key substring; a workflow log line that isn't `***` for a value you know should be masked.

**Phase to address:** Broker & Auth (secret validation) and Scheduling & CI Wiring (workflow-level masking verification) — treat as a cross-cutting concern checked at the end of every phase, not owned by one phase alone.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|-----------------|------------------|
| Skip corporate-action detection, ship on raw `average_price` | Faster v1 ship | Silent false STOP/AVG flags whenever a bonus/split happens to a held stock | Only if you personally hold zero stocks with pending/likely corporate actions at launch, and you re-check this before every future addition to holdings |
| Cache the Groww access token in `state.json` "to save an API call" | Slightly fewer auth round-trips | Guaranteed daily breakage once the token expires, indistinguishable from a broker outage | Never |
| Broad `except Exception` around the whole `sentinel.py` main | Simple, never crashes unhandled | Swallows the *specific* failure reason (auth vs. fetch vs. rate-limit vs. Telegram-send), turning every failure into the same generic "fetch failed" message that gives you no actionable next step | Only as an outer safety-net catch *after* specific handlers for each pipeline stage, never as the only error handling |
| Trust GHA cron timing as exact | No extra monitoring code | Silent missed/late runs go unnoticed indefinitely | Never for a system whose entire value is "runs so I don't have to check manually" — add the dead-man's-switch from day one |
| No dead-man's-switch, rely on "exit non-zero → GitHub emails me" | Zero extra setup | Doesn't catch the worst failure mode (ran clean, sent nothing, or cron never fired) | Only acceptable temporarily in the first 1-2 weeks while manually spot-checking each morning; graduate to a real heartbeat check before trusting it unattended |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|------------------|-------------------|
| Groww TradeAPI (`growwapi`) | Assuming `average_price` is always post-corporate-action adjusted | Verify empirically once against a known bonus/split in your own history; add quantity-delta detection as a backstop regardless |
| Groww TradeAPI auth | Persisting/caching the session token across runs | Regenerate TOTP + fresh login every single run; never write the token to `state.json` |
| Groww LTP endpoint | Looping per-symbol with no throttle/backoff | Add a fixed small delay between calls, retry once on failure, and represent "unknown LTP" as an explicit state, not a skip |
| GitHub Actions `GITHUB_TOKEN` | Assuming `contents: write` always works once granted in YAML | Test with a real `workflow_dispatch` run before enabling cron; have a fine-grained-PAT fallback ready if org policy blocks it |
| GitHub Actions scheduling | Treating cron as guaranteed-on-time | Pick a non-top-of-hour minute; add an independent dead-man's-switch; word the digest with an explicit "as of" timestamp |
| Telegram Bot API | Using `MarkdownV2`/HTML formatting without a centralized escaping helper | Prefer plain text, or centralize + unit-test escaping against adversarial symbol/number inputs |
| Telegram Bot API | Not checking the send call's actual success response | Check the response/status explicitly; fail the workflow (exit non-zero) if send didn't confirm |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|-----------------|
| Per-symbol LTP fetch loop with no batching | Slower runs, occasional 429s as holdings count grows | Check SDK for a bulk-quote call; throttle if only per-symbol calls exist | Noticeable once holdings exceed roughly a dozen-plus symbols, depending on undocumented Groww rate limits |
| `state.json` growing unbounded (every day, forever, no pruning) | File and diff size creep every commit; slower checkout/reads over years | Prune snapshots older than what weekly/trend logic actually needs (e.g., keep a rolling N days, roll old data into a compact monthly summary) | Not urgent at personal-portfolio scale/timeframe, but plan the prune policy before multi-year history piles up in git history/diffs |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Echoing exception text verbatim into Telegram or logs | API key/token/TOTP seed leaks into a chat log or log stream that isn't a secret store | Redact known secret values before any string reaches Telegram/logs; validate presence without echoing value |
| Printing TOTP seed/code during development debugging | Seed leak via terminal scrollback, screenshot, or accidental commit of a debug script | Debug TOTP generation only in a local, gitignored, non-committed script; never in code that runs in CI |
| Committing `.env`/local secrets file before `.gitignore` is set up | Secrets in git history forever, requiring rotation even after removal | Set up `.gitignore` before the first commit that touches secrets; grep history once early to confirm |
| Using a broad-scope PAT as the `contents: write` fallback | Overprivileged token if org policy blocks default token | Use a fine-grained PAT scoped to only this repo and only `contents: write` |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-------------------|
| "Day P&L" language on a pre-market run | Reads as "today's movement" when it's actually vs. yesterday's close, eroding trust once the mismatch is noticed | Label explicitly as "vs. yesterday's close" until true intraday-vs-prev-close data is confirmed available |
| Permanent TRAIL WATCH on a permanently-down stock | Alert fatigue — the flag becomes wallpaper, and real trailing-stop signals get ignored along with it | Cap/decay the flag logic (see Pitfall 2) so it signals a *change*, not a persistent state |
| Silent symbol omission on LTP fetch failure | User has no idea a stock's flag might be wrong/missing today, and may assume "no flag = HOLD is correct" | Always emit an explicit `⚠️ LTP unavailable` line rather than silent omission |
| "All quiet" message with no run-freshness indicator | Can't distinguish "genuinely nothing to flag today" from "the job partially failed and defaulted to quiet" | Include a lightweight freshness/health marker (e.g., "as of HH:MM IST, N/N symbols priced") even in the quiet case |

## "Looks Done But Isn't" Checklist

- [ ] **Peak tracking:** Often missing the exit/re-entry reset and the seed-on-first-seen logic — verify with explicit unit tests for held-30-days, first-seen-day, and sold-then-rebought scenarios, not just the accumulate-max happy path.
- [ ] **state.json persistence:** Often missing a same-day merge/upsert guard and a push-failure check — verify by manually re-running the workflow twice in one day and confirming the second run doesn't corrupt or silently fail to persist.
- [ ] **Error handling ("never silently skip a day"):** Often satisfies "doesn't crash" while still satisfying "silently sends nothing useful" — verify by deliberately breaking each pipeline stage (bad TOTP seed, unreachable Telegram, empty holdings) one at a time and confirming each produces a *distinct, actionable* Telegram message, not a generic one.
- [ ] **Secret validation at startup:** Often validates presence but not shape/format (e.g., a `TELEGRAM_CHAT_ID` that's present but wrong) — verify the "wrong chat ID" case surfaces as a diagnosable error, not a silent no-op send.
- [ ] **NSE holiday calendar:** Often hardcoded once and never revisited — verify there's a documented process/reminder for updating it each calendar year (holiday lists aren't static SDK data unless sourced from a maintained package).
- [ ] **Dead-man's-switch:** Almost always missing entirely on first ship because it's not "a feature," it's a meta-concern — verify by asking directly: "if this job silently stopped running tomorrow, how would I find out, and by when?"

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|-----------------|-----------------|
| Corporate action corrupted `avg_price`/peak for a symbol | LOW | Manually correct that symbol's entry in `state.json` (reset peak to current LTP, note the corrected cost basis) and commit; add the quantity-delta detector so it doesn't recur |
| `state.json` commit silently failed for one or more days | LOW–MEDIUM | Diff the missing days: if only the commit failed (not the fetch), you likely still have the day's Telegram message for reference to manually backfill `state.json`, or accept a small gap in trend history and reseed peaks from current LTPs |
| Double-run corrupted a same-day snapshot | LOW | Restore that date's entry from the git history of `state.json` (the prior commit before the double-run) rather than trying to reconstruct by hand |
| TRAIL WATCH stuck permanently on a stock | LOW | One-time manual edit to `state.json` to lower the stored peak to current LTP, functionally "acknowledging" the drawdown as the new baseline, plus ship the decay/cap fix so it doesn't recur |
| Secret leaked into a Telegram message or log | MEDIUM–HIGH | Rotate the leaked secret immediately (new Groww API key/TOTP seed, new Telegram bot token) regardless of how minor the exposure looks; delete the offending Telegram message if possible (does not guarantee removal from Telegram's servers, so rotation is the real fix, not deletion) |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|-------------------|----------------|
| Corporate actions corrupt avg_price/peak | Rules Engine & State Model | Unit test a synthetic bonus/split scenario (quantity jump, proportional avg_price change) and confirm flags suppress + `CORP ACTION?` fires instead of a false STOP/BOOK/AVG |
| Peak never decays / seeded wrong / survives sell | Rules Engine & State Model | Unit tests for held-long-term, first-seen, and sold-then-rebought scenarios all pass with distinct expected peaks |
| `contents: write` blocked by org policy | Scheduling & CI Wiring | A real `workflow_dispatch` run produces a visible new commit to `state.json` before cron is enabled |
| Concurrent/double runs corrupt snapshot | Scheduling & CI Wiring + Rules Engine & State Model | Manually trigger two runs same day; confirm second run merges rather than overwrites, and `concurrency:` group is set in the workflow |
| Groww TOTP/session expiry in CI | Broker & Auth | Confirm no code path reads a cached token from `state.json`; run on two consecutive days and confirm both auth independently |
| LTP fetch rate limits / partial failures | Broker & Auth | Deliberately force one symbol's fetch to fail in a test and confirm digest shows an explicit `⚠️ LTP unavailable` line, not a silent HOLD |
| GHA cron drift / best-effort scheduling | Scheduling & CI Wiring | Observe actual run timestamps over 1-2 weeks; confirm a dead-man's-switch exists independent of the workflow itself |
| UTC/IST conversion & stale-P&L semantics | Scheduling & CI Wiring + Notification Layer | Confirm cron YAML comment matches observed run time in Actions log; confirm digest wording says "vs. yesterday's close," not "Day P&L," until intraday data is confirmed |
| Alerter failure is invisible (no watcher) | Notification Layer | An independent heartbeat/monitoring check exists that does NOT depend on the sentinel job itself to report its own silence |
| Telegram message length/escaping failures | Notification Layer | Unit test digest formatter against a synthetic worst-case (all symbols flagged) and against adversarial symbol/number strings |
| Mocking SDK wrong / boundary threshold bugs | Testing & Hardening (defined alongside Rules Engine & State Model) | Boundary tests exist for every named threshold constant (at, above, below) plus a flag-precedence test |
| Secrets leakage into logs/commits | Cross-cutting, checked at every phase | Grep git history and workflow logs once per phase for literal secret values; confirm exception messages sent to Telegram are redacted |

## Sources

- [Groww API — Portfolio docs (python-sdk)](https://groww.in/trade-api/docs/python-sdk/portfolio) — MEDIUM confidence (official vendor docs, but did not explicitly confirm corporate-action adjustment behavior for `average_price` — treat as unconfirmed per design spec's own open item)
- [Groww API — Live Data / LTP docs](https://groww.in/trade-api/docs/curl/live-data) — MEDIUM confidence (official docs; exact REST rate limit for LTP not published, treat concrete numeric limits as unconfirmed)
- [growwapi on PyPI](https://pypi.org/project/growwapi/) — MEDIUM confidence
- [GitHub Docs — Controlling permissions for GITHUB_TOKEN](https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/controlling-permissions-for-github_token) — HIGH confidence (official docs)
- [GitHub community discussion — org override of workflow permissions](https://github.com/orgs/community/discussions/57244) — HIGH confidence (official GitHub product behavior, community-confirmed)
- [GitHub Actions cron drift / best-effort scheduling analysis](https://crontap.com/blog/github-actions-cron-drift-problem) — MEDIUM confidence (third-party analysis, but consistent with GitHub's own "best effort, no SLA" documentation)
- [GitHub community discussion — scheduled workflow delays](https://github.com/orgs/community/discussions/156282) — MEDIUM confidence (community-reported, consistent pattern across multiple threads)
- Telegram Bot API `sendMessage` 4096-character limit and parse-mode escaping requirements — HIGH confidence (well-established, long-standing public Telegram Bot API behavior)
- Domain experience: brokerage-API/scheduled-job/financial-alerting failure patterns (session/token expiry, stateful peak-tracking bugs, silent-failure dead-man's-switch gap) — HIGH confidence as general patterns, applied here to the project's specific architecture

---
*Pitfalls research for: personal brokerage advisory bot (Groww TradeAPI + GitHub Actions + Telegram)*
*Researched: 2026-07-09*
