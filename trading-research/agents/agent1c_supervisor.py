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

    prompt = f"""You are Agent 1C (Supervisor). Identify whether the conflict between Bull and Bear is resolvable.
You do NOT pick a winner.

CRITICAL RULE: If any material disagreement is irresolvable with available data, output DISQUALIFIED.
Uncertainty always favours disqualification. Never default to Bull.

STOCK: {bull.ticker} ({bull.company_name})

BULL NARRATIVE:
{bull.bull_narrative}

BEAR SUMMARY:
{bear.bear_summary}

BULL SCORES: asymmetry={bull.information_asymmetry_score:.2f} | prior={bull.catalyst_type_prior} | days_since={bull.days_since_catalyst}
BEAR FLAGS: priced={bear.catalyst_already_priced} | momentum_only={bear.momentum_only_risk} | bear_score={bear.bear_score:.2f}
CONTRACT MATERIALITY: {bear.contract_materiality_concern}
NEGLECT VALIDITY: {bear.neglect_validity_concern}

For each conflict: is it resolvable with available data, or fundamental uncertainty?
If ANY material disagreement is irresolvable: DISQUALIFIED.

Return ONLY valid JSON:

{{
  "outcome": "PROCEED" or "DISQUALIFIED",
  "disqualify_reason": "<if DISQUALIFIED, the specific irresolvable conflict>",
  "conflict_points": ["<conflict 1>", "<conflict 2>"],
  "resolution_summary": "<if PROCEED, how conflicts were resolved>",
  "conflict_level": "low" or "medium" or "high"
}}"""

    default = Agent1CResult(
        ticker=bull.ticker,
        outcome=DISQUALIFIED,
        disqualify_reason="Supervisor call failed — defaulting to DISQUALIFIED per uncertainty rule",
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
