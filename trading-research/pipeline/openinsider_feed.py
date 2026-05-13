"""
OpenInsider feed — primary insider-cluster discovery.

Single HTTP scrape of OpenInsider's aggregated SEC Form 4 feed returns all
qualifying open-market insider purchases across the entire US market. No more
per-ticker EDGAR scanning.

Pipeline:
  1. Fetch ~3 years of qualifying purchases from OpenInsider (cached locally per quarter)
  2. Detect clusters in the recent window: 3+ unique insiders, 30-day span, per ticker
  3. Classify each cluster member as routine vs opportunistic (Cohen-Malloy-Pomorski 2012)
     using the full 3-year scrape
  4. Return detected clusters for yfinance enrichment + reporting

Limitation: OpenInsider filters at source to purchases >= $100K. Routine traders whose
habitual buys are smaller than $100K will not show up and will be mis-classified as
opportunistic. This biases conservatively (the opportunistic soft gate only blocks
pure-routine clusters; mis-classifying a routine trader as opportunistic means the
cluster passes through, which is the safer error direction).
"""

import csv
import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from pipeline.insider_scanner import (
    CLUSTER_WINDOW_DAYS,
    InsiderCluster,
    InsiderTransaction,
    MIN_CLUSTER_INSIDERS,
    MIN_TRANSACTION_USD,
    QUALIFYING_ROLES,
    classify_routine,
)


CACHE_DIR = Path(__file__).parent.parent / "cache" / "openinsider_live"
QUARTER_CHUNK_DAYS = 90

# Cache freshness: most-recent quarter rotates fast (new filings daily), older quarters
# are essentially static once filed.
RECENT_QUARTER_TTL_SECONDS = 3600          # 1 hour for the most recent quarter
OLDER_QUARTER_TTL_SECONDS = 7 * 24 * 3600  # 1 week for older quarters

HEADERS = {
    "User-Agent": "tradefinder-research leoduncan.elearning@gmail.com (live insider screen)",
    "Accept-Encoding": "gzip, deflate",
}

# Entity-indicating keywords. An insider name containing any of these anywhere is
# treated as an institution, not an individual executive.
ENTITY_KEYWORDS = (
    "llc", "l.p.", "l.l.c.", "inc", "corp", "corporation", "ltd", "limited",
    "fund", "trust", "trustee", "bank", "capital", "management", "group",
    "holdings", "ventures", "associates", "partners", "advisors",
    "advisor", "estate", "custodian", "fbo", "u/a", "u/t/a",
)


def _is_entity_name(name: str) -> bool:
    n = name.lower().strip()
    # Strip trailing punctuation that OpenInsider sometimes appends
    n = n.rstrip(" .,;:")
    return any(kw in n for kw in ENTITY_KEYWORDS)


def _is_qualifying_role(title: str) -> bool:
    t = (title or "").lower()
    return any(role in t for role in QUALIFYING_ROLES)


def _to_float(s: str) -> float:
    return float(re.sub(r"[^\d.\-]", "", s) or 0)


def _to_int(s: str) -> int:
    return int(re.sub(r"[^\d\-]", "", s) or 0)


