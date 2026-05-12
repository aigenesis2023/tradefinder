# Simplified Engine v2 — Review Packet

A self-contained packet for an outside reviewer. Paste the whole document in and ask
for design / empirical / methodological critique.

## Reviewer framing

This is a **step-1 screening tool**, not a complete trading strategy. The engine surfaces
structurally-meaningful insider-cluster events from SEC Form 4 data. The discretionary
operator does fundamental follow-up research on each surfaced candidate before any trade.
The engine does not claim a standalone edge over passive indexing; its value is the
screen, not the alpha.

This packet replaces an earlier "v3.1" review packet that overclaimed validated edge.
The v1 simplification stripped LLM debate layers, multi-factor scoring, and untested
catalysts. v2 then recalibrated the remaining mechanical engine against academic
literature (Cohen-Malloy-Pomorski 2012, Jeng-Metrick-Zeckhauser 2003, Lakonishok-Lee
2001) rather than our own n=65 backtest, which is statistically too small for any
sub-rule validation.

---

## 1. What the engine does

Daily mechanical scan:

1. Loads a watchlist of US-listed primary-exchange tickers, $200M–$3B market cap (cached weekly).
2. For each ticker, fetches SEC EDGAR Form 4 filings.
3. Detects clusters: 3+ unique qualifying-role insiders, ≥$100K per transaction, within 14 days.
4. Excludes 10b5-1 plan trades and institutional-entity filer names.
5. Filters by materiality (cluster total ≥ 0.02% of market cap).
6. For each cluster member, fetches ~3 years of prior Form 4 history to classify
   the member as routine or opportunistic per Cohen-Malloy-Pomorski (2012).
7. Outputs a ranked list of candidates with metadata (cluster size, opportunistic count,
   materiality, market cap, liquidity, insider names, recommended hold).
8. No LLM. No scoring formula. No regime gating. No sizing multipliers.

The discretionary operator then performs fundamental research (financials, news,
valuation, sector context) on each surfaced ticker before any trade decision.

---

## 2. Parameter table

| Parameter | Value | Literature anchor |
|---|---|---|
| Unique insiders | ≥ 3 | Multi-insider clusters significantly outperform single-insider trades |
| Per-transaction floor | ≥ $100K | Defensible default for meaningful commitment |
| Cluster window | 14 days | Operational default; literature uses 2d–30d windows |
| Lookback window (current) | 21 days | Recent activity only |
| Lookback window (history check) | ~3 years | Cohen-Malloy-Pomorski 2012 |
| Qualifying roles | CEO, CFO, COO, Chairman, Director, President, EVP, SVP | Standard cohort |
| Transaction code | "P" only | Open-market purchases |
| 10b5-1 plans | Excluded | Near-zero predictive content |
| Market cap | $200M – $3B | Smaller-cap effect (Lakonishok-Lee; Jeng et al.) |
| Materiality | ≥ 0.02% of market cap | Operational filter |
| Recommended hold | **90 days** | Jeng-Metrick-Zeckhauser; Cohen-Malloy-Pomorski; Lakonishok-Lee |
| Position sizing | Flat: max 2% of equity per trade | No literature support for differential sizing |
| Round-trip cost assumption | 1.0% | Realistic for retail at $200M–$3B |
| Opportunistic/routine | Informational flag | Cohen-Malloy-Pomorski 2012 |
| Regime | Reported, not gated | Literature mixed |

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

## 4. What was deliberately removed

| Removed (vs prior versions) | Why |
|---|---|
| LLM agents (Bull/Bear/Supervisor/Synthesis) | Narrative, not signal. Removed in v1. |
| Composite scoring + weights | With one signal, weights have nothing to weight. v1. |
| Government contract catalyst | Zero backtest evidence. v1. |
| Neglect screen, information asymmetry score | Not in validated cohort. v1. |
| Confirming signals (hiring, 13F, Russell, state contracts) | Data unavailable or fires too rarely. v1. |
| High-Upside score, theme clustering | Re-encoded info or unused at this scale. v1. |
| 10-day / 20-day hold horizons | Literature consistently supports 90–180 days. v2. |
| Cluster-size sizing multipliers (1.0/1.25/1.5x) | n=7 elite sub-cohort cannot support a sizing rule. v2. |
| Regime sizing multiplier | Not in validated cohort; literature mixed. v2. |
| Elite extension to 20-day hold | Same. v2. |

---

## 5. What was added in v2 (vs v1)

1. **Opportunistic/routine classification** per Cohen-Malloy-Pomorski (2012) — informational
   metadata showing how many cluster members are non-routine traders. Not a gate.
2. **90-day hold horizon** replacing 10d/20d.
3. **$200M–$3B market cap band** replacing $500M–$5B (smaller-cap literature support).
4. **Flat 1.0x position sizing** replacing cluster-size and regime multipliers.
5. **Explicit step-1 screening framing** — engine no longer pitched as alpha generator.

---

## 6. Known weaknesses for adversarial scrutiny

### A. Statistical fragility of our own backtest
n=65 events after event-dedup. Too small to validate any sub-rule. The engine is now
calibrated against academic literature with much larger samples (~50,000+ transactions
in foundational studies), not against our own data. Our n=65 serves only as a directional
consistency check.

### B. Post-SOX effect attenuation
Sarbanes-Oxley (2002) cut Form 4 disclosure lag from up to 40 days to 2 business days.
Classical pre-2002 effect sizes likely overstate today's edge. Recent studies find
attenuated magnitudes. Median academic estimate of 2–4% gross per 90d already incorporates
this; reviewers should flag if they think 2–4% is still optimistic.

### C. Transaction cost dependence
At the low end of the academic range (~1.5% gross per 90d), 1% round-trip costs nearly
eliminate the edge. Limit orders are essential at $200M–$3B market caps.

### D. Materiality threshold (0.02%) has no academic basis
This is a practitioner rule-of-thumb. The reviewer should suggest whether 0.02% is
appropriate, too loose, or too strict — knowing that the literature has not directly
studied % of market cap thresholds.

### E. Sparse signal rate
Expected ~1–3 signals per month. A 60-day paper-trade will produce ~2–6 trades — anecdote,
not validation. The engine requires year+ of operation to accumulate meaningful data.

### F. Opportunistic flag is informational only, not gating
The Cohen-Malloy-Pomorski finding implies routine-only clusters have ~0 predictive
power. We chose to surface the flag rather than gate on it, prioritising candidate
volume for discretionary research over strict alpha optimisation. Reviewers may disagree
with this trade-off.

### G. The engine is not a complete strategy
The discretionary research the operator does on each surfaced ticker is where most of
the realised outcome will come from. The engine is only the screen. If the operator
does poor follow-up research, the screen quality won't save them.

---

## 7. Three questions for the reviewer

1. **Hold horizon**: is 90 days the right choice? Or should it be 180 days (some literature
   peaks closer to 6 months)? The current choice balances capital efficiency against
   alpha capture.

2. **Opportunistic flag — gate or not?** We chose informational-only for screen breadth.
   Should it be a hard gate (clusters with majority routine traders → exclude)?

3. **Single biggest blind spot you see** that we haven't already flagged in section 6.

---

## 8. Repo structure

```
trading-research/
├── CLAUDE.md                       # normative rulebook (v2)
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

Runtime surface (excluding backtest): ~1,300 lines of Python.

---

## 9. Style preference for review

Direct, structured, evidence-led. Push back on parameters that aren't well-justified.
The operator has been repeatedly pushing the project toward less complexity and more
honesty — sycophantic agreement is not useful. Adversarial review is.
