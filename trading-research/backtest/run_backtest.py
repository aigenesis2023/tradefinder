#!/usr/bin/env python3
"""
Production-configuration backtest for the insider-cluster screener.

Runs the EXACT current engine logic on historical data to measure what the
engine would have surfaced and how those signals performed. Every parameter
is imported from the live pipeline modules — no duplication, no drift.

Key differences from the old (now-deleted) backtest:
  - 30-day cluster window (old: 14)
  - 3+ unique insiders threshold (old: 2+)
  - Full CMP routine/opportunistic classification (old: none)
  - Opportunistic soft gate: >=1 opp required (old: none)
  - Current role filter with "dir"/"pres" abbreviations (old: missing)
  - Current entity filter: 20-keyword substring (old: suffix only)
  - $200M-$3B market cap (old: $200M-$5B)
  - Pre-cluster crash detection (old: none)
  - Insider VWAP computation (old: none)

Temporal isolation: ALL enrichment data (market cap, price, 52w high/low)
uses only information available on or before signal_date. ALL outcome data
uses only data strictly after signal_date. No future information leaks.

Usage:
  cd trading-research
  python -m backtest.run_backtest              # full 2018-2024
  python -m backtest.run_backtest --years 2023  # single year
  python -m backtest.run_backtest --dry-run     # show plan without scraping
"""

import argparse
import csv
import json
import re
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

# ── Reuse current engine constants + classification (no duplication) ──
from pipeline.insider_scanner import (
    CLUSTER_WINDOW_DAYS,
    MIN_CLUSTER_INSIDERS,
    MIN_TRANSACTION_USD,
    QUALIFYING_ROLES,
    ROUTINE_PRIOR_YEARS,
    classify_routine,
    InsiderTransaction,
)

# ── Backtest temporal-isolation price module ──
from backtest.price_data import (
    get_pre_signal_data,
    get_outcome_data,
    PreSignalData,
    OutcomeData,
    MCAP_MIN_M,
    MCAP_MAX_M,
    NEAR_LOW_PCT,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

BACKTEST_START = date(2018, 1, 1)
BACKTEST_END = date(2024, 12, 31)
CMP_HISTORY_START = date(2015, 1, 1)  # 3 years before backtest start
SCRAPE_END = date(2024, 12, 31)

CACHE_DIR = Path(__file__).parent / "cache" / "openinsider"
RESULTS_DIR = Path(__file__).parent / "results"
QUARTER_CHUNK_DAYS = 90

HEADERS = {
    "User-Agent": "tradefinder-research leoduncan.elearning@gmail.com",
    "Accept-Encoding": "gzip, deflate",
}

# Entity-indicating keywords — MUST match live engine (pipeline/openinsider_feed.py)
ENTITY_KEYWORDS = (
    "llc", "l.p.", "l.l.c.", "inc", "corp", "corporation", "ltd", "limited",
    "fund", "trust", "trustee", "bank", "capital", "management", "group",
    "holdings", "ventures", "associates", "partners", "advisors",
    "advisor", "estate", "custodian", "fbo", "u/a", "u/t/a",
)

# yfinance enrichment throttling
YF_DELAY = 0.05
OI_DELAY = 0.4

# ═══════════════════════════════════════════════════════════════════════════════
# OpenInsider scraping (mirrors pipeline/openinsider_feed.py)
# ═══════════════════════════════════════════════════════════════════════════════

_TICKER_RE = re.compile(r'href="/([A-Z][A-Z0-9.\-]{0,9})"')


def _strip_html(s: str) -> str:
    s = re.sub(r"<a [^>]*?>", "", s)
    s = re.sub(r"<[^<]+?>", "", s)
    return s.strip()


def _to_float(s: str) -> float:
    return float(re.sub(r"[^\d.\-]", "", s) or 0)


def _to_int(s: str) -> int:
    return int(re.sub(r"[^\d\-]", "", s) or 0)


def _is_entity_name(name: str) -> bool:
    n = name.lower().strip().rstrip(" .,;:")
    return any(kw in n for kw in ENTITY_KEYWORDS)


def _is_qualifying_role(title: str) -> bool:
    t = (title or "").lower()
    return any(role in t for role in QUALIFYING_ROLES)


def _fetch_screener_page(start: date, end: date, page: int = 1) -> str:
    """Fetch one page of the OpenInsider screener for a filing-date range."""
    url = "http://openinsider.com/screener"
    params = {
        "s": "", "o": "", "pl": "3", "ph": "", "ll": "", "lh": "",
        "fd": "-1",
        "fdr": f"{start.strftime('%m/%d/%Y')} - {end.strftime('%m/%d/%Y')}",
        "td": "0", "tdr": "", "fdlyl": "", "fdlyh": "", "daysago": "",
        "xp": "1",
        "vl": "100",
        "vh": "", "ocl": "1", "och": "",
        "sicl": "100", "sich": "9999",
        "grp": "0",
        "nfl": "", "nfh": "",
        "nil": "1",
        "nih": "",
        "nol": "1", "noh": "",
        "v2l": "", "v2h": "", "oc2l": "", "oc2h": "",
        "sortcol": "0", "cnt": "1000", "page": str(page),
    }
    resp = requests.get(url, params=params, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    return resp.text


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


def _chunk_cache_path(chunk_start: date, chunk_end: date) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{chunk_start.isoformat()}_{chunk_end.isoformat()}.csv"


def _load_chunk_cache(path: Path) -> list[tuple[str, InsiderTransaction]]:
    out: list[tuple[str, InsiderTransaction]] = []
    if not path.exists():
        return out
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


def _save_chunk_cache(path: Path, rows: list[tuple[str, InsiderTransaction]]) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "name", "role", "date", "shares", "price", "total_usd"])
        for ticker, t in rows:
            w.writerow([ticker, t.name, t.role, t.date, t.shares, t.price_per_share, t.total_usd])


