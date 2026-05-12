"""
run_pipeline.py — Simplified Engine v1

Mechanical insider-cluster scanner. No LLM. No bull/bear debate. No composite scoring.
No government contracts. No confirming signals. No neglect screen.

The engine surfaces the single signal that the 7-year backtest validated:
  3+ unique insiders, each >= $100K open-market purchase, within a 14-day window,
  on a $500M-$5B US-listed company, materiality >= 0.02% of market cap.

Entry price = next close after signal_date (Form 4 filing date).
Recommended hold = 10 trading days (20 for elite clusters of 5+ insiders).
Position sizing = cluster-size tier x regime multiplier x risk-per-trade.

Regime state (VIX/VIX3M, IWM vs 20d MA) is REPORTED and used as a SIZING MULTIPLIER.
It does NOT gate signals — the validated cohort was unconditional on regime.

Usage:
  python run_pipeline.py
  python run_pipeline.py --dry-run
"""

import argparse
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yfinance as yf

from orchestrator.state_manager import init_db, log_candidate, log_run_health
from orchestrator.regime_gate import check_regime, regime_gate_header
from orchestrator.universe_builder import build_neglected_universe
from orchestrator.insider_scanner import scan_insider_buying, InsiderCluster
from orchestrator.state_manager import is_deduped


# ── Validated thresholds (LOCKED — 7-year backtest n=93) ──────────────────
MARKET_CAP_MIN_M = 500
MARKET_CAP_MAX_M = 5000
MATERIALITY_FLOOR_PCT = 0.02       # cluster total >= 0.02% of market cap
MIN_DOLLAR_VOLUME = 500_000        # liquidity warning threshold
DEFAULT_HOLD_DAYS = 10
ELITE_HOLD_DAYS = 20
ELITE_CLUSTER_SIZE = 5             # 5+ insiders = elite

# Position sizing tiers (risk-per-trade multiplier)
CLUSTER_SIZE_MULT = {3: 1.0, 4: 1.25}     # default elite (5+) = 1.5
ELITE_SIZE_MULT = 1.5
REGIME_NORMAL_MULT = 1.0
REGIME_STRESSED_MULT = 0.5
MAX_RISK_PER_TRADE_PCT = 2.0       # of portfolio equity

# Scan limits
MAX_TICKERS_TO_SCAN = 500          # universe is already filtered to $500M-$5B via screener
MAX_REPORT_IDEAS = 10              # surfaced per run


@dataclass
class InsiderSignal:
    ticker: str
    company_name: str
    market_cap_m: float
    signal_date: str               # Form 4 filing date (when we'd have known)
    cluster_start: str
    cluster_end: str
    unique_insiders: int
    total_usd: float
    materiality_pct: float
    avg_daily_dollar_volume: float
    entry_price_estimate: float    # current price as proxy; actual entry = next close after signal_date
    insider_names: list = field(default_factory=list)
    insider_roles: list = field(default_factory=list)
    liquidity_warning: bool = False
    recommended_hold_days: int = DEFAULT_HOLD_DAYS
    cluster_size_multiplier: float = 1.0
    is_elite: bool = False


def _enrich_ticker(ticker: str) -> dict:
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        hist = t.history(period="3mo")
        market_cap_m = (info.get("marketCap") or 0) / 1e6
        price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
        avg_volume = float(hist["Volume"].mean()) if not hist.empty else 0
        avg_dollar_vol = avg_volume * price
        return {
            "market_cap_m": round(market_cap_m, 2),
            "price": round(price, 4),
            "avg_daily_dollar_volume": round(avg_dollar_vol, 2),
            "company_name": info.get("longName") or ticker,
            "sector": info.get("sector") or "",
        }
    except Exception:
        return {}


def _days_since(date_str: str) -> int:
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return (datetime.utcnow() - dt).days
    except Exception:
        return 0


def _build_signal(cluster: InsiderCluster, enriched: dict) -> InsiderSignal:
    market_cap_m = enriched.get("market_cap_m", 0)
    materiality_pct = (
        (cluster.total_usd / (market_cap_m * 1e6)) * 100 if market_cap_m > 0 else 0
    )
    is_elite = cluster.unique_insiders >= ELITE_CLUSTER_SIZE
    if is_elite:
        size_mult = ELITE_SIZE_MULT
    else:
        size_mult = CLUSTER_SIZE_MULT.get(cluster.unique_insiders, 1.0)

    return InsiderSignal(
        ticker=cluster.ticker,
        company_name=enriched.get("company_name", cluster.ticker),
        market_cap_m=market_cap_m,
        signal_date=cluster.cluster_end,
        cluster_start=cluster.cluster_start,
        cluster_end=cluster.cluster_end,
        unique_insiders=cluster.unique_insiders,
        total_usd=cluster.total_usd,
        materiality_pct=round(materiality_pct, 4),
        avg_daily_dollar_volume=enriched.get("avg_daily_dollar_volume", 0),
        entry_price_estimate=enriched.get("price", 0),
        insider_names=sorted({t.name for t in cluster.transactions}),
        insider_roles=sorted({t.role for t in cluster.transactions if t.role}),
        liquidity_warning=enriched.get("avg_daily_dollar_volume", 0) < MIN_DOLLAR_VOLUME,
        recommended_hold_days=ELITE_HOLD_DAYS if is_elite else DEFAULT_HOLD_DAYS,
        cluster_size_multiplier=size_mult,
        is_elite=is_elite,
    )


