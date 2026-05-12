"""
run_pipeline.py — Simplified Engine v3.0 (OpenInsider-first architecture)

Mechanical insider-cluster scanner. No LLM. No bull/bear debate. No composite scoring.
No government contracts. No confirming signals. No neglect screen. No sizing multipliers.

v3.0 architecture (vs v2.1):
  Prior: per-ticker SEC EDGAR scan — ~25-30 hours to cover the $200M-$3B universe,
         and the scan only covered the first N tickers (~5% of universe per run).
  Now:   single OpenInsider scrape returns all qualifying insider activity across the
         entire US market; cluster detection runs on the aggregated set, then yfinance
         enrichment runs only on the handful of detected candidates. Full-market
         coverage in ~30 seconds on warm cache, ~5 minutes on cold cache.

This is a STEP-1 SCREENING TOOL, not a complete trading strategy. It surfaces
structurally meaningful insider-cluster events for the operator to then research
further (fundamentals, news, sector context, valuation) before deciding whether to
take a position. The engine does not claim a standalone edge.

Calibrated against academic literature (see CLAUDE.md):
  - Cluster definition (3+ insiders, 30-day window, $100K each): Lakonishok-Lee 2001;
    Alldredge-Blank 2019; Kang et al. 2018.
  - Market cap band $200M–$3B: smaller-is-better consensus across studies.
  - 180-day hold horizon: Jeng-Metrick-Zeckhauser 2003; Cohen-Malloy-Pomorski 2012.
  - Opportunistic vs routine soft gate: Cohen-Malloy-Pomorski 2012.
  - 10b5-1 exclusion: well-established (OpenInsider filters at source via xp=1).

Realistic expectation: 4–8% gross / 3–7% net per 180-day trade (median academic
estimate). Comparable to passive indexing on risk-adjusted terms. The engine's value
is the SCREEN, not the standalone edge.

Usage:
  python run_pipeline.py
  python run_pipeline.py --dry-run
"""

import argparse
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yfinance as yf

from orchestrator.state_manager import init_db, log_candidate, log_run_health, is_deduped
from orchestrator.regime_gate import check_regime, regime_gate_header
from orchestrator.openinsider_feed import scan as scan_openinsider
from orchestrator.insider_scanner import InsiderCluster


# ── Validated thresholds (literature-aligned, v3.0) ───────────────────────
MARKET_CAP_MIN_M = 200             # Lakonishok-Lee, Jeng et al.: smaller-cap stronger
MARKET_CAP_MAX_M = 3000            # GPT/literature: $500M–$5B too wide; tighten
MIN_DOLLAR_VOLUME = 500_000        # liquidity-warning threshold
RECOMMENDED_HOLD_DAYS = 180        # v2.1: 6-month horizon (academic literature peaks ~6mo)
TRANSACTION_COST_PCT = 1.0         # realistic round-trip cost assumption for retail
MAX_RISK_PER_TRADE_PCT = 2.0       # of portfolio equity (flat, no cluster-size tier)

# OpenInsider feed parameters
RECENT_WINDOW_DAYS = 45            # surface clusters whose cluster_end is within this window
HISTORY_DAYS = 1100                # ~3 years for routine/opportunistic classification

# Short-interest "disagreement" band (Chung-Sul-Wang 2019, informational only)
DISAGREEMENT_SI_LOW_PCT = 10.0
DISAGREEMENT_SI_HIGH_PCT = 40.0

MAX_REPORT_IDEAS = 25              # full universe means more candidates to surface


@dataclass
class InsiderSignal:
    ticker: str
    company_name: str
    market_cap_m: float
    signal_date: str
    cluster_start: str
    cluster_end: str
    unique_insiders: int
    opportunistic_count: int
    routine_insiders: list
    total_usd: float
    materiality_pct: float
    avg_daily_dollar_volume: float
    entry_price_estimate: float
    short_interest_pct: float | None = None
    disagreement_flag: bool = False
    analyst_count: int | None = None
    insider_names: list = field(default_factory=list)
    insider_roles: list = field(default_factory=list)
    liquidity_warning: bool = False