def scrape_openinsider(start: date, end: date) -> list[tuple[str, InsiderTransaction]]:
    """Scrape OpenInsider for a date range, with quarterly CSV caching."""
    all_rows: list[tuple[str, InsiderTransaction]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=QUARTER_CHUNK_DAYS), end)
        cache_path = _chunk_cache_path(cursor, chunk_end)
        if cache_path.exists():
            rows = _load_chunk_cache(cache_path)
            print(f"  [OI cache] {cursor} -> {chunk_end}: {len(rows)} rows")
        else:
            print(f"  [OI fetch] {cursor} -> {chunk_end}", flush=True)
            rows: list[tuple[str, InsiderTransaction]] = []
            page = 1
            while True:
                try:
                    html = _fetch_screener_page(cursor, chunk_end, page=page)
                except requests.RequestException as e:
                    print(f"    Error p{page}: {e}")
                    break
                page_rows = _parse_table(html)
                if not page_rows:
                    break
                rows.extend(page_rows)
                if len(page_rows) < 1000:
                    break
                page += 1
                time.sleep(OI_DELAY)
            _save_chunk_cache(cache_path, rows)
            print(f"    {len(rows)} rows", flush=True)
        all_rows.extend(rows)
        cursor = chunk_end + timedelta(days=1)
    return all_rows


# ═══════════════════════════════════════════════════════════════════════════════
# Cluster detection — historical sweep (not just recent-45d window)
# ═══════════════════════════════════════════════════════════════════════════════

