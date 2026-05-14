# Stage 2 Pipeline Specification — Universal Hypothesis Testing Framework

## Version: 1.0.0 (LOCKED)
## Status: PRE-DEPLOYMENT — NO FURTHER CHANGES PERMITTED

---

## 0. Design Philosophy

This pipeline is the gatekeeper. It exists to distinguish genuine, executable trading edges from statistical artifacts, data errors, overfitted patterns, and factor recycling. The pipeline's job is to **eliminate bad ideas cheaply**. A high BROKEN rate is success — it means the pipeline is working.

### Core Principles

1. **Honest empiricism above all.** Every test must be pre-specified. No p-hacking. No specification searching. No "let's try this transformation and see if it helps."
2. **Adversarial by design.** Every result is attacked from multiple angles before it is trusted. The Statistical Breaker and Data Breaker have veto power.
3. **Reproducible and auditable.** Every verdict must be traceable to raw data and exact code. Deterministic seeds for all random operations.
4. **Retail-realistic.** All data sources are free or low-cost. Transaction costs are realistic for retail traders. Execution is feasible at standard brokerages.
5. **Universal.** The pipeline knows nothing about the hypotheses it will test. It works for any signal type (text, numerical, categorical, composite), any universe, any holding period.
6. **Locked.** Once built, the methodology does not change. No post-hoc adjustments after seeing hypotheses.

---

## 1. Hypothesis Input Specification

Every hypothesis submitted to the pipeline MUST conform to this interface. The pipeline rejects malformed specifications before running any tests.

### 1.1 Required Fields

```python
@dataclass
class HypothesisSpec:
    """Complete specification of a hypothesis to test."""

    # Identity
    name: str                           # Short, descriptive name
    uuid: str                           # Unique identifier (assigned by Bridge)
    source_agent: str                   # Which Stage 1 agent created this
    submission_number: int              # 1, 2, or 3 (max 3 refinement attempts)

    # Mechanism (documentation, not tested)
    mechanism: str                      # Causal claim: "X predicts Y because Z"
    llm_advantage: str                  # What does the LLM enable that traditional methods cannot?
    why_underweighted: str              # Why isn't this already priced in?

    # Core specification
    universe: UniverseSpec              # Which stocks to consider
    signal: SignalSpec                  # How to compute the signal
    holding_period_days: int            # How long to hold positions
    time_period: TimePeriodSpec         # Start/end dates for analysis

    # Position sizing
    position_sizing: PositionSizingSpec # How to size positions

    # Economic significance threshold
    minimum_effect_size: MinimumEffectSpec  # Below this, BROKEN regardless of p-value

    # Data requirements
    data_sources: List[DataSourceSpec]  # Exactly what data, from where, at what frequency

    # Falsifiable prediction
    falsifiable_prediction: str         # "If this edge is real, we should observe [X]"

    # Self-assessment
    self_assessed_confidence: str       # LOW / MEDIUM / HIGH
    biggest_weakness: str              # What the creator is most worried about
```

### 1.2 Universe Specification

```python
@dataclass
class UniverseSpec:
    """Specification of the stock universe."""
    universe_type: str                  # 'sp500' | 'sp1500' | 'russell3000' | 'custom'
    custom_tickers: Optional[List[str]] # Required if universe_type == 'custom'
    custom_filter: Optional[str]        # Python expression used as a filter, e.g., "market_cap > 1e9"
    min_price: float = 1.0             # Minimum price filter (penny stock exclusion)
    min_daily_volume: int = 0          # Minimum daily dollar volume
    exchanges: List[str] = field(      # Allowed exchanges
        default_factory=lambda: ['NYSE', 'NASDAQ', 'NYSEARCA', 'NYSEAMERICAN'])
    include_delisted: bool = True      # MUST be True for honest backtesting
```

### 1.3 Signal Specification

```python
@dataclass
class SignalSpec:
    """Specification of how to compute the signal."""
    signal_type: str                    # 'numeric' | 'categorical' | 'composite'
    signal_function: Callable           # Function that takes (date, universe) -> pd.Series of signals
    signal_name: str                    # Column name for the signal
    higher_is_better: bool = True      # Whether higher signal values predict higher returns
    llm_model_used: Optional[str] = None  # Which LLM model, if any (e.g., 'llama-3-8b')
    llm_temperature: Optional[float] = None  # Temperature setting for LLM
    llm_seed: Optional[int] = None     # Random seed for LLM (if applicable)
    llm_is_deterministic: bool = False # Whether LLM output is expected to be deterministic
```

### 1.4 Time Period Specification

```python
@dataclass
class TimePeriodSpec:
    """Specification of the analysis time period."""
    start_date: str                     # 'YYYY-MM-DD'
    end_date: str                       # 'YYYY-MM-DD'
    oos_start_date: Optional[str] = None  # Out-of-sample period start. If None, use final 30%
    min_training_days: int = 252        # Minimum trading days required
    frequency: str = 'daily'            # 'daily' | 'weekly' | 'monthly'
```

