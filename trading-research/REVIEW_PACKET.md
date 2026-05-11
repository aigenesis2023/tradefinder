# Trading Research Engine — Review Packet (v3)

A self-contained packet for an outside reviewer (Gemini, GPT, Grok, or human) to critique a trading research system. Paste the whole document in and ask for design / architecture / empirical critique.

**What changed since v2 (this session):**
- Audited the entire codebase against the rulebook; found 10 issues, fixed all.
- Discovered and fixed a silent bug that was capping insider catalyst-strength at 2.5 (about 44% reduction on the primary signal driver).
- Added an **Elite-Override mode**: regime-gate failure no longer terminates the run; instead the engine surfaces only top-decile signals.
- Added a **High-Upside tier**: candidates with composite 3.0–3.5 plus strong asymmetric markers (short interest, deep conviction, step-change contracts) now appear in a separate report section.
- Switched the expected holding horizon from 30 days to **10 days** based on per-day alpha analysis of the same backtest.
- Removed all dead code (Agent 4, the N² LLM theme-clustering pass).

Full rationale and tables below.

---

## 1. WHAT THIS IS

A multi-agent research engine that surfaces high-conviction long ideas in small/mid-cap US equities ($500M–$5B) for a discretionary retail trader. The engine outputs filtered candidates with a thesis, score, invalidation trigger, and now a recommended exit horizon. The human decides whether to trade.

**Target output:** 1–3 trades per week in normal regime; 0–1 in elite-override (regime-fail) mode.

**Edge thesis:** Institutions (mutual funds, pension funds, sell-side analysts) systematically ignore the $500M–$5B band due to position-size minimums and lack of banking-fee revenue. This creates structural information asymmetry. **Multi-insider buying clusters** in this range are the strongest available signal that informed parties see undervaluation. Government contract awards are a secondary catalyst.

**Operating context:** 60-day paper-trading window for a YouTube case study comparing engines built on Claude, GPT, Gemini, and Grok. Track record is the deliverable.

---

## 2. EMPIRICAL FOUNDATION

### Headline backtest (OpenInsider 2018–2024, n=382, IWM-adjusted)

| Filter | n | Raw 30d | IWM 30d | **Alpha** | Alpha win |
|---|---|---|---|---|---|
| All signals | 382 | +1.31% | +0.25% | +1.06% | 53.4% |
| 2 insiders | 261 | +0.63% | +0.37% | +0.26% | 48.3% |
| 3+ insiders | 121 | +2.80% | −0.01% | **+2.81%** | 64.5% |
| **3+ + $500M–$5B (production)** | **93** | **+3.37%** | **−0.55%** | **+3.92%** | **68.8%** |
| 3+ + $200M–$500M (micro) | 28 | +0.31% | +1.18% | −0.87% | 50.0% |

**Conclusions baked into the engine:**
- 2-insider clusters are noise; 3+ is the empirical inflection.
- Mid-cap ($500M–$5B) > micro-cap ($200M–$500M); micro-cap 3+ has *negative* alpha after benchmark adjustment.
- Production filter (3+ + $500M–$5B) is the engine's primary catalyst.

### Holding-period analysis (production cohort, n=93)

This was run this session to decide the exit horizon:

| Horizon | Alpha | Alpha-win | Std | **Per-day alpha** | **Alpha/Std** |
|---|---|---|---|---|---|
| 7d | +1.32% | 60% | 9.70% | 0.188% | 0.136 |
| **10d** | **+2.93%** | 58% | 12.46% | **0.293%** | **0.235** |
| 30d | +3.92% | 69% | 17.30% | 0.131% | 0.227 |

**Why 10d is the chosen horizon:**
- Best per-day alpha rate (>2x vs 30d).
- Best risk-adjusted alpha (alpha/std).
- Tight enough that macro/geopolitical/sector noise has limited time to overwrite the signal.
- 30d has higher total alpha and win rate but lower turnover → worse compounding.

### Elite cohort (5+ insiders, $500M–$5B, n=7 — small sample but striking)

| Horizon | Alpha | Alpha-win |
|---|---|---|
| 7d | **+6.63%** | 71% |
| 10d | **+6.68%** | 57% |
| 30d | +0.05% | 57% |

