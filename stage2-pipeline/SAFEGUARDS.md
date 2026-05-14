# Three Critical Safeguards — Structural Verdict Validity

**Version:** 1.0.0
**Status:** ACTIVE by default in signal builder and pipeline

Without these three safeguards, the pipeline produces structurally invalid verdicts — results that are indistinguishable from noise regardless of how rigorous the other components are. Each safeguard prevents a specific, well-documented failure mode in the quantitative finance and machine learning literature.

---

## SAFEGUARD 1: Temporal Contamination Detector

**File:** `signal_builder/contamination.py`
**What it prevents:** The "profit mirage" — backtested returns from LLM training-data memorization that vanish once the model's knowledge cutoff passes

### The Problem

When an LLM processes a historical document (e.g., a 2019 FDA briefing document), it may already "know" the outcome because that outcome was in its training data. The model doesn't need to analyze language — it can simply recall the drug was approved. A backtest using pre-cutoff data will show spectacular results that disappear the moment you test on post-cutoff events.

This is not a hypothetical concern. Every major LLM (GPT-4, Claude 3.5, Llama 3, Gemini) has a documented training cutoff. Any event that occurred before that cutoff — FDA drug approvals, earnings surprises, merger announcements, regulatory decisions — is potentially in the training corpus. A model asked to "analyze" a 2019 FDA document for a drug it knows was approved will output signals correlated with the known outcome, producing backtested alpha that is 100% spurious.

### Literature Failure Mode

This is the temporal equivalent of data leakage in machine learning. The standard remedy — out-of-sample testing — does not help if the model's training data IS the out-of-sample period. The literature on backtest overfitting (Bailey et al., 2014; Lopez de Prado, 2019) focuses on overfitting to price data, but LLM-based signals introduce a new leakage channel: the model's pretraining corpus.

### How It's Implemented

1. **Knowledge cutoff verification:** The LLM's documented training cutoff (default: 2023-10-01) is compared to every document's event date. Any document predating the cutoff is potentially contaminated.

2. **Placebo test** (optional, computationally expensive): For a random 20% subset of test cases, the document text is swapped with text from a DIFFERENT document (same domain, adjacent date, different outcome). If the signal predictiveness does not materially drop (threshold: 50% drop), the signal is leaking from training data rather than genuine text analysis. Example:
   - Original AUC for predicting CRL: 0.72
   - After placebo text swap: 0.18 (75% drop) -> **PASS** (signal depends on text)
   - After placebo text swap: 0.68 (6% drop) -> **FAIL** (signal leaks from training data)

3. **Pre/post cutoff comparison:** Signal predictiveness is computed separately for events before and after the knowledge cutoff. If the signal works on pre-cutoff events but degrades post-cutoff, contamination is confirmed.

4. **Signal file tagging:** Every signal file produced by the SignalBuilder carries:
   - `contamination_risk`: HIGH / MEDIUM / LOW / CLEAN
   - `contamination_rationale`: specific reasoning
   - `knowledge_cutoff_date`: the model's training cutoff
   - `pre_cutoff_events` / `post_cutoff_events`: counts
   - `placebo_test_result`: PASS / FAIL / NOT_RUN

5. **Verdict capping:** If contamination risk is HIGH and zero post-cutoff events exist, the verdict is capped at INCONCLUSIVE regardless of what the backtest shows.

### Special Case: Deterministic Extraction

The linguistic extractor uses deterministic keyword/regex methods — no LLM inference. For deterministic extraction, the contamination risk is CLEAN because there is no LLM to memorize training data. However, if the pipeline EVER uses an LLM for extraction (which the spec allows for complex tasks), contamination detection becomes critical. The detector documents the extraction method and adjusts risk accordingly.

### How to Verify It's Working

```bash
# Check contamination report in signal output
cat results/SIGNALS/{uuid}/{uuid}_contamination.json

# Expected output when extraction is deterministic:
# {
#   "contamination_risk": "CLEAN",
#   "contamination_rationale": "Extraction method is deterministic (keyword/regex)...",
#   "knowledge_cutoff_date": "2023-10-01",
#   "pre_cutoff_events": 120,
#   "post_cutoff_events": 0
# }

# When LLM extraction is used (hypothetical):
# {
#   "contamination_risk": "HIGH",
#   "contamination_rationale": "No post-cutoff events available... All data predates cutoff...",
#   "placebo_test_result": "NOT_RUN"
# }
```

