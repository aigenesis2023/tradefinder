# CLAUDE.md — Simplified Engine v3.0 Rulebook

This file is normative. Every rule is enforced in Python. There are no LLM agents.

## What this engine is — and isn't

**Is**: a daily mechanical scanner that surfaces insider-cluster buying signals on US-listed
small/mid-cap stocks ($200M–$3B) using SEC Form 4 data. It is a **Step-1 screening tool**:
it produces a starting list of candidates for the operator's own fundamental research
(business quality, valuation, news, sector context) before any trade decision.

**Isn't**: a standalone alpha-generating system. Academic literature suggests realistic gross
returns of ~2–4% per 90-day trade for filtered cluster signals — comparable to passive
indexing on a risk-adjusted basis after transaction costs and operational overhead. The
engine's value is the *screen*, not a claimable edge. The discretionary research the
operator does on each surfaced ticker is where any additional edge is generated.

---

## Parameters (all literature-aligned, see references below)

| Parameter | Value | Source |
|---|---|---|
| Unique insiders | ≥ 3 within a 30-day window | Lakonishok-Lee 2001; Alldredge-Blank 2019; Kang et al. 2018 |
| Per-transaction floor | ≥ $100,000 each | Defensible default; literature emphasizes meaningful personal commitment |
| Cluster window | **30 days** (v2.1, was 14d) | Academic studies use 1-3 month windows; insider campaigns span weeks |
| EDGAR lookback (cluster) | **45 days** (v2.1, was 21d) | Accommodates 30d cluster window with buffer for cluster_end recency |
| Routine/opportunistic check | 3-year history | Cohen-Malloy-Pomorski 2012 |
| Opportunistic soft gate | **≥1 opportunistic insider required** (v2.1) | Cohen-Malloy-Pomorski 2012: pure-routine clusters carry near-zero predictive content |
| Qualifying roles | CEO, CFO, COO, Chairman, Director, President, EVP, SVP | Standard cohort |
| Transaction code | "P" (open-market purchase) only | Excludes options/awards/gifts |
| 10b5-1 plan trades | Excluded | Carry near-zero predictive value |
| Institutional entity names | Excluded (LLC, LP, Fund, etc.) | Different motives than executive operators |
| Market cap | $200M–$3B | Smaller-cap effect well-established (Lakonishok-Lee; Jeng et al.) |
| Materiality threshold | **None** (v2.1, was 0.02%) | $100K × 3 = $300K minimum already enforces commitment; 0.02% was mathematically redundant |
| Recommended hold | **180 days** (v2.1, was 90d) | Jeng-Metrick-Zeckhauser 2003; Cohen-Malloy-Pomorski 2012; Lakonishok-Lee 2001 |
| Position sizing | Flat: max 2% of equity per trade | No literature support for cluster-size or regime multipliers |
| Transaction cost assumption | 1.0% round-trip | Realistic for retail at $200M–$3B |

---

## The opportunistic-vs-routine flag (v2.1: soft gate + metadata)

Per Cohen-Malloy-Pomorski (2012, *Journal of Finance*): an insider is classified as
**routine** if they bought in the same calendar month for 3 consecutive prior years.
Otherwise **opportunistic**. Their finding: opportunistic trades carry ~82bps/month of
abnormal return; routine trades have ~0 predictive power.

The engine fetches ~3 years of prior Form 4 history for each scanned ticker and computes
`opportunistic_count` per cluster, also surfaced in the report alongside `unique_insiders`.

**Soft gate (v2.1)**: the engine now discards clusters where `opportunistic_count == 0`
(i.e., all insiders are classified routine). Rationale: per CMP 2012, a pure-routine
cluster carries ~0 predictive content. Surfacing these for the operator to research is
asking them to evaluate definitionally-noisy candidates. The soft gate removes them
automatically. Clusters with at least 1 opportunistic insider pass through to the report
with `opportunistic_count / unique_insiders` displayed prominently for operator weighting.

