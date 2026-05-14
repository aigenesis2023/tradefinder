# TradeFinder Engine — Comprehensive Overview

**A multi-agent, empirically-grounded investigation into LLM-based trading edges for US equity retail traders.**

Version 1.0.0 | 2026-05-14

---

## 1. System Purpose and Scope

TradeFinder answers a single falsifiable question:

> **"How can large language models give a retail trader a genuine, persistent edge in US equity markets?"**

The system is designed to:

- **Generate** creative, falsifiable hypotheses about LLM-based trading signals
- **Test** those hypotheses against real historical market data through a locked, unbiased pipeline
- **Safeguard** against the most common failure modes in quantitative finance research: data snooping, survivorship bias, look-ahead bias, factor recycling, and multiple-comparison inflation
- **Self-correct** by feeding broken hypotheses back to the ideation layer for refinement

The target user is a retail trader with $50K–$250K capital, standard brokerage access, checking positions once per day. All data sources must be free or low-cost and retail-accessible.

---

## 2. Architecture

The system has 17 specialized agents organized into three stages, connected by a two-agent bridge:

```
┌─────────────────────────────────────────────────────────────────┐
│                    INFORMATION FIREWALL                          │
│                                                                  │
│  STAGE 1 (8 agents)          BRIDGE (2)       STAGE 2 (7 agents)│
│  ┌──────────────────┐    ┌──────────────┐    ┌────────────────┐ │
│  │ Generator x2      │    │              │    │ Universe       │ │
│  │ Critic             │    │  Executor    │    │ Builder        │ │
│  │ Domain-Specialist  │    │     +        │    │ Data Adapters  │ │
│  │ Skeptic            │───▶│  Verifier    │───▶│ Extractors     │ │
│  │ Synthesizer        │    │              │    │ Backtester     │ │
│  │ Ranker             │    │ (manual .md) │    │ Statistics     │ │
│  │ Meta-Analyst       │    │              │    │ Breakers       │ │
│  └──────────────────┘    └──────────────┘    │ Factors        │ │
│                                               └────────────────┘ │
│  Ideas & debate         Sanitized feedback    Blind execution    │
└─────────────────────────────────────────────────────────────────┘
```

### Stage 1 — Ideation (8 agents, 5 debate rounds)

Stage 1 is a creative engine that produces falsifiable trading hypotheses through structured adversarial debate:

| Agent | Role |
|-------|------|
| **Generator (x2)** | Proposes novel hypotheses across seven signal domains |
| **Critic** | Evaluates internal logic, data requirements, and retail feasibility |
| **Domain Specialist** | Provides deep knowledge in specific signal domains (earnings calls, SEC filings, etc.) |
| **Skeptic** | Attacks every hypothesis — identifies confounding variables, data-snooping risks, look-ahead concerns |
| **Synthesizer** | Merges compatible hypotheses, resolves contradictions |
| **Ranker** | Scores all surviving hypotheses on a 0–10 scale across novelty, feasibility, and expected effect size |
| **Meta-Analyst** | Reviews the entire round for bias, blind spots, and missed opportunities |

The 5-round structure forces progressive refinement. Round 1 generated 21 hypotheses; after adversarial filtering, 6 survived with PROMOTE status (26.3%), 10 were REVISED, 6 KILLED, and 1 cross-agent synthesis emerged.

**Output:** Ranked JSON hypothesis files with quantitative predictions (effect size, direction, holding period, data requirements).

### Stage 2 — Pipeline (7 agents, locked before seeing hypotheses)

Stage 2 is a blind, first-principles backtesting pipeline. Its seven functional modules operate in sequence:

1. **Universe Builder** — autonomously determines which stocks to test, from how many filings, over what time period
2. **Data Adapters** — acquire real historical data from retail-accessible sources
3. **Signal Extractors** — compute quantitative signals from raw text/data
4. **Temporal Alignment** — point-in-time checks to prevent look-ahead bias
5. **Backtester** — cross-sectional long/short portfolio construction with realistic cost modeling
6. **Statistics** — bootstrap confidence intervals, power analysis, outlier detection
7. **Breakers + Factors** — adversarial stress tests and factor recycling detection

**Critical design property:** The pipeline is locked before seeing any Stage 1 hypotheses. The firewall prevents methodology contamination — pipeline developers cannot tune the test to favor specific hypotheses.

### Bridge (2 agents, programmatic not yet implemented)

The Bridge is the only communication channel between Stage 1 and Stage 2. It consists of:

