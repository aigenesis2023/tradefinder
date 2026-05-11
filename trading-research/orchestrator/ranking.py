"""
Ranking — final ordering and report cap enforcement.

Rules (all Python):
  - Sort by composite_score descending
  - Max 5 ideas in final report (High Conviction pool)
  - Max 2 per theme cluster (enforced in theme_cluster.py, respected here)
  - Up to 3 separate "High Upside" picks: composite 3.0-3.5 with strong asymmetric markers
  - Excluded candidates noted in report with scores
"""

from dataclasses import dataclass, field
from typing import Optional
from agents.agent3_synthesis import Agent3Result, COMPOSITE_MIN, HIGH_UPSIDE_SCORE_MIN
from orchestrator.theme_cluster import ClusteredCandidate

MAX_REPORT_IDEAS = 5
MAX_HIGH_UPSIDE_IDEAS = 3


@dataclass
class RankedIdea:
    rank: int
    agent3: Agent3Result
    agent4: Optional[object]
    cluster_id: str
    cluster_rank: int
    cluster_peers: list


@dataclass
class RankingResult:
    included: list[RankedIdea]
    high_upside: list[RankedIdea]
    clustered_out: list
    below_threshold: list
    total_evaluated: int


def rank_ideas(
    agent3_results: list[Agent3Result],
    agent4_results: dict,  # ticker -> Agent4Result
    cluster_assignments: list[ClusteredCandidate],
) -> RankingResult:

    cluster_map = {c.ticker: c for c in cluster_assignments}
    clustered_out = []
    survivors = []

    for r in agent3_results:
        cluster = cluster_map.get(r.ticker)
        if cluster and cluster.clustered_out:
            clustered_out.append(r)
            continue
        survivors.append(r)

    # Partition: High Conviction pool clears the standard composite floor.
    # High Upside pool: composite below the floor but with strong asymmetric markers.
    high_conv_raw = [r for r in survivors if r.composite_score >= COMPOSITE_MIN]
    high_upside_raw = [
        r for r in survivors
        if r.composite_score < COMPOSITE_MIN and r.high_upside_score >= HIGH_UPSIDE_SCORE_MIN
    ]

    high_conv_raw.sort(key=lambda r: r.composite_score, reverse=True)
    # Order upside picks by upside score first, then composite
    high_upside_raw.sort(key=lambda r: (r.high_upside_score, r.composite_score), reverse=True)

    final_hc = high_conv_raw[:MAX_REPORT_IDEAS]
    final_hu = high_upside_raw[:MAX_HIGH_UPSIDE_IDEAS]
    below_threshold = high_conv_raw[MAX_REPORT_IDEAS:] + high_upside_raw[MAX_HIGH_UPSIDE_IDEAS:]

    def _wrap(results: list[Agent3Result]) -> list[RankedIdea]:
        out = []
        for i, r in enumerate(results, start=1):
            cluster = cluster_map.get(r.ticker)
            out.append(RankedIdea(
                rank=i,
                agent3=r,
                agent4=agent4_results.get(r.ticker),
                cluster_id=cluster.cluster_id if cluster else "",
                cluster_rank=cluster.cluster_rank if cluster else 1,
                cluster_peers=cluster.cluster_peers if cluster else [],
            ))
        return out

    return RankingResult(
        included=_wrap(final_hc),
        high_upside=_wrap(final_hu),
        clustered_out=clustered_out,
        below_threshold=below_threshold,
        total_evaluated=len(agent3_results),
    )