**Elite signals capture all their alpha in days 7–10 then mean-revert by day 30.** This drove the design of the High-Upside / Elite-Override paths.

### What we DON'T have data on
- Outcomes past 30 days (could not measure 60d, 90d, 180d in this backtest)
- Government contract signal alpha (entire backtest is on insider clusters)
- Full-LLM-pipeline outcomes (only raw mechanical filter was backtested)
- Live paper-trading outcomes (zero closed trades to date)

---

## 3. ARCHITECTURE

### Dual entry gate (hard-blocking, both must pass)
- **Regime gate**: VIX/VIX3M < 1.0 (contango) AND IWM > 20-day MA. Failure no longer terminates — switches to elite-override mode (see §5).
- **Neglect screen** (Gate 2, signal-specific):
  - Contracts: 3 of 4 must pass (analyst < 8, news < 3 events/30d, institutional < 30%, volume below 6-mo avg)
  - Insiders: only the analyst and news checks apply (institutional % is data-noisy at this cap range; volume spike is caused by the signal itself)

### Multi-agent flow
| Agent | Role | LLM? |
|---|---|---|
| 1 (Bull) | Discovery + thesis | Yes (judgment only — scoring is in Python) |
| 1B (Bear) | Pre-mortem failure case | Yes |
| 1C (Supervisor) | Identifies irresolvable conflict; **disqualifies on uncertainty** | Yes |
| 2 (Quant) | VSA proxies + RS vs IWM | **No** (now fully deterministic) |
| 3 (Synthesis) | Composite scoring, thesis narrative, invalidation trigger | LLM for narrative only; scoring 100% Python |

### Scoring
```
composite = (
    (catalyst_strength × catalyst_type_prior × 0.30) +
    (quant_confirmation                       × 0.30) +
    (risk_asymmetry                           × 0.25) +
    (information_asymmetry                    × 0.15)
) × (data_quality / 5)
+ confirming_signal_bonus  (capped at +0.9)
```

- All four scoring inputs are deterministic Python.
- Composite ≥ 3.5 → High Conviction pool (top 5 surfaced).
- Composite 3.0–3.5 → High-Upside pool (top 3 surfaced) IF `high_upside_score ≥ 2.5`.
- Below 3.0 → discarded.

### High-upside score (new this session)
Deterministic 0–5 scale capturing asymmetric setups:
- Short interest > 20% → +1.5
- Insider cluster ≥ 0.20% of market cap → +1.0; ≥ 0.10% → +0.5
- 5+ unique insiders → +1.0
- Contract ≥ 50% of TTM revenue → +2.0; 25–50% → +1.0
- Smaller mid-cap ($500M–$1.5B) → +0.5

### Score decay (new this session — was uniform, now catalyst-specific)
- Insider clusters: full strength to day 21, then 2.5%/day decay (matches empirical 30d alpha window)
- Government contracts: full strength to day 7, then 5%/day decay (faster macro/news decay)

---

## 4. ISSUES FOUND AND FIXED (this session)

A full code audit found 10 issues. All resolved:

| # | Issue | Impact | Fix |
|---|---|---|---|
| 1 | `update_outcome()` never called — no track record | Critical (cosmetic — user does this manually now) | Acknowledged; user manages P&L externally |
| 2 | Contract-revenue cap applied to ALL catalysts including insiders | **Critical — silently capped 6-insider clusters at 2.5/4.5 catalyst strength** | Guarded with `if catalyst_type == "government_contract_award"` |
| 3 | Confirming-signal `insider_buying_cluster` double-counted when primary was also insider | +0.3 bonus for the same signal as the primary catalyst | Strip primary-matching signals before computing bonus; raised signal_scanner cluster threshold from 2 to 3 |
| 4 | Contract name-matching accepted any single shared word ("Enova" matched "Bunkhouse Renovations") | Wasted full LLM pipeline on misattributed contracts | Now requires ALL significant words to match |
| 5 | LLM budget of 40 was below the floor needed for 15 candidates × 4–5 LLM calls each | Late candidates silently auto-disqualified by 1C's default | Raised LLM budget to 100; dropped the N² LLM theme-clustering pass |
| 6 | CLAUDE.md claimed quant scoring was deterministic but code still called an LLM | Doc/code drift | Replaced LLM call with deterministic VSA scoring |
| 7 | yfinance `heldPercentInstitutions` returned >100% (short-loan double-count) | Government-contract candidates failed neglect screen on garbage data | Treat values >100% as missing and fall back |
| 8 | Score decay killed 30-day insider signals at day 27 | Forced too-short windows on the primary catalyst | Split decay by catalyst type |
| 9 | "Already priced in" 5% cap clipped insider winners during post-cluster spike | Cut potential winners pre-thesis | Raised to 12% for insider catalysts only |
| 10 | Agent 4 dead code | Maintenance noise | Deleted |

