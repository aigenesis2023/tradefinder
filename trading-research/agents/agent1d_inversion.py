"""
Agent 1D — Narrative Inversion

Try to construct a compelling narrative. If it succeeds: DISQUALIFIED.
Edge lives in stocks Agent 1D cannot write about.

Hard rules:
  - Success = DISQUALIFIED
  - LLM failure defaults to DISQUALIFIED per uncertainty rule
"""

import json
import re
from dataclasses import dataclass
from orchestrator.request_budget import BudgetManager
from orchestrator.llm_client import call_claude
from agents.agent1_bull import Agent1Result

DISQUALIFIED = "DISQUALIFIED"
PROCEED = "PROCEED"


@dataclass
class Agent1DResult:
    ticker: str
    outcome: str  # PROCEED or DISQUALIFIED
    disqualify_reason: str
    narrative_attempt: str
    narrative_strength: float


def run_agent1d(
    bull: Agent1Result,
    budget: BudgetManager,
) -> Agent1DResult:

    prompt = f"""You are Agent 1D (Narrative Inversion). Your task is unusual:

Try to build the MOST COMPELLING possible investment narrative for this stock.
Search your knowledge for any analyst coverage, media mentions, social discussion,
or institutional interest that would make this a well-known opportunity.

If you SUCCEED in building a coherent, compelling narrative: output DISQUALIFIED.
The stock is not neglected enough — if you can write a good story, so can others.

If you GENUINELY CANNOT construct a compelling narrative despite trying: output PROCEED.

If you find yourself reaching for weak connections or thin evidence: output DISQUALIFIED.

STOCK: {bull.ticker} ({bull.company_name})
CATALYST: {bull.catalyst_type} on {bull.catalyst_date}
ANALYST COUNT: {bull.analyst_count}
MARKET CAP: ${bull.market_cap_m:.0f}M

Try hard to find any analyst reports, media coverage, social discussion, or institutional interest.

Return ONLY valid JSON:

{{
  "outcome": "PROCEED" or "DISQUALIFIED",
  "disqualify_reason": "<if DISQUALIFIED, what narrative evidence did you find?>",
  "narrative_attempt": "<the narrative you attempted to build>",
  "narrative_strength": <float 0-5, how compelling — 5 means widely covered>
}}

Remember: your success means the stock FAILS. Try hard."""

    default = Agent1DResult(
        ticker=bull.ticker,
        outcome=DISQUALIFIED,
        disqualify_reason="Agent 1D call failed — defaulting to DISQUALIFIED per uncertainty rule",
        narrative_attempt="",
        narrative_strength=0.0,
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
        return Agent1DResult(
            ticker=bull.ticker,
            outcome=outcome,
            disqualify_reason=data.get("disqualify_reason", ""),
            narrative_attempt=data.get("narrative_attempt", ""),
            narrative_strength=float(data.get("narrative_strength", 0.0)),
        )
    except Exception:
        return default
