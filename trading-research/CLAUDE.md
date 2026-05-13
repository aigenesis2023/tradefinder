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
| OpenInsider lookback (cluster) | **45 days** (v2.1, was 21d) | Accommodates 30d cluster window with buffer for cluster_end recency |
| Routine/opportunistic check | 3-year history | Cohen-Malloy-Pomorski 2012 |
| CMP reliability gate | **DATA INSUFFICIENT** label if stock has <3yr trading history | CMP routine classification is invalid for new listings; the report flags these honestly rather than gating |
| Opportunistic soft gate | **≥1 opportunistic insider required** (v2.1) | Cohen-Malloy-Pomorski 2012: pure-routine clusters carry near-zero predictive content |
| Qualifying roles | CEO, CFO, COO, Chairman, Director, President, EVP, SVP (plus SEC abbreviations "Dir", "Pres") | Standard cohort; substring matching on Form 4 titles |
| Price context | Current price + 52-week drawdown + insider VWAP comparison + pre-cluster crash flag | See Report Format section below |
| Transaction code | "P" (open-market purchase) only | Excludes options/awards/gifts |
| Institutional entity names | Excluded (LLC, LP, Fund, Bank, Trust, etc.) | Different motives than executive operators |
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

### Enforced in report (2026-05-12)

The engine now detects this case automatically. When yfinance reports <3 years of
trading history (via `firstTradeDateEpochUtc` with price-history fallback), the
report replaces the misleading "ALL OPPORTUNISTIC" badge with:

    Quality: DATA INSUFFICIENT (limited trading history)

And appends an education note:

    ⚠  DATA INSUFFICIENT: Limited trading history (<3 years).
       IPO-period insider purchases are often pre-arranged allocations,
       not discretionary conviction buys. Research accordingly.

This is a **metadata label, not a gate.** The cluster is still surfaced. The
operator decides whether to research it. But the label prevents a brand-new IPO
with pre-arranged insider allocations from masquerading as a high-conviction
opportunistic cluster.

Additionally, each signal now shows price context (current price + 52-week drawdown)
to surface crash-buying or distressed-entry patterns at a glance.

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

## Permutation test — does the cluster pattern actually add value? (2026-05-13)

We ran a randomized control trial on the 7-year backtest (n=232 signals, 2018-2024)
to answer: "does the insider-cluster pattern predict returns better than randomly
selecting mid-cap stocks from the same data?"

The control group is drawn from the **same OpenInsider dataset, same filters, same
$200M-$3B market-cap band** — the only difference is control stocks have 1 qualifying
buyer (solo) while engine signals have 3+ buyers in a 30-day window (cluster).
100 iterations, equal-weighted baskets per signal date.

### IWM alpha comparison

| Horizon | Engine (cluster 3+) | Control (solo 1 buyer) | p-value | Cohen's d | Engine %ile | Verdict |
|---|---|---|---|---|---|---|
| 7d | +1.09% | +0.14% | **0.03** | +1.89 | 97th | **SIGNIFICANT** |
| 10d | +0.72% | +0.10% | 0.11 | +1.08 | 89th | Weak edge |
| 30d | +1.03% | +0.22% | 0.20 | +0.77 | 80th | Not significant |
| 60d | +2.16% | +0.94% | 0.23 | +0.81 | 77th | Not significant |
| 90d | +2.69% | +2.79% | 0.50 | -0.05 | 50th | Zero |
| 180d | +0.83% | +3.24% | 0.76 | -0.76 | **24th** | Engine UNDERPERFORMS |

### What this means

1. **The cluster pattern provides a real, statistically significant short-term timing
   edge at 7 days.** Engine signals are at the 97th percentile of the random
   distribution — this is genuine.

2. **The edge decays rapidly.** By 30d it's not statistically significant. By 90d it's
   gone entirely. At 180d the engine UNDERPERFORMS solo-buyer stocks.