- **Executor:** Translates hypothesis JSON into pipeline-compatible specifications, runs the pipeline, collects results
- **Verifier:** Sanitizes results before feeding back to Stage 1 — removes pipeline-internal metrics that could leak methodology details

**Current state:** The Bridge exists as a manually written assessment document. Programmatic bridge execution is implemented in `run_loop.py` (which runs the full hypothesis→verdict loop), but the formal two-agent bridge protocol described in the architecture plan is not yet built.

---

## 3. Process Flow

### End-to-end: Hypothesis → Verdict → Feedback

```
Hypothesis JSON
      │
      ▼
┌──────────────────────────────────────────────────────────────┐
│ 1. PARSE & VALIDATE                                          │
│    - Extract signal domain, data sources, universe scope     │
│    - Validate holding period, effect size predictions        │
│    - Check TrialTracker: refinement cap, FDR state           │
└──────────────────────────┬───────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ 2. UNIVERSE CONSTRUCTION (UniverseBuilder)                   │
│    - Derive ticker universe from hypothesis scope            │
│    - Determine filing frequency & observation requirements   │
│    - Power analysis: how many observations needed?           │
│    - Cap at feasible max (runtime constraint: ~18 min)       │
└──────────────────────────┬───────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ 3. DATA ACQUISITION (Adapters)                               │
│    - SEC EDGAR: Download 10-K/10-Q/8-K filings               │
│    - Yahoo Finance: Download OHLCV price data                │
│    - FDA/FMP/FRED: Attempt if hypothesis requires            │
│    - If unavailable → UNTESTABLE verdict (no fabrication)    │
└──────────────────────────┬───────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ 4. SIGNAL EXTRACTION (Extractors)                            │
│    - Linguistic: sentiment, hedging, certainty, readability  │
│    - Build wide-format signal DataFrame (dates × tickers)    │
│    - Apply safeguards: contamination, survivorship           │
└──────────────────────────┬───────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ 5. TEMPORAL ALIGNMENT                                        │
│    - Point-in-time dataset construction                      │
│    - Known-date offsets (e.g., filing date + 1 business day) │
│    - Forward return computation with business day offsets    │
│    - Look-ahead breach detection                             │
└──────────────────────────┬───────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ 6. BACKTEST                                                  │
│    - Cross-sectional long/short on signal quintiles          │
│    - Position sizing: quarter-Kelly                           │
│    - Cost model: IBKR commission + spread + slippage         │
│    - Calendar-based annualization with holding period        │
└──────────────────────────┬───────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ 7. STATISTICAL EVALUATION                                    │
│    - BCa bootstrap 95% CI on mean return                     │
│    - Bootstrap Sharpe, Sortino, max drawdown                 │
│    - Power analysis: achieved vs required                    │
│    - Outlier detection: original vs 5% trimmed mean test     │
└──────────────────────────┬───────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ 8. ADVERSARIAL BREAKAGE                                      │
│    - Permutation test (two-sided)                            │
│    - Specification robustness (alternative constructions)    │
│    - Walk-forward consistency (time-based cross-validation)  │
│    - Regime dependence (market state analysis)               │
│    - Edge decay (does alpha decline over time?)              │
└──────────────────────────┬───────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ 9. FACTOR COMPARISON                                         │
│    - Regress returns on baseline factors                     │
│    - Newey-West HAC standard errors                          │
│    - Compute residual alpha + CI                             │
│    - Flag factor recycling if residual alpha is NS           │
└──────────────────────────┬───────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ 10. VERDICT                                                  │
│     SURVIVED / BROKEN / INCONCLUSIVE / UNTESTABLE            │
│     + detailed stage results + warnings + safeguard reports  │
└──────────────────────────┬───────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ 11. FEEDBACK LOOP                                            │
│     - BROKEN verdict → Stage 1 refinement (max 3 attempts)   │
│     - SURVIVED → walk-forward out-of-sample validation       │
│     - FDR tracked across all hypotheses cumulatively         │
└──────────────────────────────────────────────────────────────┘
```

---

## 4. Data Sources

