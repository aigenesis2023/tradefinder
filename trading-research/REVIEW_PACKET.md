# Simplified Engine v2 — Review Packet

Self-contained packet for an outside reviewer. Paste the whole document in and ask
for design / empirical / methodological critique.

## Reviewer framing

This is a **step-1 screening tool**, not a complete trading strategy. The engine surfaces
structurally-meaningful insider-cluster events from SEC Form 4 data. The discretionary
operator does fundamental follow-up research on each surfaced candidate before any
trade decision. The engine does not claim a standalone edge over passive indexing —
realistic expectation is roughly 2–4% gross / 1–3% net per 90-day trade, comparable to
passive indexing on risk-adjusted terms. The engine's value is the screen, not the
alpha.

Earlier iterations of this project (v3.1) overclaimed validated edge with LLM
narrative scaffolding, multi-factor scoring, and untested catalysts (government
contracts, confirming signals). v1 stripped all of that to the validated mechanical
cluster filter. v2 recalibrated parameters against academic literature
(Cohen-Malloy-Pomorski 2012, Jeng-Metrick-Zeckhauser 2003, Lakonishok-Lee 2001,
Chung-Sul-Wang 2019) rather than our own backtest, which we determined is
statistically too small for sub-rule validation.

---

## 1. What the engine does

Daily mechanical scan:

1. Loads a watchlist of US-listed primary-exchange tickers, $200M–$3B market cap (cached weekly).
2. For each ticker, fetches SEC EDGAR Form 4 filings — recent 21 days for cluster detection,
   plus ~3 years of history for routine/opportunistic classification.
3. Detects clusters: 3+ unique qualifying-role insiders, ≥$100K per transaction, within 14 days.
4. Excludes 10b5-1 plan trades and institutional-entity filer names.
5. Filters by materiality (cluster total ≥ 0.02% of market cap).
6. Tags three informational metadata fields per surfaced signal:
   - **Opportunistic count** (Cohen-Malloy-Pomorski 2012): how many cluster members are
     NOT routine traders (i.e., did NOT buy in the same calendar month for 3 consecutive
     prior years).
   - **Short interest + DISAGREEMENT flag** (Chung-Sul-Wang 2019): % of float shorted,
     plus ⚡ tag when between 10–40% (insiders buying into elevated shorts).
   - **Analyst coverage count** (Lakonishok-Lee 2001): # of sell-side analysts.
7. Outputs a ranked report (by opportunistic_count → unique_insiders → materiality)
   with full metadata per candidate.
8. **No LLM. No scoring formula. No regime gating. No sizing multipliers. No gates beyond
   the validated cluster filter — all three metadata flags are informational only.**

The discretionary operator performs fundamental research (financials, news, valuation,
sector context) on each surfaced ticker before any trade decision.

---

## 2. Parameter table

| Parameter | Value | Literature anchor |
|---|---|---|
| Unique insiders | ≥ 3 | Multi-insider clusters significantly outperform single-insider trades |
| Per-transaction floor | ≥ $100K | Defensible default for meaningful commitment |
| Cluster window | 14 days | Operational default; literature uses 2d–30d windows |
| Lookback (cluster detection) | 21 days | Recent activity only |
| Lookback (routine classification) | ~3 years | Cohen-Malloy-Pomorski 2012 |
| Qualifying roles | CEO, CFO, COO, Chairman, Director, President, EVP, SVP | Standard cohort |
| Transaction code | "P" (open-market) only | Excludes options/awards/gifts |
| 10b5-1 plans | Excluded | Near-zero predictive content |
| Market cap | $200M – $3B | Smaller-cap effect (Lakonishok-Lee; Jeng et al.) |
| Materiality | ≥ 0.02% of market cap | Operational filter (no academic basis) |
| Recommended hold | **90 days** | Jeng-Metrick-Zeckhauser; Cohen-Malloy-Pomorski; Lakonishok-Lee |
| Position sizing | Flat: max 2% of equity per trade | No literature support for differential sizing |
| Round-trip cost assumption | 1.0% | Realistic for retail at $200M–$3B |
| Opportunistic/routine | Informational flag (NOT a gate) | Cohen-Malloy-Pomorski 2012 |
| Short-interest disagreement | Informational flag (NOT a gate); ⚡ at 10–40% of float | Chung-Sul-Wang 2019 |
| Analyst coverage count | Informational flag (NOT a gate) | Lakonishok-Lee 2001 |
| Regime (VIX/IWM) | Reported, not gated | Literature mixed |

---

## 3. Empirical expectation

From post-2010 US literature, median estimates for our exact configuration:

| Metric | Estimate |
|---|---|
| Gross return per 90-day trade | 2–4% |
| Net return after 1% costs | 1–3% |
| Annualized (continuous deployment) | ~4–12% net |
| SPY benchmark (annualized) | ~10% nominal |
| Expected signals per month | ~1–3 |
| Per-trade win rate (absolute, not alpha) | 55–65% |

**The strategy is roughly competitive with passive indexing on standalone return.** Value
comes from (a) the screen serving as input to discretionary research, and (b) diversification
from pure market beta. This is not pitched as outperformance.

---

## 4. The three metadata flags — why they're informational only

We made a deliberate design choice to surface three academically-supported quality flags
as **metadata, not as gates**. Reasoning is the same in each case:

| Flag | Why not a gate |
|---|---|
| **Opportunistic count** (CMP 2012) | Literature strongly supports it as a quality differentiator. But gating reduces sample size in a strategy already producing ~1–3 signals/month. The operator's discretionary review uses this flag as input. |
| **Short-interest DISAGREEMENT** (Chung-Sul-Wang 2019) | The headline combined-signal lift in Chung-Sul-Wang is concentrated at 1-month horizons; our 90d hold sits in the decay window. Also, Lee et al. 2018 documents a "false signaling" failure mode (insiders buying defensively into shorted names, price support reverts within a year) that hard-gating would expose us to. |
| **Analyst coverage** (Lakonishok-Lee 2001) | Largely correlated with market-cap band, which we already filter on. Surfacing the raw number lets the operator see whether a candidate is genuinely neglected (~5 analysts) or a well-followed small-cap (~15+). |

The architectural philosophy: the engine's job is to surface structurally-meaningful events.
The operator's job is to apply discretionary judgment using all available information,
including these flags. Gating the engine on flags whose marginal contribution is uncertain
at our exact configuration would reduce candidate volume without proportional edge gain.

---

## 5. What was deliberately removed (vs prior versions)

| Removed | Why |
|---|---|
| LLM agents (Bull/Bear/Supervisor/Synthesis) | Narrative, not signal. Removed in v1. |
| Composite scoring + weights | With one signal type, weights have nothing to weight. v1. |
| Government contract catalyst | Zero backtest evidence. v1. |
| Neglect screen, information asymmetry score | Not in validated cohort. v1. |
| Confirming signals (hiring, 13F, Russell, state contracts) | Data unavailable or fires too rarely. v1. |
| High-Upside score, theme clustering | Re-encoded info or unused at this scale. v1. |
| 10-day / 20-day hold horizons | Literature consistently supports 90–180 days. v2. |
| Cluster-size sizing multipliers (1.0/1.25/1.5x) | n=7 elite sub-cohort cannot support a sizing rule. v2. |
| Regime sizing multiplier | Not in validated cohort; literature mixed. v2. |
| Elite extension to 20-day hold | Same. v2. |
| Hard-gating on short interest | Would cut sample ~90%; Chung-Sul-Wang lift mostly at 1-month horizon. v2. |

---

## 6. What was added in v2 (vs v1)

1. **Opportunistic/routine classification** per Cohen-Malloy-Pomorski 2012 —
   informational metadata, not a gate.
2. **90-day hold horizon** replacing 10d/20d.
3. **$200M–$3B market cap band** replacing $500M–$5B (smaller-cap literature support).
4. **Flat 1.0x position sizing** replacing cluster-size and regime multipliers.
5. **Short interest + DISAGREEMENT flag** (10–40% band, Chung-Sul-Wang 2019) —
   informational metadata.
6. **Analyst coverage count** (Lakonishok-Lee 2001) — informational metadata.
7. **Explicit step-1 screening framing** — engine no longer pitched as alpha generator.

---

## 7. Known weaknesses for adversarial scrutiny

### A. Statistical fragility of our own backtest
Our n=65 events after event-dedup (originally n=93, but the cluster-detection logic
created rolling-window duplicates — SSP alone appeared 30 times in n=93, representing
a single ~3-month buying campaign). Too small to validate any sub-rule. The engine
is now calibrated against academic literature with much larger samples (~50,000+
transactions in foundational studies), not against our own data.

### B. Post-SOX effect attenuation
Sarbanes-Oxley (2002) cut Form 4 disclosure lag from up to 40 days to 2 business days.
Classical pre-2002 effect sizes likely overstate today's edge. Recent studies find
attenuated magnitudes. Median academic estimate of 2–4% gross per 90d already
incorporates this; reviewers should flag if they think 2–4% is still optimistic.

### C. Transaction-cost dependence
At the low end of the academic range (~1.5% gross per 90d), 1% round-trip costs
nearly eliminate the edge. Limit orders are essential at $200M–$3B market caps.