**Why a soft gate and not strict (e.g., "all must be opportunistic")**: requiring all
cluster members to be opportunistic would significantly reduce candidate volume without
proportional edge improvement. The CMP finding is "routine trades carry no information";
not "any routine trader contaminates the cluster signal."

### IPO / new-listing edge case

The 3-year lookback for routine classification requires 3 years of Form 4 history per
insider. For companies that listed within the last 3 years, no insider can have the
required history. Per the CMP definition, these insiders are correctly classified as
**opportunistic by default** (you cannot be routine without a history).

This means freshly-listed companies will tend to show `opportunistic_count == unique_insiders`
(all opportunistic) regardless of whether the buying behavior is actually informational.
Operators researching such candidates during step-2 review should be aware that the
opportunistic flag carries less discriminating information for recent IPOs / spin-offs
than for mature listings. Treat "100% opportunistic" on a < 3-year-old listing as
roughly equivalent to "data insufficient to classify."

---

## The short-interest "disagreement" flag (informational only)

Per Chung, Sul, and Wang (2019, *Journal of Portfolio Management*): when insider buying
coincides with elevated short interest, abnormal returns are amplified — corporate
insiders (with private information) buying against the market's bet (heavy short positioning)
creates a positively-skewed payoff distribution. Forced covering on positive catalysts
adds mechanical upward pressure on top of the information edge.

The engine fetches `shortPercentOfFloat` from yfinance for each surfaced ticker and tags
clusters where short interest is between **10% and 40% of float** with a ⚡ DISAGREEMENT
marker. The upper bound filters out distress/fraud names where insiders may buy
defensively rather than informationally (Lee et al. 2018 — "false signaling" risk).

**The engine does NOT gate on short interest.** Reasons:

1. The Chung-Sul-Wang headline numbers show combined-signal lift mostly at 1-month
   horizons; our 90-day hold sits in the decay window. Net incremental edge at 90d is
   unclear.
2. Gating at 10–40% SI cuts the candidate pool by an estimated ~90% — too few signals
   for a discretionary screening tool.
3. The false-signaling research (insiders buying defensively into shorted names with
   price support fully reverting within a year) is a real failure mode the engine
   should not bake in.

Like the opportunistic flag, this is metadata for the operator's discretionary stage.

Source for the short-interest value: `yfinance.Ticker.info["shortPercentOfFloat"]`
(fallback to `sharesPercentSharesOut`). Data quality varies by ticker; `None` is
reported when unavailable.

---

## Analyst coverage count (informational only)

Per Lakonishok-Lee (2001) and follow-up studies: insider-buying alpha is stronger
in stocks with lower analyst coverage (information asymmetry is higher when fewer
Wall Street analysts cover the name). The engine fetches `numberOfAnalystOpinions`
from yfinance and surfaces it on each signal alongside short interest.

**Not a gate.** Lower analyst count is generally a positive contextual marker for
the insider-cluster signal, but the engine does not filter on it. The operator
uses it during step-2 discretionary research to assess whether a candidate is
genuinely under-researched (~5 or fewer analysts) or a small-cap name that is
already well-followed.

The $200M–$3B market-cap band already biases the universe toward lower coverage,
so this field often shows single-digit counts. When it shows 15–20+ analysts,
the candidate is a well-followed small-cap and the information edge per the
literature is likely smaller.

---

## Empirical expectation (what to actually anticipate)

Reasonable median estimates from post-2010 US literature for our exact configuration:

| Metric | Estimate |
|---|---|
| Gross return per 180d trade | 4–8% |
| Net return per 180d trade (after 1% costs) | 3–7% |
| Annualized (fully deployed, continuous) | ~6–14% net |
| Comparison: SPY historical annualized | ~10% nominal |
| Signals per month (expected) | ~2–5 (v2.1 — wider cluster window + materiality removal) |
| Win rate per trade (absolute, not alpha) | 55–65% |