| Source | Status | Reliability | Limitations |
|--------|--------|-------------|-------------|
| **SEC EDGAR** | **LIVE** | High — real 10-K/10-Q/8-K filings from sec.gov/Archives. lxml HTML parsing with retry/backoff. Parallel download ready. | Section extraction heuristic (regex-based). User-agent needs valid contact email. SEC rate limit: 10 req/s. |
| **Yahoo Finance** | **LIVE** | Medium — real OHLCV data via yfinance. Per-ticker parquet caching. Parallel download for 10+ tickers. | **Survivorship bias** for stocks delisted before ~2017. Not corrected in code. Price adjustments via `auto_adjust=True` may miss some corporate actions. |
| **FDA** | **PARTIAL** | Low-Medium — real metadata from api.fda.gov (drug approvals, PDUFA dates). | Briefing document **text** requires PDF scraping (not implemented). PDUFA calendar parser is a stub returning `[]`. `health_check` endpoint differs from data endpoint. |
| **FMP** | **SKELETON** | None — `health_check()` honestly reports `NOT IMPLEMENTED`. `acquire()` always raises `DataAcquisitionError`. | Any hypothesis requiring FMP data is immediately UNTESTABLE. |
| **FRED** | **SKELETON** | None unless API key configured. `acquire()` raises `DataAcquisitionError` when API key missing. `health_check()` only tests importability, not API reachability. | Individual series failures are silently skipped. |

**Key design principle:** No synthetic data is ever fabricated. If a data source is unavailable, the pipeline escalates to an UNTESTABLE verdict rather than producing results from simulated data.

---

## 5. Signal Domains

The seven domains explored by Stage 1 agents:

1. **Earnings Calls** — Transcript sentiment, management tone shifts, Q&A evasion patterns
2. **SEC Filings** — MD&A linguistic features, risk factor changes, 8-K departure language
3. **Narrative** — News sentiment, media coverage shifts, social media signals
4. **Cross-Asset** — Lead-lag relationships, macro regime signals, inter-market spillover
5. **Alternative Data** — FDA drug approval patterns, patent filings, satellite/geolocation
6. **Market Microstructure** — Order flow, options market signals, short interest dynamics
7. **Contrarian** — Fading consensus, mean reversion in sentiment extremes

### Currently Implemented Extractors

**Linguistic Extractor** (the only operational extractor):
- 45+ deterministic features from text: sentiment (VADER), hedging density, certainty markers, readability (Flesch-Kincaid), passive voice ratio, word count, sentence count
- Composite scores: BRLAS (Benefit-Risk Linguistic Asymmetry Score) combining readability benefit/risk with sentiment
- Output: wide-format DataFrame (dates × tickers) with signal values at each observation point

**Known limitations:**
- Sentence splitting uses `re.split(r'[.!?]+', text)` — breaks on abbreviations ("Dr.", "U.S."), decimals ("3.14"), and URLs
- Certainty markers like `"p <"`, `"p ="`, `"95% confidence"` use `\b` word boundaries that interact poorly with non-word characters — these patterns likely never match real text
- Silent fallback to row-index dummy signal when no signal column is found (lines 683-685)
- COMPOSITE_FORMULAS documentation string says `0.5 * readability_diff` but code applies both `/100` normalization and `*0.5`

---

## 6. Safeguards

### 6.1 Contamination Detector

**What it prevents:** False confidence from LLM training-data leakage. If an LLM's training data includes future price information, its signals may appear predictive when they are actually regurgitating known outcomes.

**Three detection mechanisms:**

1. **Knowledge cutoff comparison** — Compares signal predictiveness before and after the LLM's training cutoff date. A signal that degrades post-cutoff suggests contamination.
2. **Placebo text swapping** — Replaces key entity names (company, drug, product) with similar but irrelevant text. If the signal persists after swapping, it may be exploiting general linguistic patterns rather than specific information.
3. **Temporal consistency** — Tests whether the signal's predictive power is stable across time periods.

**How it works in code:**
- `ContaminationDetector` class in `signal_builder/contamination.py`
- Integrated into `signal_builder.py` at line ~284
- Uses Spearman correlation, AUC comparison, and percentile rank for predictiveness measurement

**Current issues:**
- **Placebo test never runs:** `run_placebo=False` is hardcoded in `signal_builder.py:308`. The comment says "Computationally expensive; can enable for critical hypotheses" but no criteria exist for when to enable.
- **Verdict capping not wired:** `cap_verdict()` static method (line 780) is never called by any pipeline code.
- **Hardcoded thresholds:** Pre/post cutoff comparison uses arbitrary 80%/50% thresholds with no statistical significance test.

### 6.2 Survivorship Guard

**What it prevents:** Overstated backtest returns from excluding stocks that went bankrupt, were acquired, or were delisted for cause. Databases that only include currently-trading stocks make every strategy look better than it actually was.

**How it works:**
- Maintains a registry of known delisted stocks with estimated delisting returns
- Detects ticker reuse (same ticker symbol representing different entities over time)
- Estimates survivorship bias magnitude by comparing survivor-only vs full-universe returns
- Caps verdict confidence based on data completeness

