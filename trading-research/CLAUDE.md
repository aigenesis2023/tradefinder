# CLAUDE.md — Simplified Engine v1 Rulebook

This file is normative. Every rule is enforced in Python. There are no agent prompts
in this version.

## Philosophy

The 7-year OpenInsider backtest (n=383, of which n=93 met production criteria) is
the only validated component. Everything else built on top — LLM debate, composite
scoring weights, government-contract catalysts, neglect screens, confirming signals,
high-upside scores, theme clustering — was untested additional filtering and has
been removed.

If a feature is not validated against the production cohort, it does not gate
signal flow. Risk management is allowed without validation (sizing, liquidity
warnings, dedup) because it never blocks a signal — only shrinks position size.

---

## THE SIGNAL (only one)

Open-market insider buying cluster, defined by:

| Condition | Threshold |
|---|---|
| Unique insiders | ≥ 3 |
| Per-transaction minimum | ≥ $100,000 |
| Cluster window | ≤ 14 days |
| Look-back window | 21 days |
| Qualifying roles | CEO, CFO, COO, Chairman, Director, President, EVP, SVP |
| Transaction code | "P" (open-market purchase only) |
| 10b5-1 plan trades | Excluded |
| Institutional entity names | Excluded (LLC, LP, Fund, Trust, etc.) |
| Market cap | $500M – $5B |
| Cluster materiality | ≥ 0.02% of market cap |

These are the exact filters that produced the validated n=93 cohort.

### Empirical priors (LOCKED — do not tune without similarly-scaled validation)

Production cohort (3+ insiders, $500M–$5B, 2018–2024, n=93):
- 10d IWM-adjusted alpha: +2.93% (per-day 0.293%) — chosen horizon
- 30d IWM-adjusted alpha: +3.92%
- 60d IWM-adjusted alpha: +7.82% (ex-COVID, n=78)
- 30d alpha win rate: 68.8%
- Mean reversion sets in by day 180 (do not hold indefinitely)

Elite sub-cohort (5+ insiders, n=7):
- Peaks at +6.68% by day 10
- Mean-reverts to +0.05% by day 30

Anti-priors (DO NOT remove these guards):
- 3+ insiders in $200M–$500M: −0.87% alpha (negative; excluded by mcap floor)
- 2-insider clusters: noise (excluded by min cluster size)

---

## REGIME (informational + sizing multiplier, NOT a gate)

The 7-year backtest cohort was unconditional on regime. We surface regime state
and use it as a position-size multiplier. We do **not** suppress signals on regime.

| State | Definition | Sizing multiplier |
|---|---|---|
| NORMAL | VIX/VIX3M < 1.0 AND IWM > 20d MA | 1.0x |
| STRESSED | Either VIX/VIX3M ≥ 1.0 OR IWM ≤ 20d MA | 0.5x |
| HARD_FAIL | Regime data fetch failed | 0.0x (no size recommended) |

Rationale: empirically regime matters (2019: +5.09% / 72% win; 2022: −5.17% / 40% win).
But a binary gate threw out signals that should be sized down, not skipped. The
multiplier preserves option to trade while reducing exposure when the macro is hostile.

---

## POSITION SIZING (advisory)

Total recommended risk per trade:

```
recommended_risk_pct = max_risk_per_trade × cluster_size_multiplier × regime_multiplier
```

| Cluster size | Multiplier |
|---|---|
| 3 insiders | 1.0x |
| 4 insiders | 1.25x |
| 5+ insiders (ELITE) | 1.5x |

`max_risk_per_trade = 2.0%` of portfolio equity.

Sizing examples:
- 3 insiders, normal regime: 1.0 × 1.0 × 2% = **2.0% risk**
- 4 insiders, stressed regime: 1.25 × 0.5 × 2% = **1.25% risk**
- 5+ insiders (elite), normal regime: 1.5 × 1.0 × 2% = **3.0% risk** (cap at 2%)
- 3 insiders, hard regime fail: 1.0 × 0.0 × 2% = **0% (skip)**

Liquidity floor: if 20d avg dollar volume < $500K → `liquidity_warning = True` and
position size additionally capped at 5% of 20-day ADV.

---

## EXIT RULES (advisory)

