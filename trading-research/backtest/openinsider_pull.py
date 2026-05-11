"""
OpenInsider historical pull → cluster CSV in our backtest format.

Fetches individual insider transactions from openinsider.com/screener for a
date range, then applies OUR clustering logic (2+ unique qualifying insiders,
14-day window, $100K minimum each, qualifying roles only) so the resulting
cluster set matches the live engine's definition.

Output schema matches backtest/results/backtest_*.csv so the existing outcome
measurement and ablation tooling work unchanged.

Usage:
    python -m backtest.openinsider_pull --start 2018-01-01 --end 2024-12-31
"""

import argparse
import csv
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

OUTPUT_DIR = Path(__file__).parent / "results"
RAW_CACHE = Path(__file__).parent / "cache" / "openinsider_raw"

# Match live engine
MIN_TRANSACTION_USD = 100_000
MIN_CLUSTER_INSIDERS = 2
CLUSTER_WINDOW_DAYS = 14

QUALIFYING_ROLES = {
    "ceo", "chief executive", "cfo", "chief financial", "coo", "chief operating",
    "chairman", "chair", "director", "board member", "president", "evp", "svp",
    "executive vice president", "senior vice president", "10%",
}

ENTITY_SUFFIXES = (
    "llc", "lp", "inc", "corp", "ltd", "fund", "trust", "advisors", "partners",
    "capital", "management", "group", "holdings", "ventures", "associates",
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (research)",
}


@dataclass
class Txn:
    filing_date: str
    trade_date: str
    ticker: str
    company: str
    insider: str
    title: str
    price: float
    qty: int
    value: float


def _is_entity(name: str) -> bool:
    n = name.lower().strip()
    return any(n.endswith(" " + s) or n.endswith(" " + s + ".") for s in ENTITY_SUFFIXES)


def _is_qualifying_role(title: str) -> bool:
    t = title.lower()
    return any(role in t for role in QUALIFYING_ROLES)


def _to_float(s: str) -> float:
    return float(re.sub(r"[^\d.\-]", "", s) or 0)


def _to_int(s: str) -> int:
    return int(re.sub(r"[^\d\-]", "", s) or 0)


def fetch_screener_page(start: date, end: date, page: int = 1) -> str:
    """Fetch one page of the OpenInsider screener for a filing-date range."""
    url = "http://openinsider.com/screener"
    params = {
        "s": "", "o": "", "pl": "3", "ph": "", "ll": "", "lh": "",
        "fd": "-1",
        "fdr": f"{start.strftime('%m/%d/%Y')} - {end.strftime('%m/%d/%Y')}",
        "td": "0", "tdr": "", "fdlyl": "", "fdlyh": "", "daysago": "",
        "xp": "1",                    # purchases only
        "vl": "100",                  # min trade value $100K
        "vh": "", "ocl": "1", "och": "",
        "sicl": "100", "sich": "9999",
        "grp": "0",
        "nfl": "", "nfh": "",
        "nil": "2",                   # min 2 insiders
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
    # First remove HTML tags allowing for embedded JS strings with > in them
    # by stripping known tooltip patterns, then a normal tag strip.
    s = re.sub(r'<a [^>]*?>', '', s)
    s = re.sub(r'<[^<]+?>', '', s)
    return s.strip()


def parse_table(html: str) -> list[Txn]:
    """Parse the main result table into Txn rows."""
    m = re.search(r'<table[^>]*tinytable[^>]*>(.*?)</table>', html, re.DOTALL)
    if not m:
        return []
    rows = re.findall(r'<tr[^>]*background[^>]*>(.*?)</tr>', m.group(1), re.DOTALL)
    out = []
    for r in rows:
        cells = re.findall(r'<td[^>]*>(.*?)</td>', r, re.DOTALL)
        if len(cells) < 13:
            continue

        # Ticker — extract from href to avoid the JS tooltip mess
        ticker_match = _TICKER_RE.search(cells[3])
        if not ticker_match:
            continue
        ticker = ticker_match.group(1)

        try:
            filing_dt = _strip_html(cells[1])[:10]
            trade_dt = _strip_html(cells[2])
            company = _strip_html(cells[4])
            insider = _strip_html(cells[5])
            title = _strip_html(cells[6])
            ttype = _strip_html(cells[7])
            price = _to_float(_strip_html(cells[8]))
            qty = _to_int(_strip_html(cells[9]))
            value = _to_float(_strip_html(cells[12]))
            if "Purchase" not in ttype:
                continue
            out.append(Txn(filing_dt, trade_dt, ticker, company, insider, title, price, qty, value))
        except (ValueError, IndexError):
            continue
    return out


def fetch_all_transactions(start: date, end: date) -> list[Txn]:
    """Iterate filing-date windows + paginate. Cache raw HTML pages."""
    RAW_CACHE.mkdir(parents=True, exist_ok=True)
    txns: list[Txn] = []

    # OpenInsider caps results at ~1000 per query so step through ~3-month chunks
    chunk_days = 90
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=chunk_days), end)
        page = 1
        while True:
            cache_key = f"{cursor}_{chunk_end}_p{page}.html"
            cache_file = RAW_CACHE / cache_key
            if cache_file.exists():
                html = cache_file.read_text()
            else:
                print(f"  [Fetch] {cursor} → {chunk_end}  page {page}")
                html = fetch_screener_page(cursor, chunk_end, page=page)
                cache_file.write_text(html)
                time.sleep(0.4)
            page_txns = parse_table(html)
            if not page_txns:
                break
            txns.extend(page_txns)
            if len(page_txns) < 1000:
                break
            page += 1
        cursor = chunk_end + timedelta(days=1)

    print(f"\n[Pull] {len(txns)} raw purchase transactions")
    return txns


