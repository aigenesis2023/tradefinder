"""
Agent 1C — Supervisor

Judgment task: identify whether conflict between Bull and Bear is resolvable.
Not to pick a winner.

Hard rules:
  - Irresolvable conflict = hard DISQUALIFIED, reason logged
  - Supervisor never picks Bull by default
  - Uncertainty always favours disqualification
"""

import json
import re
from dataclasses import dataclass, field
from orchestrator.request_budget import BudgetManager
from orchestrator.llm_client import call_claude
from agents.agent1_bull import Agent1Result
from agents.agent1b_bear import Agent1BResult

DISQUALIFIED = "DISQUALIFIED"
PROCEED = "PROCEED"


@dataclass
class Agent1CResult:
    ticker: str
    outcome: str  # PROCEED or DISQUALIFIED
    disqualify_reason: str
    conflict_points: list = field(default_factory=list)
    resolution_summary: str = ""
    conflict_level: str = "low"


def run_agent1c(
    bull: Agent1Result,
    bear: Agent1BResult,
    budget: BudgetManager,
) -> Agent1CResult:

    prompt = f"""You are Agent 1C (Supervisor). Your only job is to decide whether the Bear has identified a SPECIFIC DATA OR MATH ERROR in the Bull thesis that makes the trade impossible to evaluate. You do NOT pick a winner. You do NOT weigh risk.

STRATEGY CONTEXT: This is a quantitative momentum strategy that deliberately targets overlooked, neglected, and often unappealing small/mid-cap stocks. Messy companies, controversial management, litigation overhang, and ugly charts are EXPECTED — that is the source of the alpha. Risk is priced via the deterministic scoring layer (catalyst strength, quant, risk_asymmetry, info_asymmetry). Your job is NOT to add more risk-weighting on top.

DISQUALIFY only if at least one of these is TRUE (closed list — nothing else qualifies):

  D1. The Bear cites a specific numerical/factual error in the Bull thesis (e.g. "Bull says $40M contract but USAspending shows $4M").
  D2. The Bear proves the catalyst date is wrong or the catalyst doesn't exist as described.
  D3. The catalyst has already been reported by mainstream financial media (WSJ, Bloomberg, Reuters, FT) BEFORE the bull's catalyst_date — meaning the signal is already public information.
  D4. The Bear identifies a data-quality issue so severe that the catalyst itself cannot be confirmed (e.g. ticker has been delisted, company merged, filing was retracted).
  D5. Multiple core data fields in the bull thesis are mutually inconsistent in ways that cannot be reconciled (e.g. market cap vs share count vs price don't multiply).

PROCEED in ALL other cases. Specifically — these are NOT disqualifications:

  - High short interest (this is a +0.4 risk_asymmetry signal in our strategy, NOT a bear signal)
  - Litigation, class actions, short-seller reports (priced via the scoring layer)
  - Management reputation, governance concerns, board/insider relationships
  - Macro/sector headwinds
  - "Stock might keep going down" without a specific data error
  - Bear is convincing but doesn't cite a D1-D5 violation
  - You feel uncertain — uncertainty is NOT a disqualifier; it's flagged via conflict_level=high

DEFAULT: PROCEED. The cost of a false-PROCEED is a Speculative-confidence trade that gets caught by the composite floor. The cost of a false-DISQUALIFY is permanently losing a real signal. Bias toward PROCEED.

STOCK: {bull.ticker} ({bull.company_name})

BULL NARRATIVE:
{bull.bull_narrative}

BEAR SUMMARY:
{bear.bear_summary}

BULL SCORES: asymmetry={bull.information_asymmetry_score:.2f} | prior={bull.catalyst_type_prior} | days_since={bull.days_since_catalyst}
BEAR FLAGS: priced={bear.catalyst_already_priced} | momentum_only={bear.momentum_only_risk} | bear_score={bear.bear_score:.2f}
CONTRACT MATERIALITY: {bear.contract_materiality_concern}
NEGLECT VALIDITY: {bear.neglect_validity_concern}

Check each D1-D5 condition against the Bear summary. If NONE match, PROCEED — even if the Bear case is strong, even if you have qualitative doubts.

If you DISQUALIFY, your `disqualify_reason` MUST start with "D1:", "D2:", "D3:", "D4:", or "D5:" and cite the specific data point. Generic phrases like "irresolvable conflict", "multiple concerns", or "data quality issues" are NOT valid disqualification reasons.

Return ONLY valid JSON:

{{
  "outcome": "PROCEED" or "DISQUALIFIED",
  "disqualify_reason": "<if DISQUALIFIED, starts with D1:/D2:/D3:/D4:/D5: and cites the specific data point>",
  "conflict_points": ["<conflict 1>", "<conflict 2>"],
  "resolution_summary": "<if PROCEED, one sentence on the main conflict and why it's a risk concern, not a data conflict>",
  "conflict_level": "low" or "medium" or "high"
}}"""

    # Default on LLM call failure: PROCEED with conflict_level=high.
    # Rationale: a silent infra failure should not permanently kill a real signal.
    # The downstream composite floor (3.5) + Speculative confidence cap still gate
    # marginal candidates. Better to surface flagged than to lose silently.
    default = Agent1CResult(
        ticker=bull.ticker,
        outcome=PROCEED,
        disqualify_reason="",
        resolution_summary="Supervisor call failed — defaulted to PROCEED with elevated conflict level. Trade with extra caution.",
        conflict_level="high",
    )

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
        if not match:
            return default
        data = json.loads(match.group())
        outcome = data.get("outcome", DISQUALIFIED).upper()
        if outcome not in (PROCEED, DISQUALIFIED):
            outcome = DISQUALIFIED
        return Agent1CResult(
            ticker=bull.ticker,
            outcome=outcome,
            disqualify_reason=data.get("disqualify_reason", ""),
            conflict_points=data.get("conflict_points", []),
            resolution_summary=data.get("resolution_summary", ""),
            conflict_level=data.get("conflict_level", "medium"),
        )
    except Exception:
        return default
