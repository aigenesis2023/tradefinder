# Simplified Engine v1 — Review Packet

A self-contained packet for an outside reviewer (Gemini, GPT, Grok, human) to critique a trading research system. Paste the whole document in and ask for design / empirical / methodological critique.

**Author's note to the reviewer:** This engine was deliberately stripped from a larger v3 system. Earlier reviewers (Gemini, GPT) and the author independently concluded that v3's multi-agent LLM scaffolding, government-contract catalyst, neglect screen, composite scoring weights, confirming signals, and high-upside score were all untested layers around a single validated mechanical filter. v1 removes all of them. **Please critique what remains, not what was removed** — unless you believe a removed component should be reinstated, in which case provide the empirical case.

---

## 1. WHAT THIS IS

A daily-run, mechanical scanner that surfaces open-market insider buying clusters on US-listed mid-cap stocks ($500M–$5B). Output is a ranked list of qualifying signals with recommended hold, recommended position size, and risk flags. **No LLM is used anywhere in signal generation.** A human discretionary trader decides whether to act.

**Edge thesis:** Institutions (mutual funds, pension funds, sell-side analysts) systematically under-cover the $500M–$5B band due to position-size minima and lack of banking-fee revenue. Multi-insider purchase clusters in this band have produced statistically meaningful IWM-adjusted alpha over a 7-year backtest. The engine surfaces these clusters mechanically and lets the operator manage execution.

**Operating context:** 60-day paper-trading window to produce a verifiable track record. The engine is one of four (Claude, GPT, Gemini, Grok) for a public case-study comparison.

---

## 2. EMPIRICAL FOUNDATION

### Headline backtest (OpenInsider 2018–2024, IWM-adjusted)

| Filter | n | Raw 30d | IWM 30d | Alpha | Alpha win rate |
|---|---|---|---|---|---|
| All 3+ insider clusters | 121 | +2.80% | −0.01% | **+2.81%** | 64.5% |
| **3+ + $500M–$5B (production)** | **93** | **+3.37%** | **−0.55%** | **+3.92%** | **68.8%** |
| 3+ + $200M–$500M (micro) | 28 | +0.31% | +1.18% | −0.87% | 50.0% |
| 2-insider clusters (any mcap) | 261 | +0.63% | +0.37% | +0.26% | 48.3% |

### Holding-period analysis (production cohort, n=93)

| Horizon | Mean raw return | Median | Win rate | Per-day | IWM-adj alpha |
|---|---|---|---|---|---|
| 7d | — | — | — | 0.188% | +1.32% |
| **10d** | +1.84% | +0.18% | 52.7% | **0.249%** | +2.93% |
| 30d | +3.37% | +3.87% | 59.1% | 0.112% | +3.92% |
| 60d (ex-COVID, n=78) | +8.65% | +10.36% | **73.1%** | 0.144% | **+7.82%** |
| 180d | — | — | — | — | strongly negative (mean reversion) |

### Cluster-size effect (production cohort)

| Cluster size | n | 10d alpha | 20d/30d behaviour |
|---|---|---|---|
| 3 insiders | 71 | +2.5% est. | normal decay curve |
| 4 insiders | 15 | +3.5% est. | normal decay |
| 5+ insiders (ELITE) | 7 | **+6.68%** | mean-reverts to +0.05% by day 30 |

### Decisions baked into v1

- **10-day default hold** maximises per-day alpha. **20-day elite hold** for 5+ clusters captures the elite peak before mean-reversion.
- **$500M floor** — micro-cap 3+ is *negative* alpha after IWM adjustment.
- **3+ insider floor** — 2-insider clusters are noise.
- **Materiality floor 0.02% of market cap** — a $250K cluster on a $3B company is a token gesture, not conviction (filters in original n=93).
- **Backtest entry = filing date close**, not transaction date. The +3.92% alpha is post-filing alpha, fully reflecting the public-disclosure delay.

---

## 3. ARCHITECTURE (full pipeline)

```
1. RegimeCheck      VIX/VIX3M, IWM vs 20d MA — informational + position-size multiplier
2. UniverseBuild    yfinance screener, $500M–$5B band, cached 7d
3. InsiderScan      SEC EDGAR Form 4 per ticker (3+ insiders, 14d window, $100K+, P-code)
4. Filter           market cap recheck + materiality floor (0.02% of mcap)
5. Build signal     compute size multipliers, recommended hold, liquidity warning
6. Rank             by (unique_insiders desc, materiality_pct desc)
7. Report           write report + log to SQLite for outcome tracking
```