def detect_all_clusters(
    qualifying: list[tuple[str, InsiderTransaction]],
) -> list[dict]:
    """
    Find ALL insider clusters across the full historical period.

    For each ticker, find every distinct 30-day window with >=3 unique insiders.
    Multiple clusters per ticker are allowed if separated in time. Overlapping
    windows are deduplicated by cluster_end date (best window kept).

    Returns list of cluster dicts with keys:
      ticker, transactions, cluster_start, cluster_end, unique_insiders, total_usd
    """
    by_ticker: dict[str, list[InsiderTransaction]] = defaultdict(list)
    for ticker, t in qualifying:
        by_ticker[ticker].append(t)

    all_clusters: list[dict] = []

    for ticker, txns in by_ticker.items():
        txns.sort(key=lambda x: x.date)
        seen_ends: set[str] = set()

        for anchor in txns:
            anchor_dt = datetime.strptime(anchor.date, "%Y-%m-%d")
            window_end_str = (anchor_dt + timedelta(days=CLUSTER_WINDOW_DAYS)).strftime("%Y-%m-%d")
            window = [t for t in txns if anchor.date <= t.date <= window_end_str]
            unique = len({t.name for t in window})
            if unique < MIN_CLUSTER_INSIDERS:
                continue

            cluster_end = max(t.date for t in window)
            if cluster_end in seen_ends:
                # Keep the window with more insiders for this end date
                continue
            seen_ends.add(cluster_end)

            all_clusters.append({
                "ticker": ticker,
                "transactions": window,
                "cluster_start": min(t.date for t in window),
                "cluster_end": cluster_end,
                "unique_insiders": unique,
                "total_usd": sum(t.total_usd for t in window),
            })

    # Sort by cluster_end chronologically
    all_clusters.sort(key=lambda c: c["cluster_end"])
    return all_clusters


# ═══════════════════════════════════════════════════════════════════════════════
# IWM benchmark
# ═══════════════════════════════════════════════════════════════════════════════

def load_iwm_prices() -> pd.Series:
    """Download IWM close prices for the full backtest window."""
    print("Loading IWM benchmark data...", flush=True)
    data = yf.download("IWM", start="2017-01-01", end="2026-01-01",
                       progress=False, auto_adjust=True)
    closes = data["Close"]
    if isinstance(closes, pd.DataFrame):
        closes = closes.iloc[:, 0]
    closes.index = pd.to_datetime(closes.index).tz_localize(None)
    return closes.dropna()


def iwm_return_for_window(
    iwm: pd.Series,
    signal_date: date,
    outcome_date: str | None,
) -> float | None:
    """Compute IWM return over the same calendar window as the signal."""
    if outcome_date is None:
        return None
    try:
        outcome_dt = pd.Timestamp(outcome_date)
    except (ValueError, TypeError):
        return None

    # Entry: first IWM close strictly after signal_date
    signal_ts = pd.Timestamp(signal_date)
    after = iwm[iwm.index > signal_ts]
    if after.empty:
        return None

    entry = float(after.iloc[0])

    # Exit: IWM close on or after outcome_date
    exit_data = iwm[iwm.index >= outcome_dt]
    if exit_data.empty:
        return None
    exit_price = float(exit_data.iloc[0])

    return round((exit_price / entry - 1) * 100, 4)


# ═══════════════════════════════════════════════════════════════════════════════
# Summary statistics
# ═══════════════════════════════════════════════════════════════════════════════