### Verdict Confidence Levels

| Risk | Meaning | Verdict Cap |
|------|---------|-------------|
| CLEAN | Deterministic extraction; no LLM memorization possible | None |
| LOW | LLM used but post-cutoff data available and consistent | None |
| MEDIUM | Mixed pre/post cutoff, placebo test not run | SURVIVED_WARNING |
| HIGH | All data pre-cutoff, no post-cutoff validation possible | INCONCLUSIVE |

---

## SAFEGUARD 2: Survivorship Bias Guard

**File:** `signal_builder/survivorship.py`
**What it prevents:** Backtest return inflation from excluding stocks that went to zero

### The Problem

A backtest that only includes currently traded stocks misses every company that went bankrupt, was acquired at a discount, or was delisted for regulatory reasons. These stocks have systematically negative returns that are excluded from the analysis, inflating any strategy's apparent performance.

Consider a strategy that holds small-cap value stocks. Small-cap stocks have higher delisting rates, and delistings are disproportionately due to bankruptcy (total loss) or severe distress. By excluding delisted stocks, the strategy appears to capture a "size premium" or "value premium" that is actually just survivorship bias.

The magnitude is substantial: studies estimate survivorship bias inflates small-cap returns by 1-4% annually and US total market returns by 0.2-0.5% annually (CRSP delisting return data). For a strategy claiming 300 bps of alpha, 50-100 bps of that could be survivorship bias — the difference between a real edge and noise.

### Literature Failure Mode

This is one of the oldest and most well-documented biases in empirical finance (Dimson & Marsh, 1990; Shumway, 1997; CRSP delisting returns). The pipeline spec REQUIRES survivorship-bias-free universe construction (PIPELINE_SPEC.md Section 1.2: `include_delisted: true`), but the full implementation had not been built.

### How It's Implemented

1. **Delisted stock detection:** SEC EDGAR Form 25 filings (voluntary delisting) and Form 15 filings (deregistration) are queried for the test period. A built-in registry covers known major delistings (Hertz 2020, JCPenney 2020, SVB 2023, First Republic 2023, Twitter/X 2022, etc.).

2. **Delisting return estimation by reason:**
   - Bankruptcy: -95% (5% recovery assumption, conservative)
   - Regulatory seizure (FDIC): -85% to -90%
   - Going private: transaction-dependent (requires buyout price)
   - Acquisition/merger: transaction-dependent (requires deal premium)
   - Exchange delisting (OTC move): flag as data gap, OTC data not available
   - Unknown: -50% (highly uncertain, flagged)

3. **Universe validation:** Before any backtest, the universe is validated:
   ```
   Universe at 2019-Q1 to 2025-Q4: 3,842 stocks (3,791 active + 51 subsequently delisted)
   ```
   If delisted stock data is incomplete, the gap is explicitly reported.

4. **Bias impact estimation:** Quantifies how much survivorship bias inflates results:
   ```
   Survivorship bias inflates annualized returns by approximately X bps
   ```

5. **Confidence capping:**
   - Universe < 500 stocks AND no delistings: bias likely negligible -> LOW concern
   - Universe includes small/micro caps: bias can be significant -> cap at INCONCLUSIVE if delisted returns unverified
   - Always report survivorship assessment in audit trail

6. **Ticker reuse detection:** Checks CIK-to-ticker mapping to verify that the current company behind ticker XYZ matches the company during the test period. Flags any reuse events.

### How to Verify It's Working

```bash
# Check survivorship bias report in pipeline output
cat results/{uuid}/survivorship_bias_report.json

# Expected output:
# {
#   "total_tickers_in_universe": 3842,
#   "active_tickers": 3791,
#   "delisted_tickers": 51,
#   "delisted_with_returns": 48,
#   "delisted_missing_returns": 3,
#   "bias_assessment": "MODERATE",
#   "verdict_confidence_cap": "SURVIVED_WARNING",
#   "can_test_reliably": false
# }

# Check pipeline audit trail for survivorship section
python -c "
import json
with open('results/{uuid}/audit_trail.json') as f:
    trail = json.load(f)
    for entry in trail.get('entries', []):
        if entry.get('operation') == 'survivorship_bias_check':
            print(json.dumps(entry['outputs'], indent=2))
"
```

