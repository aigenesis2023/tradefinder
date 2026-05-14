# Stage 2 -- Universal Hypothesis Testing Pipeline

**Version:** 1.0.0 (LOCKED)

A production-quality, adversarial backtesting and validation pipeline for testing LLM-based trading hypotheses on US equities. Designed to eliminate bad ideas cheaply -- a high BROKEN rate is success.

## Design Philosophy

1. **Honest empiricism above all.** Every test is pre-specified. No p-hacking. No specification searching.
2. **Adversarial by design.** Every result is attacked from multiple angles (permutation, specification robustness, data integrity, factor decomposition) before it is trusted.
3. **Reproducible and auditable.** Every verdict is traceable to raw data and exact code. Deterministic seeds for all random operations.
4. **Retail-realistic.** All data sources are free or low-cost. Transaction costs modeled for retail brokers (Interactive Brokers pricing). Execution constraints enforced.
5. **Universal.** The pipeline knows nothing about the hypotheses it will test. Works for any signal type, any universe, any holding period.
6. **Locked.** Methodology is frozen. No post-hoc adjustments after seeing hypotheses.

## Installation

```bash
pip install -r requirements.txt
```

For live price data (optional):
```bash
pip install yfinance
```

Optional: set the `FMP_API_KEY` environment variable for point-in-time index constituent data via Financial Modeling Prep free tier.

## Quick Start

```bash
# Run with a hypothesis file
python pipeline.py --hypothesis hypothesis.json --output results/

# Run the built-in example (uses simulated data, for testing)
python pipeline.py --example --output results/ --verbose
```

## Hypothesis Specification Format

Hypotheses are submitted as JSON files. All fields are from [PIPELINE_SPEC.md](../PIPELINE_SPEC.md) Section 1.

```json
{
    "name": "Mean Reversion with LLM Noise Filter",
    "uuid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "source_agent": "Earnings Whisperer",
    "submission_number": 1,

    "mechanism": "Stocks underperforming sector peers over 5 days tend to mean-revert. LLM separates noise-driven from news-driven selloffs.",
    "llm_advantage": "Real-time parsing of unstructured earnings call text at scale, impossible before LLMs.",
    "why_underweighted": "Requires real-time NLP at scale across thousands of tickers -- cost-prohibitive before LLMs.",

    "universe": {
        "universe_type": "sp500",
        "include_delisted": true,
        "min_price": 1.0,
        "exchanges": ["NYSE", "NASDAQ", "NYSEARCA", "NYSEAMERICAN"]
    },

    "signal": {
        "signal_type": "numeric",
        "signal_name": "mean_reversion_5d",
        "higher_is_better": true,
        "llm_model_used": "llama-3-8b",
        "llm_temperature": 0.0,
        "llm_seed": 42,
        "llm_is_deterministic": true,
        "signal_source": "/path/to/precomputed_signals.parquet"
    },

    "holding_period_days": 5,

    "time_period": {
        "start_date": "2023-01-01",
        "end_date": "2025-12-31",
        "oos_start_date": null,
        "min_training_days": 252,
        "frequency": "daily"
    },

    "position_sizing": {
        "method": "equal_weight",
        "max_position_pct": 0.05,
        "max_positions": 50,
        "max_sector_pct": 0.30,
        "capital": 100000.0,
        "rebalance_frequency": "daily"
    },

    "minimum_effect_size": {
        "annualized_alpha_bps": 300,
        "sharpe_ratio": 0.3,
        "information_coefficient": 0.03,
        "hit_rate": 0.51,
        "max_drawdown_pct": 25.0
    },

    "data_sources": [
        {
            "source_type": "price",
            "provider": "yahoo",
            "frequency": "daily",
            "fields": ["adj_close", "volume"],
            "start_date": "2020-01-01",
            "end_date": "2025-12-31",
            "known_biases": ["Survivorship bias for stocks delisted before ~2017"],
            "api_tier": "free",
            "monthly_cost_usd": 0.0
        }
    ],

    "falsifiable_prediction": "A long-short portfolio long bottom quintile / short top quintile of 5-day returns should produce Sharpe > 0.3 after costs.",
    "self_assessed_confidence": "MEDIUM",
    "biggest_weakness": "Mean reversion signals may be crowded in large caps."
}
```

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Short, descriptive name |
| `uuid` | string | Unique identifier (assigned by Bridge) |
| `source_agent` | string | Stage 1 agent that created this hypothesis |
| `submission_number` | int | 1, 2, or 3 (max 3 refinement attempts) |
| `universe` | object | Stock universe specification |
| `signal` | object | Signal construction specification |
| `holding_period_days` | int | How long to hold positions |
| `time_period` | object | Start/end dates for analysis |
| `position_sizing` | object | Position sizing methodology |
| `minimum_effect_size` | object | Below this, BROKEN regardless of p-value |
| `data_sources` | array | Required data sources with known biases |
| `falsifiable_prediction` | string | What should be observed if the edge is real |
| `self_assessed_confidence` | string | LOW / MEDIUM / HIGH |
| `biggest_weakness` | string | What the creator is most worried about |

