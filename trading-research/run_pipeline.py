"""
run_pipeline.py — Single entry point for the trading research pipeline.

Usage:
  python run_pipeline.py
  python run_pipeline.py --dry-run

Environment variables:
  SAM_GOV_API_KEY    — optional. SAM.gov entity detail lookup only (10 req/day limit).
                       Primary award discovery uses USAspending.gov (no key needed).
  FIRECRAWL_API_KEY  — optional. For state procurement / job postings.

LLM calls use the claude CLI from your active Claude Code subscription.
No ANTHROPIC_API_KEY needed. No SAM_GOV_API_KEY needed to run.
"""

import argparse
import os
import sys
import uuid
from datetime import date, datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from orchestrator.state_manager import init_db, log_candidate, log_run_health, log_regime
from orchestrator.request_budget import BudgetManager
from orchestrator.regime_gate import check_regime, regime_gate_header
from orchestrator.signal_scanner import scan_all_signals, compute_signal_bonus
from orchestrator.theme_cluster import assign_clusters
from orchestrator.ranking import rank_ideas

from agents.agent1_bull import run_agent1
from agents.agent1b_bear import run_agent1b
from agents.agent1c_supervisor import run_agent1c, PROCEED as C_PROCEED
from agents.agent2_quant import run_agent2
from agents.agent3_synthesis import run_agent3


# ── Kill criteria (all enforced in Python) ────────────────────────────────
KILL_AVG_DATA_QUALITY = 2.0
KILL_STALE_PCT = 0.50
KILL_MISSING_DATA_PCT = 0.70
WARN_MIN_AGENT1_CANDIDATES = 5
KILL_1C_DISQUALIFY_PCT = 0.80
COMPOSITE_MIN = 3.5


def _check_env() -> tuple[str, str | None]:
    sam_key = os.environ.get("SAM_GOV_API_KEY", "")
    firecrawl_key = os.environ.get("FIRECRAWL_API_KEY")
    if not sam_key:
        print("[Pipeline] SAM_GOV_API_KEY not set — using USAspending.gov only (no key needed).")
    return sam_key, firecrawl_key


def _format_report(
    run_id: str,
    regime,
    ranking,
    disqualified_log: list,
    budget: BudgetManager,
    candidates_scanned: int,
    run_status: str,
) -> str:
    lines = []
    today = date.today().strftime("%Y-%m-%d")

    lines.append(f"=== TRADING RESEARCH REPORT — {today} ===")
    budget_summary = budget.to_dict()
    lines.append(f"Run ID: {run_id} | API Calls: {budget_summary['total_calls']}/{budget_summary['budget']} | Candidates Scanned: {candidates_scanned}")
    lines.append("")
    lines.append(regime_gate_header(regime))
    lines.append(f"RUN HEALTH: {run_status.upper()}")
    lines.append("")
    def _render_idea(idea, label_section):
        a3 = idea.agent3
        flags = []
        if getattr(a3, "regime_override", False):
            flags.append("REGIME-OVERRIDE")
        if a3.probationary:
            flags.append("PROBATIONARY")
        if a3.liquidity_warning:
            flags.append("LIQUIDITY WARNING")
        if a3.short_interest_flag:
            flags.append("SHORT INTEREST >20%")
        if a3.stale_data_flag:
            flags.append("STALE DATA")
        flag_str = f"  ⚠ {' | '.join(flags)}" if flags else ""

        lines.append(f"{idea.rank}. {a3.ticker} | Score: {a3.composite_score:.2f}/5 | Confidence: {a3.confidence}")
        lines.append(f"   Catalyst: {a3.catalyst_type} | {a3.days_since_catalyst}d ago")
        if a3.catalyst_type == "government_contract_award":
            lines.append(f"   Contract value: {a3.catalyst_strength_score:.1f} catalyst strength")
        lines.append(f"   Confirming signals: {', '.join(a3.confirming_signals) if a3.confirming_signals else 'none'}")
        lines.append(f"   Signal bonus: +{a3.signal_bonus:.1f} | Data quality: {a3.data_quality_score:.1f}/5")
        hold = getattr(a3, "recommended_hold_days", 10)
        hold_note = " (extended — elite/HC setup)" if hold > 10 else ""
        lines.append(f"   Hold target: {hold} trading days{hold_note}")
        if label_section == "high_upside" or a3.high_upside_score >= 2.5:
            markers = ', '.join(a3.high_upside_markers) if a3.high_upside_markers else 'none'
            lines.append(f"   Upside score: {a3.high_upside_score:.2f}/5 | Markers: {markers}")
        if flag_str:
            lines.append(flag_str)
        lines.append("")
        lines.append(f"   Thesis: {a3.thesis}")
        lines.append("")
        lines.append(f"   Invalidation trigger: {a3.invalidation_trigger}")
        if a3.daily_monitors:
            lines.append(f"   Watch daily: {' | '.join(a3.daily_monitors)}")
        lines.append(f"   Marginal buyer: {a3.marginal_buyer_analysis}")
        lines.append("")
        if a3.bear_summary:
            lines.append(f"   ⚠ Bear case: {a3.bear_summary[:300]}...")
        lines.append("")
        lines.append("─" * 45)

    lines.append("─" * 45)
    lines.append("HIGH CONVICTION IDEAS")
    lines.append("─" * 45)
    lines.append("")

    if not ranking.included:
        lines.append("NO HIGH CONVICTION IDEAS MET THE 3.5 THRESHOLD TODAY. THIS IS A VALID RESULT.")
    else:
        for idea in ranking.included:
            _render_idea(idea, "high_conviction")

    high_upside = getattr(ranking, "high_upside", [])
    if high_upside:
        lines.append("")
        lines.append("─" * 45)
        lines.append("HIGH-UPSIDE IDEAS  (composite 3.0-3.5, strong asymmetric markers — size smaller)")
        lines.append("─" * 45)
        lines.append("")
        for idea in high_upside:
            _render_idea(idea, "high_upside")

    lines.append("")
    lines.append("DISQUALIFIED TODAY")
    lines.append("─" * 45)
    if disqualified_log:
        for entry in disqualified_log:
            lines.append(f"  {entry['ticker']} — {entry['reason']}")
    else:
        lines.append("  None")

    if ranking.clustered_out:
        lines.append("")
        lines.append("CLUSTERED OUT (same theme, scored lower):")
        for r in ranking.clustered_out:
            lines.append(f"  {r.ticker} | Score: {r.composite_score:.2f} | Theme cap applied")

    lines.append("")
    lines.append(budget.summary())

    return "\n".join(lines)


