"""
run_pipeline.py — Simplified Engine v2.1 (literature-aligned screening tool)

Mechanical insider-cluster scanner. No LLM. No bull/bear debate. No composite scoring.
No government contracts. No confirming signals. No neglect screen. No sizing multipliers.

This is a STEP-1 SCREENING TOOL, not a complete trading strategy. It surfaces structurally
meaningful insider-cluster events for the operator to then research further (fundamentals,
news, sector context, valuation) before deciding whether to take a position. The engine
does not claim a standalone edge; it provides a literature-validated starting universe
for discretionary follow-up.

Calibrated against academic literature (see CLAUDE.md):
  - Cluster definition (3+ insiders, 30-day window, $100K each): Lakonishok-Lee 2001;
    Alldredge-Blank 2019; Kang et al. 2018.
  - Market cap band $200M–$3B: smaller-is-better consensus across studies.
  - 180-day hold horizon: Jeng-Metrick-Zeckhauser 2003; Cohen-Malloy-Pomorski 2012;
    Lakonishok-Lee 2001 (signal accrues over 3–12 months, peaks ~6 months).
  - Opportunistic vs routine soft gate: Cohen-Malloy-Pomorski 2012 (≥1 opportunistic
    insider required; pure-routine clusters carry near-zero predictive content).
  - 10b5-1 exclusion: well-established; routine/scheduled trades carry no signal.

v2.1 changes from v2:
  - Hold horizon 90 → 180 days (literature peaks ~6mo)
  - Cluster window 14 → 30 days (academic studies use 1-3 month windows)
  - EDGAR lookback 21 → 45 days (accommodates wider cluster window)
  - Removed 0.02% materiality threshold (was redundant with $100K × 3 minimum)
  - Soft-gate clusters with 0 opportunistic insiders (CMP noise floor)

Realistic expectation: 4–8% gross / 3–7% net per 180-day trade (median academic
estimate for modern post-SOX US small/mid-cap clusters). Comparable to passive
indexing on a risk-adjusted basis. The engine's value is the SCREEN, not the
standalone edge.

Usage:
  python run_pipeline.py
  python run_pipeline.py --dry-run
  python run_pipeline.py --max-tickers 100
"""

import argparse
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yfinance as yf

from orchestrator.state_manager import init_db, log_candidate, log_run_health, is_deduped
from orchestrator.regime_gate import check_regime, regime_gate_header
from orchestrator.universe_builder import build_neglected_universe
from orchestrator.insider_scanner import scan_insider_buying, InsiderCluster


# ── Validated thresholds (literature-aligned, v2.1) ───────────────────────
MARKET_CAP_MIN_M = 200             # Lakonishok-Lee, Jeng et al.: smaller-cap stronger
MARKET_CAP_MAX_M = 3000            # GPT/literature: $500M–$5B too wide; tighten
MIN_DOLLAR_VOLUME = 500_000        # liquidity-warning threshold
RECOMMENDED_HOLD_DAYS = 180        # v2.1: 6-month horizon (Jeng et al., Lakonishok-Lee,
                                   # Cohen-Malloy-Pomorski). 90d was on the short end of
                                   # academic guidance; insider-buying alpha builds over
                                   # 3-12 months and peaks around 6 months.
TRANSACTION_COST_PCT = 1.0         # realistic round-trip cost assumption for retail $5K–$25K
MAX_RISK_PER_TRADE_PCT = 2.0       # of portfolio equity (flat, no cluster-size tier)
EDGAR_LOOKBACK_DAYS = 45           # window for current-cluster detection (3-year history
                                   # is fetched separately by scanner for routine check)

# Short-interest "disagreement" band (Chung-Sul-Wang 2019, informational only)
# Insider buying into heavily-shorted-but-not-extreme stocks has shown stronger
# academic returns than insider buying alone. Upper bound filters out fraud/distress
# names where insiders may buy defensively. NOT a gate — surfaced as a tag for the
# operator's discretionary research.
DISAGREEMENT_SI_LOW_PCT = 10.0
DISAGREEMENT_SI_HIGH_PCT = 40.0