### 1.5 Position Sizing Specification

```python
@dataclass
class PositionSizingSpec:
    """Specification of position sizing methodology."""
    method: str                         # 'equal_weight' | 'signal_proportional' | 'risk_parity' | 'kelly'
    max_position_pct: float = 0.05      # Maximum position as fraction of portfolio
    max_positions: int = 50             # Maximum number of simultaneous positions
    max_sector_pct: float = 0.30        # Maximum exposure to any one sector
    capital: float = 100000.0           # Assumed capital in USD
    rebalance_frequency: str = 'daily'  # 'daily' | 'weekly' | 'monthly'
```

### 1.6 Minimum Effect Size

```python
@dataclass
class MinimumEffectSpec:
    """Minimum economically meaningful effect size."""
    annualized_alpha_bps: float = 300   # Minimum annualized alpha in basis points after costs
    sharpe_ratio: float = 0.3           # Minimum Sharpe ratio after costs
    information_coefficient: float = 0.03  # Minimum IC
    hit_rate: float = 0.51              # Minimum directional accuracy
    max_drawdown_pct: float = 25.0      # Maximum acceptable drawdown
```

### 1.7 Data Source Specification

```python
@dataclass
class DataSourceSpec:
    """Specification of a required data source."""
    source_type: str              # 'price' | 'fundamental' | 'sec_filing' | 'transcript' |
                                  # 'alternative' | 'sentiment' | 'custom'
    provider: str                 # 'yahoo' | 'fmp' | 'sec_edgar' | 'finnhub' | 'polygon' | 'custom'
    frequency: str                # 'daily' | 'quarterly' | 'annual' | 'realtime' | 'as_filed'
    fields: List[str]             # Required fields
    start_date: str               # Earliest data needed
    end_date: str                 # Latest data needed
    known_biases: List[str]       # MUST document known biases of this source
    api_tier: str                 # 'free' | 'paid_low_cost' | 'paid_premium'
    monthly_cost_usd: float       # Monthly subscription cost if paid
```

---

## 2. Requirement 1: Universe Construction

### 2.1 Methodology

#### 2.1.1 Point-in-Time Constituent Lists

The pipeline MUST use point-in-time (PIT) index constituent lists, NOT current constituents projected backward.

**Data source hierarchy (retail-accessible):**
1. **Primary: Financial Modeling Prep (FMP) free tier** — Historical S&P 500 constituents endpoint. Provides historical index membership changes.
2. **Secondary: SEC EDGAR filings** — Cross-reference with Form 25 (notification of removal from listing) and Form 15 (termination of registration) for delisting validation.
3. **Tertiary: Wikipedia historical index composition** — Available for major indices, validated against primary sources. Known bias: may miss intra-year changes.
4. **Backup: CRSP via WRDS (if accessible)** — Gold standard, may require academic affiliation.

**Fallback construction:** If PIT constituent lists are unavailable for the specified index, the pipeline MUST:
1. Take the current constituent list
2. Use SEC EDGAR data to identify all stocks that were delisted from that exchange during the period
3. Add those stocks back into the universe at their historical membership dates
4. Flag this as an approximation with documented uncertainty
5. Run a sensitivity analysis comparing results with and without this approximation

**Known biases of each source:**

| Source | Known Biases | Mitigation |
|--------|-------------|------------|
| FMP historical constituents | May have gaps in small-cap index coverage; update frequency may lag actual changes | Cross-reference with EDGAR delisting filings |
| SEC EDGAR | Only covers registered securities; foreign filers use different forms; processing delays of 1-5 days | Allow 5-day buffer before assuming Form 25 = delisted |
| Wikipedia | Contributor bias; may miss intra-year changes for less-watched indices | Use only as tertiary validation |
| Yahoo Finance | Survivorship bias for stocks delisted before ~2017; no historical constituent lists | Never use alone for universe construction |
| Norgate Data (~$50/mo) | Paid; requires subscription; data quality is generally high | Optional upgrade — use for validation if subscribed |

#### 2.1.2 Delisting Handling

Every stock that existed in the universe at time T but later delisted MUST be included with its delisting return.

**Delisting return sources (retail-accessible):**
1. **SEC EDGAR Form 25** — Notification of removal from listing. Provides delisting date and reason.
2. **SEC EDGAR Form 15** — Termination of registration. Provides deregistration date.
3. **FMP delisted company endpoint** — Provides delisted company reference data.
4. **Yahoo Finance** — Has some delisted stock data but with survivorship bias prior to ~2017.
5. **OTC Markets** — Some delisted stocks continue trading OTC; prices available.