The strategy is roughly competitive with passive indexing on standalone return; its value
is therefore in (a) the discretionary research it enables and (b) diversification from
pure market beta. **Do not run this as a sole strategy expecting outperformance.**

---

## Pipeline flow (v3.0)

```
1. RegimeCheck         VIX/VIX3M, IWM vs 20d MA — INFORMATIONAL ONLY
2. OpenInsider Scrape  one HTTP feed call for the last ~3 years; cached per quarter
3. Filter              role + entity-name filters; ≥$100K per transaction
4. Cluster Detect      per ticker, find best 30d window with 3+ unique insiders in
                       the last 45 days. Exactly ONE cluster surfaced per ticker.
5. OpportunisticTag    routine/opportunistic classification per CMP 2012 using the
                       same 3-year scraped history
6. OpportunisticGate   discard clusters with 0 opportunistic insiders
7. yfinance Enrich     for each surviving cluster: market cap, ADV, short interest,
                       analyst count, sector
8. McapFilter          discard if market cap outside $200M-$3B
9. Rank                by (opportunistic_count desc, unique_insiders desc, materiality desc)
10. Report             markdown report + SQLite logging for outcome tracking
```

No agents. No LLM calls. No multi-step debate. No scoring formula with weights.
No regime gating. No sizing multipliers. No fixed materiality % filter.

### v3.0 architecture change

Prior versions (v1–v2.1) used a per-ticker SEC EDGAR scan:

- For each of ~922 tickers in the $200M–$3B band, fetch ~3 years of Form 4 history
- Estimated runtime: ~25–30 hours on cold cache, every run
- In practice runs were capped at `--max-tickers N` (default 50), covering ~5% of
  the universe per run with no rotation — most of the universe was never scanned

v3.0 uses OpenInsider's aggregated feed:

- One scrape returns all qualifying open-market insider purchases across the entire
  US market for a date range
- Quarterly chunks are cached locally (1-hour TTL on the current quarter, 1-week TTL
  on older quarters that are essentially static)
- Cluster detection runs on the aggregated set
- yfinance enrichment runs only on the small number of detected candidates
- Full-market coverage in ~30 seconds on warm cache, ~5 minutes on cold cache
- The backtest already uses OpenInsider; v3.0 aligns the live pipeline with the
  validated data path

### Trade-off accepted in v3.0

OpenInsider's scraper filters at source to purchases ≥ $100K (the URL parameter `vl=100`).
This is the same minimum we use, so cluster detection is unaffected. But for routine /
opportunistic classification (Cohen-Malloy-Pomorski 2012), an insider's full purchase
history would ideally include sub-$100K trades too. If an insider habitually buys $50K
in the same calendar month every year, they're routine by CMP's definition but won't
appear in our scraped data and will be mis-classified as opportunistic.

This biases conservatively: mis-classifying a routine trader as opportunistic means the
soft gate (which only blocks clusters with zero opportunistic insiders) does not fire
inappropriately. The error direction is "we surface a cluster we might have filtered,"
not "we filter a cluster we should have surfaced." Operator's step-2 research handles
the residual risk.

---

## Exit framework (advisory — operator executes manually)

1. **Time stop**: 180 trading days. Single horizon for all signals.
2. **Hard stop**: −20% from entry (loose, to handle 180d variance — tight stops kick out winners early at this horizon).
3. **Soft target**: +25% if hit before time stop. Discretionary trim/exit.
4. **Manual invalidation**: material new info (earnings miss, fraud, regulatory action) — exit immediately.

The 180-day horizon is chosen because the academic literature consistently shows
insider-buying alpha accrues over 3–12 months, peaking around 6 months. Jeng-Metrick-
Zeckhauser (2003) and Cohen-Malloy-Pomorski (2012) both document significant cumulative
abnormal returns out through ~12 months. The 10-day, 20-day, and 90-day horizons in
earlier versions were on the short end of academic guidance.

---

## Position sizing (advisory, flat)