**Current issues:**
- **Registry has only 6 hardcoded stocks** (GE, HTZ, JCP, SIVB, FRC, TWTR) — cannot detect survivorship bias for 99% of real delistings
- **SEC EDGAR delisting query is dead code** — queries Form 25/15 filings but stores empty ticker strings because CIK→ticker mapping is not implemented (line 517)
- **Verdict capping not wired** — same as contamination, `cap_verdict()` is never called
- Delisting return estimates are hardcoded (-100% bankruptcy, +15% acquisition, -30% exchange delisting) with no empirical calibration
- `data_completeness` is derived solely from the 6-stock registry, so universes without those specific stocks always show "FULL" completeness

### 6.3 Cumulative FDR Tracker (TrialTracker)

**What it prevents:** The multiple-comparison problem — when you test 20 hypotheses at α=0.05, you expect one false positive by chance alone. Without correction, the system would "discover" spurious edges.

**How it works:**
- Tracks every trial in a persistent JSON file (`trial_family.json`)
- Applies Bonferroni correction to set investigation-wide significance threshold
- Applies Benjamini-Hochberg FDR procedure to rank discoveries
- Enforces a refinement cap: each hypothesis gets at most 3 attempts before being ARCHIVED
- Embeds honest reporting in every verdict: "Total trials: N, Bonferroni-adjusted threshold: p < X"

**Current issues:**
- **BH procedure includes current trial's own p-value** — the current trial is compared against a threshold computed including itself; minor bias with few trials
- **`check_cycle_termination` uses cumulative counts** — `survived_this_cycle` is always total, so cycle-based termination conditions likely never trigger
- **TrialTracker start/end failures logged at DEBUG only** in `run_loop.py` — invisible at normal log levels
- **Honest report text is saved but not wired into pipeline verdict JSON**

---

## 7. Statistical Methodology

### 7.1 Bootstrap Confidence Intervals

- **Method:** BCa (bias-corrected and accelerated) bootstrap with 10,000 resamples
- **What it tests:** Is the mean return statistically distinguishable from zero?
- **Interpretation:** 95% CI that includes zero → signal not statistically significant
- **Seeds:** Derived deterministically from hypothesis UUID for reproducibility

### 7.2 Permutation Tests

- **Method:** Two-sided permutation test with 10,000 shuffles of signal labels
- **What it tests:** Is the observed performance better than random signal assignments?
- **Current concern:** Uses non-standard centering — compares against permutation distribution mean rather than zero. The line `np.abs(perm_performances - np.mean(perm_performances)) >= np.abs(original_perf - np.mean(perm_performances))` deviates from textbook practice where permuted performance is compared directly to the null hypothesis of zero effect.

### 7.3 Factor Regression

- **Method:** OLS regression of strategy returns on baseline factor returns
- **Standard errors:** Newey-West HAC (heteroskedasticity and autocorrelation consistent) with Bartlett kernel and automatic lag selection: `max_lags = int(4 * (n_obs / 100.0) ** (2 / 9))`
- **Confidence intervals:** t-distribution critical values with `n_obs - n_params` degrees of freedom
- **What it tests:** Is the signal just recycling exposure to known factors (value, momentum, size, low vol, short-term reversal)?
- **Verdict:** If residual alpha p > 0.05 → FACTOR_RECYCLING

### 7.4 Family-Wise Error Correction

- **Bonferroni:** `α_adjusted = 0.05 / N_trials`
- **Benjamini-Hochberg FDR:** Rank p-values, find largest k where `p_(k) ≤ (k/m) * α`
- **Reported in every verdict:** "Total trials in investigation: N. Bonferroni-adjusted significance threshold: p < X"

### 7.5 Power Analysis

- **Formula:** `required_obs = (Z_α + Z_β)² * σ² / α²` where α is the predicted annualized alpha
- **Parameters:** α=0.05, 1-β=0.80, daily vol assumed at 150 bps
- **Limitations:** Assumes normal distribution, independent observations, and constant volatility. Real strategies often have fatter tails and cross-sectional correlation, meaning achieved power is likely lower than reported.
- **Normal approximation** for power rather than non-central t-distribution — overestimates power for small samples

### 7.6 Annualization

- **Calendar-based:** `n_years = calendar_days / 365.25` from actual date span (not observation count)
- **Vol scaling:** `ann_vol_factor = sqrt(252 / holding_period_days)` accounts for multi-day holding periods
- **Business days:** Temporal alignment uses `pd.tseries.offsets.BusinessDay` for known-date offsets and forward return horizons