## Module Overview

### pipeline.py -- Main Orchestrator
Entry point that ties everything together. Accepts a hypothesis spec and runs the full test battery automatically. Produces a final verdict (SURVIVED / BROKEN / INCONCLUSIVE / UNTESTABLE) with complete audit trail.

### universe.py -- Universe Construction
Builds survivorship-bias-free, point-in-time stock universes. Includes delisted stocks with delisting returns, detects ticker reuse via CUSIP/CIK mapping, and adjusts for corporate actions. All data sources are retail-accessible (FMP free tier, SEC EDGAR, Yahoo Finance).

### temporal.py -- Temporal Alignment
Ensures every data point is timestamped to when it was ACTUALLY available to a retail trader. Automatic look-ahead breach detection. Different known-date rules for different data types (SEC filings use acceptance date, not period end date; earnings use announcement date).

### backtest.py -- Backtesting Engine
Cross-sectional and walk-forward backtesting with realistic transaction costs:
- Commissions (Interactive Brokers retail pricing: $0.005/share, $0.35 min)
- Bid-ask spreads (varies by market cap decile: 2 bps mega cap to 200 bps nano cap)
- Slippage (varies by trade size relative to ADV)
- Short borrow costs (0.25-50% annualized depending on borrow difficulty)
- Capacity-aware position sizing

### statistics.py -- Statistical Tests
Full statistical battery:
- Distribution analysis (moments, quantiles, normality, autocorrelation)
- Block bootstrap with BCa confidence intervals (preserves serial correlation)
- Multiple comparison correction (Bonferroni + Benjamini-Hochberg FDR)
- Outlier sensitivity analysis (winsorization, trimming, influence)
- Power analysis (minimum detectable effect, achieved power)

### breakers.py -- Adversarial Tests
Designed to DESTROY false positives:
- Random permutation test (shuffle signal, verify zero alpha)
- Time period shuffling
- Specification robustness (holding period, universe, threshold variations)
- Out-of-sample holdout validation
- Walk-forward consistency analysis
- Specification curve analysis (p-hacking detection)
- Regime-conditional performance (bull/bear, high/low vol, expansion/recession, etc.)
- Edge decay detection with half-life estimation (Bai-Perron structural breaks)

### factors.py -- Baseline Factor Comparison
MANDATORY comparison against known factors:
- Momentum (12-1), Short-term reversal (1M), PEAD (SUE)
- Value (B/M), Size (market cap), Liquidity (Amihud), Low volatility
- Sector-neutral versions of all factors
- Factor exposure regression with alpha test
- Factor recycling detection (alpha non-significant after controlling for known factors)

### audit.py -- Reproducibility & Audit Trail
Ensures complete reproducibility:
- Deterministic seeds derived from hypothesis UUID
- Version tracking (pipeline, Python, packages, git hash)
- Data snapshots with SHA-256 content hashing
- LLM non-determinism handling (small models, temperature=0, fixed seeds)
- Complete audit trail from raw data to final verdict