3. **Insider buying ITSELF carries significant alpha**, consistent with the academic
   literature. The simplest possible screen ("any $200M-$3B stock where a director
   bought $100K+") produces +3.24% alpha at 180d, nearly 4× the engine's +0.83%.

4. **The 180-day hold horizon is contradicted by the data.** The engine's cluster signal
   decays to noise by 30d and underperforms by 180d. The clustering pattern we detect
   has a much shorter half-life than general insider buying.

### Why this might be

- **Coordinated buying campaigns** (3+ insiders in 30 days) often follow bad news (the
  EFOR pattern — buying after a crash). The short-term pop is the cluster effect, but
  the underlying business problems don't resolve in 180 days.
- **Solo-buyer stocks** are more likely to be steady insider accumulation without a
  preceding crash — the classic "insiders buy before good news" pattern.
- The 30d cluster window may be selecting for *crisis-response clusters* rather than
  *anticipatory clusters*. The former create a short-term floor but don't lead to
  sustained outperformance.

---

## Pipeline flow (v3.0)

```
1. OpenInsider Scrape  one HTTP feed call for the last ~3 years; cached per quarter
2. Filter              role + entity-name + $100K minimum per transaction.
                       Roles matched by substring (includes "Dir"/"Pres" abbreviations)
3. Cluster Detect      per ticker, find best 30d window with 3+ unique insiders in
                       the last 45 days. Exactly ONE cluster surfaced per ticker.
4. OpportunisticTag    routine/opportunistic classification per CMP 2012 using the
                       same 3-year scraped history
5. OpportunisticGate   discard clusters with 0 opportunistic insiders
6. yfinance Enrich     for each surviving cluster: market cap, company name, current
                       price, 52w high, trading history days. 24h JSON cache.
7. McapFilter          discard if market cap outside $200M-$3B
8. Insider VWAP        compute volume-weighted avg price from t.shares * t.price_per_share
9. Pre-cluster Close   fetch max close in 10 trading days before cluster_start (yfinance)
10. CMP Reliability    if <3yr trading history → label DATA INSUFFICIENT (metadata,
                       not a gate — cluster still surfaces)
11. Rank               by (opportunistic_count desc, unique_insiders desc, total_usd desc)
12. Report             markdown report with full price context + SQLite logging
```

No agents. No LLM calls. No multi-step debate. No scoring formula with weights.
No regime gating. No sizing multipliers. No short-interest or analyst-coverage gates.

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

## Report format (v3.1 — 2026-05-13)

Each signal in the report now includes:

```
1. TICKER — Company Name
   Cluster: N insiders | $X,XXX,XXX total | Quality: ALL OPPORTUNISTIC
   Routine traders (low signal value): ...  (if any)
   Market cap: $XXXM
   Price: $XX.XX (±X.X% from 52w high) | Insider avg: $XX.XX (current X.X% above/below)
   Cluster window: YYYY-MM-DD -> YYYY-MM-DD (Nd ago)
   Purchases: Name (Role, Date @ $price, $size), ...
   ⚠  Pre-cluster: $XX.XX — insiders bought after XX% crash  (if >20% decline)
   Pre-cluster: $XX.XX — insiders bought into XX% decline     (if >5% decline)
   Recommended hold: 180 days
```

### New fields (2026-05-13)

| Field | Source | What it tells the operator |
|---|---|---|
| Insider purchase prices | `InsiderTransaction.price_per_share` and `.total_usd` | What each insider actually paid |
| Insider VWAP vs current | `t.shares * t.price_per_share / total_shares` | Whether insiders are up or down on their trade |
| Staleness (Nd ago) | `date.today() - cluster_end` | How stale the signal is (can be up to 45d) |
| Pre-cluster crash flag | `_get_pre_cluster_close()` — max close in 10 trading days before `cluster_start` | Whether the cluster formed after a crash |

The pre-cluster crash flag uses the **maximum** close in the 10-day lookback (not the
last close). This ensures it captures the pre-crash price even when `cluster_start`
immediately follows the crash. Example: EFOR crashed -52% on Apr 23; insiders bought
Apr 24. The last close before Apr 24 was $19.53 (the crashed price), but the max close
was $40.55 (the pre-crash price). Using max surfaces the real story.

### EFOR case study (why this matters)

On 2026-05-12, EFOR showed "5 insiders, $1.5M, ALL OPPORTUNISTIC" — looks like a
strong signal. But the pre-cluster flag reveals: `⚠ Pre-cluster: $40.55 — insiders
bought after 52% crash`. The insiders bought the day after a catastrophic Q1 2026
earnings miss (EPS $0.69 vs $0.98 consensus). CEO put $1M at $19.24.

Without the flag, this looks equivalent to insiders accumulating in stable conditions.
With the flag, the operator knows to research whether this is conviction buying
("market overreacted") or management defending the stock. The answer requires
fundamental analysis of the business — the engine's job is to surface the question.

---

## Web access workaround (deepseek model)

The `WebSearch` tool is unsupported on deepseek-v4-pro (returns API error). The `WebFetch`
tool works. For web research in this project:

1. **Search**: `WebFetch` → `https://html.duckduckgo.com/html/?q=your+query`
2. **Read article**: `WebFetch` → specific article URL
3. **Fallback**: `curl` or Python `requests` via Bash; yfinance `.news` for recent headlines

Do not rely on `WebSearch`. Use the DuckDuckGo → WebFetch two-step pattern.

---

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

Rationale: neither the literature nor our own backtest (n=383 measured signals)
supports differential sizing on cluster size, market regime, or "elite" extensions. Flat
sizing is the only defensible default.

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

## What changed in v3.1 (2026-05-13 — signal-quality report enhancements)

1. **Insider purchase prices in report** — each purchase shows price paid and size
   (e.g., `CEO @ $19.24, $999,786`). Previously only name, role, date.
2. **Insider VWAP vs current price** — volume-weighted average purchase price compared
   to current market price, with % delta ("current 3.9% below"). Shows whether
   insiders are in the money or underwater.
3. **Staleness indicator** — cluster window line appends days since last purchase
   (e.g., `(16d ago)`). Makes recency obvious without mental math.
4. **Pre-cluster crash flag** — fetches max close in 10 trading days before
   `cluster_start`. Flags if insiders bought after a crash (>20% decline = ⚠ flag,
   >5% decline = context note). Uses max close (not last close) so it captures
   the pre-crash price even when cluster_start immediately follows the crash day.
5. **Web access workaround documented** — `WebFetch` + DuckDuckGo HTML search as
   alternative to `WebSearch` (unsupported on deepseek-v4-pro).

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
- **yfinance**: per-cluster enrichment — market cap, company name.

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

1. **Sample-size limit**: our 7-year (2018-2024) OpenInsider backtest has n=383 measured
   signals (n=232 for the cluster-3+ sub-cohort used in permutation testing). This is adequate
   for headline statistics but insufficient for sub-rule validation. The engine is calibrated
   against the broader academic literature.
2. **Cluster signal decays — engine is a short-timing tool, not a 180d hold strategy**: a
   permutation test (100 iterations, same OpenInsider data, same $200M-$3B band) found the
   cluster pattern adds a real 7d edge (p=0.03, d=+1.89) but this edge decays to statistical
   insignificance by 30d and **reverses** by 180d (engine +0.83% alpha vs solo-buyer +3.24%).
   The engine's strongest use case is short-term timing, not the 180d hold the literature
   recommends for general insider buying. The cluster filter may be selecting crisis-response
   clusters (buying after crashes) rather than anticipatory ones.
3. **Simpler screens produce more 180d alpha**: the simplest possible filter ("any $200M-$3B
   stock where one insider bought $100K+") produced +3.24% IWM alpha at 180d — nearly 4× the
   engine's +0.83%. Insider buying itself carries alpha (consistent with Lakonishok-Lee,
   Jeng-Metrick-Zeckhauser); the cluster pattern concentrates short-term timing at the expense
   of long-term returns.
4. **Effect attenuation**: post-Sarbanes-Oxley (2002), the disclosure lag dropped from 40 days
   to 2 business days. The classical effect is partially priced in faster now. Recent studies
   (post-2010) find smaller magnitudes than older studies.
5. **Transaction costs eat thin edges**: at the bottom of the academic range, after 1% costs,
   net edge approaches zero. Use limit orders; avoid market orders at this market-cap band.
6. **Right-tail dependence**: a meaningful share of historical alpha comes from a few outsized
   winners. Most trades will be modest gains or modest losses. Do not over-position any single
   signal.
7. **Operator discipline matters more than the screen**: the discretionary research applied
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