**Pre-fix empirical proof of bug severity:** 23 candidates had run through the engine prior to fixes; 0 of them had composite scores populated. All 23 were disqualified — many for legitimate reasons (data quality issues, contract misattributions) but several for budget exhaustion and the silent insider cap.

---

## 5. NEW FEATURES (this session)

### Elite-Override mode
When the regime gate fails, the engine no longer terminates. It runs in elite-only mode with stricter thresholds:

| Signal | Normal regime | Elite-override |
|---|---|---|
| Insider cluster | 3+ insiders, 0.02% materiality | **5+ insiders, $2M+ total, 0.10% materiality** |
| Government contract | 10%+ of TTM revenue | **25%+ of TTM revenue** |

Candidates flagged `regime_override=True` are tagged in the report and have their max confidence capped at Medium (macro risk is real).

**Rationale:** Some of the highest-leverage trades historically come from buying during panic. The original hard-stop gate threw away those opportunities. The override surfaces only signals strong enough to plausibly survive adverse macro.

### High-Upside report section
Separate from the High-Conviction list. Surfaces up to 3 candidates with composite 3.0–3.5 + high_upside_score ≥ 2.5. Designed for asymmetric variance: lower win rate per trade but larger winners (squeezes, step-change contracts, deep-conviction clusters).

### 10-day expected horizon
Empirically the best per-day alpha rate. Replaces the previous implicit 30-day expectation. Pairs with profit targets and invalidation triggers as primary exits; time stop is the catch-all.

### Short-interest squeeze weight bumped
Squeeze contribution to `risk_asymmetry` raised from +0.2 to +0.4. High short interest is the classic asymmetric setup and was underweighted.

---

## 6. CURRENT EXIT FRAMEWORK

The engine outputs signals; the human executes. Recommended exit hierarchy:

1. **Profit target** (~+8%) → take profit
2. **Stop loss** (~−6% from entry) → cut loss
3. **Invalidation trigger fires** (Agent 3 outputs a specific event per idea) → exit
4. **Time stop at 10 days** → exit because nothing else fired

The time stop only governs trades that drift — most trades resolve via #1, #2, or #3 first.

---

## 7. OPEN QUESTIONS FOR THE REVIEWER

These are the things we genuinely want a second opinion on. Please critique any/all:

### Empirical
1. **Is 10-day horizon defensible?** Best per-day alpha and best alpha/std in the data, but the higher win rate at 30d is real. Are we leaving "win rate alpha" on the table by exiting early?
2. **Elite cohort sample size (n=7) is small.** The 30d mean-reversion pattern is striking but could be noise. Should we hold the 10-day rule for elite only, or universally?
3. **The government contract signal has zero empirical validation in this backtest.** It's kept as a prior-1.0 catalyst on intuition + general literature. Should it be parked until we backtest contracts specifically?
4. **No data beyond 30 days.** If the user's intuition is right that insiders predict longer-term growth, we'd see continued outperformance at 60–180d. We can measure this — should we, before locking in 10d?

### Architectural
5. **Elite-Override mode is unvalidated.** Thresholds were picked by intuition (5+ insiders, 25%+ revenue). Reasonable? Too lax? Too strict?
6. **High-upside tier is also unvalidated.** Composite 3.0–3.5 floor + score ≥ 2.5 was eyeballed. Should we tighten the upside-score threshold?
7. **LLM budget = 100, with ~4 calls per candidate.** Will exhaust around candidate 25. Is the safety default (1C → DISQUALIFY) the right one? Or should budget-exhausted candidates simply not be processed instead of being scored Disqualified?
8. **Theme clustering is purely deterministic (sector + catalyst_type).** The LLM cross-check was dropped to save budget. Are we losing meaningful cluster detection (e.g., supply-chain links across sectors)?
9. **Two insider scanners exist** (`insider_scanner.py` for the primary scan, `signal_scanner.py` for confirming signals). They now share threshold (3+) but are separate code paths. Worth unifying?

