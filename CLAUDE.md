# TradeFinder — LLM Trading Edge Investigation

A 17-agent, 3-stage investigation answering: "How can large language models give a retail trader a genuine, persistent edge in US equity markets?"

## Architecture

- **Stage 1** (8 agents, 5 rounds): Creative hypothesis generation with adversarial Skeptic review
- **Stage 2** (7 agents): Blind, locked backtesting pipeline built from first principles
- **Bridge** (2 agents): Executor + Verifier — the only channel between Stage 1 and Stage 2

Information firewall: Stage 1 and Stage 2 never communicate. Pipeline is locked before seeing any hypotheses.

## Current State

First full cycle complete. 6 PROMOTE hypotheses, 10 REVISE, 6 KILL. Executable loop built with signal construction framework and three literature-required safeguards (contamination detection, survivorship guard, cumulative FDR tracking).

## Key Files

- `.claude/PLAN.md` — Full 17-agent specification
- `stage1/` — Stage 1 outputs (round1-5, ranked hypotheses)
- `stage2-pipeline/` — Pipeline implementation + signal builder + safeguards
- `bridge/` — Bridge verdicts and sanitized feedback

## Key Constraints

- Retail trader: $50K-$250K capital, standard brokerage, checking once per day
- Data: free or low-cost retail-accessible only (SEC EDGAR, Yahoo Finance, FDA.gov)
- All signals must be falsifiable with quantitative predictions
