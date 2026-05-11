# CLAUDE.md — Trading Research Pipeline Rulebook (v3)

This file is normative. Every rule here is enforced in Python. Agent prompts handle judgment only.
When in doubt, disqualify. The goal of the 60-day paper-trading window is a verified track record, not ideas.

---

## DUAL ENTRY GATE

### Gate 1 — Regime Gate (`orchestrator/regime_gate.py`)

| Condition | Threshold | Pass |
|---|---|---|
| VIX/VIX3M ratio | Below 1.0 (contango) | VIX < VIX3M |
| IWM | Above 20-day MA | IWM > IWM_MA20 |

- **Both pass → NORMAL mode** (full engine activity, ~1–3 trades/week)
- **Either fails → ELITE-OVERRIDE mode** (engine still runs, but only top-decile signals surface; see below)
- **Data fetch fails → HARD STOP** (no override possible without data)
- Log regime state to `regime_history` table on every run.

### Gate 2 — Neglect Screen (`orchestrator/neglect_screen.py`)

Signal-specific rules — see "Neglect Screen rules" below.

---

## ELITE-OVERRIDE MODE (new in v3)

When the regime gate fails, the engine does NOT terminate. It runs in elite-only mode with stricter thresholds. Surviving candidates are tagged `regime_override=True` and capped at Medium confidence.

| Signal | Normal mode | Elite-Override mode |
|---|---|---|
| Insider cluster | 3+ insiders, 0.02% materiality, ≥$100K each | **5+ insiders, $2M+ total, 0.10% materiality** |
| Government contract | 10%+ of TTM revenue | **≥25% of TTM revenue** |

**Rationale:** Some of the highest-asymmetric trades occur during panics. The old hard-terminate gate threw those away. Elite thresholds keep the safety profile while letting genuinely exceptional signals through.

---

## MARKET CAP FILTER

| Range | Treatment |
|---|---|
| $200M–$5B | Primary universe |
| $100M–$200M | Probationary — set `liquidity_warning = True` |
| Below $100M | Discard and log |

- Hard cap: 15 candidates into debate layer per run.
- Max 50% of those 15 may be probationary.
- **Insider scan is restricted to $500M–$5B only** (empirical: 3+ insiders in $200M–$500M = −0.87% alpha).

---

## CATALYST PRIORITY

| Catalyst Type | Status | Prior |
|---|---|---|
| `government_contract_award` | PRIMARY | 1.0x |
| `insider_buying_cluster` | PRIMARY (empirically validated) | 0.85x |
| `neglected_firm_pre_coverage` | Secondary | 0.9x |
| Others | PARKED post Day 60 | — |

### Insider cluster definition (`orchestrator/insider_scanner.py`)

- **3+** unique insiders, each ≥$100K open-market purchase (Form 4 code "P"), within a 14-day window. Scanned 45 days back.
- Qualifying roles: CEO, CFO, COO, Chairman, Director, President, EVP, SVP.
- Institutional entity names filtered (LLC, LP, fund, etc.).
- 10b5-1 plan transactions excluded.
- Cluster total ≥ 0.02% of market cap (materiality floor).

### Government contract rules (`orchestrator/contract_scanner.py`)

- USAspending API, $500K minimum, 90-day window.
- Contract <10% of TTM revenue: auto-cap at Speculative (applies ONLY to contract catalysts, fixed in v3 — was incorrectly capping insider clusters too).
- Contract `days_since_catalyst > 30`: auto-cap at Speculative (stale).
- Name matching: ALL significant search words must appear in recipient name (v3 fix; previous logic accepted any single shared word and produced misattributions).
- When ticker has BOTH contract AND insider cluster: contract is primary, insider added as confirming signal.

### Neglect Screen — Signal-Specific Rules

**Government contracts**: Full 4-condition screen (analyst <8, news <3 events/30d, institutional <30%, volume below 6-mo avg). Hard discard if <2/4 pass.
- `heldPercentInstitutions > 100%` is treated as a yfinance data artifact (short-loan double-count) and discarded as missing data.

**Insider clusters**: Only analyst-count and news-count conditions apply.
- Institutional ownership EXCLUDED (index funds alone occupy 15–20% of float at $500M–$5B).
- Volume ratio EXCLUDED (insider buying itself causes the spike — circular check).
- Hard discard only if `analyst_count >= 10 AND news_count_30d >= 5` (market already aware).

### Empirical priors (LOCKED — do not tune without similarly-scaled validation)

7-year backtest (n=383, OpenInsider 2018–2024):
- 3+ insiders outperform 2 (30d: 59.5% win / +2.80% vs 50.6% / +0.63%).
- Mid-cap ($500M–$5B) > micro-cap on every window.
- Regime decisive (2019: +5.09% / 72% win; 2022: −5.17% / 40% win).
- Raw mechanical baseline: 53.4% win / +1.31% at 30d.
- Production cohort (3+, $500M–$5B, n=93): +3.92% IWM-adjusted alpha at 30d.