Recommended exit hierarchy per surfaced signal:

1. **Time stop** (default exit):
   - Standard clusters (3–4 insiders): **10 trading days**
   - Elite clusters (5+ insiders): **20 trading days**
2. **Cut on −6%** from entry (advisory stop loss)
3. **Trim on +8%** if hit before time stop (advisory profit target)
4. Manual invalidation if material new info emerges

Source: 10d/20d horizons selected from per-day alpha analysis on n=93 cohort.

---

## DEDUP

- Same ticker: 5-day cooldown (an insider signal that already surfaced does not
  re-surface every day until a new cluster forms).
- No theme dedup, no supply-chain dedup (those were artifacts of multi-catalyst
  v3 design).

---

## ENTRY PRICE (for logging / paper trade tracking)

Entry = next regular-session close after `signal_date` (latest Form 4 filing date
in the cluster). This matches the backtest convention; the +3.92% alpha is the
post-filing alpha, not the pre-filing alpha.

---

## RUN-LEVEL OUTPUT

The pipeline produces a daily report with:
1. Regime state (informational + multiplier).
2. List of qualifying clusters, ranked by `(unique_insiders, materiality_pct)` desc.
3. Per signal: ticker, cluster size, total $, materiality %, market cap, ADV,
   insider names, recommended hold, recommended size, flags.
4. Discarded log (clusters that detected but failed mcap or materiality).

"No qualifying clusters today" is a valid output. The validated cohort produced
~1 signal/month on average; many days will be empty.

---

## WHAT IS DELIBERATELY ABSENT

These were present in v3 and removed in Simplified v1. They are not deprecated —
they are intentionally not built.

| Removed | Why |
|---|---|
| Bull / Bear / Supervisor LLM agents | Generated narrative; did not enter scoring; risk of anchoring trader on confabulated thesis. |
| Composite scoring weights | With one signal type, multi-factor weights have nothing to weight. |
| Information asymmetry score | Coverage / news / institutional filters were not part of the validated cohort. |
| Neglect screen | Same — not in validated cohort. |
| Government contract catalyst | Zero backtest evidence; literature supports the effect for large-caps only. |
| Confirming signals (hiring, 13F, Russell, state contracts) | Most rely on data we don't have or fire too rarely to move outcomes. |
| High-Upside score | Re-encodes cluster size + short interest already visible in the surfaced signal. |
| Theme clustering | At ~1 signal/month, sector/theme overlap is not a practical problem. |
| Quant scoring (VSA, RS, compression) | Not in validated cohort. Add back only after feature-level backtest. |
| Elite-override hard gate | Replaced with sizing multiplier — same intent, no signal suppression. |

---

## DOMICILE

No country filter. Form 4 is the bottleneck: only SEC-registered Section 16 filers
reach the scanner. Foreign-domiciled US-listed names that file Form 4 flow through
normally (matches the n=383 validated cohort which included foreign issuers).

---

## DATA SOURCES

- **SEC EDGAR Form 4**: primary signal source (free, 10 req/sec limit).
- **yfinance**: market data (market cap, price, ADV, sector).
- **VIX, VIX3M, IWM** (via yfinance): regime context.

No paid APIs. No LLM. No SAM.gov. No USAspending. No Firecrawl.

---

## VALIDATION ROADMAP (future, not v1)

Features that may earn their place into v2 only after passing a backtest gate on
the n=93 cohort (or a refreshed extended cohort):

1. Insider role mix (CEO+CFO+independent director vs three directors).
2. Cluster velocity (3 buys in 2 days vs 3 in 14).
3. Purchase price vs 30-day VWAP.
4. Insider tenure / repeat-cluster history per ticker.
5. Short interest > 20% as a sizing modifier (academic support; not in cohort).
6. Single "is catalyst already public?" check (one LLM call per surfaced signal,
   D3-style — the one LLM use that has defensible signal value).

Each addition must demonstrate a measurable improvement (alpha, win rate, or
volatility-adjusted return) on the existing cohort before going live.

---

## "NO SIGNAL TODAY" IS A VALID OUTPUT

```
NO QUALIFYING CLUSTERS TODAY. THIS IS A VALID RESULT.
```

Do not manufacture conviction to fill a report.