### Verdict Confidence Levels

| Data Completeness | Bias Severity | Verdict Cap |
|-------------------|---------------|-------------|
| FULL | NEGLIGIBLE (<10 bps) | None |
| FULL | MODERATE (10-50 bps) | None (report only) |
| FULL | SIGNIFICANT (50-200 bps) | SURVIVED_WARNING |
| PARTIAL | ANY | SURVIVED_WARNING |
| MINIMAL | ANY | SURVIVED_WARNING |
| NONE | Universe > 500 tickers | INCONCLUSIVE |
| NONE | Universe < 500 tickers | SURVIVED_WARNING |

---

## SAFEGUARD 3: Cumulative False Discovery Rate Tracker

**File:** `signal_builder/trial_tracker.py`
**What it prevents:** The silent drift of the effective false discovery rate upward with each BROKEN->refine->retest cycle

### The Problem

The pipeline applies Bonferroni and FDR corrections within each individual hypothesis test. But the loop generates, tests, refines, and retests hypotheses. Each iteration adds to the family of tests. The standard correction within a single test (e.g., adjusting for 5 p-values within one hypothesis) does nothing to control the cumulative false discovery rate across 30+ hypotheses tested across 3+ cycles of refinement.

This is a well-known problem in multiple testing: if you test 20 independent true-null hypotheses at alpha = 0.05, you expect 1 false positive. The Bonferroni correction for test #20 in isolation is alpha/5 = 0.01 within that test's p-values. But across 20 tests, the family-wise error rate is 1 - (1 - 0.05)^20 = 64% without correction. Within-test correction does not fix across-test multiplicity.

The literature (Ioannidis, 2005 "Why Most Published Research Findings Are False"; Simmons, Nelson, & Simonsohn, 2011 "False-Positive Psychology"; Harvey, Liu, & Zhu, 2016 "...and the Cross-Section of Expected Returns") identifies this as THE mechanism by which multi-stage research pipelines find spurious patterns.

### Literature Failure Mode

In the trading-strategy context specifically: Sullivan, Timmermann, and White (1999) showed that a universe of ~7,000 technical trading rules tested on the DJIA produced zero significant rules after applying White's Reality Check (a family-wise error rate control). Without the correction, many rules appeared significant. The parallel in our pipeline: 17 agents, each generating multiple hypotheses, each potentially refined 3 times, creates a test family of potentially 100+ tests. Without family-wise control, spurious SURVIVED verdicts are inevitable.

### How It's Implemented

1. **Persistent trial log** (`trial_family.json`):
   ```json
   {
     "investigation_id": "a1b2c3d4",
     "total_hypotheses_tested": 24,
     "total_tests_run": 31,
     "total_broken_refine_cycles": 7,
     "trials": [...]
   }
   ```

2. **Family-wise error correction across ALL trials:**
   - Bonferroni: adjusted alpha = 0.05 / total_tests
   - Benjamini-Hochberg FDR: ranks all p-values, computes BH threshold
   - Reports BOTH: per-hypothesis significance AND investigation-wide significance

3. **Hard refinement cap enforcement:**
   - Max 3 submissions per hypothesis UUID
   - Exceed this and the verdict is: "ARCHIVED (REFINEMENT CAP REACHED)"
   - This prevents the worst form of p-hacking: iterative refinement with data

4. **Global cap enforcement:**
   - If an entire Stage 1 -> Bridge cycle produces zero SURVIVED hypotheses:
     "INVESTIGATION TERMINATED: No hypotheses survived cycle N. The idea space in this direction appears exhausted."
   - Prevents infinite-loop searching that guarantees spurious findings

5. **Honest reporting in every verdict:**
   ```
   This hypothesis is trial 12 of 31 in this investigation.
   Bonferroni-adjusted significance threshold: p < 0.0016.
   Unadjusted p-value for this test: 0.03.
   The unadjusted result is nominally significant but does NOT survive family-wise correction.
   ```
   This prevents the most common form of false confidence: reporting individual-test p-values as if they were the only test run.

