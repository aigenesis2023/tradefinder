"""
Agent 3 — Synthesis and Confluence

Scoring is 100% deterministic Python. LLM is used only for narrative
(thesis, invalidation_trigger, daily_monitors, marginal_buyer_analysis).

Composite formula:
  composite = (
    (catalyst_strength * catalyst_type_prior * 0.30) +
    (quant_confirmation * 0.30) +
    (risk_asymmetry * 0.25) +
    (information_asymmetry * 0.15)
  ) * (data_quality / 5)
  + confirming_signal_bonus (capped at 0.9)
"""

import json
import re
from dataclasses import dataclass, field
from typing import Optional
from orchestrator.request_budget import BudgetManager
from orchestrator.llm_client import call_claude
from agents.agent1_bull import Agent1Result
from agents.agent1b_bear import Agent1BResult
from agents.agent1c_supervisor import Agent1CResult
from agents.agent2_quant import Agent2Result
from orchestrator.signal_scanner import SignalScanResult

COMPOSITE_MIN = 3.5
# A separate, lower floor for "high-upside" candidates that don't quite clear
# COMPOSITE_MIN but have strong asymmetric markers (high short interest,
# heavy insider conviction, step-change contracts). Surfaced in a separate
# section of the report so the user can choose to take the variance.
HIGH_UPSIDE_COMPOSITE_FLOOR = 3.0
HIGH_UPSIDE_SCORE_MIN = 2.5

SIGNAL_BONUS_CAP = 0.9
CONTRACT_SPECULATIVE_THRESHOLD_PCT = 10.0
CONTRACT_STALE_DAYS = 30  # USAspending lag concern: contracts older than this auto-cap at Speculative
# Decay schedule depends on catalyst type. Insider clusters' empirical alpha is
# measured at 30 days from cluster_end, so decay starts later and runs slower.
SCORE_DECAY_DAYS_CONTRACT = 7
SCORE_DECAY_RATE_CONTRACT = 0.05
SCORE_DECAY_DAYS_INSIDER = 21
SCORE_DECAY_RATE_INSIDER = 0.025


@dataclass
class Agent3Result:
    ticker: str
    thesis: str
    invalidation_trigger: str
    daily_monitors: list
    confidence: str
    composite_score: float
    catalyst_strength_score: float
    quant_confirmation_score: float
    risk_asymmetry_score: float
    information_asymmetry_score: float
    data_quality_score: float
    marginal_buyer_score: float
    marginal_buyer_analysis: str
    bear_summary: str
    catalyst_type: str
    catalyst_type_prior: float
    confirming_signals: list
    confirming_signal_count: int
    signal_bonus: float
    probationary: bool
    liquidity_warning: bool
    short_interest_flag: bool
    stale_data_flag: bool
    sector_beta_flag: bool
    rs_vs_iwm: Optional[float]
    proxies_computed: int
    missing_data_fields: list
    days_since_catalyst: int
    high_upside_score: float = 0.0
    high_upside_markers: list = field(default_factory=list)
    regime_override: bool = False
    recommended_hold_days: int = 10
    discard_reason: Optional[str] = None


def _compute_data_quality(agent1: Agent1Result, agent2: Agent2Result) -> float:
    score = 5.0
    all_missing = set(agent1.missing_data + agent2.missing_data)
    score -= len(all_missing) * 0.3
    if agent2.stale_data_flag:
        score -= 1.0
    return max(0.5, round(score, 2))


def _apply_score_decay(catalyst_strength: float, days_since: int, catalyst_type: str) -> float:
    if catalyst_type == "insider_buying_cluster":
        decay_start, decay_rate = SCORE_DECAY_DAYS_INSIDER, SCORE_DECAY_RATE_INSIDER
    else:
        decay_start, decay_rate = SCORE_DECAY_DAYS_CONTRACT, SCORE_DECAY_RATE_CONTRACT
    if days_since <= decay_start:
        return catalyst_strength
    excess = days_since - decay_start
    return max(0.0, round(catalyst_strength * (1 - decay_rate * excess), 3))