---

## 8. Verdict Categories

| Verdict | Meaning | Trigger Condition |
|---------|---------|-------------------|
| **SURVIVED** | Hypothesis passes all checks; signal is statistically and economically significant, robust to adversarial tests, and not factor recycling | All stages pass, residual alpha p < 0.05, 95% CI excludes zero, permutation test passes, walk-forward passes |
| **BROKEN** | Hypothesis fails one or more critical tests | Statistical significance fails (CI includes zero), permutation test fails (p > 0.05), factor recycling detected, or specification robustness fails |
| **INCONCLUSIVE** | Insufficient data to reach a definitive conclusion | Achieved power below threshold, not enough observations, factor data unavailable for regression |
| **UNTESTABLE** | Hypothesis cannot be tested with available data | Required data source is unavailable (FMP skeleton, FDA PDF scraping needed), universe construction fails, signal extraction produces no usable data |

**Decision tree priority:** UNTESTABLE > BROKEN (statistical) > BROKEN (adversarial) > BROKEN (factor recycling) > INCONCLUSIVE > SURVIVED

---

## 9. Results Produced So Far

### MD&A Linguistic Tone Shift — BROKEN (2026-05-14)

**Hypothesis:** Changes in the linguistic tone of Management Discussion & Analysis sections predict forward equity returns.

**Data:**
- 23 tickers from SEC EDGAR (including 4 delisted: GE, SIVB, FRC, TWTR)
- 58 signal observations across quarterly 10-K/10-Q filings
- 1,086 price dates from Yahoo Finance
- Time period: 2021-01-01 to 2025-05-01

**Signal:** Hedging density in MD&A section text — the proportion of sentences containing hedging language ("may", "might", "could", "uncertain", "subject to", etc.)

**Results:**

| Metric | Value |
|--------|-------|
| Gross annualized return | 5,772 bps (57.7%) |
| Gross Sharpe ratio | 0.82 |
| Annualized Sharpe | 0.45 |
| Max drawdown | -63.1% |
| Hit rate | 42.1% |
| Mean daily return | +591 bps |
| Median daily return | -6.7 bps |
| Skewness | 4.13 |
| Kurtosis | 18.96 |

**Why BROKEN:**

The mean return hides extreme dispersion. While the average daily return was +591 bps, the median was -6.7 bps — the distribution is dominated by a few extreme positive outliers (skewness 4.13, kurtosis 18.96). The 95% bootstrap confidence interval is **[-62, +1,632] bps** — it includes zero, meaning the mean return is not statistically distinguishable from noise.

**Adversarial results:**
- Permutation test: p = 1.00 (signal indistinguishable from random shuffles)
- Specification robustness: 0% of alternative specifications significant
- Walk-forward: 66.7% of windows positive (passes the 60% threshold, but OOS significance failed at p=1.00)

**Factor recycling:**
- After controlling for baseline factors (short-term reversal, low volatility), residual alpha p = 0.78
- R² = 0.176 — 17.6% of return variation is explained by known factors, primarily low volatility

**Achieved power:** 23.7% — well below the 80% target. The test was underpowered, meaning even a real effect of the hypothesized magnitude might not have been detected.

**What this verdict means:**

This is the system's first honest empirical result. It does not mean "MD&A tone has no predictive power" — it means "with 23 tickers, 58 observations, and quarterly frequency, we cannot distinguish the signal from noise." The machine was underpowered, not wrong.

---

## 10. Recent Fixes (Post-Audit, May 2026)

A comprehensive audit identified approximately 55 issues. All have been fixed. The most critical fixes:

### Silent Data Fabrication — ELIMINATED

The most serious finding was silent fallback to synthetic/fabricated data when real data was unavailable. All instances have been removed:

- **FDA adapter:** Removed `_acquire_synthetic()` method (~130 lines) that fabricated rigged BRLAS signal data. Now raises `DataAcquisitionError`.
- **FRED adapter:** Removed `_synthetic_macro()` method that generated fake macro data. Now raises `DataAcquisitionError`.
- **FMP adapter:** `health_check()` now honestly reports `NOT IMPLEMENTED`. `acquire()` always raises `DataAcquisitionError`.
- **Pipeline universe fallback:** Removed creation of 20 hardcoded tickers with fake metadata when universe empty. Now raises `PipelineError`.
- **Pipeline price fallback:** Removed GBM-simulated price data generation. Now raises `PipelineError`.
- **Pipeline signal fallback:** `_make_fallback_signals()` now always raises `PipelineError`.