### Holding-horizon priors (added v3, same cohort)

Per-day alpha analysis on n=93 production:
- 7d: +1.32% / per-day 0.188% / alpha-std 0.136
- **10d: +2.93% / per-day 0.293% / alpha-std 0.235** ← optimal
- 30d: +3.92% / per-day 0.131% / alpha-std 0.227

Elite cohort (5+ insiders, n=7): peaks at +6.68% by day 10, mean-reverts to +0.05% by day 30.

**Decision: 10-day expected holding horizon.** Best per-day alpha and best risk-adjusted return.

---

## SCORING FORMULAS

### Information Asymmetry Score

```
information_asymmetry_score =
    (recency_vs_lag          * 0.30) +
    (coverage_gap            * 0.40) +
    (narrative_inconsistency * 0.30)
```
Coverage gap scale: ≤3 analysts = 5, 4–5 = 4, 6–8 = 3, >8 = below 3.

| Score | Treatment |
|---|---|
| < 1.5 | Discard |
| 1.5–2.5 | Probationary |
| < 2.0 | Cap confidence at Speculative |
| ≥ 3.5 | Required for High Conviction |

### Composite Score

```
composite = (
    (catalyst_strength × catalyst_type_prior × 0.30) +
    (quant_confirmation                       × 0.30) +
    (risk_asymmetry                           × 0.25) +
    (information_asymmetry                    × 0.15)
) × (data_quality / 5)
+ confirming_signal_bonus  (capped at +0.9)
```

- All four component scores are **deterministic Python** (no LLM):
  - `catalyst_strength`: insider cluster size (3→3.4, 4→3.8, 5→4.2, 6+→4.5) + materiality bonus (≥0.1% +0.15, ≥0.2% +0.3). Contract: revenue tiers (10%→3.0, 15%→3.5, 25%→4.0, 50%+→4.5).
  - `quant_confirmation`: deterministic VSA + RS scoring in `agent2_quant.py` (v3 fix — was LLM-driven previously despite claim otherwise).
  - `risk_asymmetry`: RS vs IWM ±0.4, quant ≥3.5 +0.3, **short interest >20% +0.4** (raised from +0.2 in v3), fresh signal ≤5d +0.3.
  - `information_asymmetry`: from Agent 1 (analyst coverage 40%, recency 30%, narrative gap 30%). LLM provides the narrative_inconsistency input only.
- LLM (Agent 3) used only for narrative output: thesis, invalidation_trigger, daily_monitors, marginal_buyer_analysis.

### Confirming-signal bonus (v3: no double-count)

If a confirming signal matches the PRIMARY catalyst type (e.g. insider cluster as both primary and confirming), the matching signal is stripped before computing bonus. Was double-counting in v2.

### Signal pools (v3)

| Pool | Composite floor | Upside score floor | Cap |
|---|---|---|---|
| High Conviction | ≥ 3.5 | — | 5 ideas |
| High Upside (new) | ≥ 3.0 | ≥ 2.5 | 3 ideas |

### High-Upside score (new in v3, deterministic 0–5)

- Short interest >20% → +1.5 (squeeze fuel)
- Insider cluster ≥0.20% of market cap → +1.0; ≥0.10% → +0.5
- 5+ unique insiders → +1.0
- Contract ≥50% of TTM revenue → +2.0; 25–50% → +1.0
- Smaller mid-cap ($500M–$1.5B) → +0.5

---

## MULTI-SIGNAL CONFIRMATION

Each confirming signal adds +0.3, capped at +0.9. Confirming signals do NOT substitute for a primary catalyst. Signal that matches the primary catalyst type is stripped before bonus calculation.

| Signal | Tag |
|---|---|
| State/local government contract | `state_government_contract` |
| SEC Form 4 insider buying cluster | `insider_buying_cluster` |
| Job posting surge | `hiring_surge` |
| Specialist fund 13F initiation | `specialist_fund_initiation` |
| Russell reconstitution candidate | `russell_inclusion_candidate` |

The signal_scanner's internal insider check uses the same 3+ cluster threshold as the primary scanner (v3 fix — was 2 previously).

---

## CONFIDENCE LEVEL CAPS

| Condition | Max Confidence |
|---|---|
| Probationary | Speculative |
| `asymmetry_score` < 2.0 | Speculative |
| `liquidity_warning` = True | Medium |
| `regime_override` = True | Medium |
| Neglect screen failed | Cannot be High |

High Conviction definition: composite ≥ 3.5 AND asymmetry ≥ 3.5 AND neglect screen passed AND regime gate passed (not override).

---

## ADVERSARIAL AGENT FLOW

