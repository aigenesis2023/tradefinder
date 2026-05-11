"""
Agent 1 — Bull (Narrative Researcher)

Judgment task: find the strongest possible case FOR the trade.
Role is explicitly Bull. Must argue for the opportunity as if you believe it unconditionally.

All filtering, scoring, and thresholds are enforced in Python below.
The LLM prompt handles judgment only — narrative quality, catalyst assessment, coverage gap analysis.

Discovery direction (NEW):
  Start from a cached watchlist of neglected publicly-listed small-caps,
  then check each for recent USAspending.gov contract activity.
  This is the correct direction — start from tickers we can trade, find catalysts on them.
  Old approach (contract → ticker) mostly found private companies.
"""

import json
import re
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional
import yfinance as yf
import requests

from orchestrator.request_budget import BudgetManager
from orchestrator.neglect_screen import screen_ticker, NeglectResult
from orchestrator.llm_client import call_claude
from orchestrator.state_manager import is_deduped
from orchestrator.universe_builder import build_neglected_universe
from orchestrator.contract_scanner import scan_contracts
from orchestrator.insider_scanner import scan_insider_buying, InsiderCluster

# ── Thresholds (all Python, never in prompts) ─────────────────────────────

MARKET_CAP_MIN_M = 200
MARKET_CAP_MAX_M = 5000
MARKET_CAP_PROBATIONARY_MIN_M = 100
DAILY_DOLLAR_VOLUME_MIN = 500_000

ASYMMETRY_DISCARD_BELOW = 1.5
ASYMMETRY_PROBATIONARY_MIN = 1.5
ASYMMETRY_PROBATIONARY_MAX = 2.5
ASYMMETRY_HIGH_CONVICTION_MIN = 3.5
ASYMMETRY_SPECULATIVE_CAP = 2.0

PRICE_LAG_THRESHOLD_PCT = 3.0
# Hard discard: catalyst already reflected in price. Insider clusters routinely
# cause a same-day spike that isn't full pricing — the empirical 30-day alpha
# is measured AFTER that spike. Government contracts decay faster post-news.
ALREADY_PRICED_IN_PCT_CONTRACT = 5.0
ALREADY_PRICED_IN_PCT_INSIDER = 12.0

CONTRACT_REVENUE_THRESHOLD_PCT = 10.0  # below this → downgrade to Speculative in scoring

CATALYST_TYPE_PRIORS = {
    "government_contract_award": 1.0,
    "state_government_contract": 1.0,
    "neglected_firm_pre_coverage": 0.9,
    "insider_buying_cluster": 0.85,
    "supply_chain_echo": 0.7,
    "pead": 0.7,
    "risk_factor_delta": 0.6,
    "unknown": 0.5,
}

MAX_CANDIDATES = 15
MAX_PROBATIONARY_PCT = 0.5

# Elite-override thresholds — applied only when the regime gate has failed.
# Calibrated to be top-decile signal strength: levels at which executive
# conviction or contract magnitude is large enough to plausibly survive
# adverse macro beta.
ELITE_INSIDER_MIN_BUYERS = 5
ELITE_INSIDER_MATERIALITY_PCT = 0.10   # 0.10% of market cap (5x the normal floor)
ELITE_INSIDER_TOTAL_USD_MIN = 2_000_000
ELITE_CONTRACT_PCT_REVENUE = 25.0

# SAM.gov — 10 req/day public limit. Only used for entity UEI lookup if needed.
SAM_GOV_ENTITY_URL = "https://api.sam.gov/entity-information/v3/entities"
HEADERS = {"User-Agent": "tradefinder-research/1.0"}


# ── Dataclasses ────────────────────────────────────────────────────────────