def filter_qualifying(txns: list[Txn]) -> list[Txn]:
    """Apply our role + value + entity filters."""
    out = []
    for t in txns:
        if t.value < MIN_TRANSACTION_USD:
            continue
        if _is_entity(t.insider):
            continue
        if not _is_qualifying_role(t.title):
            continue
        out.append(t)
    return out


@dataclass
class Cluster:
    ticker: str
    company: str
    signal_date: str        # max filing_date in window
    cluster_start: str      # min trade_date in window
    cluster_end: str        # max trade_date in window
    total_usd: float
    unique_insiders: int
    insider_names: str      # for diagnostic


def detect_clusters(txns: list[Txn]) -> list[Cluster]:
    """Apply 14-day cluster logic per ticker."""
    by_ticker: dict[str, list[Txn]] = defaultdict(list)
    for t in txns:
        by_ticker[t.ticker].append(t)

    clusters: list[Cluster] = []
    for ticker, ticker_txns in by_ticker.items():
        ticker_txns.sort(key=lambda x: x.trade_date)
        seen_ends: set[str] = set()
        for anchor in ticker_txns:
            cutoff = (datetime.strptime(anchor.trade_date, "%Y-%m-%d")
                      + timedelta(days=CLUSTER_WINDOW_DAYS)).strftime("%Y-%m-%d")
            window = [t for t in ticker_txns
                      if anchor.trade_date <= t.trade_date <= cutoff]
            unique_names = {t.insider for t in window}
            if len(unique_names) < MIN_CLUSTER_INSIDERS:
                continue
            cluster_end = max(t.trade_date for t in window)
            if cluster_end in seen_ends:
                continue
            seen_ends.add(cluster_end)
            clusters.append(Cluster(
                ticker=ticker,
                company=window[0].company,
                signal_date=max(t.filing_date for t in window),
                cluster_start=min(t.trade_date for t in window),
                cluster_end=cluster_end,
                total_usd=sum(t.value for t in window),
                unique_insiders=len(unique_names),
                insider_names="; ".join(sorted(unique_names))[:400],
            ))
    return clusters


def write_clusters_csv(clusters: list[Cluster], start: date, end: date) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"openinsider_clusters_{start}_{end}.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "company_name", "signal_date", "cluster_start",
                    "cluster_end", "total_usd", "unique_insiders", "insider_names"])
        for c in sorted(clusters, key=lambda x: x.signal_date):
            w.writerow([c.ticker, c.company, c.signal_date, c.cluster_start,
                        c.cluster_end, round(c.total_usd), c.unique_insiders,
                        c.insider_names])
    print(f"\n[Output] {len(clusters)} clusters → {out}")
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    args = p.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    print(f"[OpenInsider] {start} → {end}")
    print(f"[Filter] role-qualifying P-purchase >= ${MIN_TRANSACTION_USD:,}")
    print(f"[Cluster] {MIN_CLUSTER_INSIDERS}+ unique insiders within "
          f"{CLUSTER_WINDOW_DAYS} days")

    raw_txns = fetch_all_transactions(start, end)
    qual = filter_qualifying(raw_txns)
    print(f"[Filter] {len(qual)} qualifying transactions "
          f"(after role/value/entity filters)")

    clusters = detect_clusters(qual)
    print(f"[Cluster] {len(clusters)} clusters detected")

    write_clusters_csv(clusters, start, end)


if __name__ == "__main__":
    main()