def _deterministic_catalyst_strength(agent1: Agent1Result) -> float:
    """Score based on empirically-validated cluster size and revenue impact, not LLM opinion."""
    if agent1.catalyst_type == "insider_buying_cluster":
        n = agent1.unique_insiders
        if n >= 6:   base = 4.5
        elif n >= 5: base = 4.2
        elif n >= 4: base = 3.8
        else:        base = 3.4  # exactly 3 (scanner enforces 3+ minimum)
        if agent1.market_cap_m > 0 and agent1.insider_total_usd > 0:
            pct = (agent1.insider_total_usd / (agent1.market_cap_m * 1e6)) * 100
            if pct >= 0.2: base += 0.3
            elif pct >= 0.1: base += 0.15
        return min(5.0, round(base, 2))
    else:
        pct = agent1.contract_award_value_pct_revenue
        if pct >= 50:   return 4.5
        elif pct >= 25: return 4.0
        elif pct >= 15: return 3.5
        elif pct >= 10: return 3.0
        else:           return 2.0


def _deterministic_risk_asymmetry(agent1: Agent1Result, agent2: Agent2Result) -> float:
    """Risk/reward proxy from price action and structure, not LLM opinion."""
    score = 2.5
    if agent2.rs_vs_iwm is not None:
        score += 0.4 if agent2.rs_vs_iwm > 0 else -0.4
    if agent2.quant_confirmation_score >= 3.5:
        score += 0.3
    elif agent2.quant_confirmation_score < 2.0:
        score -= 0.3
    if agent2.short_interest_flag:
        score += 0.4  # squeeze optionality — high short interest is the classic asymmetric setup
    if agent1.days_since_catalyst <= 5:
        score += 0.3  # fresh = better entry, less alpha decay
    return max(0.5, min(5.0, round(score, 2)))


def _compute_high_upside_score(agent1: Agent1Result, agent2: Agent2Result) -> tuple[float, list]:
    """
    Score 0-5 for asymmetric upside potential. Markers list explains the score.

    This is a tilt toward variance, not toward expected value. Setups scoring
    high here can have a lower win rate than the headline composite implies,
    but their winners are larger — classic short-squeeze / step-change / deep-
    conviction setups.
    """
    score = 0.0
    markers: list[str] = []

    # Short interest >20% — squeeze fuel
    if agent2.short_interest_flag:
        si = (agent2.short_interest_pct or 0) * 100
        score += 1.5
        markers.append(f"short_interest {si:.0f}%")

    if agent1.catalyst_type == "insider_buying_cluster":
        # Insider conviction depth (size relative to market cap)
        if agent1.market_cap_m > 0 and agent1.insider_total_usd > 0:
            pct = (agent1.insider_total_usd / (agent1.market_cap_m * 1e6)) * 100
            if pct >= 0.20:
                score += 1.0
                markers.append(f"insider materiality {pct:.2f}% of mcap")
            elif pct >= 0.10:
                score += 0.5
                markers.append(f"insider materiality {pct:.2f}% of mcap")
        # Wide consensus inside the C-suite
        if agent1.unique_insiders >= 5:
            score += 1.0
            markers.append(f"{agent1.unique_insiders} insiders")

    if agent1.catalyst_type == "government_contract_award":
        if agent1.contract_award_value_pct_revenue >= 50:
            score += 2.0
            markers.append(f"contract {agent1.contract_award_value_pct_revenue:.0f}% of revenue (step-change)")
        elif agent1.contract_award_value_pct_revenue >= 25:
            score += 1.0
            markers.append(f"contract {agent1.contract_award_value_pct_revenue:.0f}% of revenue")

    # Smaller-within-band: $500M-$1.5B has more upside than $3-5B for the same signal
    if 500 <= agent1.market_cap_m <= 1500:
        score += 0.5
        markers.append(f"smaller mid-cap (${agent1.market_cap_m:.0f}M)")

    return round(min(5.0, score), 2), markers


