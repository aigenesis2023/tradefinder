# CLAUDE.md — Simplified Engine v2 Rulebook

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
| Unique insiders | ≥ 3 within a 14-day window | Lakonishok-Lee 2001; Alldredge-Blank 2019; Kang et al. 2018 |
| Per-transaction floor | ≥ $100,000 each | Defensible default; literature emphasizes meaningful personal commitment |
| Cluster window | 14 days | Operationally defensible; literature uses 2d–30d windows |
| Lookback window | 21 days | Empirical alpha lives within recent cluster activity |
| Routine/opportunistic check | 3-year history | Cohen-Malloy-Pomorski 2012 |
| Qualifying roles | CEO, CFO, COO, Chairman, Director, President, EVP, SVP | Standard cohort |
| Transaction code | "P" (open-market purchase) only | Excludes options/awards/gifts |
| 10b5-1 plan trades | Excluded | Carry near-zero predictive value |
| Institutional entity names | Excluded (LLC, LP, Fund, etc.) | Different motives than executive operators |
| Market cap | $200M–$3B | Smaller-cap effect well-established (Lakonishok-Lee; Jeng et al.) |
| Materiality | ≥ 0.02% of market cap | Operational filter, no academic basis but defensible |
| Recommended hold | **90 days** | Jeng-Metrick-Zeckhauser 2003; Cohen-Malloy-Pomorski 2012; Lakonishok-Lee 2001 |
| Position sizing | Flat: max 2% of equity per trade | No literature support for cluster-size or regime multipliers |
| Transaction cost assumption | 1.0% round-trip | Realistic for retail at $200M–$3B |

---

## The opportunistic-vs-routine flag (informational only)

Per Cohen-Malloy-Pomorski (2012, *Journal of Finance*): an insider is classified as
**routine** if they bought in the same calendar month for 3 consecutive prior years.
Otherwise **opportunistic**. Their finding: opportunistic trades carry ~82bps/month of
abnormal return; routine trades have ~0 predictive power.

The engine fetches ~3 years of prior Form 4 history for each scanned ticker and computes
`opportunistic_count` per cluster. This is surfaced in the report alongside `unique_insiders`.

**The engine does NOT gate on opportunistic count.** It is an informational flag for the
operator to consider during discretionary follow-up. Clusters where all members are
opportunistic carry higher expected signal value. Clusters dominated by routine traders
should be weighted accordingly during research.

Rationale for not gating: the engine is a screen, not an edge-extractor. The operator
applies the second filter (fundamentals, news, valuation) where this flag becomes one
of several inputs. Hard gating reduces candidate surface for research.

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
| Gross return per 90d trade | 2–4% |
| Net return per 90d trade (after 1% costs) | 1–3% |
| Annualized (fully deployed, continuous) | ~4–12% net |
| Comparison: SPY historical annualized | ~10% nominal |
| Signals per month (expected) | ~1–3 |
| Win rate per trade (absolute, not alpha) | 55–65% |

The strategy is roughly competitive with passive indexing on standalone return; its value
is therefore in (a) the discretionary research it enables and (b) diversification from
pure market beta. **Do not run this as a sole strategy expecting outperformance.**

---

## Pipeline flow

```
1. RegimeCheck      VIX/VIX3M, IWM vs 20d MA — INFORMATIONAL ONLY
2. UniverseBuild    yfinance screener, $200M–$3B, cached 7d
3. InsiderScan      SEC EDGAR Form 4 per ticker (3+ insiders, 14d window, $100K+, P-code)
4. OpportunisticTag 3-year history check per cluster member, classify each as routine/opp
5. Filter           mcap recheck + materiality floor (0.02% of mcap)
6. Rank             by (opportunistic_count desc, unique_insiders desc, materiality desc)
7. Report           markdown report + SQLite logging for outcome tracking
```

No agents. No LLM calls. No multi-step debate. No scoring formula with weights.
No regime gating. No sizing multipliers.

---

## Exit framework (advisory — operator executes manually)

1. **Time stop**: 90 trading days. Single horizon for all signals.
2. **Hard stop**: −15% from entry (loose, to handle 90d variance — tight stops kick out winners early at this horizon).
3. **Soft target**: +15% if hit before time stop. Discretionary trim/exit.
4. **Manual invalidation**: material new info (earnings miss, fraud, regulatory action) — exit immediately.

The 90-day horizon is chosen because the academic literature consistently shows insider-
buying alpha accrues over 3–12 months, peaking around 90–180 days. The 10-day and 20-day
horizons in earlier versions were not literature-supported.

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

1. **Opportunistic/routine classification** (Cohen-Malloy-Pomorski 2012) — informational metadata, not a gate.
2. **90-day hold horizon** (was 10d/20d) — aligned with literature.
3. **$200M–$3B market cap** (was $500M–$5B) — smaller-cap effect stronger per literature.
4. **Flat 1.0x sizing** (was cluster-size tiered) — no statistical basis for differentiation.
5. **Step-1 screening framing** — engine explicitly positioned as research-input, not standalone strategy.

---

## Domicile

No country filter. Form 4 is the bottleneck: only SEC-registered Section 16 filers reach
the scanner. Foreign-domiciled US-listed names that file Form 4 flow through normally.

---

## Data sources

- **SEC EDGAR Form 4**: primary signal source (free, 10 req/sec limit, 3-year history per scanned ticker).
- **yfinance**: market data (market cap, price, ADV, sector).
- **VIX, VIX3M, IWM** (via yfinance): regime context (informational only).

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