## Verdict Logic (Decision Tree)

The pipeline applies this decision tree, from [PIPELINE_SPEC.md](../PIPELINE_SPEC.md) Section 11.1:

```
1. DATA CHECK -> Data available? NO -> UNTESTABLE
2. TEMPORAL CHECK -> Look-ahead breaches? YES -> BROKEN
3. STATISTICAL SIGNIFICANCE -> p < 0.05 after Bonferroni? NO -> BROKEN
4. ECONOMIC SIGNIFICANCE -> Post-cost alpha > minimum? NO -> BROKEN
5. ADVERSARIAL BREAKAGE:
   a. Permutation test p < 0.05? NO -> BROKEN
   b. Walk-forward > 60% windows positive? NO -> BROKEN
   c. Alternative specs > 50% significant? NO -> BROKEN
6. FACTOR COMPARISON -> Residual alpha significant? NO -> BROKEN (factor recycling)
7. EDGE DECAY:
   a. Half-life < 1 year? -> SURVIVED_WARNING
   b. Regime-dependent? -> SURVIVED_WARNING
8. ALL PASS -> SURVIVED
```

### Verdict Types

| Verdict | Meaning |
|---------|---------|
| **SURVIVED** | Passes ALL checks. Signal is real, significant, meaningful, robust, and not factor recycling. |
| **SURVIVED_WARNING** | Passes all but has edge-decay or regime-dependency flags. Requires monitoring. |
| **BROKEN** | Failed one or more checks. Specific failure mode documented. |
| **INCONCLUSIVE** | Borderline results or insufficient data to decide. |
| **UNTESTABLE** | Required data not available through retail-accessible sources. |

## Output Format

```
results/{hypothesis_uuid}/
├── verdict.json              # Final verdict with supporting data
├── audit_trail.json          # Complete audit trail (can be independently replayed)
├── results_summary.json      # All metrics in machine-readable format
├── charts/                   # Intended for visualizations
├── data/                     # Processed data snapshots (parquet)
│   ├── universe_snapshot.parquet
│   ├── signals.parquet
│   └── strategy_returns.parquet
└── logs/
    └── pipeline_run.log
```

### Verdict JSON Structure

```json
{
    "hypothesis_uuid": "a1b2c3d4...",
    "hypothesis_name": "Mean Reversion with LLM Noise Filter",
    "pipeline_version": "1.0.0",
    "run_timestamp": "2026-05-13T12:00:00Z",
    "verdict": "SURVIVED",
    "verdict_reason": "ALL CHECKS PASSED. Post-cost alpha: 450 bps/year, Sharpe: 0.52",
    "failure_stage": null,
    "checks": {
        "data_availability": {"passed": true},
        "temporal_alignment": {"passed": true, "look_ahead_breaches": 0},
        "statistical_significance": {"passed": true, "ci_95_mean_daily_bps": [1.2, 8.4]},
        "economic_significance": {"passed": true, "post_cost_annualized_alpha_bps": 450},
        "adversarial_breakage": {
            "permutation_test_p": 0.002,
            "walk_forward_positive_pct": 75.0,
            "alternative_specs_passed_pct": 80.0
        },
        "factor_comparison": {
            "residual_alpha_p_value": 0.02,
            "factor_recycling": false,
            "dominant_factors": ["momentum"]
        },
        "edge_decay": {
            "half_life_years": 3.5,
            "regime_dependent": false
        }
    },
    "metrics": {
        "sharpe_ratio": 0.52,
        "max_drawdown_pct": 18.5,
        "hit_rate": 0.55,
        "profit_factor": 1.35,
        "information_coefficient": 0.045
    },
    "warnings": [],
    "audit_trail_hash": "sha256...",
    "seeds_used": {"global": 42, "bootstrap": 137, ...}
}
```

## Running the Full Pipeline (Code)

```python
from pipeline import HypothesisPipeline, HypothesisSpec

hypothesis = HypothesisSpec.from_json_file("hypothesis.json")
pipeline = HypothesisPipeline(output_dir="results/", verbose=True)
result = pipeline.run(hypothesis)

print(f"Verdict: {result['verdict']}")
print(f"Reason: {result['verdict_reason']}")
```