### D. Materiality threshold (0.02%) has no academic basis
Practitioner rule-of-thumb. Reviewers should suggest whether 0.02% is appropriate.
Literature has not directly studied % of market cap thresholds.

### E. Sparse signal rate
Expected ~1–3 signals per month. A 60-day paper trade will produce ~2–6 trades —
anecdote, not validation. The engine requires year+ of operation to accumulate
meaningful data.

### F. Three metadata flags = informational decisions that may need to become gates
We chose informational-only for all three (opportunistic, short interest, analyst
coverage). The empirical literature *suggests* hard gating could improve hit rate
at the cost of sample size. Reviewers may disagree with the not-gating decision.

### G. Engine is not a complete strategy
The discretionary research the operator does on each surfaced ticker is where most
of the realised outcome will come from. The engine is only the screen.

### H. Data quality of metadata fields
- `shortPercentOfFloat`: yfinance pulls from FINRA bi-monthly reports — up to 3-week
  lag. Sometimes missing for thinly-followed names.
- `numberOfAnalystOpinions`: Yahoo Finance updates irregularly; occasionally returns
  0 for names that do have at least one analyst.
- `is_routine` classification depends on 3-year SEC Form 4 history per insider;
  newer-listed companies or recent IPOs may not have enough history.

The engine reports `None` / "not available" honestly rather than guessing.

---

## 8. Four questions for the reviewer

1. **Hold horizon**: is 90 days the right choice? Or should it be 180 days (some
   literature peaks closer to 6 months)? Current choice balances capital efficiency
   against alpha capture.

2. **The "informational only" decision for all three flags** (opportunistic, short
   interest, analyst coverage) is the most consequential design choice in v2. Should
   any of them be hard gates instead? On what empirical basis?

3. **Materiality threshold** (0.02% of market cap) — practitioner rule, no academic
   basis. Suggest a defensible alternative or confirm this is reasonable.

4. **Single biggest blind spot you see** that we haven't already flagged in section 7.

---

## 9. Repo structure

```
trading-research/
├── CLAUDE.md                       # normative rulebook (v2 with metadata sections)
├── REVIEW_PACKET.md                # this document
├── run_pipeline.py                 # main entry, 90d hold, no LLM
├── orchestrator/
│   ├── insider_scanner.py          # SEC EDGAR Form 4 + 3yr opportunistic classification
│   ├── regime_gate.py              # VIX/VIX3M, IWM 20d MA — informational only
│   ├── universe_builder.py         # yfinance screener, $200M–$3B
│   └── state_manager.py            # SQLite logging + dedup
├── backtest/
│   ├── measure_absolute_returns.py # post-hoc measurement on n=65 cohort
│   └── (validation infrastructure unchanged from v1)
├── data/                           # SQLite DB
├── cache/                          # CIK map, Form 4 history, watchlist
└── research_logs/                  # per-run reports (markdown)
```

Runtime surface (excluding backtest): ~1,400 lines of Python.

---

## 10. Academic references

Engine parameters trace to:

- **Lakonishok & Lee (2001)**, "Are Insider Trades Informative?", *Review of Financial Studies* — size effect, analyst coverage effect
- **Jeng, Metrick & Zeckhauser (2003)**, "Estimating the Returns to Insider Trading", *Review of Economics and Statistics* — 6-month horizon
- **Cohen, Malloy & Pomorski (2012)**, "Decoding Inside Information", *Journal of Finance* — routine vs opportunistic classification (82bps/month for opportunistic, ~0 for routine)
- **Brochet (2010)**, on post-SOX information content of insider trades
- **Wang, Shin & Francis (2012)**, "Are CFOs' Trades More Informative…?", *JFQA*
- **Alldredge & Blank (2019)**, on insider trade clustering
- **Kang, Kim & Wang (2018)**, on cluster trade timing post-SOX
- **Chung, Sul & Wang (2019)**, *Journal of Portfolio Management* — short-interest + insider-buying combined signal
- **Lee et al. (2018)** working paper, "Insider Purchases after Short Interest Spikes" — false signaling caveat

---

## 11. Style preference for review

Direct, structured, evidence-led. Push back on parameters that aren't well-justified.
The operator has been repeatedly pushing the project toward less complexity and more
honesty — sycophantic agreement is not useful. Adversarial review is.

Particularly welcome:
- Identification of any parameter not anchored to a specific citation
- Skepticism on the "metadata not gate" decision for the three flags
- Realistic execution friction estimates we may have understated
- Anything we've missed about how this strategy actually plays out for a small retail operator
