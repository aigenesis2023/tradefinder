"""
Agent 1B — Bear

Judgment task: find the strongest possible case AGAINST the trade.
Given identical data to Agent 1 (Bull). Must assume the trade loses money.
Evaluated on quality of failure case, not agreement with Agent 1.
"""

import json
import re
from dataclasses import dataclass
from orchestrator.request_budget import BudgetManager
from orchestrator.llm_client import call_claude
from agents.agent1_bull import Agent1Result


@dataclass
class Agent1BResult:
    ticker: str
    bear_summary: str
    catalyst_already_priced: bool
    momentum_only_risk: bool
    contract_materiality_concern: bool
    neglect_validity_concern: bool
    liquidity_execution_risk: str
    short_interest_context: str
    marginal_buyer_concern: str
    bear_score: float


def run_agent1b(
    bull_result: Agent1Result,
    market_data: dict,
    budget: BudgetManager,
) -> Agent1BResult:

    prompt = f"""You are Agent 1B (Bear). Your role is to find the strongest possible case AGAINST this trade.
Assume the trade loses money. Explain convincingly why. Flip the thesis and argue it.
You are evaluated on the quality of your failure case, NOT on whether you agree with the bull.

STRATEGY CONTEXT: This strategy deliberately targets messy, overlooked, often unappealing companies.
Controversial management, litigation history, and ugly charts are expected and acceptable.
Your bear case must be FINANCIAL and DATA-BASED, not reputational or ethical.

FOCUS YOUR BEAR CASE ON:
- Is the catalyst already fully priced in to the stock price?
- Is this momentum-only with no underlying fundamental change?
- Are there specific data errors or contradictions in the bull thesis?
- Liquidity/execution risks for this specific trade
- Macro or sector headwinds that could overwhelm the catalyst

DO NOT INCLUDE in your bear case (these are NOT disqualifiers for this strategy):
- Company reputation or management track record (irrelevant to 10-day alpha)
- Litigation or legal history (unless it directly threatens the specific catalyst)
- Ethical concerns about the business or industry
- Generic "small caps are risky" arguments

STOCK: {bull_result.ticker} ({bull_result.company_name})
CATALYST: {bull_result.catalyst_type} on {bull_result.catalyst_date}
CATALYST DETAIL: {bull_result.catalyst_description}
CONTRACT VALUE AS PCT OF REVENUE: {bull_result.contract_award_value_pct_revenue:.1f}%
ANALYST COUNT: {bull_result.analyst_count}
MARKET CAP: ${bull_result.market_cap_m:.0f}M
DAYS SINCE CATALYST: {bull_result.days_since_catalyst}
INFORMATION ASYMMETRY SCORE: {bull_result.information_asymmetry_score:.2f}
PROBATIONARY: {bull_result.probationary}
LIQUIDITY WARNING: {bull_result.liquidity_warning}

BULL NARRATIVE: {bull_result.bull_narrative}

MARKET DATA:
{json.dumps(market_data, default=str, indent=2)}

Address ALL of the following in your response. Return ONLY valid JSON:

{{
  "bear_summary": "<two paragraphs arguing the bear case as if you believe it>",
  "catalyst_already_priced": <true/false>,
  "momentum_only_risk": <true/false>,
  "contract_materiality_concern": "<one sentence>",
  "neglect_validity_concern": "<one sentence>",
  "liquidity_execution_risk": "<one sentence>",
  "short_interest_context": "<one sentence>",
  "marginal_buyer_concern": "<one sentence>",
  "bear_score": <float 0-5, how strong is the bear case>
}}"""

    default = Agent1BResult(
        ticker=bull_result.ticker,
        bear_summary="Bear analysis unavailable.",
        catalyst_already_priced=False,
        momentum_only_risk=False,
        contract_materiality_concern="",
        neglect_validity_concern="",
        liquidity_execution_risk="",
        short_interest_context="",
        marginal_buyer_concern="",
        bear_score=2.5,
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
        return Agent1BResult(
            ticker=bull_result.ticker,
            bear_summary=data.get("bear_summary", ""),
            catalyst_already_priced=bool(data.get("catalyst_already_priced", False)),
            momentum_only_risk=bool(data.get("momentum_only_risk", False)),
            contract_materiality_concern=data.get("contract_materiality_concern", ""),
            neglect_validity_concern=data.get("neglect_validity_concern", ""),
            liquidity_execution_risk=data.get("liquidity_execution_risk", ""),
            short_interest_context=data.get("short_interest_context", ""),
            marginal_buyer_concern=data.get("marginal_buyer_concern", ""),
            bear_score=float(data.get("bear_score", 2.5)),
        )
    except Exception:
        return default