def _regime_multiplier(regime) -> tuple[float, str]:
    if regime.gate_pass:
        return REGIME_NORMAL_MULT, "NORMAL"
    if regime.vix_value is None:
        return 0.0, "HARD_FAIL"
    return REGIME_STRESSED_MULT, "STRESSED"


def _format_report(
    run_id: str,
    regime,
    regime_state: str,
    regime_mult: float,
    signals: list,
    tickers_scanned: int,
    discarded_log: list,
) -> str:
    lines = []
    today = date.today().strftime("%Y-%m-%d")
    lines.append(f"=== SIMPLIFIED ENGINE v1 — INSIDER CLUSTER REPORT — {today} ===")
    lines.append(f"Run ID: {run_id} | Tickers Scanned: {tickers_scanned} | Signals Surfaced: {len(signals)}")
    lines.append("")
    lines.append(regime_gate_header(regime))
    lines.append(f"REGIME STATE: {regime_state} | Sizing multiplier: {regime_mult}x")
    lines.append("(Regime is informational + position-sizing only. It does NOT gate signals.)")
    lines.append("")
    lines.append("─" * 60)
    lines.append("INSIDER CLUSTER SIGNALS")
    lines.append("─" * 60)

    if not signals:
        lines.append("")
        lines.append("NO QUALIFYING CLUSTERS TODAY. THIS IS A VALID RESULT.")
        lines.append("(Validated cohort historically produced ~1 signal/month.)")
    else:
        signals.sort(key=lambda s: (s.unique_insiders, s.materiality_pct), reverse=True)
        for i, s in enumerate(signals[:MAX_REPORT_IDEAS], start=1):
            total_size_mult = round(s.cluster_size_multiplier * regime_mult, 3)
            recommended_risk_pct = round(MAX_RISK_PER_TRADE_PCT * total_size_mult, 3)
            flags = []
            if s.is_elite:
                flags.append("ELITE 5+ INSIDERS")
            if s.liquidity_warning:
                flags.append("LIQUIDITY WARNING")
            flag_str = f"  ⚠ {' | '.join(flags)}" if flags else ""
            lines.append("")
            lines.append(f"{i}. {s.ticker} — {s.company_name}")
            lines.append(f"   Cluster: {s.unique_insiders} insiders | ${s.total_usd:,.0f} total | {s.materiality_pct:.3f}% of mcap")
            lines.append(f"   Market cap: ${s.market_cap_m:,.0f}M | ADV: ${s.avg_daily_dollar_volume:,.0f}")
            lines.append(f"   Cluster window: {s.cluster_start} to {s.cluster_end} | Signal date: {s.signal_date}")
            lines.append(f"   Insiders: {', '.join(s.insider_names)}")
            if s.insider_roles:
                lines.append(f"   Roles: {', '.join(s.insider_roles)}")
            lines.append(f"   Entry: next close after {s.signal_date} (current ~${s.entry_price_estimate:.2f})")
            lines.append(f"   Hold: {s.recommended_hold_days} trading days")
            lines.append(f"   Sizing: cluster {s.cluster_size_multiplier}x × regime {regime_mult}x = {total_size_mult}x")
            lines.append(f"          (recommended risk: {recommended_risk_pct:.2f}% of equity, max {MAX_RISK_PER_TRADE_PCT}%)")
            if flag_str:
                lines.append(flag_str)

    lines.append("")
    lines.append("─" * 60)
    if discarded_log:
        lines.append(f"DISCARDED ({len(discarded_log)}):")
        for entry in discarded_log[:20]:
            lines.append(f"  {entry['ticker']} — {entry['reason']}")
        if len(discarded_log) > 20:
            lines.append(f"  ... and {len(discarded_log) - 20} more")
    else:
        lines.append("DISCARDED: none")
    lines.append("")
    lines.append("─" * 60)
    lines.append("EXIT RULES (advisory — user executes manually):")
    lines.append("  1. Time stop at recommended hold (10d standard / 20d elite)")
    lines.append("  2. Cut on -6% from entry (advisory stop)")
    lines.append("  3. Trim on +8% if hit before time stop (advisory target)")
    lines.append("Validation source: 7-year OpenInsider backtest, n=93 production cohort.")
    return "\n".join(lines)