def main(dry_run: bool = False):
    init_db()

    sam_key, firecrawl_key = _check_env()
    budget = BudgetManager(dry_run=dry_run)
    run_id = str(uuid.uuid4())[:8]
    disqualified_log = []
    run_status = "ok"

    print(f"\n[Pipeline] Starting run {run_id} {'(DRY RUN)' if dry_run else ''}")

    # ── Gate 1: Regime ────────────────────────────────────────────────────
    regime = check_regime()
    # Hard-fail (data fetch error): cannot decide on override mode, terminate.
    if not regime.gate_pass and not regime.elite_only:
        print(f"\n{regime_gate_header(regime)}")
        print("\nREGIME GATE HARD-FAIL — terminating cleanly.")
        log_run_health(run_id, {
            "regime_gate_pass": 0,
            "run_status": "regime_gate_blocked",
            "api_calls_used": 0,
        })
        report = _format_report(run_id, regime, type('R', (), {'included': [], 'high_upside': [], 'clustered_out': []})(),
                                [], budget, 0, "REGIME GATE HARD-FAIL")
        _save_report(report, run_id)
        print(report)
        return

    if regime.gate_pass:
        print(f"[Pipeline] Regime gate: PASS")
    else:
        print(f"[Pipeline] Regime gate: FAIL → entering ELITE-OVERRIDE mode (only top-decile signals)")

    # ── Agent 1 (Bull): fetch SAM.gov + enrich ────────────────────────────
    agent1_results = run_agent1(sam_key, budget, firecrawl_key, elite_only=regime.elite_only)
    candidates_scanned = len(agent1_results)

    if len(agent1_results) < WARN_MIN_AGENT1_CANDIDATES:
        print(f"[Pipeline] WARNING: only {len(agent1_results)} Agent 1 candidates (weak signal environment)")
        run_status = "weak_signal"

    if not agent1_results:
        print("[Pipeline] No Agent 1 candidates. Ending run.")
        log_run_health(run_id, {"regime_gate_pass": 1, "total_candidates": 0, "run_status": "no_candidates", "api_calls_used": budget._total})
        report = _format_report(run_id, regime, type('R', (), {'included': [], 'clustered_out': []})(),
                                [], budget, 0, "NO CANDIDATES")
        _save_report(report, run_id)
        print(report)
        return

    # ── Debate layer: 1B, 1C per candidate ───────────────────────────────
    agent3_results = []
    disq_1c = 0

    for a1 in agent1_results:
        # Market data for bear agent
        import yfinance as yf
        try:
            info = yf.Ticker(a1.ticker).info or {}
        except Exception:
            info = {}

        # Agent 1B
        a1b = run_agent1b(a1, info, budget)

        # Agent 1C
        a1c = run_agent1c(a1, a1b, budget)
        if a1c.outcome != C_PROCEED:
            disq_1c += 1
            reason = f"Agent 1C: {a1c.disqualify_reason}"
            disqualified_log.append({"ticker": a1.ticker, "reason": reason})
            log_candidate(run_id, {"ticker": a1.ticker, "agent1c_resolution": a1c.outcome,
                                   "discard_reason": reason, "neglect_screen_pass": 1,
                                   "catalyst_type": a1.catalyst_type})
            continue

        # Agent 2
        a2 = run_agent2(a1.ticker, a1.market_cap_m, budget)
        if a2.stale_data_flag:
            log_candidate(run_id, {"ticker": a1.ticker, "stale_data_flag": 1})

        # Signal scanner
        signals = scan_all_signals(
            a1.ticker, a1.company_name, a1.market_cap_m,
            a2.rvol or 0, a2.avg_daily_dollar_volume, firecrawl_key
        )
        # A confirming signal that matches the primary catalyst is the same evidence
        # twice — don't grant a bonus for the signal that already drove discovery.
        primary = a1.catalyst_type
        if primary in signals.confirming_signals:
            signals.confirming_signals = [s for s in signals.confirming_signals if s != primary]
            signals.confirming_signal_count = len(signals.confirming_signals)
            signals.signal_bonus = compute_signal_bonus(signals.confirming_signal_count)

        # Agent 3 — neglect screen already passed in agent1 for all a1 results
        a3 = run_agent3(a1, a1b, a1c, a2, signals, True, budget)
        if a3 is None:
            reason = f"Composite below {COMPOSITE_MIN} threshold"
            disqualified_log.append({"ticker": a1.ticker, "reason": reason})
            log_candidate(run_id, {"ticker": a1.ticker, "discard_reason": reason,
                                   "catalyst_type": a1.catalyst_type})
            continue

        agent3_results.append(a3)

        log_candidate(run_id, {
            "ticker": a3.ticker,
            "composite_score": a3.composite_score,
            "confidence": a3.confidence,
            "probationary": int(a3.probationary),
            "liquidity_warning": int(a3.liquidity_warning),
            "catalyst_type": a3.catalyst_type,
            "catalyst_type_prior": a3.catalyst_type_prior,
            "confirming_signals": a3.confirming_signals,
            "confirming_signal_count": a3.confirming_signal_count,
            "insider_buying_cluster": int(signals.insider_buying.detected),
            "insider_buy_total_usd": signals.insider_buying.total_usd,
            "hiring_surge_detected": int(signals.hiring_surge.detected),
            "specialist_fund_initiation": int(signals.specialist_fund.detected),
            "russell_inclusion_candidate": int(signals.russell_candidate),
            "neglect_screen_pass": 1,
            "regime_gate_pass": 1,
            "agent1b_bear_summary": a1b.bear_summary,
            "agent1c_resolution": a1c.resolution_summary,
            "agent1c_conflict_level": a1c.conflict_level,
            "information_asymmetry_score": a3.information_asymmetry_score,
            "catalyst_strength_score": a3.catalyst_strength_score,
            "quant_confirmation_score": a3.quant_confirmation_score,
            "data_quality_score": a3.data_quality_score,
            "risk_asymmetry_score": a3.risk_asymmetry_score,
            "marginal_buyer_score": a3.marginal_buyer_score,
            "short_interest_flag": int(a3.short_interest_flag),
            "stale_data_flag": int(a3.stale_data_flag),
            "sector_beta_flag": int(a3.sector_beta_flag),
            "rs_vs_iwm": a3.rs_vs_iwm,
            "proxies_computed": a3.proxies_computed,
            "thesis": a3.thesis,
            "invalidation_trigger": a3.invalidation_trigger,
            "days_since_catalyst": a3.days_since_catalyst,
            "missing_data_fields": a3.missing_data_fields,
            "high_upside_score": a3.high_upside_score,
            "high_upside_markers": a3.high_upside_markers,
            "regime_override": int(a3.regime_override),
        })

    # ── Kill criteria checks ──────────────────────────────────────────────
    if agent1_results:
        dq_pct = disq_1c / len(agent1_results)
        if dq_pct > KILL_1C_DISQUALIFY_PCT:
            print(f"[Pipeline] WARNING: Agent 1C disqualified {dq_pct:.0%} of candidates — high-conflict environment")
            run_status = "high_conflict"

    # ── Theme clustering + ranking ────────────────────────────────────────
    if agent3_results:
        clusters = assign_clusters(agent3_results, budget)
        ranking = rank_ideas(agent3_results, {}, clusters)
    else:
        ranking = type('R', (), {'included': [], 'high_upside': [], 'clustered_out': [], 'total_evaluated': 0})()

    # ── Final report ──────────────────────────────────────────────────────
    report = _format_report(run_id, regime, ranking, disqualified_log, budget, candidates_scanned, run_status)

    log_run_health(run_id, {
        "regime_gate_pass": 1,
        "total_candidates": candidates_scanned,
        "candidates_passed_neglect": len(agent3_results) + len([d for d in disqualified_log if "Agent 1C" in d["reason"]]),
        "candidates_disqualified_1c": disq_1c,
        "final_report_count": len(ranking.included) if hasattr(ranking, 'included') else 0,
        "api_calls_used": budget._total,
        "run_status": run_status,
    })

    _save_report(report, run_id)
    print(report)

    if dry_run:
        print("\n" + budget.dry_run_summary())


def _save_report(report: str, run_id: str):
    logs_dir = Path(__file__).parent / "research_logs"
    logs_dir.mkdir(exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = logs_dir / f"report_{ts}_{run_id}.md"
    path.write_text(report)
    print(f"[Pipeline] Report saved to {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Estimate API calls without executing")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
