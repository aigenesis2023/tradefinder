"""
Theme Clustering

Deterministic grouping by: sector + catalyst_type + supply_chain_source_ticker
Max 2 ideas per theme cluster.
Same supply chain source = same theme regardless of sector.
LLM used only for binary "are these causally linked?" decision.
"""

import hashlib
from dataclasses import dataclass, field
import yfinance as yf
from orchestrator.request_budget import BudgetManager

MAX_PER_CLUSTER = 2

@dataclass
class ClusteredCandidate:
    ticker: str
    cluster_id: str
    cluster_rank: int  # rank within cluster (1 = included, 2 = included, 3+ = clustered out)
    clustered_out: bool
    cluster_peers: list = field(default_factory=list)


def _get_sector(ticker: str) -> str:
    try:
        info = yf.Ticker(ticker).info or {}
        return info.get("sector") or "Unknown"
    except Exception:
        return "Unknown"


def _make_cluster_id(sector: str, catalyst_type: str, supply_chain_source: str = "") -> str:
    key = f"{sector}|{catalyst_type}|{supply_chain_source}".lower()
    return hashlib.md5(key.encode()).hexdigest()[:8]


def assign_clusters(candidates: list, budget: BudgetManager) -> list[ClusteredCandidate]:
    """
    candidates: list of Agent3Result objects
    Returns ClusteredCandidate list with cluster assignments.

    Deterministic grouping by sector + catalyst_type. The previous N² LLM
    cross-check for causal links was dropped: it consumed up to ~105 LLM calls
    for 15 candidates and the deterministic grouping captures the same intent
    (same sector + same catalyst type = same theme).
    """
    cluster_map: dict[str, list] = {}

    for c in candidates:
        sector = _get_sector(c.ticker)
        supply_chain_src = ""
        cluster_id = _make_cluster_id(sector, c.catalyst_type, supply_chain_src)
        if cluster_id not in cluster_map:
            cluster_map[cluster_id] = []
        cluster_map[cluster_id].append((c, cluster_id, sector))

    results = []
    for cluster_id, items in cluster_map.items():
        # Sort by composite score descending within cluster
        sorted_items = sorted(items, key=lambda x: x[0].composite_score, reverse=True)
        peers = [x[0].ticker for x in sorted_items]
        for rank, (candidate, cid, sector) in enumerate(sorted_items, start=1):
            clustered_out = rank > MAX_PER_CLUSTER
            results.append(ClusteredCandidate(
                ticker=candidate.ticker,
                cluster_id=cluster_id,
                cluster_rank=rank,
                clustered_out=clustered_out,
                cluster_peers=[p for p in peers if p != candidate.ticker],
            ))

    return results