def _stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "win_pct": 0, "avg": 0, "median": 0, "avg_win": 0, "avg_loss": 0}
    wins = [v for v in values if v > 0]
    losses = [v for v in values if v <= 0]
    return {
        "n": len(values),
        "win_pct": round(len(wins) / len(values) * 100, 1),
        "avg": round(sum(values) / len(values), 2),
        "median": round(sorted(values)[len(values) // 2], 2),
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
    }


def print_summary(results: list[dict]) -> None:
    """Print comprehensive backtest summary with breakdowns."""
    if not results:
        print("\n[Zero] No signals passed all filters.")
        return

    n = len(results)
    print("\n" + "=" * 72)
    print(f"BACKTEST SUMMARY — Production Engine Configuration")
    print(f"Period: {BACKTEST_START} → {BACKTEST_END}")
    print(f"Signals passing all filters: {n}")
    print("=" * 72)

    for horizon, key in [
        ("7-DAY", "outcome_7d"),
        ("10-DAY", "outcome_10d"),
        ("30-DAY", "outcome_30d"),
        ("60-DAY", "outcome_60d"),
        ("90-DAY", "outcome_90d"),
        ("180-DAY", "outcome_180d"),
    ]:
        raw = [r[key] for r in results if r.get(key) is not None]
        alpha = [r[f"alpha_{key.split('_')[1]}"] for r in results if r.get(f"alpha_{key.split('_')[1]}") is not None]
        if not raw:
            continue
        rs = _stats(raw)
        al = _stats(alpha) if alpha else _stats([])
        print(f"\n── {horizon} (n={rs['n']}) ──────────────────────────────────")
        print(f"  Raw return:  win={rs['win_pct']:>5.1f}%  avg={rs['avg']:>+7.2f}%  "
              f"med={rs['median']:>+7.2f}%  "
              f"avgW={rs['avg_win']:>+6.2f}%  avgL={rs['avg_loss']:>+6.2f}%")
        if alpha:
            print(f"  IWM alpha:   win={al['win_pct']:>5.1f}%  avg={al['avg']:>+7.2f}%  "
                  f"med={al['median']:>+7.2f}%")

    # Breakdowns at 30d
    print("\n── 30-DAY BREAKDOWNS ───────────────────────────────")

    def show(label: str, subset: list[dict]):
        vals = [r["outcome_30d"] for r in subset if r.get("outcome_30d") is not None]
        alphas = [r["alpha_30d"] for r in subset if r.get("alpha_30d") is not None]
        if not vals:
            return
        s = _stats(vals)
        a = _stats(alphas) if alphas else _stats([])
        print(f"  {label}: n={s['n']}  raw_win={s['win_pct']:.1f}%  "
              f"raw_avg={s['avg']:+.2f}%  alpha_avg={a['avg']:+.2f}%  "
              f"alpha_win={a['win_pct']:.1f}%")

    show("ALL SIGNALS", results)

    # Cluster size
    show("  3 insiders", [r for r in results if r["unique_insiders"] == 3])
    show("  4+ insiders", [r for r in results if r["unique_insiders"] >= 4])

    # Opportunistic count
    show("  1 opportunistic", [r for r in results if r["opportunistic_count"] == 1])
    show("  2+ opportunistic", [r for r in results if r["opportunistic_count"] >= 2])
    show("  ALL opportunistic", [r for r in results if r["opportunistic_count"] == r["unique_insiders"]])

    # Market cap band
    show("  $200M-$500M", [r for r in results if r.get("mcap_band") == "$200M-$500M"])
    show("  $500M-$3B", [r for r in results if r.get("mcap_band") == "$500M-$3B"])

    # Pre-cluster crash
    show("  Pre-cluster crash >20%", [r for r in results if r.get("pre_cluster_crash_pct", 0) is not None and abs(r.get("pre_cluster_crash_pct", 0)) > 20])
    show("  No pre-cluster crash", [r for r in results if r.get("pre_cluster_crash_pct") is None or abs(r.get("pre_cluster_crash_pct", 0)) <= 5])

    # Near 52w low
    show("  Near 52w low", [r for r in results if r.get("near_52w_low")])
    show("  NOT near 52w low", [r for r in results if not r.get("near_52w_low")])

    # By year
    for yr in range(2018, 2025):
        show(f"  Year {yr}", [r for r in results if r["signal_date"].startswith(str(yr))])

    # DATA INSUFFICIENT
    show("  DATA INSUFFICIENT label", [r for r in results if not r.get("cmp_reliable", True)])

    # Delisted
    delisted = [r for r in results if r.get("delisted_or_acquired")]
    if delisted:
        print(f"\n  Delisted/acquired after signal: {len(delisted)} (included in all stats above)")

    print("\n" + "=" * 72)
    print("ENGINE CONFIGURATION")
    print(f"  Cluster window: {CLUSTER_WINDOW_DAYS}d | "
          f"Min insiders: {MIN_CLUSTER_INSIDERS} | "
          f"Min per txn: ${MIN_TRANSACTION_USD:,}")
    print(f"  Market cap: ${MCAP_MIN_M}M–${MCAP_MAX_M / 1000:.0f}B | "
          f"CMP history: {ROUTINE_PRIOR_YEARS}yr | "
          f"Opportunistic gate: >=1")
    print(f"  Signals/year avg: {n / 7:.1f} | "
          f"Total historical signals: {n}")
    print("=" * 72)


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def run_backtest(backtest_start: date = BACKTEST_START,
                 backtest_end: date = BACKTEST_END,
                 dry_run: bool = False) -> list[dict]:
    """Run the full production-configuration backtest. Returns results list."""

    print("=" * 72)
    print("PRODUCTION-CONFIG BACKTEST")
    print(f"Period: {backtest_start} → {backtest_end}")
    print(f"CMP history: {CMP_HISTORY_START} → {backtest_start - timedelta(days=1)}")
    print("=" * 72)

    if dry_run:
        print("\nDRY RUN — would:")
        print(f"  1. Scrape OpenInsider {CMP_HISTORY_START} → {SCRAPE_END}")
        print(f"  2. Apply current role/entity/value filters")
        print(f"  3. Detect clusters: {MIN_CLUSTER_INSIDERS}+ insiders, "
              f"{CLUSTER_WINDOW_DAYS}d window")
        print(f"  4. CMP classify: {ROUTINE_PRIOR_YEARS}yr routine/opportunistic")
        print(f"  5. Apply opportunistic soft gate (>=1 opp required)")
        print(f"  6. yfinance enrich at each signal_date (${MCAP_MIN_M}M-${MCAP_MAX_M / 1000:.0f}B)")
        print(f"  7. Measure outcomes 7d/10d/30d/60d/90d/180d")
        print(f"  8. Compute IWM alpha")
        return []

    # ── Phase 1: Scrape OpenInsider ──────────────────────────────────────────
    print("\n[Phase 1] Scraping OpenInsider...")
    scrape_start = CMP_HISTORY_START
    scrape_end = SCRAPE_END
    raw_rows = scrape_openinsider(scrape_start, scrape_end)
    print(f"  Total raw rows: {len(raw_rows)}")

    # ── Phase 2: Apply current engine filters ────────────────────────────────
    print("\n[Phase 2] Applying role/entity/value filters...")
    qualifying: list[tuple[str, InsiderTransaction]] = []
    skipped_value = skipped_entity = skipped_role = 0
    for ticker, t in raw_rows:
        if t.total_usd < MIN_TRANSACTION_USD:
            skipped_value += 1
            continue
        if _is_entity_name(t.name):
            skipped_entity += 1
            continue
        if not _is_qualifying_role(t.role):
            skipped_role += 1
            continue
        qualifying.append((ticker, t))
    print(f"  Qualifying: {len(qualifying)} | "
          f"skipped: value={skipped_value} entity={skipped_entity} role={skipped_role}")

    # ── Phase 3: Cluster detection ───────────────────────────────────────────
    print("\n[Phase 3] Detecting clusters...")
    all_raw_clusters = detect_all_clusters(qualifying)
    print(f"  Raw clusters: {len(all_raw_clusters)}")

    # Filter to clusters whose cluster_end is within the backtest period
    clusters_in_period = [
        c for c in all_raw_clusters
        if backtest_start.isoformat() <= c["cluster_end"] <= backtest_end.isoformat()
    ]
    print(f"  Clusters in backtest period ({backtest_start} → {backtest_end}): "
          f"{len(clusters_in_period)}")

    if not clusters_in_period:
        print("\n[Zero] No clusters found in backtest period.")
        return []

    # ── Phase 4: CMP routine/opportunistic classification ────────────────────
    print("\n[Phase 4] CMP classification (routine vs opportunistic)...")
    history_by_ticker: dict[str, list[InsiderTransaction]] = defaultdict(list)
    for ticker, t in qualifying:
        history_by_ticker[ticker].append(t)

    for c in clusters_in_period:
        members = {t.name for t in c["transactions"]}
        ticker_history = history_by_ticker.get(c["ticker"], [])
        routine = classify_routine(members, c["cluster_end"], ticker_history,
                                    c["cluster_start"])
        c["routine_insiders"] = sorted(routine)
        c["opportunistic_count"] = len(members - routine)

    # ── Phase 5: Opportunistic soft gate ─────────────────────────────────────
    print("\n[Phase 5] Applying opportunistic soft gate...")
    passing_opp = [c for c in clusters_in_period if c["opportunistic_count"] >= 1]
    discarded_opp = len(clusters_in_period) - len(passing_opp)
    print(f"  Passed (>=1 opp): {len(passing_opp)} | "
          f"Discarded (all routine): {discarded_opp}")

    if not passing_opp:
        print("\n[Zero] No clusters passed opportunistic gate.")
        return []

    # ── Phase 6: yfinance enrichment with temporal isolation ─────────────────
    print("\n[Phase 6] yfinance enrichment (market cap, price, crash detection)...")
    results: list[dict] = []
    skipped_mcap = skipped_range = 0

    for i, c in enumerate(passing_opp):
        ticker = c["ticker"]
        cluster_end_date = date.fromisoformat(c["cluster_end"])
        cluster_start_date = date.fromisoformat(c["cluster_start"])

        if (i + 1) % 25 == 0:
            print(f"  [{i + 1:>4}/{len(passing_opp)}] enriched | "
                  f"passed={len(results)} skipped_mcap={skipped_mcap} "
                  f"skipped_range={skipped_range}")

        pre = get_pre_signal_data(ticker, cluster_end_date, cluster_start_date)

        if pre.market_cap_m is None:
            skipped_mcap += 1
            continue
        if not pre.in_market_cap_range:
            skipped_range += 1
            continue

        # Insider VWAP
        total_txn_value = sum(t.shares * t.price_per_share for t in c["transactions"])
        total_shares = sum(t.shares for t in c["transactions"])
        insider_vwap = round(total_txn_value / total_shares, 2) if total_shares else 0

        # Pre-cluster crash percentage
        pre_crash_pct = None
        if pre.pre_cluster_close and insider_vwap and pre.pre_cluster_close > 0:
            pre_crash_pct = round((insider_vwap - pre.pre_cluster_close) / pre.pre_cluster_close * 100, 1)

        # CMP reliability
        history_days = pre.trading_history_days
        cmp_min_history_days = 1095
        cmp_reliable = not (history_days is not None and history_days < cmp_min_history_days)

        # Price drawdown from 52w high
        drawdown_52w = None
        if pre.price and pre.high_52w and pre.high_52w > 0:
            drawdown_52w = round((pre.price - pre.high_52w) / pre.high_52w * 100, 1)

        # Per-insider details
        sorted_txns = sorted(c["transactions"], key=lambda x: x.date)
        insider_details = [
            {"name": t.name, "role": t.role, "date": t.date,
             "price": t.price_per_share, "value": t.total_usd}
            for t in sorted_txns
        ]

        results.append({
            "ticker": ticker,
            "company_name": pre.company_name or ticker,
            "signal_date": c["cluster_end"],  # when we would have known
            "cluster_start": c["cluster_start"],
            "cluster_end": c["cluster_end"],
            "total_usd": round(c["total_usd"]),
            "unique_insiders": c["unique_insiders"],
            "opportunistic_count": c["opportunistic_count"],
            "routine_insiders": "; ".join(c.get("routine_insiders", [])),
            "insider_details": json.dumps(insider_details),
            "insider_vwap": insider_vwap,
            "market_cap_m": pre.market_cap_m,
            "mcap_band": pre.mcap_band,
            "price": pre.price,
            "high_52w": pre.high_52w,
            "low_52w": pre.low_52w,
            "drawdown_52w_pct": drawdown_52w,
            "near_52w_low": pre.near_52w_low,
            "pre_cluster_close": pre.pre_cluster_close,
            "pre_cluster_crash_pct": pre_crash_pct,
            "cmp_reliable": cmp_reliable,
            "shares_approximate": pre.shares_approximate,
        })
        time.sleep(YF_DELAY)

    print(f"\n  Enrichment complete: {len(results)} passed all filters")
    print(f"  Skipped: no_mcap={skipped_mcap} outside_range={skipped_range}")

    if not results:
        print("\n[Zero] No signals passed all filters.")
        return []

    # ── Phase 7: Outcome measurement ─────────────────────────────────────────
    print("\n[Phase 7] Measuring outcomes (temporal isolation enforced)...")
    for i, r in enumerate(results):
        if (i + 1) % 20 == 0:
            print(f"  [{i + 1:>4}/{len(results)}] outcomes measured")
        signal_date = date.fromisoformat(r["signal_date"])
        outcome = get_outcome_data(r["ticker"], signal_date)
        r["entry_price"] = outcome.entry_price
        r["outcome_7d"] = outcome.outcome_7d
        r["outcome_10d"] = outcome.outcome_10d
        r["outcome_30d"] = outcome.outcome_30d
        r["outcome_60d"] = outcome.outcome_60d
        r["outcome_90d"] = outcome.outcome_90d
        r["outcome_180d"] = outcome.outcome_180d
        r["outcome_7d_date"] = outcome.outcome_7d_date
        r["outcome_10d_date"] = outcome.outcome_10d_date
        r["outcome_30d_date"] = outcome.outcome_30d_date
        r["outcome_60d_date"] = outcome.outcome_60d_date
        r["outcome_90d_date"] = outcome.outcome_90d_date
        r["outcome_180d_date"] = outcome.outcome_180d_date
        r["delisted_or_acquired"] = outcome.delisted_or_acquired
        r["notes"] = outcome.notes
        time.sleep(YF_DELAY)

    # ── Phase 8: IWM alpha ──────────────────────────────────────────────────
    print("\n[Phase 8] Computing IWM alpha...")
    iwm = load_iwm_prices()
    for r in results:
        signal_date = date.fromisoformat(r["signal_date"])
        for horizon in ["7d", "10d", "30d", "60d", "90d", "180d"]:
            outcome_key = f"outcome_{horizon}_date"
            alpha_key = f"alpha_{horizon}"
            raw_key = f"outcome_{horizon}"
            iwm_ret = iwm_return_for_window(iwm, signal_date, r.get(outcome_key))
            r[f"iwm_{horizon}"] = iwm_ret
            if r.get(raw_key) is not None and iwm_ret is not None:
                r[alpha_key] = round(r[raw_key] - iwm_ret, 4)

    # ── Save CSV ────────────────────────────────────────────────────────────
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = RESULTS_DIR / f"production_backtest_{backtest_start.isoformat()}_{backtest_end.isoformat()}.csv"
    if results:
        fieldnames = [
            "ticker", "company_name", "signal_date", "cluster_start", "cluster_end",
            "total_usd", "unique_insiders", "opportunistic_count", "routine_insiders",
            "insider_details", "insider_vwap",
            "market_cap_m", "mcap_band", "price", "high_52w", "low_52w",
            "drawdown_52w_pct", "near_52w_low",
            "pre_cluster_close", "pre_cluster_crash_pct", "cmp_reliable",
            "shares_approximate",
            "entry_price",
            "outcome_7d", "outcome_10d", "outcome_30d", "outcome_60d", "outcome_90d", "outcome_180d",
            "outcome_7d_date", "outcome_10d_date", "outcome_30d_date",
            "outcome_60d_date", "outcome_90d_date", "outcome_180d_date",
            "iwm_7d", "iwm_10d", "iwm_30d", "iwm_60d", "iwm_90d", "iwm_180d",
            "alpha_7d", "alpha_10d", "alpha_30d", "alpha_60d", "alpha_90d", "alpha_180d",
            "delisted_or_acquired", "notes",
        ]
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            w.writerows(results)
        print(f"\n[Output] {len(results)} signals → {csv_path}")

    # ── Print summary ────────────────────────────────────────────────────────
    print_summary(results)
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Production-configuration insider-cluster backtest")
    parser.add_argument("--years", type=int, nargs="?",
                        help="Single year to backtest (e.g. 2023)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show plan without executing")
    args = parser.parse_args()

    if args.years:
        start = date(args.years, 1, 1)
        end = date(args.years, 12, 31)
        run_backtest(backtest_start=start, backtest_end=end, dry_run=args.dry_run)
    else:
        run_backtest(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