| Agent | Role | LLM? |
|---|---|---|
| 1 (Bull) | Discovery + thesis | Yes (narrative only) |
| 1B (Bear) | Pre-mortem failure case | Yes |
| 1C (Supervisor) | Identifies irresolvable conflict — disqualifies on uncertainty, never defaults to Bull | Yes |
| 2 (Quant) | Deterministic VSA + RS | **No** (v3) |
| 3 (Synthesis) | Composite scoring (Python) + narrative (LLM) | LLM narrative only |

Agent 1D (Inversion) and Agent 4 (Devil's Advocate) were removed. Agent 1D file retained for reference; Agent 4 file deleted.

---

## VSA / QUANT RULES (deterministic — v3)

Score is computed from 5 VSA proxies + relative strength vs IWM, all in Python:
- Volume percentile (vs 30d): top quintile +0.6, above-median +0.3, bottom quintile −0.3
- ATR compression: <0.7 → +0.4 (compression = constructive); >1.3 → −0.2 (expansion)
- Close position in candle: ≥0.7 → +0.3; ≤0.3 → −0.3
- Absorption detected (multi-day high-vol flat VWAP): +0.5
- RS vs IWM: >+2% → +0.4; <−2% → −0.4

Plus hard adjustments:
- Fewer than 3 of 5 proxies computable: cap at 2.5
- Sector beta detected (whole sector elevated RVOL): −0.5
- Short interest >20%: `short_interest_flag = True` (always)
- $100M–$200M name + ADV <$500K: `liquidity_warning = True`

---

## SCORE DECAY (v3: catalyst-specific)

- Insider clusters: full strength to day 21, then 2.5%/day decay. Aligned with 30-day empirical alpha window.
- Government contracts: full strength to day 7, then 5%/day decay. Reflects faster news-cycle alpha decay.

---

## DATA QUALITY AND STALENESS

- OHLCV > 2 trading days stale: `stale_data_flag = True`.
- Missing data: never discard. Penalise `data_quality_score`.
- Average `data_quality_score` < 2.0: cap output at Speculative.

Cache TTLs: OHLCV 1 trading day, filings 90 days, contract award 7 days.

---

## DEDUP RULES (`state_manager.is_deduped`)

- Same ticker: 14-day cooldown (contracts) / 5-day cooldown (insiders).
- Same theme cluster: 7 days.
- Same supply-chain source ticker: 7 days.

---

## THEME CLUSTERING (v3: pure deterministic)

- Grouping key: `sector + catalyst_type + supply_chain_source_ticker`
- Max 2 ideas per theme in final report.
- The previous N² LLM causal-link check was removed (consumed up to 105 LLM calls per run for 15 candidates; deterministic grouping captures the same intent).

---

## API BUDGET (per run — v3)

| Source | Max calls |
|---|---|
| LLM agents | 100 (raised from 40) |
| Market data | 20 |
| Firecrawl | 15 |
| SEC EDGAR | 5 |
| Total | 140 |

LLM raised because v2's 40 was below the floor needed for 15 candidates × ~4 LLM calls each, causing late candidates to be silently disqualified by 1C's budget-exhausted default.

---

## RUN-LEVEL KILL CRITERIA

| Condition | Action |
|---|---|
| Regime data fetch fails | Hard terminate, no output |
| Regime gate fails | Enter Elite-Override mode (no longer hard stop) |
| Avg `data_quality_score` < 2.0 | Speculative labels only |
| `stale_data_flag` > 50% of candidates | Abort run |
| > 70% discarded for missing data | Flag low reliability |
| Agent 1 < 5 candidates | Warn: weak signal environment |
| Nothing reaches composite ≥ 3.0 + upside qualifying | Empty report (valid) |
| Agent 1C disqualifies > 80% | Log: high-conflict environment |

---

## EXIT RULES (advisory — user executes manually)

The engine surfaces signals; the human trades and manages P&L externally. Recommended exit hierarchy per trade:

1. **Profit target** (~+8% standard, ~+12% high-upside) → take profit
2. **Stop loss** (~−6% from entry) → cut loss
3. **Invalidation trigger** (specific event from Agent 3) → exit
4. **Time stop at 10 trading days** → exit if nothing else fired

Time stop is the catch-all; most trades resolve via 1, 2, or 3.

---

## POSITION SIZING (advisory)

- Max risk per trade: 2% of portfolio equity. Position $ = (0.02 × equity) / stop_pct.
- High Conviction up to 2% risk; Medium 1%; Speculative 0.5%.
- Position $ also capped at 5% of 20-day ADV (2.5% for liquidity-warning names).
- Sector soft cap: no more than 50% of active paper-trade positions in one GICS sector.
- Slippage assumption: 60–80 bps round-trip in the $500M–$5B band.

---

## "NO OPPORTUNITIES" IS A VALID OUTPUT

```
NO HIGH CONVICTION IDEAS MET THE 3.5 THRESHOLD TODAY. THIS IS A VALID RESULT.
```

Do not manufacture conviction to fill a report.