## LLM Non-Determinism Handling

Per the specification:

- **Extraction tasks** (classify, score, extract structured data): MUST use small deterministic models (7B-8B, temperature=0, fixed seeds). Output must be deterministic.
- **Synthesis tasks** (summarize, reason, discover): May use larger models with temperature > 0. MUST report result range across multiple runs (min 5). If verdict changes across runs, flag as "non-deterministic."

The `SignalSpec` records `llm_model_used`, `llm_temperature`, `llm_seed`, and `llm_is_deterministic`. The audit trail captures this metadata for every pipeline run.

## Known Limitations

### Data Source Biases

All retail-accessible data sources have known biases:

| Source | Primary Biases |
|--------|---------------|
| **Yahoo Finance** | Survivorship bias for stocks delisted before ~2017. No historical index constituent lists. Corporate action adjustments may lag by 1-2 days. |
| **FMP Free Tier** | 250 API calls/day limit. Historical constituent data may miss intra-quarter changes. Incomplete delisted company coverage pre-2000. |
| **SEC EDGAR** | Only covers SEC-registered securities. Foreign filers use different forms (20-F, 6-K). 1-5 day processing delay. Pre-2000 filings less structured. |
| **Polygon Free** | 5 API calls/minute. Historical depth varies by subscription. Corporate action completeness varies. |
| **Norgate ($50/mo)** | Paid. Methodology partially proprietary. Not independently auditable. |

### Pipeline Limitations

1. **Data availability boundary.** Hypotheses requiring proprietary data (credit card transactions, satellite imagery, CDS spreads) are marked UNTESTABLE. The pipeline only tests what retail traders can actually access.

2. **Simulated vs. real data.** When run with `--example`, the pipeline uses simulated price data (geometric Brownian motion). This is for pipeline testing only. Real hypotheses MUST be tested with actual market data.

3. **Transaction cost estimates.** Spread and slippage models are conservative estimates. Actual costs depend on broker, time of day, order type, and market conditions. Results should be interpreted as "edge must exceed this conservative cost threshold."

4. **Survivorship bias in fallback data.** When FMP API is unavailable, the pipeline falls back to current constituent lists with known delistings removed. This is an approximation and is flagged in the audit trail.

5. **No intraday data.** The pipeline uses daily closing prices. Strategies requiring intraday execution timing cannot be accurately tested.

6. **No options/derivatives.** The pipeline only handles equity positions (long/short). Options strategies, volatility trading, and multi-asset strategies are not supported.

7. **Static factor library.** Baseline factor comparisons use academic factor definitions that may not capture all known anomalies. Factor construction from retail data is inherently noisier than institutional data (e.g., CRSP/Compustat).

8. **Hard 3-submission limit.** The Bridge enforces a maximum of 3 refinement attempts per hypothesis UUID to prevent overfitting through repeated resubmission. This is a design constraint, not a technical one.

### Three Critical Safeguards (Verdict Validity)

The pipeline includes three safeguards that are the difference between a verdict you can act on and a verdict the literature would classify as structurally invalid. These run automatically during signal construction AND pipeline execution.

#### 1. Temporal Contamination Detector

Prevents the "profit mirage": backtested returns from LLM training-data memorization that vanish once the model's knowledge cutoff passes. Tags every signal file with `contamination_risk` (HIGH/MEDIUM/LOW/CLEAN). Caps verdict to INCONCLUSIVE when all data predates the model's training cutoff. Uses knowledge cutoff verification, placebo text swapping, and pre/post cutoff performance comparison.

#### 2. Survivorship Bias Guard

Detects and quantifies survivorship bias from using only currently-traded stocks in backtests. Parses SEC EDGAR Form 25/15 for delistings, estimates delisting returns by reason (bankruptcy, acquisition, etc.), validates universe construction includes delisted stocks, and quantifies the bias impact. Caps verdict confidence when delisted return data is incomplete.

