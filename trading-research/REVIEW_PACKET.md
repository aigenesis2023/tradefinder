# Simplified Engine v2.1 — Review Packet

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
statistically too small for sub-rule validation. **v2.1 incorporates external
reviewer feedback** that flagged (a) the 90-day hold as on the short end of academic
guidance, (b) the 14-day cluster window as artificially splitting coordinated
campaigns, (c) the 0.02% materiality threshold as mathematically redundant, and
(d) pure-routine clusters as worth auto-discarding rather than surfacing.

---

## 1. What the engine does

Daily mechanical scan:

1. Loads a watchlist of US-listed primary-exchange tickers, $200M–$3B market cap (cached weekly).
2. For each ticker, fetches SEC EDGAR Form 4 filings — recent **45 days** for cluster detection,
   plus ~3 years of history for routine/opportunistic classification.
3. Detects clusters: 3+ unique qualifying-role insiders, ≥$100K per transaction, **within 30 days**.
4. Excludes 10b5-1 plan trades and institutional-entity filer names.
5. **Soft-gate**: discards clusters with `opportunistic_count == 0` (pure-routine clusters
   carry near-zero predictive content per CMP 2012).
6. Re-fetches market cap via yfinance and discards if it has drifted outside $200M–$3B
   since the (up-to-7-day-stale) watchlist cache.
7. Tags three informational metadata fields per surfaced signal:
   - **Opportunistic count** (Cohen-Malloy-Pomorski 2012): how many cluster members are
     NOT routine traders (i.e., did NOT buy in the same calendar month for 3 consecutive
     prior years).
   - **Short interest + DISAGREEMENT flag** (Chung-Sul-Wang 2019): % of float shorted,
     plus ⚡ tag when between 10–40% (insiders buying into elevated shorts).
   - **Analyst coverage count** (Lakonishok-Lee 2001): # of sell-side analysts.
8. Outputs a ranked report (by opportunistic_count → unique_insiders → materiality)
   with full metadata per candidate.
9. **No LLM. No scoring formula. No regime gating. No sizing multipliers. No materiality
   % filter (removed in v2.1 — was mathematically redundant). The only quality gate beyond
   the cluster filter is the opportunistic soft gate.**

The discretionary operator performs fundamental research (financials, news, valuation,
sector context) on each surfaced ticker before any trade decision.

---

## 2. Parameter table

| Parameter | Value | Literature anchor |
|---|---|---|
| Unique insiders | ≥ 3 | Multi-insider clusters significantly outperform single-insider trades |
| Per-transaction floor | ≥ $100K | Defensible default for meaningful commitment |
| Cluster window | **30 days** (v2.1, was 14d) | Academic studies use 1-3 month windows |
| Lookback (cluster detection) | **45 days** (v2.1, was 21d) | Accommodates 30d window with buffer |
| Lookback (routine classification) | ~3 years | Cohen-Malloy-Pomorski 2012 |
| Qualifying roles | CEO, CFO, COO, Chairman, Director, President, EVP, SVP | Standard cohort |
| Transaction code | "P" (open-market) only | Excludes options/awards/gifts |
| 10b5-1 plans | Excluded | Near-zero predictive content |
| Market cap | $200M – $3B | Smaller-cap effect (Lakonishok-Lee; Jeng et al.) |
| Materiality threshold | **None** (v2.1, was 0.02%) | $100K × 3 minimum already enforces commitment; 0.02% was redundant |
| Recommended hold | **180 days** (v2.1, was 90d) | Jeng-Metrick-Zeckhauser; Cohen-Malloy-Pomorski; Lakonishok-Lee |
| Position sizing | Flat: max 2% of equity per trade | No literature support for differential sizing |
| Round-trip cost assumption | 1.0% | Realistic for retail at $200M–$3B |
| Opportunistic/routine | **Soft gate ≥ 1 + metadata** (v2.1, was metadata-only) | Cohen-Malloy-Pomorski 2012 |
| Short-interest disagreement | Informational flag (NOT a gate); ⚡ at 10–40% of float | Chung-Sul-Wang 2019 |
| Analyst coverage count | Informational flag (NOT a gate) | Lakonishok-Lee 2001 |
| Regime (VIX/IWM) | Reported, not gated | Literature mixed |