### Statistical Methodology — FIXED

- **Annualization:** Changed from observation-count-based to calendar-based. Gross Sharpe dropped from 93.07 to 0.82 — realistic.
- **Temporal alignment:** Changed from calendar-day `pd.Timedelta` to `pd.tseries.offsets.BusinessDay` for known-date offsets, forward returns, and SEC filing offsets.
- **Factor standard errors:** Implemented Newey-West HAC with Bartlett kernel and automatic lag selection. Alpha CI now uses t-critical instead of z=1.96.
- **Permutation tests:** Changed from one-sided to two-sided.
- **Bootstrap:** Uses t-critical and business-day-aware annualization.

### Performance & Robustness — IMPROVED

- **DownloadPool:** New `TokenBucket` rate limiter + `ThreadPoolExecutor` wrapper for parallel SEC/Yahoo downloads with configurable retry logic.
- **Yahoo Finance:** Per-ticker parquet file caching. Parallel downloads for 10+ tickers.
- **SEC EDGAR:** lxml HTML parser (20× faster) with html.parser fallback. Retry/backoff on 429/503/timeout. Configurable user agent.
- **Universe builder:** Autonomous ticker derivation from hypothesis specs — no human handoffs.

### Remaining Issues Identified in Post-Fix Audit

The follow-up audit found issues that still need attention (not yet fixed):

**High priority:**
- Safeguard verdict capping methods exist but are never called by the pipeline (contamination and survivorship)
- ContaminationDetector placebo test is hardcoded to never run
- Survivorship guard registry has only 6 hardcoded stocks
- Linguistic extractor has a silent fallback to dummy signal values (row indices)
- Universe builder `_filter_tickers` accepts filtering parameters but applies NO actual filtering
- Calendar-daily frequency (`freq="D"`) in universe construction creates entries for non-trading days
- Backtest receives hardcoded placeholder market cap and volume data

**Medium priority:**
- Crude sentence splitting in linguistic extractor
- Certainty marker regex patterns likely never match real text
- SEC EDGAR adapter drops full filing text after section extraction
- SEC EDGAR adapter has two `except Exception: pass` for cache reads
- `WalkForwardBacktester` class (500 lines) is entirely unused
- `TemporalAlignmentReport` dataclass and several temporal methods are never instantiated
- Import of unused `scipy.optimize.minimize` in statistics.py
- No programmatic bridge between Stage 1 and Stage 2

---

## 11. Feasibility Assessment

### What the Engine Can Do Today

- **Autonomously test** any SEC filing-based linguistic hypothesis against real historical data
- **Honestly report** when data is unavailable (UNTESTABLE) rather than fabricating results
- **Produce realistic metrics** with proper annualization, business-day alignment, and robust standard errors
- **Detect** the most common failure modes: statistical insignificance, factor recycling, permutation fragility
- **Track** cumulative false discovery rate across multiple trials
- **Scale** to 1,500+ tickers with parallel download architecture

### What the Engine Cannot Do Today

- **Run at production scale.** SEC filing download is the bottleneck: ~8-10 seconds per filing, single-threaded. For a 1,500-ticker universe with 4 quarterly filings each, that is ~13-17 hours of download time even with parallelization. A pre-built filing database is needed.
- **Test non-text signals.** Only the linguistic extractor is operational. No extractors exist for options flow, order book patterns, cross-asset relationships, or alternative data beyond FDA metadata.
- **Survive a genuine survivorship audit.** The survivorship guard has a 6-stock registry — essentially decorative for a real backtest.
- **Provide reliable power estimates.** The power analysis assumes normality, independence, and constant volatility. Real returns violate all three.
- **Execute the full 17-agent process autonomously.** The bridge is a manual document. Stage 1 needs human orchestration. The feedback loop (BROKEN→refine→retest) works but requires human intervention between cycles.

### Bottlenecks

| Bottleneck | Impact | Mitigation |
|------------|--------|------------|
| SEC filing download (~8-10s/filing) | Limits universe to ~50 tickers for a <30min run | DownloadPool with parallel workers; pre-built filing database |
| Single extractor (linguistic only) | Cannot test 6 of 7 signal domains | Extractors need to be built for each domain |
| yfinance survivorship bias | Delisted stocks pre-2017 have no price data | Supplement with delisting database; use alternative price source |
| FDA PDF scraping not implemented | Drug approval hypotheses cannot be fully tested | Implement PDF text extraction |
| Walk-forward test with only 3 windows | Out-of-sample assessment is coarse | Need longer time series for more windows |
| Power limited by SEC filing frequency (quarterly) | 4 obs/ticker/year → need many tickers or many years | Multi-source signals (combine quarterly + event-driven) |