**Delisting return estimation:**
- If final trading price is available: use it (delisting return = (final_price / entry_price) - 1)
- If acquired/merged: use acquisition price
- If bankrupt/liquidated: assume -100% return (total loss)
- If voluntarily delisted (going private): use buyout price
- If unknown: flag as missing, use multiple imputation methods, report sensitivity

#### 2.1.3 Ticker Reuse Detection

Ticker symbols are NOT unique over time. The same ticker may represent different companies at different times.

**Detection method:**
1. Maintain a mapping of (ticker, date) → (PERMNO, company_name, CUSIP)
2. When CUSIP/PERMNO changes for the same ticker, flag as a ticker reuse event
3. Create separate entity IDs for different companies that shared a ticker
4. Validate with SEC EDGAR CIK numbers (which ARE stable across ticker changes)
5. Report any detected ticker reuses in the audit log

#### 2.1.4 Corporate Actions

All prices MUST be adjusted for:
- Stock splits (forward and reverse)
- Stock dividends
- Spin-offs
- Rights offerings

**Adjustment methodology:**
- Use adjusted close prices from data provider
- Cross-validate split ratios with SEC filings (8-K, 10-Q, 10-K)
- Flag any discrepancies between provider adjustments and SEC-reported ratios

#### 2.1.5 Index Membership Changes

Track when stocks enter/leave the index:
- Addition date (IPO, promotion from smaller index, spin-off)
- Removal date (delisting, acquisition, demotion to smaller index, bankruptcy)
- Reason for change

---

## 3. Requirement 2: Temporal Alignment

### 3.1 Known-Date Tagging

Every data point MUST be tagged with its "known date" — the date a retail trader could have acted on it.

**Known-date assignment rules:**

| Data Type | Known Date | Rationale |
|-----------|-----------|-----------|
| SEC filings (10-K, 10-Q, 8-K) | SEC acceptance/timestamp date + 1 business day | Filing may be submitted after hours |
| Earnings call transcripts | Transcript publication date + 1 day | Typically available within 24 hours |
| Price data | Trade date | Available at market close |
| Analyst reports | Publication date + 1 day | Not immediately distributed |
| News articles | Publication date | Available immediately |
| Social media | Post timestamp | Available immediately |
| Economic data releases | Release date + 1 day | Verify release schedule |
| Alternative data | Data provider API response timestamp | Varies by provider |
| Fundamental data (COMPUSTAT style) | Filing acceptance date, NOT fiscal period end date | Critical — many researchers use quarter end, which is WRONG |

**Temporal alignment algorithm:**
1. For each observation date T (the date we evaluate the signal):
   a. Collect all data points with known_date <= T
   b. Exclude any data points with known_date > T (look-ahead breach)
   c. Use the most recent available data for each field
   d. Record the data lag (T - known_date) for each field