@dataclass
class CandidateRaw:
    ticker: str
    company_name: str
    catalyst_type: str
    catalyst_date: str
    catalyst_description: str
    contract_value_usd: float = 0.0
    ttm_revenue_usd: float = 0.0
    market_cap_m: float = 0.0
    avg_daily_dollar_volume: float = 0.0
    analyst_count: int = 0
    price: float = 0.0
    price_change_since_catalyst_pct: float = 0.0
    probationary: bool = False
    liquidity_warning: bool = False
    missing_data: list = field(default_factory=list)
    raw_news: list = field(default_factory=list)


@dataclass
class Agent1Result:
    ticker: str
    company_name: str
    catalyst_type: str
    catalyst_type_prior: float
    catalyst_date: str
    catalyst_description: str
    contract_award_value_pct_revenue: float
    information_asymmetry_score: float
    recency_vs_lag_score: float
    coverage_gap_score: float
    narrative_inconsistency_score: float
    market_cap_m: float
    probationary: bool
    liquidity_warning: bool
    discard_reason: Optional[str]
    bull_narrative: str
    missing_data: list = field(default_factory=list)
    analyst_count: int = 0
    days_since_catalyst: int = 0
    unique_insiders: int = 0
    insider_total_usd: float = 0.0
    regime_override: bool = False   # True when surfaced during regime-gate failure


# ── Data fetching ──────────────────────────────────────────────────────────

def _fetch_sam_entity_detail(uei: str, sam_api_key: str) -> dict:
    if not sam_api_key or not uei:
        return {}
    try:
        resp = requests.get(
            SAM_GOV_ENTITY_URL,
            params={"api_key": sam_api_key, "ueiSAM": uei},
            headers=HEADERS,
            timeout=15,
        )
        if resp.status_code != 200:
            return {}
        entities = resp.json().get("entityData", [])
        return entities[0] if entities else {}
    except Exception:
        return {}


def _enrich_ticker(ticker: str) -> dict:
    """Fetch market data for a ticker via yfinance."""
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        hist = t.history(period="6mo")

        market_cap_m = (info.get("marketCap") or 0) / 1e6
        price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
        avg_volume = float(hist["Volume"].mean()) if not hist.empty else 0
        avg_dollar_vol = avg_volume * price
        ttm_revenue = (info.get("totalRevenue") or 0) / 1e6
        low_52w = float(info.get("fiftyTwoWeekLow") or 0)
        high_52w = float(info.get("fiftyTwoWeekHigh") or 0)

        return {
            "market_cap_m": round(market_cap_m, 2),
            "price": round(price, 4),
            "avg_daily_dollar_volume": round(avg_dollar_vol, 2),
            "ttm_revenue_m": round(ttm_revenue, 2),
            "company_name": info.get("longName") or ticker,
            "sector": info.get("sector") or "",
            "country": (info.get("country") or "").strip(),
            "low_52w": low_52w,
            "high_52w": high_52w,
        }
    except Exception:
        return {}


# ── Scoring helpers ────────────────────────────────────────────────────────

def _get_coverage_score(analyst_count: int) -> float:
    if analyst_count <= 3:
        return 5.0
    elif analyst_count <= 5:
        return 4.0
    elif analyst_count <= 8:
        return 3.0
    else:
        return max(0.0, 3.0 - (analyst_count - 8) * 0.3)


def _get_catalyst_type_prior(catalyst_type: str) -> float:
    return CATALYST_TYPE_PRIORS.get(catalyst_type, 0.5)


def _contract_value_pct_revenue(contract_usd: float, ttm_revenue_m: float) -> float:
    if ttm_revenue_m <= 0 or contract_usd <= 0:
        return 0.0
    return round((contract_usd / 1e6) / ttm_revenue_m * 100, 2)


def _days_since(date_str: str) -> int:
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return (datetime.utcnow() - dt).days
    except Exception:
        return 0