def _deterministic_marginal_buyer_score(agent2: Agent2Result) -> float:
    if agent2.short_interest_flag:
        return 4.0
    if agent2.rs_vs_iwm is not None and agent2.rs_vs_iwm > 0 and agent2.quant_confirmation_score >= 3.5:
        return 3.5
    return 2.5


def _compute_recommended_hold(agent1: Agent1Result, composite: float, high_upside_score: float) -> int:
    """
    10 trading days is the default (best per-day alpha).
    Extend to 20 for elite clusters or high-conviction + strong upside markers.
    Data: 60 trading-day window shows +7.82% IWM-adj alpha (ex-COVID, n=78), 73% win rate —
    the signal keeps running well beyond the initial 10-day pop for strong setups.
    """
    if agent1.unique_insiders >= 5:
        return 20
    if composite >= COMPOSITE_MIN and high_upside_score >= 3.0:
        return 20
    return 10


def _compute_composite(catalyst_strength, catalyst_prior, quant, risk, info_asymmetry, data_quality, signal_bonus) -> float:
    raw = (
        (catalyst_strength * catalyst_prior * 0.30) +
        (quant * 0.30) +
        (risk * 0.25) +
        (info_asymmetry * 0.15)
    ) * (data_quality / 5)
    return round(raw + min(signal_bonus, SIGNAL_BONUS_CAP), 3)


def _determine_confidence(composite, probationary, asymmetry_score, liquidity_warning, neglect_pass, stale_contract) -> str:
    if probationary or asymmetry_score < 2.0:
        return "Speculative"
    if stale_contract:
        return "Speculative"
    if liquidity_warning:
        return "Medium" if composite >= COMPOSITE_MIN else "Speculative"
    if not neglect_pass:
        return "Medium" if composite >= COMPOSITE_MIN else "Speculative"
    if composite >= COMPOSITE_MIN:
        return "High"
    elif composite >= 3.0:
        return "Medium"
    return "Speculative"


def _llm_narrative(agent1, agent1b, agent1c, agent2, signals, budget) -> dict:
    """Narrow LLM call — narrative only. Scores are computed in Python."""
    prompt = f"""You are Agent 3 (Synthesis). Write the investment thesis for a human trader.
Scoring has already been computed. Your job is narrative and context only.

STOCK: {agent1.ticker} ({agent1.company_name})
CATALYST: {agent1.catalyst_type} | Date: {agent1.catalyst_date}
CATALYST DETAIL: {agent1.catalyst_description}
DAYS SINCE CATALYST: {agent1.days_since_catalyst}

BULL NARRATIVE: {agent1.bull_narrative}
BEAR SUMMARY: {agent1b.bear_summary}
SUPERVISOR RESOLUTION: {agent1c.resolution_summary}
QUANT NOTES: {agent2.quant_notes}
TREND CONTEXT: {agent2.trend_context}
CONFIRMING SIGNALS: {signals.confirming_signals}

Return ONLY valid JSON:
{{
  "thesis": "<one paragraph — the opportunity, why now, why others missed it>",
  "invalidation_trigger": "<one sentence — what specific event kills this thesis?>",
  "daily_monitors": ["<watch 1>", "<watch 2>", "<watch 3>"],
  "marginal_buyer_analysis": "<one sentence on who the expected buyer is>"
}}"""

    default = {
        "thesis": "", "invalidation_trigger": "", "daily_monitors": [],
        "marginal_buyer_analysis": "",
    }

    if budget.dry_run:
        budget.estimate("llm")
        return default
    if not budget.can_call("llm"):
        return default

    budget._register("llm")
    raw = call_claude(prompt)
    if not raw:
        return default
    try:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        return {**default, **json.loads(match.group())} if match else default
    except Exception:
        return default