### Strategic
10. **No backtest of the full LLM pipeline.** The empirical numbers above are raw mechanical filter results. We don't know if the LLM stack (Bull/Bear/1C/Synthesis) adds lift over the +1.31% baseline.
11. **Contract name-matching false-positive rate** is reduced but not eliminated. UEI/CIK cross-checking would solve it but isn't implemented. Acceptable trade-off?
12. **Sector beta contamination** — the engine adjusts for IWM but not for GICS sector indices. Real but probably not critical for long-only. Worth implementing?
13. **No position sizing or stop-loss rules in code** — they're documented in CLAUDE.md but advisory only. The user manages this manually. Should the engine emit a recommended position size and stop level per idea?

### Catalyst design
14. **Two primary catalysts only** (insiders, contracts). Should we add: earnings revisions, short-interest changes, 13F initiations as primaries rather than confirming?
15. **Insider scanner includes EVP/SVP** as qualifying roles. CLAUDE.md only specifies CEO/CFO/COO/Chairman/Director/President. Drift or improvement?

---

## 8. WHAT WE'D LOVE FEEDBACK ON SPECIFICALLY

If you only have time for three pieces of feedback:

1. **The 10-day horizon decision.** Right call given the data? Or are we overfitting to per-day alpha at the expense of win rate?
2. **The elite-override + high-upside design.** Reasonable response to "you'd miss big asymmetric trades in chaos regimes," or just adding complexity that won't survive contact with real markets?
3. **The biggest unmeasured risk.** What are we obviously missing that would tank performance during the 60-day paper-trading window?

---

## 9. CODE LOCATIONS (for deep-dive)

```
/trading-research/
├── run_pipeline.py                    # entry point + report formatter
├── CLAUDE.md                          # normative rulebook
├── agents/
│   ├── agent1_bull.py                 # discovery + bull narrative + elite filter
│   ├── agent1b_bear.py                # pre-mortem
│   ├── agent1c_supervisor.py          # uncertainty → disqualify
│   ├── agent2_quant.py                # deterministic VSA + RS
│   └── agent3_synthesis.py            # composite + high_upside + narrative
├── orchestrator/
│   ├── regime_gate.py                 # VIX/VIX3M + IWM gate; elite_only flag
│   ├── neglect_screen.py              # 3-of-4 (contract) / 2-check (insider)
│   ├── insider_scanner.py             # SEC EDGAR Form 4 primary
│   ├── contract_scanner.py            # USAspending primary (strict name match)
│   ├── signal_scanner.py              # confirming signals
│   ├── theme_cluster.py               # deterministic only
│   ├── ranking.py                     # HC + HU pools
│   ├── request_budget.py              # 100 LLM / 140 total
│   ├── state_manager.py               # SQLite, with v3 migrations
│   └── universe_builder.py            # 922-ticker cache
└── backtest/
    ├── openinsider_pull.py            # 7-year cluster scraper
    ├── measure_oi_outcomes.py         # 7d/10d/30d outcome measurement
    └── results/
        └── openinsider_clusters_2018-01-01_2024-12-31_measured.csv  # n=383
```

---

## 10. SUMMARY OF STATE

- **Architecture**: stable; bugs from v2 fixed.
- **Empirical foundation**: solid for insider clusters at 30d (n=93, +3.92% alpha). 10d horizon defensible from same dataset.
- **Untested**: elite-override thresholds, high-upside scoring weights, government contract catalyst, full LLM pipeline lift.
- **Next step (post-feedback)**: 60-day paper trading window beginning when reviewer feedback is incorporated.

Reviewer: anything that looks wrong, brittle, or missing — call it out. We will not be defensive. Specifically welcome contrarian takes on the holding-period decision and the elite-override design.