def _fetch_screener_page(start: date, end: date, page: int = 1) -> str:
    """Fetch one page of the OpenInsider screener for a filing-date range."""
    url = "http://openinsider.com/screener"
    params = {
        "s": "", "o": "", "pl": "3", "ph": "", "ll": "", "lh": "",
        "fd": "-1",
        "fdr": f"{start.strftime('%m/%d/%Y')} - {end.strftime('%m/%d/%Y')}",
        "td": "0", "tdr": "", "fdlyl": "", "fdlyh": "", "daysago": "",
        "xp": "1",            # purchases only
        "vl": "100",          # min trade value $100K
        "vh": "", "ocl": "1", "och": "",
        "sicl": "100", "sich": "9999",
        "grp": "0",
        "nfl": "", "nfh": "",
        "nil": "1",           # at least 1 insider — no pre-filter; we'll cluster ourselves
        "nih": "",
        "nol": "1", "noh": "",
        "v2l": "", "v2h": "", "oc2l": "", "oc2h": "",
        "sortcol": "0", "cnt": "1000", "page": str(page),
    }
    resp = requests.get(url, params=params, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    return resp.text


_TICKER_RE = re.compile(r'href="/([A-Z][A-Z0-9.\-]{0,9})"')


def _strip_html(s: str) -> str:
    s = re.sub(r"<a [^>]*?>", "", s)
    s = re.sub(r"<[^<]+?>", "", s)
    return s.strip()


def _parse_table(html: str) -> list[tuple[str, InsiderTransaction]]:
    m = re.search(r'<table[^>]*tinytable[^>]*>(.*?)</table>', html, re.DOTALL)
    if not m:
        return []
    rows = re.findall(r'<tr[^>]*background[^>]*>(.*?)</tr>', m.group(1), re.DOTALL)
    out: list[tuple[str, InsiderTransaction]] = []
    for r in rows:
        cells = re.findall(r'<td[^>]*>(.*?)</td>', r, re.DOTALL)
        if len(cells) < 13:
            continue
        ticker_m = _TICKER_RE.search(cells[3])
        if not ticker_m:
            continue
        ticker = ticker_m.group(1)
        try:
            trade_dt = _strip_html(cells[2])[:10]
            name = _strip_html(cells[5])
            title = _strip_html(cells[6])
            ttype = _strip_html(cells[7])
            price = _to_float(_strip_html(cells[8]))
            qty = _to_int(_strip_html(cells[9]))
            value = _to_float(_strip_html(cells[12]))
            if "Purchase" not in ttype:
                continue
            txn = InsiderTransaction(
                name=name,
                role=title,
                date=trade_dt,
                shares=float(qty),
                price_per_share=price,
                total_usd=value,
                transaction_code="P",
            )
            out.append((ticker, txn))
        except (ValueError, IndexError):
            continue
    return out


def _quarter_cache_path(start: date, end: date) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{start.isoformat()}_{end.isoformat()}.csv"


def _is_cache_fresh(path: Path, is_recent_quarter: bool) -> bool:
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    ttl = RECENT_QUARTER_TTL_SECONDS if is_recent_quarter else OLDER_QUARTER_TTL_SECONDS
    return age < ttl


def _save_chunk_cache(path: Path, rows: list[tuple[str, InsiderTransaction]]) -> None:
    """Persist parsed transactions for one quarter chunk."""
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "name", "role", "date", "shares", "price", "total_usd"])
        for ticker, t in rows:
            w.writerow([ticker, t.name, t.role, t.date, t.shares, t.price_per_share, t.total_usd])


def _load_chunk_cache(path: Path) -> list[tuple[str, InsiderTransaction]]:
    out: list[tuple[str, InsiderTransaction]] = []
    with path.open() as f:
        r = csv.DictReader(f)
        for row in r:
            try:
                out.append((
                    row["ticker"],
                    InsiderTransaction(
                        name=row["name"],
                        role=row["role"],
                        date=row["date"],
                        shares=float(row["shares"] or 0),
                        price_per_share=float(row["price"] or 0),
                        total_usd=float(row["total_usd"] or 0),
                        transaction_code="P",
                    ),
                ))
            except (KeyError, ValueError):
                continue
    return out


def _fetch_chunk(start: date, end: date, is_recent_quarter: bool) -> list[tuple[str, InsiderTransaction]]:
    """Fetch one quarter chunk, paginating, with caching."""
    cache_path = _quarter_cache_path(start, end)
    if _is_cache_fresh(cache_path, is_recent_quarter):
        return _load_chunk_cache(cache_path)

    print(f"  [OpenInsider] Fetching {start} -> {end}", flush=True)
    page = 1
    rows: list[tuple[str, InsiderTransaction]] = []
    while True:
        try:
            html = _fetch_screener_page(start, end, page=page)
        except requests.RequestException as e:
            print(f"  [OpenInsider] Fetch error {start}-{end} p{page}: {e}", flush=True)
            break
        page_rows = _parse_table(html)
        if not page_rows:
            break
        rows.extend(page_rows)
        if len(page_rows) < 1000:
            break
        page += 1
        time.sleep(0.4)
    _save_chunk_cache(cache_path, rows)
    return rows