def run_agent3(
    agent1: Agent1Result,
    agent1b: Agent1BResult,
    agent1c: Agent1CResult,
    agent2: Agent2Result,
    signals: SignalScanResult,
    neglect_pass: bool,
    budget: BudgetManager,
) -> Optional["Agent3Result"]:

    if agent1c.outcome != "PROCEED":
        return None

    data_quality = _compute_data_quality(agent1, agent2)
    days_since = agent1.days_since_catalyst

    catalyst_strength = _deterministic_catalyst_strength(agent1)
    catalyst_strength = _apply_score_decay(catalyst_strength, days_since, agent1.catalyst_type)
    if (
        agent1.catalyst_type == "government_contract_award"
        and agent1.contract_award_value_pct_revenue < CONTRACT_SPECULATIVE_THRESHOLD_PCT
    ):
        catalyst_strength = min(catalyst_strength, 2.5)

    quant = agent2.quant_confirmation_score
    risk = _deterministic_risk_asymmetry(agent1, agent2)
    info_asym = agent1.information_asymmetry_score
    prior = agent1.catalyst_type_prior
    signal_bonus = signals.signal_bonus

    composite = _compute_composite(catalyst_strength, prior, quant, risk, info_asym, data_quality, signal_bonus)
    stale_contract = (
        agent1.catalyst_type == "government_contract_award"
        and days_since > CONTRACT_STALE_DAYS
    )
    confidence = _determine_confidence(composite, agent1.probationary, info_asym, agent1.liquidity_warning, neglect_pass, stale_contract)

    high_upside_score, high_upside_markers = _compute_high_upside_score(agent1, agent2)
    qualifies_high_upside = (
        composite >= HIGH_UPSIDE_COMPOSITE_FLOOR
        and high_upside_score >= HIGH_UPSIDE_SCORE_MIN
    )
    recommended_hold = _compute_recommended_hold(agent1, composite, high_upside_score)

    # Regime-override candidates carry elevated macro risk by construction —
    # cap confidence to keep position sizing honest. The surfacing decision
    # itself is intentional.
    if agent1.regime_override and confidence == "High":
        confidence = "Medium"

    # Hard floor: anything below HIGH_UPSIDE_COMPOSITE_FLOOR is too weak to surface in any pool.
    if composite < HIGH_UPSIDE_COMPOSITE_FLOOR:
        return None
    # Sub-threshold candidates only get through if they qualify for the high-upside pool.
    if composite < COMPOSITE_MIN and not qualifies_high_upside:
        return None

    llm = _llm_narrative(agent1, agent1b, agent1c, agent2, signals, budget)

    return Agent3Result(
        ticker=agent1.ticker,
        thesis=llm.get("thesis", ""),
        invalidation_trigger=llm.get("invalidation_trigger", ""),
        daily_monitors=llm.get("daily_monitors", []),
        confidence=confidence,
        composite_score=composite,
        catalyst_strength_score=catalyst_strength,
        quant_confirmation_score=quant,
        risk_asymmetry_score=risk,
        information_asymmetry_score=info_asym,
        data_quality_score=data_quality,
        marginal_buyer_score=_deterministic_marginal_buyer_score(agent2),
        marginal_buyer_analysis=llm.get("marginal_buyer_analysis", ""),
        bear_summary=agent1b.bear_summary,
        catalyst_type=agent1.catalyst_type,
        catalyst_type_prior=prior,
        confirming_signals=signals.confirming_signals,
        confirming_signal_count=signals.confirming_signal_count,
        signal_bonus=signal_bonus,
        probationary=agent1.probationary,
        liquidity_warning=agent1.liquidity_warning,
        short_interest_flag=agent2.short_interest_flag,
        stale_data_flag=agent2.stale_data_flag,
        sector_beta_flag=agent2.sector_beta_flag,
        rs_vs_iwm=agent2.rs_vs_iwm,
        proxies_computed=agent2.proxies_computed,
        missing_data_fields=list(set(agent1.missing_data + agent2.missing_data)),
        days_since_catalyst=days_since,
        high_upside_score=high_upside_score,
        high_upside_markers=high_upside_markers,
        regime_override=agent1.regime_override,
        recommended_hold_days=recommended_hold,
    )
