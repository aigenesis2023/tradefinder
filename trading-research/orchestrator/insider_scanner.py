"""
Insider scanner — shared data types and helpers for insider-cluster detection.

v3.0: primary discovery moved to `orchestrator/openinsider_feed.py` (single HTTP scrape
of OpenInsider's aggregated feed) which is dramatically faster than the prior
per-ticker SEC EDGAR scan. This module now provides only:

  - The InsiderTransaction and InsiderCluster dataclasses
  - The shared filter constants (cluster window, minimum sizes, qualifying roles)
  - The classify_routine() helper implementing Cohen-Malloy-Pomorski (2012, JF)

The CMP routine/opportunistic rule:
  An insider is "routine" if they bought in the same calendar month for
  ROUTINE_PRIOR_YEARS consecutive prior years. Otherwise opportunistic.
  Routine trades have ~0 predictive power; opportunistic trades carry the alpha.
"""

from dataclasses import dataclass, field
from datetime import datetime


# ── Cluster thresholds ────────────────────────────────────────────────────
MIN_TRANSACTION_USD = 100_000   # per-transaction minimum
MIN_CLUSTER_INSIDERS = 3
CLUSTER_WINDOW_DAYS = 30        # v2.1: academic studies use 1-3 month windows

# Cohen-Malloy-Pomorski routine classification
ROUTINE_PRIOR_YEARS = 3

# Qualifying roles — exclude rank-and-file employee purchases. Roles checked
# substring-insensitive against insider title (lower-cased).
QUALIFYING_ROLES = {
    "ceo", "chief executive", "chief executive officer",
    "cfo", "chief financial", "chief financial officer",
    "coo", "chief operating", "chief operating officer",
    "chairman", "chair",
    "director", "board member",
    "president",
    "evp", "svp", "executive vice president", "senior vice president",
}


@dataclass
class InsiderTransaction:
    name: str
    role: str
    date: str              # YYYY-MM-DD
    shares: float
    price_per_share: float
    total_usd: float
    transaction_code: str  # "P" = open-market purchase


@dataclass
class InsiderCluster:
    ticker: str
    detected: bool
    transactions: list[InsiderTransaction] = field(default_factory=list)
    cluster_start: str = ""
    cluster_end: str = ""
    total_usd: float = 0.0
    unique_insiders: int = 0
    opportunistic_count: int = 0
    routine_insiders: list = field(default_factory=list)
    notes: str = ""

    @property
    def days_since_last_buy(self) -> int:
        if not self.cluster_end:
            return 999
        try:
            dt = datetime.strptime(self.cluster_end, "%Y-%m-%d")
            return (datetime.utcnow() - dt).days
        except ValueError:
            return 999


def classify_routine(
    cluster_members: set[str],
    cluster_end_date: str,
    full_history: list[InsiderTransaction],
) -> set[str]:
    """
    Classify each cluster member as routine vs opportunistic per Cohen-Malloy-Pomorski
    (2012, *Journal of Finance*).

    An insider is "routine" if they have a buy on the SAME calendar month in EACH of
    the past ROUTINE_PRIOR_YEARS years (default: 3). Routine trades carry ~0 predictive
    power; opportunistic trades drive the alpha.

    Returns the SET of names classified as routine. Members not in the set are
    opportunistic (the desirable class). Empty history → all members opportunistic by
    default (an insider with no prior history cannot be routine).
    """
    try:
        end_dt = datetime.strptime(cluster_end_date, "%Y-%m-%d")
    except ValueError:
        return set()

    signal_month = end_dt.month
    signal_year = end_dt.year

    routine: set[str] = set()
    for name in cluster_members:
        prior_buys = [
            t for t in full_history
            if t.name == name and t.date < cluster_end_date
        ]
        months_hit = 0
        for years_back in range(1, ROUTINE_PRIOR_YEARS + 1):
            target_year = signal_year - years_back
            for t in prior_buys:
                try:
                    t_dt = datetime.strptime(t.date, "%Y-%m-%d")
                except ValueError:
                    continue
                if t_dt.year == target_year and t_dt.month == signal_month:
                    months_hit += 1
                    break
        if months_hit >= ROUTINE_PRIOR_YEARS:
            routine.add(name)

    return routine