def _save_report(report: str, run_id: str) -> Path:
    logs_dir = Path(__file__).parent / "research_logs"
    logs_dir.mkdir(exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = logs_dir / f"report_{ts}_{run_id}.md"
    path.write_text(report)
    return path


def main(dry_run: bool = False, max_tickers: int = MAX_TICKERS_TO_SCAN):
    init_db()
    run_id = str(uuid.uuid4())[:8]
    print(f"\n[Pipeline] Starting run {run_id} {'(DRY RUN)' if dry_run else ''}")

    # 1. Regime — informational + sizing multiplier
    regime = check_regime()
    print(regime_gate_header(regime))
    regime_mult, regime_state = _regime_multiplier(regime)
    print(f"[Pipeline] Regime state: {regime_state} | sizing multiplier: {regime_mult}x")

    if regime.vix_value is None:
        # Hard-fail (data fetch failed). Still scan but cap sizing at 0.
        print("[Pipeline] Regime data fetch failed. Signals will still surface; recommended size is 0.")

    # 2. Universe
    watchlist = build_neglected_universe()
    if not watchlist:
        print("[Pipeline] Watchlist empty.")
        log_run_health(run_id, {"total_candidates": 0, "run_status": "no_universe"})
        return

    # Restrict to validated mcap band ($500M-$5B); the screener pulls $200M+ but
    # insider alpha is only validated at >= $500M.
    eligible = [w for w in watchlist if MARKET_CAP_MIN_M <= w.get("market_cap_m", 0) <= MARKET_CAP_MAX_M]
    eligible = eligible[:max_tickers]
    print(f"[Pipeline] {len(eligible)} tickers in $500M-$5B band to scan.")

    if dry_run:
        print(f"[Pipeline] DRY RUN — would scan {len(eligible)} tickers via SEC EDGAR Form 4.")
        return

    signals: list[InsiderSignal] = []
    discarded_log: list[dict] = []

    # 3. Scan each ticker for insider clusters
    for entry in eligible:
        ticker = entry["ticker"]
        blocked, dedup_reason = is_deduped(ticker)
        if blocked:
            continue

        try:
            cluster = scan_insider_buying(ticker, days_back=21)
        except Exception as e:
            print(f"[Pipeline] {ticker} scan error: {e}")
            continue

        if not cluster.detected:
            continue

        # Materiality + market cap re-check via fresh enrichment
        enriched = _enrich_ticker(ticker)
        if not enriched:
            discarded_log.append({"ticker": ticker, "reason": "enrichment_failed"})
            continue

        market_cap_m = enriched.get("market_cap_m", 0)
        if market_cap_m < MARKET_CAP_MIN_M or market_cap_m > MARKET_CAP_MAX_M:
            discarded_log.append({"ticker": ticker, "reason": f"mcap ${market_cap_m:.0f}M outside $500M-$5B"})
            continue

        if market_cap_m > 0:
            materiality_pct = (cluster.total_usd / (market_cap_m * 1e6)) * 100
            if materiality_pct < MATERIALITY_FLOOR_PCT:
                discarded_log.append({
                    "ticker": ticker,
                    "reason": f"materiality {materiality_pct:.4f}% below {MATERIALITY_FLOOR_PCT}% floor",
                })
                continue

        signal = _build_signal(cluster, enriched)
        signals.append(signal)

        log_candidate(run_id, {
            "ticker": signal.ticker,
            "catalyst_type": "insider_buying_cluster",
            "catalyst_date": signal.signal_date,
            "days_since_catalyst": _days_since(signal.signal_date),
            "insider_buying_cluster": 1,
            "insider_buy_total_usd": signal.total_usd,
            "insider_buy_names": signal.insider_names,
            "liquidity_warning": int(signal.liquidity_warning),
            "regime_gate_pass": int(regime.gate_pass),
        })

    # 4. Report
    report = _format_report(
        run_id, regime, regime_state, regime_mult, signals, len(eligible), discarded_log,
    )
    path = _save_report(report, run_id)
    print(report)
    print(f"\n[Pipeline] Report saved to {path}")

    log_run_health(run_id, {
        "regime_gate_pass": int(regime.gate_pass),
        "total_candidates": len(eligible),
        "final_report_count": len(signals),
        "run_status": "ok",
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Show plan without scanning")
    parser.add_argument("--max-tickers", type=int, default=MAX_TICKERS_TO_SCAN, help="Cap on tickers to scan")
    args = parser.parse_args()
    main(dry_run=args.dry_run, max_tickers=args.max_tickers)