2. Compute the signal using only data available at T
3. Measure forward return from T + 1 (next day's open) to T + holding_period + 1

**Lag reporting:**
- For each signal component, report: mean lag, median lag, max lag, p95 lag
- Flag any component where mean lag > 30 days (potentially stale data)

### 3.2 Point-in-Time Data Construction

The pipeline MUST simulate point-in-time data availability:

1. **Fundamental data:** Use filing acceptance dates, not fiscal period end dates. A 10-K for FY ending 2020-12-31 filed on 2021-02-15 is known on 2021-02-16, not 2021-01-01.
2. **Earnings data:** Use earnings announcement dates from 8-K filings, not the "quarter end date" from standard databases.
3. **Index membership:** Use the date the index change was announced (not effective date, not first day of quarter).
4. **Price data:** Use the closing price on the signal computation date. Forward returns from next open.

### 3.3 Look-Ahead Breach Detection

The pipeline automatically scans for look-ahead breaches:
1. For each observation, verify that every input data point has known_date <= observation_date
2. Report any breaches with: observation date, data field, known_date, date difference
3. If breaches are detected, the pipeline issues a FATAL DATA ERROR — results are invalid

---

## 4. Requirement 3: Control Groups

### 4.1 Control Group Construction

For each hypothesis, construct control groups to isolate the signal from confounding variables.

**Control group types:**

1. **Sector-matched control:** For each stock in the signal group, select stocks from the same sector (GICS sector code) that do NOT have the signal.
2. **Size-matched control:** Match on market capitalization decile at the time of signal observation.
3. **Liquidity-matched control:** Match on average daily dollar volume decile.
4. **Combined control:** Match on sector AND size AND liquidity simultaneously.

**Matching methodology:**
- **Propensity score matching (primary):** Estimate P(signal | sector, size, liquidity) using logistic regression. Match each signal stock to the k=3 nearest non-signal stocks by propensity score. Use caliper of 0.25 standard deviations.
- **Coarsened exact matching (secondary/validation):** Create strata by sector quintile x size quintile x liquidity quintile. Compare signal and non-signal stocks within each stratum.
- **Nearest-neighbor matching (tertiary/robustness):** Match on Mahalanobis distance using sector, log market cap, log dollar volume, volatility.

**Control group quality checks:**
1. Report standardized mean differences (SMD) for each matching variable before and after matching. SMD should be < 0.1 after matching.
2. Report the effective sample size after matching.
3. If matching reduces sample size by > 50%, flag as a sample size concern.

### 4.2 Analysis with Controls

1. Compute signal-group returns minus control-group returns (hedged portfolio)
2. Test whether the hedged portfolio has significant alpha
3. If the signal is significant in the raw comparison but NOT significant in the hedged comparison, flag as "possible sector/size/liquidity confound"
4. Report results for both raw and hedged portfolios

---

## 5. Requirement 4: Transaction Costs

### 5.1 Cost Model

All results MUST be reported gross AND net of transaction costs. Economic significance requires post-cost alpha.

#### 5.1.1 Commission Model

```python
# Interactive Brokers US equity pricing (retail benchmark)
COMMISSION_PER_SHARE = 0.005  # $0.005 per share
COMMISSION_MIN = 1.00         # $1.00 minimum per trade
COMMISSION_MAX_PCT = 0.01     # 1% of trade value maximum
```

#### 5.1.2 Bid-Ask Spread Model

The spread varies by market capitalization and liquidity:

| Market Cap Decile | Estimated Half-Spread (bps) | Description |
|-------------------|-----------------------------|-------------|
| 1 (Mega cap, >$200B) | 2 | Very tight |
| 2-3 (Large cap) | 3-5 | Tight |
| 4-5 (Mid cap) | 5-10 | Moderate |
| 6-7 (Small cap) | 10-25 | Wider |
| 8 (Micro cap) | 25-50 | Wide |
| 9 (Nano cap) | 50-100 | Very wide |
| 10 (Sub-nano) | 100-200+ | Extremely wide |

**Implementation:**
- Estimate half-spread as a function of market cap, dollar volume, and price
- Use daily high-low range as a conservative spread estimate when tick data unavailable
- Double the half-spread for round-trip (entry + exit)
- Use the model: `half_spread_bps = max(2, 200 * exp(-0.5 * log10(market_cap_millions)))`

#### 5.1.3 Slippage Model

Slippage is estimated as a function of trade size relative to average daily volume (ADV):

```python
def estimate_slippage_bps(trade_value: float, adv: float, market_cap: float) -> float:
    """
    Estimate slippage in basis points.
    Based on Almgren et al. (2005) and retail broker estimates.
    """
    participation_rate = trade_value / adv if adv > 0 else 1.0

    # Linear model for small participation rates
    if participation_rate <= 0.01:  # <1% of ADV
        slippage = 2.0 * participation_rate * 100  # 2 bps per 1% participation
    elif participation_rate <= 0.05:  # 1-5% of ADV
        slippage = 5.0 * participation_rate * 100
    else:  # >5% of ADV — likely problematic for retail
        slippage = 25.0 * participation_rate * 100

    # Small/micro cap penalty
    size_penalty = max(1.0, 3.0 - 0.3 * np.log10(max(market_cap, 1e6)))

    return slippage * size_penalty
```

#### 5.1.4 Short Borrow Costs

If the strategy involves shorting:

```python
def estimate_borrow_cost(annualized_rate_pct: float, holding_period_days: int) -> float:
    """
    Estimate short borrow cost.
    Easy-to-borrow: 0.25-0.50% annualized
    Hard-to-borrow: 2-10% annualized
    Impossible: flagged as not shortable
    """
    daily_rate = annualized_rate_pct / 100 / 252
    return daily_rate * holding_period_days
```

Easy-to-borrow stocks: S&P 500, most S&P 400. Hard-to-borrow: small caps, high short interest, recent IPOs. The pipeline flags any stock in the bottom 30% of market cap as potentially hard-to-borrow.

#### 5.1.5 Total Cost Calculation

For each trade:
```python
total_cost = (
    commission +
    half_spread * trade_value * 2 +  # round trip
    slippage * trade_value +
    borrow_cost * trade_value  # if short
)
```

### 5.2 Position Sizing Constraints

- Maximum position: min(5% of portfolio, 5% of ADV)
- No position that cannot be exited within 1 day at <5% of ADV
- Flag any position that requires >2 days to exit as "capacity constrained"
- Total portfolio turnover reported daily

---

## 6. Requirement 5: Statistical Rigor

### 6.1 Distribution Analysis

For every signal and strategy return stream, compute and report:

| Metric | Description |
|--------|-------------|
| Mean return | Average daily/weekly/monthly return |
| Median return | Median daily/weekly/monthly return |
| Standard deviation | Volatility of returns |
| Skewness | Distribution asymmetry |
| Kurtosis | Tail thickness (excess kurtosis) |
| Min / Max | Extreme returns |
| 95% Bootstrap CI for mean | Confidence interval for the mean (10,000 resamples) |
| Sharpe ratio | Annualized, using risk-free rate proxy |
| Sortino ratio | Downside-only volatility |
| Max drawdown | Maximum peak-to-trough decline |
| Max drawdown duration | Days to recovery |
| Calmar ratio | Annualized return / max drawdown |
| Information coefficient | Correlation(signal, forward return) |
| Hit rate | Proportion of positive returns |
| Profit factor | Gross gains / gross losses |
| Omega ratio | Probability-weighted gain/loss ratio |

### 6.2 Bootstrap Confidence Intervals

**Method:** Block bootstrap (preserves serial correlation)
- Block length: automatically selected via Politis & Romano (2004) algorithm
- 10,000 resamples
- Report: 90%, 95%, 99% confidence intervals for mean return, Sharpe ratio, alpha
- Use bias-corrected and accelerated (BCa) intervals

### 6.3 Multiple Comparison Correction

The pipeline tests multiple hypotheses. Correction is MANDATORY.

**Bonferroni correction:**
- Adjusted alpha = 0.05 / N (where N = number of hypotheses tested)
- Report unadjusted and adjusted p-values
- This is conservative; used as the primary correction

**Benjamini-Hochberg False Discovery Rate:**
- Control FDR at q = 0.10
- Report which hypotheses survive FDR control
- Less conservative; used as secondary validation

**Within-hypothesis multiple testing:**
- If a hypothesis is tested across multiple sub-periods or specifications, apply Bonferroni within the hypothesis
- Report number of implicit tests performed

### 6.4 Outlier Analysis

1. **Winsorization sensitivity:** Test with no winsorization, 1%/99%, and 2.5%/97.5% thresholds. Report whether conclusions change.
2. **Influence analysis:** Compute DFBETAS for each observation (or grouped by time period). Identify observations that substantially alter regression coefficients.
3. **Trimmed mean analysis:** Report 5%, 10%, 25% trimmed means.
4. **If removing < 5% of extreme observations eliminates the significance, flag as "outlier-driven."**

### 6.5 Power Analysis

For each hypothesis:
1. Compute the minimum detectable effect (MDE) given sample size, volatility, and desired power (0.80)
2. Compute achieved power for the hypothesized minimum effect size
3. If achieved power < 0.80 for the minimum effect size, flag as "underpowered"

---

## 7. Requirement 6: Adversarial Breakage

### 7.1 Random Permutation Test (Primary Breakage)

**Method:**
1. Shuffle the signal values randomly across all observations (destroying any real signal-forward return relationship)
2. Re-run the full backtest with shuffled signals
3. Repeat 1,000 times
4. Compute the p-value as: (number of shuffled backtests with performance >= original) / 1000
5. If p > 0.05, the signal cannot be distinguished from noise — BROKEN

### 7.2 Time Period Shuffling

**Method:**
1. Randomly reassign signal values to different time periods
2. Re-run backtest
3. Repeat 1,000 times
4. If the strategy performs similarly across shuffled time periods, the signal is not time-specific — FAILS

### 7.3 Alternative Specification Robustness

Test multiple reasonable alternative specifications:
1. **Holding period variation:** Test original +/- 50% of specified holding period
2. **Universe variation:** Test broader and narrower universes
3. **Signal threshold variation:** For categorical signals, vary the classification threshold
4. **Position sizing variation:** Test equal-weight vs. signal-proportional vs. constrained

If the signal only works under ONE specific specification and degrades rapidly under reasonable alternatives, flag as "fragile specification — likely overfitted."

### 7.4 Out-of-Sample Holdout

**Method:**
1. Reserve the final 30% of the time period (by calendar time, NOT randomly) for out-of-sample testing
2. Any optimization or specification tuning MUST be done on the first 70% only
3. Report in-sample and out-of-sample performance separately
4. If out-of-sample performance is not statistically significant (at p < 0.05 after Bonferroni), flag as "failed out-of-sample validation"

### 7.5 Walk-Forward Analysis

**Method:**
1. Divide the data into rolling windows (e.g., 5-year training, 1-year testing)
2. For each window, compute the signal using only data available at that time
3. Test whether the signal consistently generates alpha in the subsequent out-of-sample period
4. Report: number of windows with positive alpha, mean walk-forward alpha, walk-forward hit rate
5. If < 60% of windows have positive alpha, flag as "inconsistent"

### 7.6 P-Hacking Vulnerability Assessment

1. **Specification curve analysis:** For a grid of reasonable specification choices (holding period, universe filter, position sizing), compute the distribution of p-values.
2. If many specifications produce non-significant results and only a small fraction produce significant results, the "significant" result is likely p-hacked.
3. Report the distribution of p-values across all reasonable specifications.

---

## 8. Requirement 7: Edge Decay

### 8.1 Rolling Window Analysis

**Method:**
1. Use a rolling window of 3 years, stepping by 1 quarter
2. For each window, compute the strategy's annualized alpha
3. Plot the rolling alpha over time
4. Fit a linear trend to the rolling alpha series
5. If the trend is significantly negative (p < 0.05), the edge is decaying — flag as "edge decay detected"

### 8.2 Edge Half-Life Estimation

**Method:**
1. Compute the autocorrelation of rolling alpha at multiple lags
2. Fit an exponential decay model: alpha(t) = alpha(0) * exp(-lambda * t)
3. Half-life = ln(2) / lambda
4. Report half-life estimate with confidence interval
5. If half-life < 2 years, flag as "short-lived edge"

### 8.3 Regime-Conditional Performance

**Regime classification:**
- **Bull/Bear:** S&P 500 >/below 200-day moving average
- **High/Low Volatility:** VIX >/below 20 (long-term median)
- **Expansion/Recession:** NBER recession dates
- **Rising/Falling Rates:** 10Y yield direction over trailing 6 months
- **High/Low Dispersion:** Cross-sectional dispersion of S&P 500 returns (above/below median)

For each regime:
1. Report mean return, Sharpe, hit rate during regime
2. Test whether performance differs significantly across regimes (two-sample t-test with Bonferroni)
3. If the strategy only works in one regime class, flag as "regime-dependent"

### 8.4 Structural Break Detection

**Method:**
1. Bai-Perron test for structural breaks in the strategy's alpha time series
2. If structural breaks are detected around known market structure changes (Reg NMS 2007, decimalization, COVID, etc.), flag
3. Report post-break alpha separately

---

## 9. Requirement 8: Reproducibility

### 9.1 Deterministic Random Seeds

ALL random operations MUST use fixed, documented seeds:

```python
GLOBAL_SEED = 42
BOOTSTRAP_SEED = 137
PERMUTATION_SEED = 841
TRAIN_TEST_SEED = 580
FACTOR_SEED = 733
REGIME_SEED = 251
```

Seeds are derived deterministically from the hypothesis UUID to ensure different hypotheses get different but reproducible random sequences:

```python
def get_hypothesis_seed(uuid: str, base_seed: int) -> int:
    """Derive a deterministic seed from hypothesis UUID and base seed."""
    uuid_hash = int(hashlib.sha256(uuid.encode()).hexdigest()[:8], 16)
    return (base_seed + uuid_hash) % (2**31)
```

### 9.2 Version Tracking

Every pipeline run records:
- Pipeline version (from this specification)
- Python version, package versions (from pip freeze)
- OS and architecture
- Date and time of run
- Exact data sources used with access dates
- Git hash of pipeline code

### 9.3 Data Snapshots

- All input data is cached with content hashing (SHA-256)
- If data sources are dynamic (APIs), record: exact query parameters, timestamp of retrieval, response checksum
- Flag non-reproducible data sources

### 9.4 LLM Non-Determinism Handling

For any hypothesis that uses an LLM for signal extraction:

1. **Extraction tasks** (classify, score, extract structured data from text):
   - MUST use a small deterministic model (7B-8B parameters)
   - MUST use temperature = 0
   - MUST use fixed random seeds
   - Output MUST be deterministic (same input → same output)
   - Document model name, version, quantization, and hardware

2. **Synthesis tasks** (summarize, reason, discover patterns):
   - May use larger models
   - Temperature may be > 0
   - Output may be non-deterministic
   - MUST report the range of results across multiple runs (at least 5)
   - MUST report the standard deviation of key metrics across runs
   - If the verdict changes across runs, flag as "non-deterministic — results contingent on LLM sampling"

### 9.5 Audit Trail

Every verdict produces a complete audit trail:

```python
@dataclass
class AuditEntry:
    timestamp: str
    stage: str                         # 'universe' | 'temporal' | 'backtest' | 'statistics' | ...
    operation: str                     # 'universe_construction' | 'bootstrap_ci' | ...
    inputs: Dict[str, Any]             # Hash or summary of inputs
    outputs: Dict[str, Any]            # Hash or summary of outputs
    parameters: Dict[str, Any]         # Parameters used
    data_hashes: Dict[str, str]        # SHA-256 hashes of data files
    warnings: List[str]                # Any warnings generated
```

The full audit trail is output as a JSON file that can be independently verified.

---

## 10. Requirement 9: Baseline Factor Comparison

### 10.1 Mandatory Factor Library

Every hypothesis MUST be compared against these baseline factors:

| Factor | Construction | Source |
|--------|-------------|--------|
| Momentum (12-1) | Return from t-12 to t-1 months, skip most recent month | Jegadeesh & Titman (1993) |
| Short-term reversal (1M) | Return in month t-1 | Jegadeesh (1990) |
| Post-earnings drift (PEAD) | Standardized unexpected earnings (SUE) | Ball & Brown (1968) |
| Value (B/M) | Book-to-market ratio | Fama & French (1992) |
| Size | Log market capitalization | Banz (1981) |
| Liquidity | Amihud illiquidity measure | Amihud (2002) |
| Low volatility | Inverse of trailing 12-month daily volatility | Ang et al. (2006) |
| Sector-neutral momentum | Momentum within GICS sector | Moskowitz & Grinblatt (1999) |
| Sector-neutral value | B/M within GICS sector | Asness et al. (2000) |
| Sector-neutral size | Size within GICS sector | Fama & French industry factors |
| Sector-neutral low vol | Low vol within GICS sector | Sector-neutral BAB |
| Sector-neutral reversal | Reversal within GICS sector | Industry-relative reversal |

### 10.2 Factor Comparison Methodology

For each hypothesis:

1. **Factor exposure regression:**
   ```
   r_hypothesis = alpha + beta_1 * MOM + beta_2 * STR + beta_3 * PEAD +
                  beta_4 * VALUE + beta_5 * SIZE + beta_6 * LIQ + beta_7 * LOWVOL +
                  beta_8 * SECTOR_MOM + beta_9 * SECTOR_VALUE +
                  beta_10 * SECTOR_SIZE + beta_11 * SECTOR_LOWVOL +
                  beta_12 * SECTOR_REVERSAL + epsilon
   ```
2. **Report:** alpha (intercept), all betas, t-statistics, R-squared
3. **Alpha test:** Test whether alpha is significantly positive after controlling for all baseline factors
4. **Residual analysis:** After hedging out baseline factor exposures, does the residual return stream have significant alpha?
5. **Factor loading decomposition:** What fraction of the strategy's return is explained by each factor?

### 10.3 Factor Recycling Detection

If the hypothesis alpha is NOT significant after controlling for baseline factors (p > 0.05 after Bonferroni), flag as **"factor recycling — hypothesis is explained by known factors."**

Report the dominant factor exposures and the fraction of total return explained by known factors.

---

## 11. Verdict Logic

### 11.1 Decision Tree

```
1. DATA CHECK
   ├─ Data available? ─ NO → UNTESTABLE
   └─ YES → Continue

2. TEMPORAL CHECK
   ├─ Look-ahead breaches detected? ─ YES → FATAL (fix data)
   └─ NO → Continue

3. STATISTICAL SIGNIFICANCE
   ├─ Raw alpha p < 0.05 after Bonferroni? ─ NO → BROKEN (not significant)
   └─ YES → Continue

4. ECONOMIC SIGNIFICANCE
   ├─ Post-cost alpha > minimum_effect_size.annualized_alpha_bps? ─ NO → BROKEN (not meaningful)
   └─ YES → Continue

5. ADVERSARIAL BREAKAGE
   ├─ Permutation test passes (p < 0.05)? ─ NO → BROKEN (permutation)
   ├─ OOS significance (p < 0.05)? ─ NO → BROKEN (OOS validation)
   ├─ Walk-forward > 60% windows positive? ─ NO → BROKEN (inconsistent)
   ├─ Alternative specs > 50% significant? ─ NO → BROKEN (fragile spec)
   └─ ALL PASS → Continue

6. FACTOR COMPARISON
   ├─ Residual alpha significant after baseline factors? ─ NO → BROKEN (factor recycling)
   └─ YES → Continue

7. EDGE DECAY
   ├─ Edge half-life < 1 year? ─ YES → SURVIVED (with WARNING: short half-life)
   ├─ Regime-dependent? ─ YES → SURVIVED (with WARNING: regime-dependent)
   └─ NO → Continue → SURVIVED

8. SURVIVED with no warnings
```

### 11.2 Verdict Types

- **SURVIVED:** Passes ALL checks. Signal is statistically significant, economically meaningful post-costs, robust to adversarial breakage, not explained by known factors.
- **SURVIVED (WARNING):** Passes all checks but has an edge decay or regime-dependency flag. Usable but requires monitoring.
- **BROKEN:** Failed one or more checks. Specific failure mode documented.
- **INCONCLUSIVE:** Borderline results, insufficient data, or Bridge agents disagree.
- **UNTESTABLE:** Required data not available through retail-accessible sources.

---

## 12. Output Format

### 12.1 Output Structure

```
/workspaces/tradefinder/outputs/{hypothesis_uuid}/
├── audit_trail.json          # Complete audit trail
├── verdict.json              # Final verdict with all supporting data
├── results_summary.json      # All metrics in machine-readable format
├── charts/                   # Visualizations
│   ├── equity_curve.png
│   ├── rolling_alpha.png
│   ├── regime_performance.png
│   ├── factor_loadings.png
│   ├── distribution_analysis.png
│   ├── permutation_test.png
│   └── walk_forward.png
├── data/                     # Processed data snapshots
│   ├── universe_snapshot.parquet
│   ├── signal_snapshot.parquet
│   ├── returns_snapshot.parquet
│   └── factor_returns.parquet
└── logs/                     # Execution logs
    └── pipeline_run.log
```

### 12.2 Verdict JSON Schema

```json
{
    "hypothesis_uuid": "string",
    "hypothesis_name": "string",
    "pipeline_version": "1.0.0",
    "run_timestamp": "ISO8601",
    "verdict": "SURVIVED | SURVIVED_WARNING | BROKEN | INCONCLUSIVE | UNTESTABLE",
    "verdict_reason": "string explaining the primary reason",
    "failure_stage": "null or the stage where it failed",
    "checks": {
        "data_availability": {"passed": true, "details": {}},
        "temporal_alignment": {"passed": true, "look_ahead_breaches": []},
        "statistical_significance": {
            "passed": true,
            "raw_p_value": 0.001,
            "bonferroni_adjusted_p": 0.01,
            "fdr_adjusted_p": 0.005,
            "bootstrap_ci_95": [-0.01, 0.05]
        },
        "economic_significance": {
            "passed": true,
            "post_cost_annualized_alpha_bps": 450,
            "minimum_required_bps": 300,
            "post_cost_sharpe": 0.45,
            "post_cost_max_drawdown_pct": 18.5
        },
        "adversarial_breakage": {
            "permutation_test_p": 0.002,
            "oos_significance_p": 0.01,
            "walk_forward_positive_pct": 75.0,
            "alternative_specs_passed_pct": 80.0,
            "all_passed": true
        },
        "factor_comparison": {
            "residual_alpha_p_value": 0.02,
            "r_squared": 0.15,
            "dominant_factors": ["momentum"],
            "factor_recycling": false
        },
        "edge_decay": {
            "half_life_years": 3.5,
            "decay_trend_p_value": 0.12,
            "regime_dependent": false,
            "structural_breaks": []
        }
    },
    "metrics": {
        "annualized_return_pct": 12.5,
        "annualized_volatility_pct": 18.2,
        "sharpe_ratio": 0.52,
        "sortino_ratio": 0.78,
        "max_drawdown_pct": 22.1,
        "max_drawdown_days": 145,
        "calmar_ratio": 0.57,
        "information_coefficient": 0.045,
        "hit_rate": 0.55,
        "profit_factor": 1.35,
        "skewness": 0.23,
        "kurtosis": 4.1,
        "mean_return_bps_daily": 4.8,
        "median_return_bps_daily": 3.2
    },
    "warnings": ["string"],
    "audit_trail_hash": "sha256",
    "data_source_hashes": {}
}
```

---

## 13. Acceptance Criteria (Pipeline Self-Test)

Before the pipeline is locked, it MUST pass these self-tests:

1. **Null signal test:** A random signal MUST be BROKEN with 95%+ probability over 100 trials
2. **Known factor test:** A pure momentum signal MUST be detected as factor recycling (not SURVIVED)
3. **Look-ahead contamination test:** A signal that accidentally uses forward-looking data MUST be detected
4. **Survivorship bias test:** A universe that excludes delisted stocks MUST be detected and flagged
5. **Reproducibility test:** Running the same hypothesis twice MUST produce identical results
6. **Ticker reuse test:** A ticker that was recycled MUST NOT merge histories silently
7. **Transaction cost test:** A signal that is profitable gross but not net MUST be flagged as economically insignificant

---

## 14. Appendices

### A. Data Provider Biases (Complete Catalog)

*See `implementation/universe.py` for the complete, code-embedded catalog.*

### B. Default Parameters

All default parameters are embedded in the code as class constants. They are documented in the code and here for reference.

### C. References

- Almgren, R., Thum, C., Hauptmann, E., & Li, H. (2005). Direct estimation of equity market impact.
- Amihud, Y. (2002). Illiquidity and stock returns.
- Ang, A., Hodrick, R. J., Xing, Y., & Zhang, X. (2006). The cross-section of volatility and expected returns.
- Bai, J., & Perron, P. (2003). Computation and analysis of multiple structural change models.
- Benjamini, Y., & Hochberg, Y. (1995). Controlling the false discovery rate.
- Fama, E. F., & French, K. R. (1992). The cross-section of expected stock returns.
- Jegadeesh, N., & Titman, S. (1993). Returns to buying winners and selling losers.
- Politis, D. N., & Romano, J. P. (1994). The stationary bootstrap.
