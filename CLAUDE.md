# TradeFinder — LLM Trading Edge Investigation

A 17-agent, 3-stage investigation answering: "How can large language models give a retail trader a genuine, persistent edge in US equity markets?"

## Architecture

- **Stage 1** (8 agents, 5 rounds): Creative hypothesis generation with adversarial Skeptic review
- **Stage 2** (7 agents): Blind, locked backtesting pipeline built from first principles
- **Bridge** (2 agents): Executor + Verifier — the only channel between Stage 1 and Stage 2

Information firewall: Stage 1 and Stage 2 never communicate. Pipeline is locked before seeing any hypotheses.

## Current State

**Audit complete (2026-05-14):** 55 issues fixed across 15 files. All silent data fabrication eliminated — pipeline now honestly reports UNTESTABLE when data is unavailable. DownloadPool with token-bucket rate limiting enables parallel SEC/Yahoo data acquisition. Calendar-based annualization with business-day temporal alignment produces realistic metrics. Factor regression uses Newey-West HAC standard errors. Permutation tests are two-sided.

**Verified end-to-end run:** MD&A Tone Shift → BROKEN (Sharpe 0.82, bootstrap CI includes zero, permutation p=1.0, power 23.7%).

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