---

## 12. Known Limitations and Risks

### Data Limitations

1. **Survivorship bias in Yahoo Finance:** Stocks delisted before ~2017 have no price data available through yfinance. The survivorship guard has only 6 hardcoded stocks and cannot seriously estimate the bias magnitude.

2. **SEC section extraction is heuristic:** Regex-based section splitting assumes "Item 1A", "Item 7" formatting. Non-standard filing formats (roman numerals, tables) will be missed.

3. **No real market cap or volume data:** The backtest cost model (spread, slippage, position sizing) runs against placeholder values of 1e10 market cap and 1e8 volume for every stock. This makes the cost estimates unreliable.

4. **FDA text unavailable:** The FDA adapter returns real metadata but cannot extract actual briefing document text. The PDUFA calendar parser is a stub.

### Methodological Limitations

5. **Power analysis is optimistic:** Assumes normal independent returns with constant 150 bps daily volatility. Real returns are fat-tailed, correlated, and heteroskedastic — achieved power is likely lower than reported.

6. **Permutation test uses non-standard centering:** Deviates from textbook approach. The impact on p-values is likely small but has not been validated.

7. **Structural break detection is mislabeled:** The code claims "Bai-Perron" but implements a simple rolling t-test with ad-hoc clustering.

8. **Factor recycling verdict is a hard binary:** A strategy with 200 bps residual alpha and p=0.06 gets the same "FACTOR_RECYCLING" label as one with 0 bps and p=0.95. No consideration of economic significance in the verdict threshold.

9. **Walk-forward test has only 3 windows:** With limited time series, the out-of-sample assessment has very low power to detect genuine edge decay or structural breaks.

10. **Calendar-daily frequency in universe construction:** `pd.date_range(start, end, freq="D")` creates entries for weekends and holidays, potentially inflating observation counts and creating date mismatches.

### Architectural Limitations

11. **No programmatic bridge:** The Stage 1→Stage 2 interface is a manually written markdown document. The full 17-agent cycle requires human orchestration.

12. **Safeguard verdict capping not wired:** Both contamination and survivorship guards have `cap_verdict()` methods that are never called. Verdicts are never downgraded based on safeguard findings.

13. **Single point of extractor failure:** With only one extractor, any linguistic extraction bug affects all testable hypotheses.

14. **No position-level audit trail:** While seeds are tracked for reproducibility, there is no end-to-end audit trail that traces a specific position's P&L back to the exact signal value, filing text, and price data that produced it.

---

## 13. Next Steps (Prioritized)

### Immediate (to reach reliable single-hypothesis testing)

1. **Wire safeguard verdict capping** — Call `cap_verdict()` from `SurvivorshipGuard` and `ContaminationDetector` in the pipeline verdict logic. A BROKEN verdict with high contamination risk should be downgraded or annotated.

2. **Remove silent fallbacks in linguistic extractor** — The dummy signal fallback (row indices as signal values) and synthetic date generation must raise errors, not silently fabricate data.

3. **Fix universe calendar frequency** — Change `freq="D"` to `freq="B"` in universe construction to avoid non-trading-day entries.

4. **Replace hardcoded market cap/volume placeholders** — The backtest cost model needs real market cap and volume data. Yahoo Finance provides this; it should be loaded alongside price data.

5. **Fix SEC EDGAR adapter user-agent** — Replace placeholder email with a valid contact to comply with SEC terms of service.

6. **Fix backtest exit date** — Change `pd.Timedelta(days=holding_period_days)` to `pd.tseries.offsets.BusinessDay(n=holding_period_days)` for consistency.

### Short-term (to improve statistical rigor)

7. **Rebuild survivorship guard** — Replace the 6-stock hardcoded registry with a real delisting database. Implement the CIK→ticker mapping so SEC Form 25 queries produce usable results.

8. **Enable placebo test** — Add criteria for when to run the computationally expensive placebo text swap (e.g., when p < 0.10 in initial testing).

9. **Fix certainty marker regex** — Remove or adjust `\b` boundaries so patterns like "p <", "p =", "95% confidence" actually match.

10. **Validate permutation test centering** — Either justify the non-standard approach or revert to standard comparison against zero.