#### 3. Cumulative False Discovery Rate Tracker

Tracks the TOTAL number of hypothesis tests across the entire investigation in a persistent `trial_family.json` file. Applies family-wise Bonferroni correction (adjusted alpha = 0.05 / total_tests) and Benjamini-Hochberg FDR across all p-values. Enforces a hard cap of 3 refinement attempts per hypothesis UUID. Terminates the investigation if zero hypotheses SURVIVE a full cycle. Embeds investigation-wide significance context in every verdict (e.g., "trial 12 of 31, Bonferroni threshold p < 0.0016").

These safeguards are documented in detail in [SAFEGUARDS.md](../SAFEGUARDS.md).

### Acceptance Criteria (Self-Checks)

Before locking, the pipeline must pass these tests (see PIPELINE_SPEC.md Section 13):

1. Null signal test: Random signal BROKEN with 95%+ probability over 100 trials
2. Known factor test: Pure momentum signal detected as factor recycling
3. Look-ahead contamination test: Forward-looking data detected
4. Survivorship bias test: Universe without delisted stocks flagged
5. Reproducibility test: Same hypothesis twice produces identical results
6. Ticker reuse test: Recycled ticker histories not merged silently
7. Transaction cost test: Gross-profitable, net-unprofitable signal flagged

## Signal Construction Framework

The pipeline expects pre-computed signal files (`signal_source` path in the hypothesis). The **Signal Construction Framework** (`signal_builder/`) bridges the gap between hypothesis specification and pipeline execution by building signals from raw data.

### Architecture

```
HypothesisSpec -> DataAdapter -> SignalExtractor -> SignalBuilder -> Signal File (.parquet)
                                                                         |
                                                                         v
                                                                  pipeline.py
```

### The Full Loop

```bash
# One command: hypothesis -> signal -> verdict
python run_loop.py --hypothesis hypothesis.json --output results/

# Or build signal separately, then test
python signal_builder/signal_builder.py --hypothesis hypothesis.json --output signals/
python pipeline.py --hypothesis hypothesis.json --output results/
```

### Data Adapters

| Adapter | Source | Cost | Status |
|---------|--------|------|--------|
| **FDA** | fda.gov briefing documents, Drugs@FDA | Free | Full implementation |
| **SEC EDGAR** | sec.gov filings (10-K, 10-Q, 8-K) | Free | Functional skeleton |
| **Yahoo Finance** | yfinance price/volume data | Free | Functional skeleton |
| **FMP** | Financial Modeling Prep API | Free tier (250/day) | Skeleton (needs API key) |
| **FRED** | St. Louis Fed macro data | Free (needs API key) | Functional skeleton |

### Signal Extractors

| Extractor | Features | Method |
|-----------|----------|--------|
| **Linguistic** | Hedging density, certainty markers, active/passive ratio, readability, pronoun ratio, sentiment, composite scores (BRLAS, departure language, pronoun divergence) | Deterministic (keyword + regex) |
| **Filing Diff** | Document version comparison | Skeleton |
| **Classification** | Text categorization | Skeleton |

### How the Loop Works

1. **Signal Builder** reads the `HypothesisSpec`, identifies required data adapters, acquires raw data, applies extractors, validates the output, and saves to `.parquet`.
2. **Pipeline** loads the signal file and runs the full test battery (universe, temporal, backtest, statistics, adversarial, factors, edge decay).
3. **Verdict** is produced: SURVIVED, SURVIVED_WARNING, BROKEN, INCONCLUSIVE, or UNTESTABLE.

### Proof of Life

```bash
# Run the FDA BRLAS test (synthetic data, full loop)
python tests/test_fda_brlas.py --verbose
```

This test exercises the full loop with synthetic FDA documents. If FDA.gov is reachable, it attempts live data. The synthetic dataset has known linguistic patterns (hedged benefits + certain risks for high-CRL drugs) that the extractor should detect, proving the loop is functional.

See `signal_builder/README.md` for detailed documentation on adding new adapters and extractors.

## Requirements

- Python 3.10+
- See `requirements.txt` for package versions
