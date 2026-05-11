"""
Universe Builder — maintains a cached list of US small/mid-cap tickers for daily scanning.

Discovery flow (optimised for government contract catalyst):
  1. Weekly: fetch ~250 primary-exchange US small/mid-cap tickers from yfinance screener
     (filtered by market cap $500M-$5B, US region). Cache with company names in SQLite.
     This is FAST — no per-ticker yfinance calls, just screener data.
  2. Daily (in agent1): for each cached ticker, scan USAspending (fast API calls).
     Only run the expensive neglect screen on tickers that have contract hits.
     This reduces neglect screen calls from ~250/run to ~5-10/run.

Sorting descending by market cap: larger small-caps have higher government contracting rates
(~6% hit rate for $500M-$5B vs ~1.6% for $200M-$500M).

yfinance screener is free, no key required.
"""

import time
import yfinance as yf
from yfinance.screener.screener import screen
from yfinance.screener.query import EquityQuery
from datetime import datetime, timedelta

from orchestrator.state_manager import get_conn

WATCHLIST_TTL_DAYS = 7

# Screener: 5 batches × 100 rows → ~250 primary-exchange US tickers
SCREENER_BATCH_SIZE = 100
SCREENER_MAX_BATCHES = 10  # 1000 rows → ~500 primary-exchange US tickers

# Primary US exchanges only — OTC/pink sheet tickers won't have USAspending contracts
PRIMARY_EXCHANGES = {"NYQ", "NMS", "NGM", "NCM", "ASE", "NYS", "NAS", "NASDAQ", "NYSE", "AMEX"}


def _ensure_watchlist_table():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS watchlist (
                ticker TEXT PRIMARY KEY,
                company_name TEXT,
                market_cap_m REAL,
                last_updated TEXT NOT NULL
            );
        """)


def _fetch_one_range(
    mcap_min: int,
    mcap_max: int,
    max_batches: int,
    label: str,
) -> list[tuple[str, str, float]]:
    """Fetch one market cap band from the yfinance screener."""
    q = EquityQuery('and', [
        EquityQuery('gt', ['intradaymarketcap', mcap_min]),
        EquityQuery('lt', ['intradaymarketcap', mcap_max]),
        EquityQuery('eq', ['region', 'us']),
    ])
    results = []
    for batch in range(max_batches):
        offset = batch * SCREENER_BATCH_SIZE
        try:
            result = screen(
                q,
                offset=offset,
                size=SCREENER_BATCH_SIZE,
                sortField='intradaymarketcap',
                sortAsc=False,
            )
            quotes = result.get('quotes', [])
            if not quotes:
                break
            for item in quotes:
                sym = item.get('symbol', '')
                exchange = item.get('exchange', '')
                if not sym or '.' in sym or not sym.isalpha() or len(sym) > 5:
                    continue
                if exchange not in PRIMARY_EXCHANGES:
                    continue
                # Common stock only — filter ETFs, funds, preferred shares, warrants
                if item.get('quoteType', 'EQUITY') != 'EQUITY':
                    continue
                if len(sym) >= 4 and sym[-1] in ('P', 'W', 'R') and sym[:-1].isalpha():
                    continue
                name = item.get('longName') or item.get('shortName') or sym
                mcap = round((item.get('marketCap') or 0) / 1e6, 1)
                results.append((sym, name, mcap))
            total = result.get('total', 0)
            if offset + SCREENER_BATCH_SIZE >= total:
                break
            time.sleep(0.3)
        except Exception as e:
            print(f"[Universe] Screener batch {batch} ({label}) failed: {e}")
            break
    return results


def _fetch_yfinance_tickers(max_batches: int = SCREENER_MAX_BATCHES) -> list[tuple[str, str, float]]:
    """
    Fetch US-listed tickers across two market cap bands.

    $500M–$5B: used for both government contract and insider buying signals.
    $200M–$500M: used for insider buying signals only (government contracts
                  in agent1 skip tickers below $500M). Insider signals are
                  proportionally more meaningful at this size — a $250K buy
                  on a $400M company is 0.06% of market cap (material).

    Two separate screener queries ensure $200M–$500M companies are captured —
    a single descending sort hits the $500M+ companies first and may not
    return enough small-cap results within the batch limit.
    """
    large = _fetch_one_range(500_000_000, 5_000_000_000, max_batches, "$500M-$5B")
    small = _fetch_one_range(200_000_000, 500_000_000, max_batches, "$200M-$500M")
    results = large + small

    # Dedup by ticker, preserve order
    seen = set()
    deduped = []
    for sym, name, mcap in results:
        if sym not in seen:
            seen.add(sym)
            deduped.append((sym, name, mcap))
    return deduped


def _load_cached_watchlist() -> list[dict] | None:
    """Returns cached watchlist if fresher than TTL, else None."""
    _ensure_watchlist_table()
    cutoff = (datetime.utcnow() - timedelta(days=WATCHLIST_TTL_DAYS)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT ticker, company_name, market_cap_m FROM watchlist WHERE last_updated > ?",
            (cutoff,)
        ).fetchall()
    if not rows:
        return None
    return [dict(r) for r in rows]


def _save_watchlist(entries: list[dict]):
    _ensure_watchlist_table()
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute("DELETE FROM watchlist")
        for e in entries:
            conn.execute(
                """INSERT OR REPLACE INTO watchlist
                   (ticker, company_name, market_cap_m, last_updated)
                   VALUES (?, ?, ?, ?)""",
                (e["ticker"], e.get("company_name", ""), e.get("market_cap_m", 0), now)
            )


def build_neglected_universe(force_rebuild: bool = False) -> list[dict]:
    """
    Returns the small/mid-cap ticker universe for daily USAspending scanning.
    Uses SQLite cache (7-day TTL). Set force_rebuild=True to ignore cache.

    NOTE: The neglect screen is NOT run here — it runs in agent1 only for
    tickers that have USAspending contract hits. This reduces neglect screen
    calls from ~250/run to ~5-10/run (huge speedup).

    Each entry: {ticker, company_name, market_cap_m}
    """
    if not force_rebuild:
        cached = _load_cached_watchlist()
        if cached:
            print(f"[Universe] Loaded {len(cached)} tickers from screener cache.")
            return cached

    print("[Universe] Refreshing screener ticker cache (runs once per week)...")

    tickers = _fetch_yfinance_tickers()
    if not tickers:
        print("[Universe] No tickers from screener — check connectivity.")
        return []

    watchlist = [
        {"ticker": sym, "company_name": name, "market_cap_m": mcap}
        for sym, name, mcap in tickers
    ]

    print(f"[Universe] Cached {len(watchlist)} primary-exchange US tickers for scanning.")
    _save_watchlist(watchlist)
    return watchlist