6. **Investigation context:** Initialized at loop start, passed through to signal builder and pipeline, embedded in every verdict output.

### How to Verify It's Working

```bash
# Check trial family file
cat results/trial_family.json

# Look for investigation context in verdict
python -c "
import json
with open('results/{uuid}/verdict.json') as f:
    v = json.load(f)
    # Trial family context is in the warnings
    for w in v.get('warnings', []):
        if 'FAMILY-WISE' in w:
            print(w)
"

# Check that refinement cap is enforced (run same hypothesis 4 times)
python run_loop.py --hypothesis my_hypothesis.json --output results/
# On the 4th run, output should be:
# VERDICT: ARCHIVED (REFINEMENT CAP REACHED)
```

### Verdict Interpretation with Family-Wise Context

| Scenario | Per-Test p-value | Family-wise Threshold | Correct Interpretation |
|----------|-----------------|----------------------|----------------------|
| Trial 3 of 5 | 0.01 | 0.01 (Bonferroni) | Marginally significant |
| Trial 12 of 31 | 0.03 | 0.0016 (Bonferroni) | NOT significant family-wise |
| Trial 20 of 50 | 0.001 | 0.001 (Bonferroni) | At the boundary |
| Trial 5 of 8 | 0.0001 | 0.00625 (Bonferroni) | Clearly significant |

---

## Integration Architecture

```
run_loop.py
    |
    +---> TrialTracker (initialized here, passed downstream)
    |
    +---> SignalBuilder
    |         |
    |         +---> DataAdapter.acquire()
    |         +---> SignalExtractor.extract()
    |         +---> ContaminationDetector.detect()  <-- SAFEGUARD 1
    |         +---> SurvivorshipGuard.validate()    <-- SAFEGUARD 2
    |         +---> Save signal + safeguards JSON
    |
    +---> HypothesisPipeline
              |
              +---> Universe Construction
              |         +---> SurvivorshipGuard           <-- SAFEGUARD 2 (universe)
              +---> Backtest -> Statistics -> Adversarial -> Factors -> Edge Decay
              +---> Verdict + investigation-wide context  <-- SAFEGUARD 3 (FDR)
```

## What Verdict Confidence Levels Mean

| With All Safeguards | Without Safeguards |
|---------------------|-------------------|
| SURVIVED: The signal survived 7 adversarial tests, contamination check is CLEAN or LOW, survivorship bias is NEGLIGIBLE, and the result survives family-wise FDR correction (trial 5 of 12). This is actionable. | SURVIVED: The signal had a p-value < 0.05 in one test. Might be trial 47 of 100, all pre-cutoff contaminated, on a survivor-biased universe. Structurally invalid. |
| SURVIVED_WARNING: Edge exists but has caveats (decaying, regime-dependent, survivorship data incomplete). Monitor closely. | SURVIVED_WARNING: Not distinguished from SURVIVED because safeguards weren't run. Both equally meaningless. |
| BROKEN: Signal failed at least one gate. Specific failure documented. This is success — the pipeline did its job. | BROKEN: Signal failed. But other "SURVIVED" results are equally broken, just not detected. |
| INCONCLUSIVE: Data constraints (contamination HIGH, survivorship NONE) prevent reliable testing. Need more/better data. | Not produced — pipeline confidently returns wrong answer. |
| ARCHIVED: Refinement cap reached. Prevents p-hacking via iterative resubmission. | Not enforced — hypothesis refined indefinitely until p < 0.05. |

## Running Without Safeguards (Not Recommended)

The safeguards are active by default. To disable them (for debugging only):

```python
# Disable in SignalBuilder
builder = SignalBuilder(
    enable_contamination_detection=False,
    enable_survivorship_guard=False,
)

# Disable in Pipeline
pipe = HypothesisPipeline(
    enable_survivorship_guard=False,
)
```

Disabling safeguards means verdicts are structurally invalid per the quantitative finance literature. Do this only when testing pipeline infrastructure, never when evaluating whether a trading edge is real.
