# TradeFinder — LLM Trading Edge Investigation

A 17-agent, 3-stage investigation answering: "How can large language models give a retail trader a genuine, persistent edge in US equity markets?"

## Architecture

- **Stage 1** (8 agents, 5 rounds): Creative hypothesis generation with adversarial Skeptic review
- **Stage 2** (7 agents): Blind, locked backtesting pipeline built from first principles
- **Bridge** (2 agents): Executor + Verifier — the only channel between Stage 1 and Stage 2

Information firewall: Stage 1 and Stage 2 never communicate. Pipeline is locked before seeing any hypotheses.

## Current State

First real empirical verdict produced (2026-05-14). The loop works end-to-end with real data: hypothesis JSON → SEC EDGAR filing download → linguistic extraction → signal → pipeline → verdict. First test (MD&A Tone Shift) was BROKEN — hedging density in 10-K filings doesn't predict returns. The machine works; now it needs more hypotheses fed through it.

## Data Adapters

| Adapter | Status | What it provides |
|---------|--------|-----------------|
| SEC EDGAR | **LIVE** | Real 10-K/10-Q/8-K filing text from sec.gov/Archives |
| Yahoo Finance | **LIVE** | Real OHLCV price data (survivorship bias pre-2017) |
| FDA | PARTIAL | Real metadata from api.fda.gov, but document text needs PDF scraping |
| FMP | SKELETON | Not connected |
| FRED | SKELETON | Not connected |

## Key Files

- `.claude/PLAN.md` — Full 17-agent specification
- `stage1/` — Stage 1 outputs (round1-5, ranked hypotheses)
- `stage2-pipeline/` — Pipeline implementation + signal builder + safeguards
- `stage2-pipeline/signal_builder/adapters/sec_edgar.py` — SEC filing download (real data)
- `stage2-pipeline/signal_builder/adapters/fda.py` — FDA adapter (synthetic fallback)
- `stage2-pipeline/signal_builder/adapters/yahoo_finance.py` — Yahoo price data
- `stage2-pipeline/run_loop.py` — Full loop runner (hypothesis → verdict)
- `stage2-pipeline/hypothesis_mda_tone.json` — Example hypothesis template
- `bridge/` — Bridge verdicts and sanitized feedback

## Key Constraints

- Retail trader: $50K-$250K capital, standard brokerage, checking once per day
- Data: free or low-cost retail-accessible only (SEC EDGAR, Yahoo Finance, FDA.gov)
- All signals must be falsifiable with quantitative predictions
- Three safeguards active: contamination detection, survivorship guard, cumulative FDR tracking