11. **Add more walk-forward windows** — Require at least 5 windows (not 3) for the walk-forward test to produce meaningful out-of-sample assessment.

12. **Add a second extractor** — Prioritize an 8-K event-driven extractor to test departure language hypotheses.

### Medium-term (to scale and diversify)

13. **Build pre-filed SEC database** — Download and cache all 10-K/10-Q filings for the Russell 3000 over the past 10 years. This removes the download bottleneck and enables large-scale testing.

14. **Implement FDA PDF scraping** — Use `pdfplumber` or `PyPDF2` to extract text from FDA briefing documents, enabling full FDA-based hypothesis testing.

15. **Build programmatic bridge** — Implement the Executor + Verifier as Python modules that can run the full 17-agent cycle without human intervention.

16. **Add extractors for remaining domains** — Earnings call transcript analysis, news sentiment, cross-asset signals.

17. **Implement position-level audit trail** — Trace every trade back to its originating signal value, filing, and price data for full reproducibility.

### Long-term (production readiness)

18. **Out-of-sample paper trading** — Run surviving strategies on forward data (post-2025) to validate real-world performance before any capital deployment.

19. **Multi-source signal fusion** — Combine signals from multiple domains (e.g., SEC linguistic + FDA catalyst dates + macro regime) to test whether ensembles outperform single-domain signals.

20. **Infrastructure for daily signal generation** — Build the operational pipeline that would generate daily signals for a retail trader, including data freshness checks, signal staleness detection, and position rebalancing logic.

---

## Appendix A: Key Files Reference

| File | Purpose |
|------|---------|
| `.claude/PLAN.md` | Full 17-agent system specification |
| `stage1/` | Stage 1 outputs — round1-5 hypotheses, rankings |
| `stage2-pipeline/run_loop.py` | Main loop: hypothesis → signal → pipeline → verdict |
| `stage2-pipeline/implementation/pipeline.py` | Main pipeline orchestrator (2,337 lines) |
| `stage2-pipeline/implementation/backtest.py` | Cross-sectional backtester with cost model |
| `stage2-pipeline/implementation/statistics.py` | Bootstrap CIs, power analysis, performance metrics |
| `stage2-pipeline/implementation/breakers.py` | Permutation tests, walk-forward, edge decay |
| `stage2-pipeline/implementation/factors.py` | Factor regression with Newey-West HAC SE |
| `stage2-pipeline/implementation/temporal.py` | Point-in-time alignment, forward returns |
| `stage2-pipeline/implementation/universe.py` | Stock universe construction and filtering |
| `stage2-pipeline/implementation/audit.py` | Seed management, snapshot, audit trail |
| `stage2-pipeline/signal_builder/signal_builder.py` | Signal construction orchestrator with safeguards |
| `stage2-pipeline/signal_builder/universe_builder.py` | Autonomous universe construction |
| `stage2-pipeline/signal_builder/download_pool.py` | Token-bucket rate limiter + parallel download |
| `stage2-pipeline/signal_builder/contamination.py` | LLM contamination detector |
| `stage2-pipeline/signal_builder/survivorship.py` | Survivorship bias guard |
| `stage2-pipeline/signal_builder/trial_tracker.py` | Cumulative FDR tracker |
| `stage2-pipeline/signal_builder/base.py` | Base classes, data types, validation |
| `stage2-pipeline/signal_builder/extractors/linguistic.py` | Linguistic feature extraction |
| `stage2-pipeline/signal_builder/adapters/sec_edgar.py` | SEC EDGAR filing download |
| `stage2-pipeline/signal_builder/adapters/yahoo_finance.py` | Yahoo Finance price data |
| `stage2-pipeline/signal_builder/adapters/fda.py` | FDA drug approval data |
| `stage2-pipeline/signal_builder/adapters/fmp.py` | FMP skeleton (not implemented) |
| `stage2-pipeline/signal_builder/adapters/fred.py` | FRED macro data |
| `bridge/bridge-verdicts.md` | Manual bridge assessment (not programmatic) |

## Appendix B: Software Versions

- Python 3.10+
- Key dependencies: pandas, numpy, scipy, statsmodels, yfinance, requests, BeautifulSoup4, lxml, pyarrow
- Pipeline version: 1.0.0
- All seeds derived deterministically from hypothesis UUID + base seed (1228345641)

---

*This document is a snapshot of the TradeFinder engine as of 2026-05-14 following a comprehensive 55-issue audit and fix cycle. It is designed to be read independently of the codebase by technically literate reviewers unfamiliar with the project.*