- Max risk per trade: **2.0% of portfolio equity**. Position $ = (0.02 × equity) / stop_pct.
- Liquidity floor: if 20d ADV < $500K → `liquidity_warning`, additionally cap position at 5% of ADV.
- No cluster-size multipliers. No regime multipliers. No elite-tier sizing.

Rationale: neither the literature nor our own backtest (n=65 events, statistically too small)
supports differential sizing on cluster size, market regime, or "elite" extensions. Flat
sizing is the only defensible default.

---

## Dedup

- Same ticker: 5-day cooldown.
- No theme dedup, supply-chain dedup, or sector dedup.

---

## Regime — informational only

VIX/VIX3M ratio and IWM vs 20d MA are computed and displayed at the top of each report.
They do not gate signals or modify position size. Rationale:

1. Our n=65 backtest cohort was unconditional on regime; any regime overlay would be
   untested.
2. Literature is mixed on regime sensitivity — some studies find stronger effect in
   bear markets; others find no clean regime split. No consensus on a tractable rule.
3. Operator can apply regime context in their discretionary research.

---

## "No signal today" is a valid output

```
NO QUALIFYING CLUSTERS TODAY. THIS IS A VALID RESULT.
```

Do not manufacture conviction to fill a report. The validated cohort produces ~1 signal
per month on average; many days will be empty.

---

## What was deliberately removed in v2 (and why)

| Removed | Why |
|---|---|
| 10-day standard hold + 20-day elite extension | Literature consistently supports 90–180 day horizons. 10d is too short for insider alpha to materialize. |
| Cluster-size sizing multipliers (1.0/1.25/1.5x) | n=7 elite sub-cohort cannot support a sizing rule. No literature backing. |
| Regime sizing multiplier (1.0/0.5/0.0x) | Not in validated cohort. Literature is mixed. Pure overlay. |
| Government contract catalyst | Zero backtest evidence. Removed in v1. |
| LLM agents (Bull/Bear/Supervisor/Synthesis) | No signal value. Narrative theatre. Removed in v1. |
| Composite scoring weights | With one signal type, weights have nothing to weight. Removed in v1. |
| Information asymmetry score, neglect screen | Not in validated cohort. Removed in v1. |
| Confirming signals (hiring, 13F, Russell) | Most rely on data we don't have or fire too rarely. Removed in v1. |
| High-Upside score | Re-encoded existing visible information. Removed in v1. |
| Theme clustering | Not needed at ~1 signal/month. Removed in v1. |

---

## What was added in v2

1. **Opportunistic/routine classification** (Cohen-Malloy-Pomorski 2012).
2. **90-day hold horizon** (was 10d/20d) — aligned with literature.
3. **$200M–$3B market cap** (was $500M–$5B) — smaller-cap effect stronger per literature.
4. **Flat 1.0x sizing** (was cluster-size tiered) — no statistical basis for differentiation.
5. **Step-1 screening framing** — engine explicitly positioned as research-input, not standalone strategy.
6. **Short interest + DISAGREEMENT flag** (Chung-Sul-Wang 2019) — informational metadata.
7. **Analyst coverage count** (Lakonishok-Lee 2001) — informational metadata.

## What changed in v2.1 (external review feedback)

1. **Hold horizon 90 → 180 days** — literature peaks ~6mo (Jeng et al. 2003 cumulative
   abnormal returns through ~14mo; CMP 2012 significant out through 12mo). 90d was on the
   short end of academic guidance.
2. **Cluster window 14 → 30 days + EDGAR lookback 21 → 45 days** — academic studies use
   1–3 month cluster windows; insider campaigns commonly span weeks. 14d was artificially
   splitting single coordinated campaigns into multiple disjointed events.
3. **Materiality threshold (0.02%) removed** — was mathematically redundant. At our
   3-insider × $100K = $300K minimum, the threshold only binds above ~$1.5B market cap.
   The $100K × 3 absolute floor already enforces meaningful commitment across the band.
