# Signal Construction Framework

**Version:** 1.0.0

The missing layer that turns hypothesis testing from manual assessment into an automated loop. Takes a hypothesis specification, acquires raw data, builds the signal, and produces a file ready for `pipeline.py` ingestion.

## Architecture

```
HypothesisSpec (JSON)
    |
    v
SignalBuilder (orchestrator)
    |
    +---> DataAdapter.acquire()     # Download raw data from source
    |         |
    |         +---> FDA Adapter     # fda.gov briefing documents
    |         +---> SEC EDGAR       # sec.gov filings
    |         +---> Yahoo Finance   # Price data via yfinance
    |         +---> FMP             # Financial Modeling Prep API
    |         +---> FRED            # Federal Reserve macro data
    |
    +---> DataAdapter.validate()    # Check data quality
    |
    +---> SignalExtractor.extract() # Build signal from raw data
    |         |
    |         +---> Linguistic      # Hedging, certainty, readability, etc.
    |         +---> Filing Diff     # Compare document versions (skeleton)
    |         +---> Classification  # Category labels (skeleton)
    |
    v
Signal File (.parquet)
    |
    v
pipeline.py                        # Test the signal
    |
    v
Empirical Verdict (JSON)
```

## Quick Start

```bash
# Build a signal from a hypothesis file
python signal_builder/signal_builder.py --hypothesis hypothesis.json --output signals/

# Run the full loop (build + test)
python run_loop.py --hypothesis hypothesis.json --output results/
```

## How to Add a New Data Adapter

1. Create a new file in `signal_builder/adapters/` (e.g., `twitter.py`)
2. Subclass `DataAdapter` from `base.py`
3. Implement `source_name`, `version`, `acquire()`, `validate()`
4. Optionally implement `health_check()`
5. Register in `adapters/__init__.py` `ADAPTER_REGISTRY` dict

### Minimal Adapter Template

```python
from ..base import DataAdapter, DataSourceSpec, RawData

class MyAdapter(DataAdapter):
    @property
    def source_name(self) -> str:
        return "my_source"

    @property
    def version(self) -> str:
        return "1.0.0"

    def acquire(self, spec: DataSourceSpec) -> RawData:
        # Download/acquire data here
        # Return RawData(records=pd.DataFrame(...), source_type=..., provider=...)
        pass

    def validate(self, raw_data: RawData) -> tuple[bool, list[str]]:
        return raw_data.validate()
```

## How to Add a New Signal Extractor

1. Create a new file in `signal_builder/extractors/` (e.g., `named_entity.py`)
2. Subclass `SignalExtractor` from `base.py`
3. Implement `extractor_name`, `version`, `extract()`
4. Register in `extractors/__init__.py` `EXTRACTOR_REGISTRY` dict

## Hypothesis Specification Format

Hypotheses must conform to the format in `PIPELINE_SPEC.md` Section 1. The signal builder reads the same `HypothesisSpec` that `pipeline.py` accepts.

Key fields for signal building:
- `data_sources`: List of `DataSourceSpec` objects specifying providers and date ranges
- `signal`: Signal specification (name, type, direction)
- `time_period`: Start and end dates for data acquisition

## Signal File Schema

All generated signal files use this standard schema:

**Wide format (primary, for pipeline ingestion):**
- Index: date (DatetimeIndex) — the observation date
- Columns: ticker/identifier (e.g., drug names, ticker symbols)
- Values: signal values (numeric)

**Metadata file (alongside .parquet):**
- `builder_version`: Framework version
- `adapter_name` / `adapter_version`: Which adapter was used
- `extractor_name` / `extractor_version`: Which extractor was used
- `extractor_method`: "deterministic" or "llm_temperature_zero"
- Parameters used, timestamps, content hashes

## Three Critical Safeguards

The signal builder runs three safeguards after signal extraction but before saving. These are the difference between a verdict you can act on and a verdict the literature would classify as structurally invalid.

### SAFEGUARD 1: Temporal Contamination Detector (`contamination.py`)

**Problem:** When an LLM processes a historical document (e.g., a 2019 FDA briefing document), it may already "know" the outcome because that outcome was in its training data. The model doesn't need to analyze language — it can simply recall the drug was approved.

**Solution:** Three-pronged detection:
1. Knowledge cutoff verification — flag documents predating the LLM cutoff (default: 2023-10-01)
2. Placebo test — swap text across documents; if signal still works, it's leaking from training data
3. Pre/post cutoff comparison — signal should work on post-cutoff events too

**Output:** Every signal file is tagged with `contamination_risk` (HIGH/MEDIUM/LOW/CLEAN) and rationale. HIGH risk + no post-cutoff data caps verdict to INCONCLUSIVE.

### SAFEGUARD 2: Survivorship Bias Guard (`survivorship.py`)

**Problem:** A backtest that only includes currently traded stocks misses every company that went to zero, systematically inflating returns.

**Solution:**
1. SEC EDGAR Form 25/15 parsing for delisted stock detection
2. Delisting return estimation by reason (bankruptcy: -95%, acquisition: premium-dependent, etc.)
3. Universe validation: "Universe at 2019-Q1: 3,842 stocks (3,791 active + 51 subsequently delisted)"
4. Bias impact estimation: quantify return inflation from survivor-only vs. full universe
5. Ticker reuse detection via CIK-to-ticker mapping

**Output:** Survivorship bias assessment (NEGLIGIBLE/MODERATE/SIGNIFICANT/SEVERE) and confidence cap. If delisted returns cannot be sourced for a large universe, verdict confidence is capped.

### SAFEGUARD 3: Cumulative False Discovery Rate Tracker (`trial_tracker.py`)

**Problem:** The pipeline applies Bonferroni/FDR within each hypothesis test, but the loop generates, tests, refines, and retests. Each BROKEN->refine->retest cycle adds to the family of tests. Without tracking TOTAL trials, the effective FDR drifts upward. This is THE mechanism by which multi-agent systems find spurious patterns.

**Solution:**
1. Persistent `trial_family.json` log of every hypothesis test across the entire investigation
2. Family-wise Bonferroni: adjusted alpha = 0.05 / total_tests
3. Benjamini-Hochberg FDR across all p-values in the trial family
4. Hard refinement cap: max 3 submissions per hypothesis UUID
5. Global termination: zero SURVIVED in a cycle -> investigation exhausted
6. Honest reporting in every verdict: "This hypothesis is trial 12 of 31. Bonferroni threshold: p < 0.0016. Unadjusted p-value: 0.03. Does NOT survive family-wise correction."

**Integration:** Initialized at loop start, passed through to signal builder and pipeline. Every verdict output includes investigation-wide FDR context.

## Design Principles

1. **LLM non-determinism:** Primary extraction is keyword/regex-based (deterministic). LLM extraction is optional but must use temperature=0 with fixed seeds.

2. **Retail accessibility:** All data sources are free or low-cost. Paid APIs (FMP, FRED) are optional with clear fallbacks.

3. **Reproducibility:** Every signal file embeds metadata (builder version, adapter version, extractor version, parameters, content hashes). Audit trail chains back from pipeline verdict to signal construction.

4. **Error handling:** If data cannot be acquired, the signal builder raises `UntestableHypothesisError` with specific data gap documentation.

5. **The loop is the product:** Every design decision supports the goal of `hypothesis JSON in, empirical verdict out`.