No agents. No LLM calls. No multi-step debate. No scoring formula with weights.

### Position sizing (advisory)

```
recommended_risk_pct = max_risk_per_trade × cluster_size_mult × regime_mult
```

| Component | Values |
|---|---|
| `max_risk_per_trade` | 2.0% of equity |
| `cluster_size_mult` | 3 insiders = 1.0x; 4 = 1.25x; 5+ = 1.5x |
| `regime_mult` | NORMAL = 1.0x; STRESSED = 0.5x; HARD_FAIL = 0x |

Liquidity floor: if 20d ADV < $500K → liquidity_warning, additional cap at 5% of ADV.

### Exit rules (advisory — operator executes manually)

1. Time stop: 10 trading days (standard) / 20 trading days (5+ elite).
2. Cut at −6% from entry.
3. Trim at +8%.
4. Manual invalidation on material new info.

### Dedup

Same ticker: 5-day cooldown. No theme or supply-chain dedup.

---

## 4. WHAT WAS DELIBERATELY REMOVED (and why)

| Removed | Why |
|---|---|
| Agent 1 (Bull LLM), 1B (Bear), 1C (Supervisor), 3 (Synthesis narrative) | Outputs were narrative, did not enter scoring. Risk: anchoring the operator on a confabulated thesis. |
| Agent 2 (deterministic VSA/RS scoring) | Not in the validated cohort. Reinstate only after feature-level backtest. |
| Government contract catalyst | Zero backtest evidence. Literature supports the effect for large-caps only. |
| Neglect screen (analyst <8, news <3, institutional <30%, volume) | Not in validated cohort — adding it filters out validated winners. |
| Composite scoring weights (0.30/0.30/0.25/0.15) | With one signal type there is nothing to weight. Heuristic numbers had no derivation. |
| High-Upside score | Re-encoded cluster size + short interest already visible in surfaced signal. |
| Confirming signals (job postings, 13F initiations, Russell candidacy, state contracts) | Most rely on data the engine doesn't have (LinkedIn, real-time 13F). Likely fired on stale data or not at all. |
| Theme clustering | At ~1 signal/month, sector overlap is not a practical problem. |
| Information asymmetry score | Subcomponents not in validated cohort. |
| Elite-override binary gate during regime fail | Replaced by sizing multiplier — same intent, no signal suppression. |
| Domicile filter | Already removed in v3.1; validated cohort included foreign issuers. |

**Total removal:** ~3,000 lines of runtime Python deleted; engine surface area dropped from ~3,000 to 1,224 runtime lines.

---

## 5. KNOWN RISKS AND OPEN QUESTIONS (for the reviewer)

This is where the author wants the most adversarial scrutiny.

### A. Statistical fragility
- **n=93 means ~13 signals/year.** Point estimate of +3.92% alpha at 30d has wide CI; a handful of outliers (post-COVID rebound, Mar 2020 panic clusters) could be carrying the mean.
- The 60-day +7.82% alpha is ex-COVID; including COVID inflates results.
- Cluster-size sub-cohorts (5+ insiders = n=7) are far too small to be conclusive on their own — yet the engine sizes those positions higher.

### B. Absolute vs alpha returns
- Headline win rate is **alpha** win rate (beat IWM). A retail trader gets absolute P&L, not alpha.
- Author has not yet computed absolute (cash) P&L distribution at 10d on n=93. **This is the most important pre-paper-trade question** — at 53% absolute win rate with +8/−6 R:R, the system loses money before costs.

### C. Transaction costs
- $500M–$5B names typically have 30–60 bps round-trip spreads; $100K order incurs 20–50 bps slippage.
- Engine assumes zero costs. Realistic net alpha at 10d may be 1.0–1.5%, not 2.93%.

### D. Filing-date timing
- Engine enters on close *after* Form 4 filing. Backtest does the same — so the post-filing alpha decay (well-documented in literature) is already baked into the headline number.
- However: real-time engine has additional latency (EDGAR pull lag, daily run cadence). May miss same-day entries.

