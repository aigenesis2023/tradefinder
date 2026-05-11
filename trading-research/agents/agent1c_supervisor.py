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

STRATEGY CONTEXT: This is a quantitative momentum strategy that deliberately targets overlooked, neglected,
and often unappealing small/mid-cap stocks. Messy companies, controversial management, and litigious histories
are EXPECTED — that is exactly where the information asymmetry and neglect alpha comes from.

CRITICAL RULE: Disqualify ONLY on DATA or MATH conflicts. Specifically:
- Mathematical errors in the bull thesis (numbers don't add up)
- Factual contradictions that are irresolvable with available data (e.g. Bear proves catalyst date is wrong)
- The catalyst has ALREADY been reported in mainstream financial media (priced in)
- Data quality is so poor that no conclusion is possible

DO NOT DISQUALIFY for any of the following — these are features, not bugs:
- Company reputation or management controversy
- Litigation history or pending lawsuits (unless they directly threaten the specific catalyst)
- Controversial industry or ethical concerns
- Overleveraged balance sheet (already factored into scoring via quant/risk components)
- Bear case is "this might not work" without citing a specific irresolvable data conflict
- Bear score is high but based on speculation rather than fact

When in doubt about a DATA conflict: DISQUALIFIED.
When the Bear's argument is qualitative risk/opinion rather than factual contradiction: PROCEED.

STOCK: {bull.ticker} ({bull.company_name})

BULL NARRATIVE:
{bull.bull_narrative}

BEAR SUMMARY:
{bear.bear_summary}

BULL SCORES: asymmetry={bull.information_asymmetry_score:.2f} | prior={bull.catalyst_type_prior} | days_since={bull.days_since_catalyst}
BEAR FLAGS: priced={bear.catalyst_already_priced} | momentum_only={bear.momentum_only_risk} | bear_score={bear.bear_score:.2f}
CONTRACT MATERIALITY: {bear.contract_materiality_concern}
NEGLECT VALIDITY: {bear.neglect_validity_concern}

For each conflict: is it a resolvable DATA disagreement, or a speculative risk opinion?
Disqualify only on irresolvable data/math conflicts. Risk opinions → PROCEED.

Return ONLY valid JSON:

{{
  "outcome": "PROCEED" or "DISQUALIFIED",
  "disqualify_reason": "<if DISQUALIFIED, the specific irresolvable DATA conflict — must cite data, not opinion>",
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