def fetch_qualifying_transactions(history_days: int = 1100) -> list[tuple[str, InsiderTransaction]]:
    """Scrape OpenInsider for the past `history_days`, parse + role/entity filter.

    Returns a list of (ticker, transaction) tuples. The full history is needed for
    routine-vs-opportunistic classification (Cohen-Malloy-Pomorski 2012 requires
    3 prior years per insider).
    """
    today = date.today()
    start = today - timedelta(days=history_days)

    cursor = start
    all_rows: list[tuple[str, InsiderTransaction]] = []
    while cursor <= today:
        chunk_end = min(cursor + timedelta(days=QUARTER_CHUNK_DAYS), today)
        # Most-recent chunk gets short TTL; everything older is essentially static.
        is_recent = (today - chunk_end).days < QUARTER_CHUNK_DAYS
        chunk_rows = _fetch_chunk(cursor, chunk_end, is_recent_quarter=is_recent)
        all_rows.extend(chunk_rows)
        cursor = chunk_end + timedelta(days=1)

    # Apply role + entity + minimum-value filters.
    qualifying: list[tuple[str, InsiderTransaction]] = []
    for ticker, t in all_rows:
        if t.total_usd < MIN_TRANSACTION_USD:
            continue
        if _is_entity_name(t.name):
            continue
        if not _is_qualifying_role(t.role):
            continue
        qualifying.append((ticker, t))

    print(f"[OpenInsider] {len(all_rows)} raw rows -> {len(qualifying)} qualifying transactions",
          flush=True)
    return qualifying


def detect_clusters(
    transactions: list[tuple[str, InsiderTransaction]],
    recent_window_days: int = 45,
    cluster_span_days: int = CLUSTER_WINDOW_DAYS,
) -> list[InsiderCluster]:
    """Detect insider clusters within the recent window.

    For each ticker with qualifying activity in the last `recent_window_days`, find the
    cluster_span_days window with the most unique insiders. Require >= MIN_CLUSTER_INSIDERS
    unique names. Emit at most ONE cluster per ticker (the best one).
    """
    today = date.today()
    recent_cutoff = (today - timedelta(days=recent_window_days)).isoformat()

    # Group all qualifying transactions by ticker for the recent window
    by_ticker: dict[str, list[InsiderTransaction]] = defaultdict(list)
    for ticker, t in transactions:
        if t.date >= recent_cutoff:
            by_ticker[ticker].append(t)

    clusters: list[InsiderCluster] = []
    for ticker, txns in by_ticker.items():
        txns.sort(key=lambda x: x.date)
        best_window: list[InsiderTransaction] = []
        best_unique: int = 0
        for anchor in txns:
            anchor_dt = datetime.strptime(anchor.date, "%Y-%m-%d")
            window_end_str = (anchor_dt + timedelta(days=cluster_span_days)).strftime("%Y-%m-%d")
            window = [t for t in txns if anchor.date <= t.date <= window_end_str]
            unique = len({t.name for t in window})
            if unique > best_unique:
                best_unique = unique
                best_window = window
            elif unique == best_unique and best_window and window:
                # Tie-break: prefer the most recent end date
                if max(t.date for t in window) > max(t.date for t in best_window):
                    best_window = window
        if best_unique < MIN_CLUSTER_INSIDERS or not best_window:
            continue
        clusters.append(InsiderCluster(
            ticker=ticker,
            transactions=best_window,
            cluster_start=min(t.date for t in best_window),
            cluster_end=max(t.date for t in best_window),
            total_usd=sum(t.total_usd for t in best_window),
            unique_insiders=best_unique,
        ))

    return clusters


def scan(recent_window_days: int = 45, history_days: int = 1100) -> list[InsiderCluster]:
    """Top-level: scrape OpenInsider, detect recent clusters, classify each member.

    Returns a list of qualifying clusters with opportunistic_count and routine_insiders
    populated. Each cluster represents ONE recent buying campaign per ticker.
    """
    all_txns = fetch_qualifying_transactions(history_days=history_days)
    clusters = detect_clusters(
        all_txns,
        recent_window_days=recent_window_days,
        cluster_span_days=CLUSTER_WINDOW_DAYS,
    )

    # Routine/opportunistic classification: per cluster, look back into the full history
    # for each member and apply the CMP same-month-3-consecutive-years rule.
    history_by_ticker: dict[str, list[InsiderTransaction]] = defaultdict(list)
    for ticker, t in all_txns:
        history_by_ticker[ticker].append(t)

    for cluster in clusters:
        members = {t.name for t in cluster.transactions}
        ticker_history = history_by_ticker.get(cluster.ticker, [])
        routine = classify_routine(members, cluster.cluster_end, ticker_history)
        cluster.routine_insiders = sorted(routine)
        cluster.opportunistic_count = len(members - routine)

    print(f"[OpenInsider] {len(clusters)} cluster signals detected in last {recent_window_days}d.",
          flush=True)
    return clusters