### E. Threshold derivation
- All thresholds in v1 trace to the validated cohort (3+ insiders, $500M–$5B, 0.02% materiality, 14-day window, $100K per transaction). These are *the cohort definition*, not heuristics.
- BUT: cluster-size multipliers (1.0/1.25/1.5x) and regime multipliers (1.0/0.5/0x) are heuristic. They have not been derived from data.

### F. Regime as multiplier vs gate
- 2019 cohort: +5.09% raw / 72% win. 2022: −5.17% raw / 40% win. Regime clearly matters.
- v1 chose multiplier over gate to preserve option-to-trade in stressed regimes.
- Reviewer question: should regime affect the *trade selection* (skip 3-insider, keep 5+ insider) rather than the *size* (everything keeps but half size)? Current implementation does the latter.

### G. The "is it already public?" check
- A single LLM call per surfaced signal could verify whether the catalyst was already reported by mainstream financial media (WSJ/Bloomberg/Reuters/FT) before signal_date.
- v1 does NOT include this check. Adding it would re-introduce LLM dependency.
- Reviewer question: is one well-bounded LLM call worth the dependency, or is the materiality + cluster-size filter already selecting against widely-covered news?

### H. Survivorship / look-ahead in backtest
- Backtest uses `filing_date <= as_of_date` constraint, so no future-knowledge.
- Universe sourcing for the backtest cohort: signals are detected by scanning historical Form 4 filings on tickers that existed at the time. Survivorship-bias check: delisted/acquired tickers ARE included with a `delisted_or_acquired` flag.
- Reviewer question: any hole in this reasoning?

### I. Sample concentration
- Backtest has not been sliced by sector. If signals concentrate in 1–2 sectors (e.g. biotech, REITs), sector beta could explain alpha.
- Sector-adjusted backtest is a stated next step.

---

## 6. VALIDATION ROADMAP (not in v1, will only ship if validated)

Each must demonstrate measurable lift on n=93 (or refreshed cohort) before reintroduction:

1. **Insider role mix** — CEO+CFO+independent director clusters vs three same-role clusters.
2. **Cluster velocity** — 3 buys in 2 days vs 3 in 14.
3. **Purchase price vs 30-day VWAP** — buying strength vs buying weakness.
4. **Insider tenure / cluster repeat history** per ticker.
5. **Short interest > 20%** as a sizing modifier (academic support, not in cohort).
6. **Single "already public?" LLM check** (one call per surfaced signal, D3-style).
7. **Sector-beta adjustment** to alpha measurement.

---

## 7. FILES (repo structure)

```
trading-research/
├── CLAUDE.md                       # normative rulebook (this packet's authority)
├── REVIEW_PACKET.md                # this document
├── run_pipeline.py                 # main entry — 339 lines, no LLM
├── orchestrator/
│   ├── insider_scanner.py          # SEC EDGAR Form 4 cluster detection (320 lines)
│   ├── regime_gate.py              # VIX/VIX3M + IWM 20d MA (122 lines)
│   ├── universe_builder.py         # yfinance screener cache (186 lines)
│   └── state_manager.py            # SQLite logging + dedup (257 lines)
├── backtest/                       # validation infrastructure (unchanged from v3)
│   ├── cluster_detector.py
│   ├── edgar_index.py
│   ├── iwm_benchmark.py
│   ├── measure_oi_outcomes.py
│   ├── openinsider_pull.py
│   ├── price_data.py
│   └── run_backtest.py
├── data/                           # SQLite DB
├── cache/                          # CIK map, watchlist
└── research_logs/                  # per-run reports (markdown)
```

**Runtime surface (excludes backtest):** 1,224 lines of Python.
**Total Python in repo (incl. backtest):** 2,751 lines.

---

## 8. THE QUESTION FOR THE REVIEWER

Three asks, in priority order:

1. **Empirical**: Is the n=93 cohort an adequate foundation for a 60-day paper-trade case study? What is the most likely way the headline alpha number is misleading?

2. **Architectural**: Is there anything in the v1 pipeline that should also be removed (it does not earn its place)? Conversely, is there anything from the removed list that should be reinstated — and on what empirical basis?

3. **Operational**: For a discretionary retail operator running this engine daily over 60 days, what is the single most likely failure mode that has not been addressed?

Critique style: please be adversarial. The author has been through one round of pushing back on Claude's reflexive defence of complexity and would rather hear the hard truth now than after 60 days of paper trading.