4. **Opportunistic soft gate (≥1 opportunistic insider)** — automatically discard
   clusters with zero opportunistic insiders. Per CMP 2012, pure-routine clusters carry
   ~0 predictive content; surfacing them for discretionary research is asking the operator
   to evaluate definitionally-noisy candidates.
5. **Documented IPO / new-listing edge case** — companies listed <3 years ago will tend
   to show `opportunistic_count == unique_insiders` regardless of actual signal quality.
6. **Documented fresh mcap re-check** — pipeline re-fetches market cap via yfinance after
   the watchlist scan; tickers that drifted outside $200M–$3B since the (up-to-7-day-stale)
   watchlist cache are discarded.

---

## Domicile

No country filter. Form 4 is the bottleneck: only SEC-registered Section 16 filers reach
the scanner. Foreign-domiciled US-listed names that file Form 4 flow through normally.

---

## Data sources (v3.0)

- **OpenInsider feed** (http://openinsider.com): primary signal source. Single
  aggregated feed of SEC Form 4 filings, scraped via HTTP with local quarterly
  caching. Free, no API key, no published rate limits (we throttle to 0.4s
  between requests). The same source used by the backtest.
- **yfinance**: per-cluster enrichment — market cap, price, ADV, sector, short
  interest, analyst count.
- **VIX, VIX3M, IWM** (via yfinance): regime context (informational only).

SEC EDGAR is no longer directly scraped in v3.0. OpenInsider aggregates Form 4
filings from EDGAR, so the underlying authority is the same; the difference is
the discovery path.

No paid APIs. No LLM. No SAM.gov. No USAspending. No Firecrawl.

---

## Academic references

Engine parameters trace to (where applicable):

- **Lakonishok & Lee (2001)**, "Are Insider Trades Informative?", *Review of Financial Studies*
- **Jeng, Metrick & Zeckhauser (2003)**, "Estimating the Returns to Insider Trading", *Review of Economics and Statistics*
- **Cohen, Malloy & Pomorski (2012)**, "Decoding Inside Information", *Journal of Finance*
- **Brochet (2010)**, on post-SOX information content of insider trades
- **Wang, Shin & Francis (2012)**, "Are CFOs' Trades More Informative…?", *JFQA*
- **Alldredge & Blank (2019)**, on insider trade clustering
- **Kang, Kim & Wang (2018)**, on cluster trade timing post-SOX

The operator should verify these references and read the introductions and key tables
of at least Cohen-Malloy-Pomorski (2012) and Jeng-Metrick-Zeckhauser (2003) before
committing capital.

---

## Honest caveats (DO read before operating)

1. **Sample-size limit**: our own backtest cohort is n=65 after dedup. Too small to validate
   any sub-rule. The engine is calibrated against the broader academic literature, not against
   our small empirical sample.
2. **Effect attenuation**: post-Sarbanes-Oxley (2002), the disclosure lag dropped from 40 days
   to 2 business days. The classical effect is partially priced in faster now. Recent studies
   (post-2010) find smaller magnitudes than older studies.
3. **Transaction costs eat thin edges**: at the bottom of the academic range, after 1% costs,
   net edge approaches zero. Use limit orders; avoid market orders at this market-cap band.
4. **Right-tail dependence**: a meaningful share of historical alpha comes from a few outsized
   winners. Most trades will be modest gains or modest losses. Do not over-position any single
   signal.
5. **Operator discipline matters more than the screen**: the discretionary research applied
   after the screen is where most of the realized outcome will come from. Cutting corners on
   research will produce worse results than not running the engine at all.

---

## Reframe — what success looks like

Success is NOT:
- Beating SPY by a large margin
- Producing consistent monthly profits
- A 60-day paper trade with great numbers

Success IS:
- A disciplined screening process that surfaces structurally-meaningful events
- The operator developing fundamental-research skill on the surfaced candidates
- Multi-year track record of disciplined execution
- Honest measurement of outcomes vs alternatives (SPY, alternative strategies)

The screen is the engine's contribution. The trade decision is yours.