def _price_change_since_date(ticker: str, catalyst_date: str) -> float | None:
    """
    Return % price change from catalyst_date close to latest close.
    Returns None if data is unavailable (not a discard signal — penalises data_quality).
    """
    try:
        dt = datetime.strptime(catalyst_date[:10], "%Y-%m-%d")
    except Exception:
        return None
    try:
        hist = yf.Ticker(ticker).history(start=dt.strftime("%Y-%m-%d"), period="5d", auto_adjust=True)
        if hist.empty or len(hist) < 2:
            return None
        price_at_catalyst = float(hist["Close"].iloc[0])
        price_now = float(hist["Close"].iloc[-1])
        if price_at_catalyst == 0:
            return None
        return round((price_now - price_at_catalyst) / price_at_catalyst * 100, 2)
    except Exception:
        return None


def _compute_asymmetry_score(
    recency_vs_lag: float,
    coverage_gap: float,
    narrative_inconsistency: float,
) -> float:
    return round(
        (recency_vs_lag * 0.30) +
        (coverage_gap * 0.40) +
        (narrative_inconsistency * 0.30),
        3
    )


def _apply_market_cap_rules(market_cap_m: float) -> tuple[bool, bool, str | None]:
    """Returns (keep, probationary, discard_reason)."""
    if market_cap_m < MARKET_CAP_PROBATIONARY_MIN_M:
        return False, False, f"market_cap {market_cap_m:.0f}M below minimum {MARKET_CAP_PROBATIONARY_MIN_M}M"
    if market_cap_m < MARKET_CAP_MIN_M:
        return True, True, None
    if market_cap_m > MARKET_CAP_MAX_M:
        return False, False, f"market_cap {market_cap_m:.0f}M above maximum {MARKET_CAP_MAX_M}M"
    return True, False, None


# ── LLM judgment ──────────────────────────────────────────────────────────

def _llm_bull_analysis(
    candidate: CandidateRaw,
    neglect: NeglectResult,
    budget: BudgetManager,
) -> dict:
    if candidate.catalyst_type == "insider_buying_cluster":
        catalyst_block = (
            f"CATALYST: insider_buying_cluster — last buy on {candidate.catalyst_date}\n"
            f"CLUSTER DETAIL: {candidate.catalyst_description}\n"
            f"TOTAL INSIDER BUY: ${candidate.contract_value_usd:,.0f}\n"
            f"CURRENT PRICE: ${candidate.price:.2f}"
        )
    else:
        catalyst_block = (
            f"CATALYST: {candidate.catalyst_type} on {candidate.catalyst_date}\n"
            f"CATALYST DETAIL: {candidate.catalyst_description}\n"
            f"CONTRACT VALUE: ${candidate.contract_value_usd:,.0f}"
        )

    prompt = f"""You are Agent 1 (Bull). Your role is to find the strongest possible case FOR this trade.
Argue for the opportunity as if you believe it unconditionally.

You are evaluating whether this stock represents a genuine information asymmetry opportunity.

STOCK: {candidate.ticker} ({candidate.company_name})
{catalyst_block}
TTM REVENUE: ${candidate.ttm_revenue_usd * 1e6:,.0f}
MARKET CAP: ${candidate.market_cap_m:.0f}M
PRICE CHANGE SINCE CATALYST: {candidate.price_change_since_catalyst_pct:.1f}%
ANALYST COUNT: {candidate.analyst_count}
NEWS (last 30d): {json.dumps(candidate.raw_news[:5], default=str)}

NEGLECT SCREEN: {neglect.conditions_passed}/4 conditions passed
  - Analysts: {neglect.analyst_count} ({'pass' if neglect.analyst_pass else 'fail'})
  - News 30d: {neglect.news_count_30d} ({'pass' if neglect.news_pass else 'fail'})
  - Institutional: {neglect.institutional_pct:.1f}% ({'pass' if neglect.institutional_pass else 'fail'})
  - Volume ratio: {neglect.volume_ratio:.2f} ({'pass' if neglect.volume_pass else 'fail'})

Score the following on a 0.0-5.0 scale. Return ONLY valid JSON, no prose outside the JSON.

{{
  "recency_vs_lag_score": <float 0-5, how much pricing lag exists since catalyst>,
  "narrative_inconsistency_score": <float 0-5, how inconsistent is market narrative vs fundamentals>,
  "bull_narrative": "<one paragraph making the strongest possible bull case>",
  "catalyst_strength_assessment": "<one sentence on catalyst quality>",
  "coverage_gap_notes": "<one sentence on why coverage is sparse>"
}}

Be honest. If the opportunity is weak, score it low — a weak bull case is still a bull case."""

    result = {"recency_vs_lag_score": 2.5, "narrative_inconsistency_score": 2.5,
              "bull_narrative": "", "catalyst_strength_assessment": "", "coverage_gap_notes": ""}

    if budget.dry_run:
        budget.estimate("llm")
        return result

    if not budget.can_call("llm"):
        return result

    budget._register("llm")
    raw = call_claude(prompt)
    if raw:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            try:
                result.update(json.loads(match.group()))
            except Exception:
                pass

    return result


