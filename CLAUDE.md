# TradeFinder — LLM Trading Edge Investigation

A 17-agent, 3-stage investigation answering: "How can large language models give a retail trader a genuine, persistent edge in US equity markets?"

## Architecture

- **Stage 1** (8 agents, 5 rounds): Creative hypothesis generation with adversarial Skeptic review
- **Stage 2** (7 agents): Blind, locked backtesting pipeline built from first principles
- **Bridge** (2 agents): Executor + Verifier — the only channel between Stage 1 and Stage 2

Information firewall: Stage 1 and Stage 2 never communicate. Pipeline is locked before seeing any hypotheses.

## Current State

**Audit complete (2026-05-14):** 55 issues fixed across 15 files. All silent data fabrication eliminated. DownloadPool, Newey-West HAC SE, calendar annualization, business-day temporal alignment all in place.

**Engine status — 4 hypotheses tested, all BROKEN:**
1. MD&A Tone Shift → BROKEN (Sharpe 0.82, CI includes zero)
2. Risk Factor Drift → BROKEN (CI includes zero, p=1.0)
3. FDA BRLAS → BROKEN (α=339bps < 500bps min, 20 events)
4. CAM Expansion Velocity → BROKEN (hit rate 51.85% < 55% min)

**Infrastructure built (2026-05-14 session):**
- EventStudyBacktester: handles sparse/event-driven signals (FDA, M&A, regulatory)
- Sparse signal auto-detection: routes to event study vs cross-sectional backtest
- LLMExtractor: generic LLM-based signal extraction (Anthropic/DeepSeek API, temp=0)
- 8-K section extraction: Item 5.02 (departure), Item 2.02 (earnings), etc.
- SEC User-Agent fix: honest `TradeFinderResearch/1.0` — browser-mimetic strings rejected
- Universe refresh: 10,347 SEC tickers available (was stuck at 61 due to WAF)

**13 of 16 Stage 1 hypotheses still untested. Signal construction is the bottleneck.**

**Next session:**
- Departure Language Severity run was mid-LLM-extraction when interrupted — restart needed
- Pronoun Divergence needs transcript data source (not on SEC EDGAR)
- Consider pre-building filing cache for faster iteration
- Fix LLM response parsing (DeepSeek returns thinking block before text)

## Data Adapters

| Adapter | Status | What it provides |
|---------|--------|-----------------|
| SEC EDGAR | **LIVE** | Real 10-K/10-Q/8-K filing text from sec.gov/Archives, lxml parsing, retry/backoff |
| Yahoo Finance | **LIVE** | Real OHLCV price data, per-ticker parquet caching, parallel download pool |
| FDA | PARTIAL | Real metadata from api.fda.gov; raises DataAcquisitionError when text unavailable |
| FMP | SKELETON | Honestly reports NOT IMPLEMENTED — no fake data |
| FRED | SKELETON | Raises DataAcquisitionError when API key missing — no synthetic fallback |

## Key Files

- `.claude/PLAN.md` — Full 17-agent specification
- `stage1/` — Stage 1 outputs (round1-5, ranked hypotheses)
- `stage2-pipeline/` — Pipeline implementation + signal builder + safeguards
- `stage2-pipeline/signal_builder/universe_builder.py` — Autonomous universe construction (no human ticker selection)
- `stage2-pipeline/signal_builder/download_pool.py` — TokenBucket rate limiter + ThreadPoolExecutor download pool
- `stage2-pipeline/signal_builder/adapters/sec_edgar.py` — SEC filing download with retry/backoff + CIK cache
- `stage2-pipeline/signal_builder/adapters/yahoo_finance.py` — Yahoo price data with parquet caching + parallel download
- `stage2-pipeline/implementation/pipeline.py` — Main pipeline (no silent fallbacks, proper error escalation)
- `stage2-pipeline/implementation/backtest.py` — Calendar-based annualization with holding period support
- `stage2-pipeline/implementation/temporal.py` — Point-in-time alignment with business day offsets
- `stage2-pipeline/implementation/factors.py` — Factor recycling detection with Newey-West HAC SE
- `stage2-pipeline/implementation/breakers.py` — Two-sided permutation tests, edge decay in years
- `stage2-pipeline/run_loop.py` — Full loop runner (hypothesis → verdict)
- `bridge/` — Bridge verdicts and sanitized feedback

## Key Constraints

- Retail trader: $50K-$250K capital, standard brokerage, checking once per day
- Data: free or low-cost retail-accessible only (SEC EDGAR, Yahoo Finance, FDA.gov)
- All signals must be falsifiable with quantitative predictions
- Three safeguards active: contamination detection, survivorship guard, cumulative FDR tracking
- No silent data fabrication — unavailable data produces UNTESTABLE verdict, not fake results