# Scan limits
MAX_TICKERS_TO_SCAN = 500          # universe is already filtered to $200M-$3B
MAX_REPORT_IDEAS = 15              # screening-tool: surface more candidates for review


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
    short_interest_pct: float | None = None    # % of float; None when data missing
    disagreement_flag: bool = False             # True when SI within DISAGREEMENT band
    analyst_count: int | None = None            # # of sell-side analysts covering (yfinance)
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

        # yfinance returns shortPercentOfFloat as a decimal (e.g. 0.15 = 15%).
        # Some tickers also expose shortPercentOfSharesOutstanding; we prefer % of float.
        si_raw = info.get("shortPercentOfFloat")
        if si_raw is None or si_raw == 0:
            si_raw = info.get("sharesPercentSharesOut")
        short_interest_pct = (
            round(float(si_raw) * 100, 2) if si_raw is not None and si_raw > 0 else None
        )

        # Analyst coverage count — proxy for institutional attention. Lower = more
        # under-researched = literature suggests stronger insider-trade alpha.
        # Informational only; not a gate.
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
    tickers_scanned: int,
    discarded_log: list,
) -> str:
    lines = []
    today = date.today().strftime("%Y-%m-%d")
    lines.append(f"=== SIMPLIFIED ENGINE v2.1 — INSIDER CLUSTER SCREENING — {today} ===")
    lines.append(f"Run ID: {run_id} | Tickers Scanned: {tickers_scanned} | Signals Surfaced: {len(signals)}")
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
        lines.append("(Validated cohort historically produces ~1 signal/month.)")
    else:
        # Rank: more opportunistic insiders > more total insiders > higher materiality
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
            if s.short_interest_pct is None:
                si_line = "Short interest: not available"
            else:
                si_line = f"Short interest: {s.short_interest_pct:.1f}% of float"
            if s.analyst_count is None:
                analyst_line = "Analyst coverage: not available"
            else:
                analyst_line = f"Analyst coverage: {s.analyst_count} analyst(s)"
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
        for entry in discarded_log[:20]:
            lines.append(f"  {entry['ticker']} — {entry['reason']}")
        if len(discarded_log) > 20:
            lines.append(f"  ... and {len(discarded_log) - 20} more")
    else:
        lines.append("DISCARDED: none")
    lines.append("")
    lines.append("─" * 70)
    lines.append("REFERENCE")
    lines.append(f"  Recommended hold:           {RECOMMENDED_HOLD_DAYS} days (Jeng-Metrick-Zeckhauser; Cohen-Malloy-Pomorski)")
    lines.append(f"  Assumed round-trip cost:    {TRANSACTION_COST_PCT}% (retail at $200M–$3B)")
    lines.append(f"  Position size guidance:     max {MAX_RISK_PER_TRADE_PCT}% of equity per signal")
    lines.append(f"  Realistic gross return:     4–8% per 180d trade (median academic estimate)")
    lines.append(f"  Realistic net return:       3–7% per 180d trade after costs")
    lines.append(f"  Opportunistic flag (CMP):   informational only; do not auto-trade routine clusters")
    lines.append(f"  ⚡ DISAGREEMENT flag:        short interest {DISAGREEMENT_SI_LOW_PCT:.0f}–{DISAGREEMENT_SI_HIGH_PCT:.0f}% of float (insiders buying into elevated shorts)")
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


def main(dry_run: bool = False, max_tickers: int = MAX_TICKERS_TO_SCAN):
    init_db()
    run_id = str(uuid.uuid4())[:8]
    print(f"\n[Pipeline] Starting run {run_id} {'(DRY RUN)' if dry_run else ''}")

    # Regime — informational only (no gate, no multiplier)
    regime = check_regime()
    print(regime_gate_header(regime))

    # Universe
    watchlist = build_neglected_universe()
    if not watchlist:
        print("[Pipeline] Watchlist empty.")
        log_run_health(run_id, {"total_candidates": 0, "run_status": "no_universe"})
        return

    eligible = [w for w in watchlist if MARKET_CAP_MIN_M <= w.get("market_cap_m", 0) <= MARKET_CAP_MAX_M]
    eligible = eligible[:max_tickers]
    print(f"[Pipeline] {len(eligible)} tickers in ${MARKET_CAP_MIN_M}M-${MARKET_CAP_MAX_M}M band to scan.")

    if dry_run:
        print(f"[Pipeline] DRY RUN — would scan {len(eligible)} tickers via SEC EDGAR Form 4.")
        return

    signals: list[InsiderSignal] = []
    discarded_log: list[dict] = []

    for entry in eligible:
        ticker = entry["ticker"]
        blocked, _ = is_deduped(ticker)
        if blocked:
            continue

        try:
            cluster = scan_insider_buying(ticker, days_back=EDGAR_LOOKBACK_DAYS)
        except Exception as e:
            print(f"[Pipeline] {ticker} scan error: {e}")
            continue

        if not cluster.detected:
            continue

        # Soft gate: a cluster of all-routine insiders carries near-zero predictive
        # information per Cohen-Malloy-Pomorski 2012. Filter those out automatically
        # rather than burden the operator with noise candidates.
        if cluster.opportunistic_count < 1:
            discarded_log.append({
                "ticker": ticker,
                "reason": "all insiders classified routine (no opportunistic signal)",
            })
            continue

        enriched = _enrich_ticker(ticker)
        if not enriched:
            discarded_log.append({"ticker": ticker, "reason": "enrichment_failed"})
            continue

        # Fresh market-cap re-check (the watchlist cache is up to 7 days stale;
        # this catches names that drifted outside the $200M-$3B band since cache).
        market_cap_m = enriched.get("market_cap_m", 0)
        if market_cap_m < MARKET_CAP_MIN_M or market_cap_m > MARKET_CAP_MAX_M:
            discarded_log.append({"ticker": ticker, "reason": f"mcap ${market_cap_m:.0f}M outside ${MARKET_CAP_MIN_M}M-${MARKET_CAP_MAX_M}M"})
            continue

        # NOTE: prior v2 had a 0.02%-of-market-cap materiality filter here. Removed in
        # v2.1: at our 3-insider × $100K = $300K minimum, the 0.02% threshold only binds
        # above ~$1.5B mcap and was effectively cosmetic across most of the universe.
        # The $100K × 3 absolute minimum already enforces meaningful commitment.

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

    report = _format_report(run_id, regime, signals, len(eligible), discarded_log)
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