# ── Main entry point ──────────────────────────────────────────────────────

def _insider_cluster_description(cluster: InsiderCluster) -> str:
    """Build a compact human-readable description of an insider buying cluster."""
    names = ", ".join({t.name for t in cluster.transactions})
    roles = ", ".join({t.role for t in cluster.transactions if t.role})
    return (
        f"{cluster.unique_insiders} insiders ({names}) bought ${cluster.total_usd:,.0f} total "
        f"between {cluster.cluster_start} and {cluster.cluster_end}. "
        f"Roles: {roles or 'unknown'}."
    )


def run_agent1(
    sam_gov_key: str,
    budget: BudgetManager,
    firecrawl_key: str | None = None,
    elite_only: bool = False,
) -> list[Agent1Result]:
    """
    Discovery flow:
      1. Load small-cap watchlist (cached weekly)
      2. Parallel scans on all fresh tickers:
         a. USAspending — government contract awards (primary, prior 1.0)
         b. SEC EDGAR Form 4 — insider buying clusters (primary, prior 0.85)
      3. Merge hits; if a ticker has both catalysts, government contract wins as primary
      4. Enrich, apply filters, run LLM analysis on all hits
    """
    results = []
    probationary_count = 0
    sam_calls_used = 0
    SAM_CALL_BUDGET = 5

    # ── Step 1: Load universe ─────────────────────────────────────────────
    watchlist = build_neglected_universe()
    if not watchlist:
        print("[Agent1] Watchlist is empty — run universe_builder manually.")
        return []

    fresh = []
    for entry in watchlist:
        is_blocked, _ = is_deduped(entry["ticker"])
        if not is_blocked:
            fresh.append(entry)

    print(f"[Agent1] {len(fresh)}/{len(watchlist)} watchlist tickers fresh (not seen in 14d).")

    # ── Step 2a: Scan USAspending ─────────────────────────────────────────
    # Only $500M+ companies — smaller companies rarely win federal contracts.
    contract_eligible = [e for e in fresh if e.get("market_cap_m", 0) >= 500]
    print(f"[Agent1] Scanning USAspending for contract activity ({len(contract_eligible)} tickers ≥$500M)...")
    contract_hit_map: dict[str, dict] = {}  # ticker → best_award

    for entry in contract_eligible:
        company_name = entry.get("company_name", entry["ticker"])
        awards = scan_contracts(company_name)
        if awards:
            contract_hit_map[entry["ticker"]] = awards[0]

    print(f"[Agent1] {len(contract_hit_map)} tickers with recent verified contracts.")

    # ── Step 2b: Scan SEC EDGAR Form 4 for insider buying clusters ────────
    # 7-year backtest (n=382): 3+ insiders in $200M-$500M shows -0.87% alpha / 50% alpha_win.
    # Only $500M-$5B has real signal: +3.92% alpha / 68.8% alpha_win (n=93). Restrict accordingly.
    insider_eligible = [e for e in fresh if e.get("market_cap_m", 0) >= 500]
    print(f"[Agent1] Scanning SEC EDGAR for insider buying clusters ({len(insider_eligible)} tickers ≥$500M)...")
    insider_hit_map: dict[str, InsiderCluster] = {}  # ticker → cluster

    for entry in insider_eligible:
        ticker = entry["ticker"]
        try:
            cluster = scan_insider_buying(ticker, days_back=45)
            if cluster.detected:
                insider_hit_map[ticker] = cluster
        except Exception as e:
            print(f"[Agent1] Insider scan error for {ticker}: {e}")

    print(f"[Agent1] {len(insider_hit_map)} tickers with insider buying clusters.")

    # ── Step 2c: Build unified candidate hit list ─────────────────────────
    # Each entry: (watchlist_entry, catalyst_type, catalyst_value_usd, catalyst_date,
    #              description, uei, insider_cluster_or_none)
    Hit = tuple  # typed alias
    all_hits: list[Hit] = []

    all_hit_tickers = set(contract_hit_map) | set(insider_hit_map)
    entry_map = {e["ticker"]: e for e in fresh}

    for ticker in all_hit_tickers:
        if ticker not in entry_map:
            continue
        entry = entry_map[ticker]

        if ticker in contract_hit_map:
            # Government contract wins as primary when both are present
            award = contract_hit_map[ticker]
            all_hits.append((
                entry,
                "government_contract_award",
                award["contract_value_usd"],
                award["catalyst_date"],
                award["description"],
                award.get("uei", ""),
                insider_hit_map.get(ticker),  # confirming signal if also present
            ))
        else:
            cluster = insider_hit_map[ticker]
            all_hits.append((
                entry,
                "insider_buying_cluster",
                cluster.total_usd,
                cluster.cluster_end,
                _insider_cluster_description(cluster),
                "",
                cluster,
            ))

    if not all_hits:
        print("[Agent1] No contract or insider activity found today.")
        return []

    # Sort by catalyst value descending (larger = more material)
    all_hits.sort(key=lambda x: x[2], reverse=True)
    print(f"[Agent1] {len(all_hits)} total hits ({len(contract_hit_map)} contracts, "
          f"{len(insider_hit_map)} insider clusters, "
          f"{len(set(contract_hit_map) & set(insider_hit_map))} overlap).")

    # ── Step 3: Process hits through filters + LLM ────────────────────────
    candidates_processed = 0

    for entry, catalyst_type, catalyst_value, catalyst_date, description, uei, cluster in all_hits:
        if candidates_processed >= MAX_CANDIDATES:
            break

        ticker = entry["ticker"]

        # Elite-override filter: when the regime gate has failed, only top-decile
        # signals are allowed through. Tests on the raw signal — before any market
        # data fetch — so we don't burn yfinance budget on candidates that can't
        # pass anyway.
        if elite_only:
            if catalyst_type == "insider_buying_cluster":
                if cluster is None or cluster.unique_insiders < ELITE_INSIDER_MIN_BUYERS:
                    print(f"[Agent1] (elite) Discarding {ticker}: needs {ELITE_INSIDER_MIN_BUYERS}+ insiders during override mode")
                    continue
                if catalyst_value < ELITE_INSIDER_TOTAL_USD_MIN:
                    print(f"[Agent1] (elite) Discarding {ticker}: cluster ${catalyst_value:,.0f} below ${ELITE_INSIDER_TOTAL_USD_MIN:,} elite floor")
                    continue
            # Contract elite check happens after enrichment (needs market cap + revenue)

        enriched = _enrich_ticker(ticker)
        if not enriched:
            continue

        country = enriched.get("country", "").lower()
        if country and country not in ("united states", "usa", "us"):
            print(f"[Agent1] Discarding {ticker}: foreign company ({country})")
            continue

        market_cap_m = enriched.get("market_cap_m", 0)
        keep, probationary, discard_reason = _apply_market_cap_rules(market_cap_m)
        if not keep:
            print(f"[Agent1] Discarding {ticker}: {discard_reason}")
            continue

        if probationary:
            max_prob = int(MAX_CANDIDATES * MAX_PROBATIONARY_PCT)
            if probationary_count >= max_prob:
                continue
            probationary_count += 1

        liquidity_warning = probationary
        avg_dollar_vol = enriched.get("avg_daily_dollar_volume", 0)
        if market_cap_m < MARKET_CAP_MIN_M and avg_dollar_vol < DAILY_DOLLAR_VOLUME_MIN:
            liquidity_warning = True

        ttm_revenue_m = enriched.get("ttm_revenue_m", 0)
        contract_pct = _contract_value_pct_revenue(catalyst_value, ttm_revenue_m)

        # Elite-override: now that we have revenue + market cap, finalise the elite check.
        if elite_only:
            if catalyst_type == "government_contract_award":
                if contract_pct < ELITE_CONTRACT_PCT_REVENUE:
                    print(f"[Agent1] (elite) Discarding {ticker}: contract {contract_pct:.1f}% of revenue below {ELITE_CONTRACT_PCT_REVENUE:.0f}% elite floor")
                    continue
            elif catalyst_type == "insider_buying_cluster" and market_cap_m > 0:
                materiality_pct = (catalyst_value / (market_cap_m * 1e6)) * 100
                if materiality_pct < ELITE_INSIDER_MATERIALITY_PCT:
                    print(f"[Agent1] (elite) Discarding {ticker}: cluster {materiality_pct:.3f}% of mcap below {ELITE_INSIDER_MATERIALITY_PCT}% elite floor")
                    continue

        neglect = screen_ticker(ticker)

        if catalyst_type == "insider_buying_cluster":
            # For insider signals, only analyst coverage and news silence matter.
            # Institutional % is wrong at $500M-$5B (index funds alone own 15-20%;
            # "30%" would eliminate the entire investable universe). Also yfinance
            # heldPercentInstitutions can exceed 100% via short-lending double-count.
            # Volume ratio is backwards — insider buying itself causes the spike.
            # Hard discard: stock is BOTH heavily followed AND recently in the news
            # (means market has already had time to process the signal).
            market_has_noticed = neglect.analyst_count >= 10 and neglect.news_count_30d >= 5
            if market_has_noticed:
                print(f"[Agent1] Discarding {ticker}: insider signal likely priced in "
                      f"(analysts={neglect.analyst_count}, news30d={neglect.news_count_30d})")
                continue
            if neglect.analyst_count >= 10:
                print(f"[Agent1] {ticker}: high analyst count ({neglect.analyst_count}) for insider signal — proceeding with cap")
        else:
            # Government contracts: full 3/4 neglect screen (original logic)
            if neglect.conditions_passed < 2:
                print(f"[Agent1] Discarding {ticker}: severely non-neglected ({neglect.conditions_passed}/4) — {neglect.notes}")
                continue
            if not neglect.passes:
                print(f"[Agent1] {ticker}: neglect screen 2/4 — will cap at Medium confidence")

        analyst_count = neglect.analyst_count
        coverage_score = _get_coverage_score(analyst_count)

        days_since = _days_since(catalyst_date)
        price_change_pct = _price_change_since_date(ticker, catalyst_date)
        priced_in_threshold = (
            ALREADY_PRICED_IN_PCT_INSIDER
            if catalyst_type == "insider_buying_cluster"
            else ALREADY_PRICED_IN_PCT_CONTRACT
        )
        if price_change_pct is None:
            price_change_pct = 0.0
        elif price_change_pct >= priced_in_threshold:
            print(f"[Agent1] Discarding {ticker}: already up {price_change_pct:.1f}% since catalyst — priced in")
            continue

        if catalyst_type == "government_contract_award" and sam_gov_key and uei and sam_calls_used < SAM_CALL_BUDGET:
            _fetch_sam_entity_detail(uei, sam_gov_key)
            sam_calls_used += 1

        # For insider signals: cluster total must be >= 0.02% of market cap to be material.
        # A CEO buying $380K on a $3.3B company is a token gesture, not conviction.
        if catalyst_type == "insider_buying_cluster" and market_cap_m > 0:
            materiality_floor = market_cap_m * 1e6 * 0.0002  # 0.02% of market cap
            if catalyst_value < materiality_floor:
                print(f"[Agent1] Discarding {ticker}: insider cluster ${catalyst_value:,.0f} "
                      f"too small vs ${market_cap_m:.0f}M market cap (<0.02%)")
                continue

        price = enriched.get("price", 0)

        candidate = CandidateRaw(
            ticker=ticker,
            company_name=enriched.get("company_name", entry["company_name"]),
            catalyst_type=catalyst_type,
            catalyst_date=catalyst_date,
            catalyst_description=description[:300],
            contract_value_usd=catalyst_value,
            ttm_revenue_usd=ttm_revenue_m,
            market_cap_m=market_cap_m,
            avg_daily_dollar_volume=avg_dollar_vol,
            analyst_count=analyst_count,
            price=price,
            price_change_since_catalyst_pct=price_change_pct,
            probationary=probationary,
            liquidity_warning=liquidity_warning,
            missing_data=neglect.missing_data.copy(),
        )

        llm_scores = _llm_bull_analysis(candidate, neglect, budget)

        recency_score = llm_scores.get("recency_vs_lag_score", 2.5)
        if abs(price_change_pct) < PRICE_LAG_THRESHOLD_PCT and days_since <= 14:
            recency_score = min(5.0, recency_score + 0.5)

        if catalyst_type == "insider_buying_cluster":
            # Form 4 filed within 2 business days — very fresh signal
            if days_since <= 5:
                recency_score = min(5.0, recency_score + 0.5)

        narrative_score = llm_scores.get("narrative_inconsistency_score", 2.5)
        asymmetry = _compute_asymmetry_score(recency_score, coverage_score, narrative_score)

        discard = None
        if asymmetry < ASYMMETRY_DISCARD_BELOW:
            discard = f"asymmetry_score {asymmetry:.2f} below discard threshold {ASYMMETRY_DISCARD_BELOW}"

        # Build description: append confirming insider signal note if overlap
        full_description = description[:300]
        if catalyst_type == "government_contract_award" and cluster is not None:
            full_description += f" [CONFIRMING: insider cluster {cluster.unique_insiders} buyers ${cluster.total_usd:,.0f}]"

        result = Agent1Result(
            ticker=ticker,
            company_name=enriched.get("company_name", entry["company_name"]),
            catalyst_type=catalyst_type,
            catalyst_type_prior=_get_catalyst_type_prior(catalyst_type),
            catalyst_date=catalyst_date,
            catalyst_description=full_description,
            contract_award_value_pct_revenue=contract_pct,
            information_asymmetry_score=asymmetry,
            recency_vs_lag_score=recency_score,
            coverage_gap_score=coverage_score,
            narrative_inconsistency_score=narrative_score,
            market_cap_m=market_cap_m,
            probationary=probationary,
            liquidity_warning=liquidity_warning,
            discard_reason=discard,
            bull_narrative=llm_scores.get("bull_narrative", ""),
            missing_data=neglect.missing_data.copy(),
            analyst_count=analyst_count,
            days_since_catalyst=days_since,
            unique_insiders=cluster.unique_insiders if catalyst_type == "insider_buying_cluster" and cluster else 0,
            insider_total_usd=cluster.total_usd if catalyst_type == "insider_buying_cluster" and cluster else 0.0,
            regime_override=elite_only,
        )

        results.append(result)
        candidates_processed += 1

    valid = [r for r in results if r.discard_reason is None]
    discarded = [r for r in results if r.discard_reason is not None]
    print(f"[Agent1] {len(valid)} valid candidates, {len(discarded)} discarded.")
    return valid
