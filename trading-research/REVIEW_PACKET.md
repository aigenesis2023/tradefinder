# Simplified Engine v3.0 — Review Packet

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

Earlier iterations of this project (the original v3.1, unrelated to the current v3.0)
overclaimed validated edge with LLM narrative scaffolding, multi-factor scoring, and
untested catalysts. v1 stripped all of that to the validated mechanical cluster filter.
v2 recalibrated parameters against academic literature (Cohen-Malloy-Pomorski 2012,
Jeng-Metrick-Zeckhauser 2003, Lakonishok-Lee 2001, Chung-Sul-Wang 2019) rather than our
own backtest. v2.1 incorporated external reviewer feedback (hold horizon, cluster
window, materiality redundancy, opportunistic soft gate).

**v3.0 is an architectural change**: discovery moved from per-ticker SEC EDGAR scanning
(which required ~25–30 hours on cold cache to cover the $200M–$3B universe and was in
practice capped at ~5% of the universe per run with no rotation) to OpenInsider's
aggregated feed (single scrape returns all qualifying activity across the US market).
The backtest already used OpenInsider; v3.0 aligns the live data path with the
validated one. Parameters and academic anchors are unchanged from v2.1.

---

## 1. What the engine does

Daily mechanical scan:

1. **OpenInsider feed scrape** for the last ~3 years of qualifying open-market purchases
   across the entire US market. Quarterly chunks cached locally (1-hour TTL on the
   current quarter, 1-week TTL on older). Filters at source: purchases only, ≥ $100K
   per transaction.
2. **Role + entity filter**: only CEO/CFO/COO/Chairman/Director/President/EVP/SVP
   trades; institutional-entity filer names (LLC, LP, Fund, etc.) excluded.
3. **Cluster detection**: per ticker, find the best 30-day window with ≥ 3 unique
   insiders, within the last 45 days. Emit at most ONE cluster per ticker (fixes the
   rolling-window-duplicate bug in the backtest's earlier detect_clusters).
4. **Opportunistic classification** per CMP 2012: each cluster member is "routine" if
   they bought in the same calendar month for 3 consecutive prior years in the
   scraped history; otherwise opportunistic.
5. **Opportunistic soft gate**: discard clusters with `opportunistic_count == 0`.
6. **yfinance enrichment** per surviving cluster: market cap, ADV, short interest,
   analyst count, sector. Runs only on detected candidates (typically 5–30 per scan),
   not the whole universe.
7. **Market cap filter**: discard if market cap outside $200M–$3B.
8. **Tags three informational metadata fields** per surfaced signal:
   - **Opportunistic count** (CMP 2012): non-routine cluster members.
   - **Short interest + DISAGREEMENT flag** (Chung-Sul-Wang 2019): % of float shorted,
     plus ⚡ tag when between 10–40% (insiders buying into elevated shorts).
   - **Analyst coverage count** (Lakonishok-Lee 2001): # of sell-side analysts.
9. **Output** a ranked report (by opportunistic_count → unique_insiders → materiality)
   with full metadata per candidate.

**No LLM. No scoring formula. No regime gating. No sizing multipliers. No fixed
materiality % filter (removed in v2.1). The only quality gate beyond the cluster
filter is the opportunistic soft gate.**

10b5-1 plan trades: OpenInsider does not directly tag these as a separate transaction
type. The scrape's `xp=1` parameter returns all open-market purchases (P-code) which
includes some 10b5-1 plan trades. In practice the cluster requirement (3+ different
insiders coordinating within 30 days) makes 10b5-1 plan trades exceptionally unlikely
to drive a cluster (10b5-1 plans are pre-scheduled individually months in advance and
do not coordinate across executives). This is a slight relaxation from v2.1's EDGAR-
based footnote check; reviewers may flag.

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

**v2.1 (incorporating prior reviewer feedback):**
8. **Hold horizon 90 → 180 days** — literature peaks ~6mo (Jeng et al.; CMP).
9. **Cluster window 14 → 30 days + EDGAR lookback 21 → 45 days** — academic studies
   use 1-3 month windows; insider campaigns span weeks.
10. **Materiality threshold (0.02%) removed** — was mathematically redundant.
11. **Opportunistic soft gate (≥ 1 opportunistic insider required)** — automatically
    discard pure-routine clusters per CMP 2012 noise finding.
12. **Documented IPO / new-listing edge case** — companies listed < 3 years ago default
    to all-opportunistic classification.

**v3.0 (architectural change — coverage problem):**
13. **Discovery moved from per-ticker SEC EDGAR scan → OpenInsider aggregated feed.**
    Prior pipeline runs covered ~5% of the universe per run with no rotation; v3.0
    covers 100% of the US market in ~30 seconds on warm cache / ~5 minutes cold.
14. **Single-cluster-per-ticker emission** — fixes the rolling-window-duplicate bug
    that inflated the backtest cohort (SSP appeared 30 times in n=93 from one
    continuous buying campaign).
15. **Backtest and live data paths now identical** — both use OpenInsider. Prior
    inconsistency (backtest = OpenInsider, live = EDGAR) is gone.

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

1. **OpenInsider-only architecture (v3.0).** Reliance on a third-party scraper for
   primary discovery is a new dependency. Should we add a secondary discovery path
   (SEC EDGAR direct) for redundancy, or accept the simpler single-source design?

2. **10b5-1 plans no longer explicitly excluded** (v3.0). The scrape returns all P-code
   purchases without distinguishing 10b5-1 plan trades. Is the cluster requirement
   (3+ coordinated executives) sufficient natural filter, or do we need an EDGAR-based
   footnote check on detected clusters?

3. **Routine classification limitation.** OpenInsider's source-side filter (≥ $100K)
   means we don't see sub-$100K routine buys. Insiders with habitual sub-$100K monthly
   purchases will be mis-classified as opportunistic. Acceptable trade-off, or should
   we hit EDGAR for full per-insider history on detected clusters?

4. **Single biggest blind spot you see** that we haven't already flagged in section 7.

---

## 9. Repo structure

```
trading-research/
├── CLAUDE.md                       # normative rulebook (v3.0)
├── REVIEW_PACKET.md                # this document
├── run_pipeline.py                 # main entry, 180d hold, OpenInsider discovery, no LLM
├── orchestrator/
│   ├── openinsider_feed.py         # v3.0 primary discovery via OpenInsider scrape
│   ├── insider_scanner.py          # shared data types + classify_routine helper (CMP 2012)
│   ├── regime_gate.py              # VIX/VIX3M, IWM 20d MA — informational only
│   ├── universe_builder.py         # yfinance screener (legacy; unused in v3.0 main path)
│   └── state_manager.py            # SQLite logging + dedup
├── backtest/
│   ├── measure_absolute_returns.py # post-hoc measurement on n=65 cohort
│   ├── openinsider_pull.py         # backtest's OpenInsider scrape (now mirrors live path)
│   └── (validation infrastructure unchanged from v1)
├── data/                           # SQLite DB
├── cache/
│   ├── openinsider_live/           # v3.0: quarterly chunks of scraped feed (CSV)
│   └── ...                         # legacy CIK map, Form 4 XML, watchlist
└── research_logs/                  # per-run reports (markdown)
```

Runtime surface (excluding backtest): ~1,200 lines of Python.

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