def _enrich_ticker(ticker: str) -> dict:
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        hist = t.history(period="3mo")
        market_cap_m = (info.get("marketCap") or 0) / 1e6
        price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
        avg_volume = float(hist["Volume"].mean()) if not hist.empty else 0
        avg_dollar_vol = avg_volume * price

        si_raw = info.get("shortPercentOfFloat")
        if si_raw is None or si_raw == 0:
            si_raw = info.get("sharesPercentSharesOut")
        short_interest_pct = (
            round(float(si_raw) * 100, 2) if si_raw is not None and si_raw > 0 else None
        )

        analyst_raw = info.get("numberOfAnalystOpinions")
        analyst_count = int(analyst_raw) if analyst_raw is not None else None

        return {
            "market_cap_m": round(market_cap_m, 2),
            "price": round(price, 4),
            "avg_daily_dollar_volume": round(avg_dollar_vol, 2),
            "company_name": info.get("longName") or ticker,
            "sector": info.get("sector") or "",
            "short_interest_pct": short_interest_pct,
            "analyst_count": analyst_count,
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
    si_pct = enriched.get("short_interest_pct")
    disagreement_flag = bool(
        si_pct is not None
        and DISAGREEMENT_SI_LOW_PCT <= si_pct <= DISAGREEMENT_SI_HIGH_PCT
    )
    return InsiderSignal(
        ticker=cluster.ticker,
        company_name=enriched.get("company_name", cluster.ticker),
        market_cap_m=market_cap_m,
        signal_date=cluster.cluster_end,
        cluster_start=cluster.cluster_start,
        cluster_end=cluster.cluster_end,
        unique_insiders=cluster.unique_insiders,
        opportunistic_count=cluster.opportunistic_count,
        routine_insiders=cluster.routine_insiders,
        total_usd=cluster.total_usd,
        materiality_pct=round(materiality_pct, 4),
        avg_daily_dollar_volume=enriched.get("avg_daily_dollar_volume", 0),
        entry_price_estimate=enriched.get("price", 0),
        short_interest_pct=si_pct,
        disagreement_flag=disagreement_flag,
        analyst_count=enriched.get("analyst_count"),
        insider_names=sorted({t.name for t in cluster.transactions}),
        insider_roles=sorted({t.role for t in cluster.transactions if t.role}),
        liquidity_warning=enriched.get("avg_daily_dollar_volume", 0) < MIN_DOLLAR_VOLUME,
    )


def _format_report(
    run_id: str,
    regime,
    signals: list,
    candidates_evaluated: int,
    discarded_log: list,
) -> str:
    lines = []
    today = date.today().strftime("%Y-%m-%d")
    lines.append(f"=== SIMPLIFIED ENGINE v3.0 — INSIDER CLUSTER SCREENING — {today} ===")
    lines.append(f"Run ID: {run_id} | Clusters evaluated: {candidates_evaluated} | Signals surfaced: {len(signals)}")
    lines.append("")
    lines.append("STEP-1 SCREENING TOOL. Signals below are candidates for further research")
    lines.append("(fundamentals, news, valuation, sector context) before any trade decision.")
    lines.append("The engine does NOT claim a standalone edge. The screen is the value.")
    lines.append("")
    lines.append(regime_gate_header(regime))
    lines.append("(Regime is informational only. The engine does not gate or size on regime.)")
    lines.append("")
    lines.append("─" * 70)
    lines.append("INSIDER CLUSTER SIGNALS")
    lines.append("─" * 70)

    if not signals:
        lines.append("")
        lines.append("NO QUALIFYING CLUSTERS TODAY. THIS IS A VALID RESULT.")
        lines.append(f"(OpenInsider feed evaluated {candidates_evaluated} cluster candidates; "
                     f"none passed the mcap + opportunistic filters.)")
    else:
        signals.sort(
            key=lambda s: (s.opportunistic_count, s.unique_insiders, s.materiality_pct),
            reverse=True,
        )
        for i, s in enumerate(signals[:MAX_REPORT_IDEAS], start=1):
            quality_flag = (
                "⭐ ALL OPPORTUNISTIC" if s.opportunistic_count == s.unique_insiders
                else f"{s.opportunistic_count}/{s.unique_insiders} opportunistic"
            )
            liq = " ⚠ THIN LIQUIDITY" if s.liquidity_warning else ""
            disagreement = " ⚡ DISAGREEMENT (high SI + insider buying)" if s.disagreement_flag else ""
            si_line = (
                f"Short interest: {s.short_interest_pct:.1f}% of float"
                if s.short_interest_pct is not None
                else "Short interest: not available"
            )
            analyst_line = (
                f"Analyst coverage: {s.analyst_count} analyst(s)"
                if s.analyst_count is not None
                else "Analyst coverage: not available"
            )
            lines.append("")
            lines.append(f"{i}. {s.ticker} — {s.company_name}{disagreement}")
            lines.append(f"   Cluster: {s.unique_insiders} insiders | ${s.total_usd:,.0f} total | {s.materiality_pct:.3f}% of mcap")
            lines.append(f"   Quality: {quality_flag}{liq}")
            if s.routine_insiders:
                lines.append(f"   Routine traders (low signal value): {', '.join(s.routine_insiders)}")
            lines.append(f"   Market cap: ${s.market_cap_m:,.0f}M | ADV: ${s.avg_daily_dollar_volume:,.0f}")
            lines.append(f"   {si_line} | {analyst_line}")
            lines.append(f"   Cluster window: {s.cluster_start} → {s.cluster_end} | Signal date: {s.signal_date}")
            lines.append(f"   Insiders: {', '.join(s.insider_names)}")
            if s.insider_roles:
                lines.append(f"   Roles: {', '.join(s.insider_roles)}")
            lines.append(f"   Entry: next close after {s.signal_date} (current ~${s.entry_price_estimate:.2f})")
            lines.append(f"   Recommended hold: {RECOMMENDED_HOLD_DAYS} days")

    lines.append("")
    lines.append("─" * 70)
    if discarded_log:
        lines.append(f"DISCARDED ({len(discarded_log)}):")
        for entry in discarded_log[:30]:
            lines.append(f"  {entry['ticker']} — {entry['reason']}")
        if len(discarded_log) > 30:
            lines.append(f"  ... and {len(discarded_log) - 30} more")
    else:
        lines.append("DISCARDED: none")
    lines.append("")
    lines.append("─" * 70)
    lines.append("REFERENCE")
    lines.append(f"  Discovery:                  OpenInsider feed (full-market scan)")
    lines.append(f"  Recommended hold:           {RECOMMENDED_HOLD_DAYS} days (Jeng-Metrick-Zeckhauser; Cohen-Malloy-Pomorski)")
    lines.append(f"  Assumed round-trip cost:    {TRANSACTION_COST_PCT}% (retail at $200M–$3B)")
    lines.append(f"  Position size guidance:     max {MAX_RISK_PER_TRADE_PCT}% of equity per signal")
    lines.append(f"  Realistic gross return:     4–8% per 180d trade (median academic estimate)")
    lines.append(f"  Realistic net return:       3–7% per 180d trade after costs")
    lines.append(f"  Opportunistic soft gate:    cluster discarded if 0 opportunistic insiders (CMP 2012)")
    lines.append(f"  ⚡ DISAGREEMENT flag:        short interest {DISAGREEMENT_SI_LOW_PCT:.0f}–{DISAGREEMENT_SI_HIGH_PCT:.0f}% of float")
    lines.append(f"                              Chung-Sul-Wang 2019. Informational only; not a gate.")
    lines.append("")
    lines.append("DO YOUR OWN RESEARCH ON EACH SURFACED TICKER BEFORE TRADING.")
    return "\n".join(lines)


def _save_report(report: str, run_id: str) -> Path:
    logs_dir = Path(__file__).parent / "research_logs"
    logs_dir.mkdir(exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = logs_dir / f"report_{ts}_{run_id}.md"
    path.write_text(report)
    return path


def main(dry_run: bool = False):
    init_db()
    run_id = str(uuid.uuid4())[:8]
    print(f"\n[Pipeline] Starting run {run_id} {'(DRY RUN)' if dry_run else ''}")

    regime = check_regime()
    print(regime_gate_header(regime))

    if dry_run:
        print(f"[Pipeline] DRY RUN — would scrape OpenInsider for last {RECENT_WINDOW_DAYS}d "
              f"and classify against {HISTORY_DAYS}d history.")
        return

    # Phase 1: full-market discovery via OpenInsider
    clusters = scan_openinsider(
        recent_window_days=RECENT_WINDOW_DAYS,
        history_days=HISTORY_DAYS,
    )

    signals: list[InsiderSignal] = []
    discarded_log: list[dict] = []

    # Phase 2: per-cluster enrichment + filtering
    for cluster in clusters:
        ticker = cluster.ticker
        blocked, _ = is_deduped(ticker)
        if blocked:
            continue

        # Opportunistic soft gate (CMP 2012)
        if cluster.opportunistic_count < 1:
            discarded_log.append({
                "ticker": ticker,
                "reason": "all insiders classified routine (no opportunistic signal)",
            })
            continue

        enriched = _enrich_ticker(ticker)
        if not enriched:
            discarded_log.append({"ticker": ticker, "reason": "yfinance enrichment failed"})
            continue

        market_cap_m = enriched.get("market_cap_m", 0)
        if market_cap_m < MARKET_CAP_MIN_M or market_cap_m > MARKET_CAP_MAX_M:
            discarded_log.append({
                "ticker": ticker,
                "reason": f"mcap ${market_cap_m:.0f}M outside ${MARKET_CAP_MIN_M}M-${MARKET_CAP_MAX_M}M",
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

    report = _format_report(run_id, regime, signals, len(clusters), discarded_log)
    path = _save_report(report, run_id)
    print(report)
    print(f"\n[Pipeline] Report saved to {path}")

    log_run_health(run_id, {
        "regime_gate_pass": int(regime.gate_pass),
        "total_candidates": len(clusters),
        "final_report_count": len(signals),
        "run_status": "ok",
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Show plan without scraping")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