---

## 3. Empirical expectation

From post-2010 US literature, median estimates for our exact configuration:

| Metric | Estimate |
|---|---|
| Gross return per 180-day trade | 4–8% |
| Net return after 1% costs | 3–7% |
| Annualized (continuous deployment) | ~6–14% net |
| SPY benchmark (annualized) | ~10% nominal |
| Expected signals per month | ~2–5 (v2.1: wider window + no materiality threshold) |
| Per-trade win rate (absolute, not alpha) | 55–65% |

**The strategy is roughly competitive with passive indexing on standalone return.** Value
comes from (a) the screen serving as input to discretionary research, and (b) diversification
from pure market beta. This is not pitched as outperformance.

---

## 4. The quality-flag treatment (v2.1)

Three academically-supported quality flags are computed per signal. After v2.1 reviewer
feedback, treatment is no longer uniform:

| Flag | v2.1 treatment | Rationale |
|---|---|---|
| **Opportunistic count** (CMP 2012) | **Soft gate (≥1 required) + metadata** | Pure-routine clusters carry ~0 predictive content per CMP. Auto-discarding them removes definitionally-noisy candidates without significantly reducing useful pipeline volume. |
| **Short-interest DISAGREEMENT** (Chung-Sul-Wang 2019) | Metadata only (not a gate) | Chung-Sul-Wang lift concentrates at 1-month horizons; our 180d hold sits in the decay window. Lee et al. 2018 "false signaling" risk would expose us to systematic failures if hard-gated. |
| **Analyst coverage** (Lakonishok-Lee 2001) | Metadata only (not a gate) | Correlated with market-cap band already applied. Hard-gating would tighten the funnel without independent edge gain. |

The architectural philosophy: the engine's job is to surface structurally-meaningful
events. The opportunistic soft gate is the only quality filter beyond the cluster
definition itself because it directly applies the strongest finding from the engine's
anchor paper (CMP 2012). The other two flags inform the operator's discretionary review
but do not gate.

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

## 6. What was added in v2 / v2.1 (vs v1)

**v2:**
1. **Opportunistic/routine classification** per Cohen-Malloy-Pomorski 2012.
2. **90-day hold horizon** replacing 10d/20d.
3. **$200M–$3B market cap band** replacing $500M–$5B (smaller-cap literature support).
4. **Flat 1.0x position sizing** replacing cluster-size and regime multipliers.
5. **Short interest + DISAGREEMENT flag** (10–40% band, Chung-Sul-Wang 2019).
6. **Analyst coverage count** (Lakonishok-Lee 2001).
7. **Explicit step-1 screening framing** — engine no longer pitched as alpha generator.

**v2.1 (incorporating reviewer feedback):**
8. **Hold horizon 90 → 180 days** — literature peaks ~6mo (Jeng et al.; CMP).
9. **Cluster window 14 → 30 days + EDGAR lookback 21 → 45 days** — academic studies
   use 1-3 month windows; insider campaigns span weeks.
10. **Materiality threshold (0.02%) removed** — was mathematically redundant.
11. **Opportunistic soft gate (≥ 1 opportunistic insider required)** — automatically
    discard pure-routine clusters per CMP 2012 noise finding.
12. **Documented IPO / new-listing edge case** — companies listed < 3 years ago default
    to all-opportunistic classification.
13. **Documented fresh mcap re-check** — pipeline re-fetches market cap; out-of-band
    drift since watchlist cache is caught.

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

1. **Hold horizon now 180 days** (v2.1). Is this the right ceiling, or does the
   literature support an even longer hold (12 months)? Capital efficiency trade-off?

2. **Opportunistic soft gate (≥1)** is now the only quality gate beyond the cluster
   filter itself. Is this the right level of strictness, or should it be tighter
   (e.g., majority opportunistic) or looser (pure metadata)?

3. **Cluster window now 30 days** with 45-day EDGAR lookback. Is this the right
   width, or should it be wider (60 days) for completeness? Does the wider window
   risk capturing unrelated activity that wasn't a real cluster?

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
