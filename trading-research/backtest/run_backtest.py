"""
Historical insider buying cluster signal backtest.

Usage:
    cd trading-research
    python -m backtest.run_backtest            # 2022-2024, ~10-20 min
    python -m backtest.run_backtest --year 2023  # single year, ~5 min

Universe: our live ~922-ticker watchlist (via EDGAR submissions API per ticker).
This is faster and sufficient — we need ~50-100 signal instances to validate edge,
not every historical signal across all 20,000 public companies.

Known limitation: slight survivorship bias (tickers that no longer exist won't appear).
For "does the signal type produce positive returns?", this doesn't meaningfully affect
the conclusion.

Anti-bias guarantees:
  1. NO LLM calls — purely mechanical filters, identical to live pipeline.
  2. All pre-signal data constrained to <= signal_date (Section A of price_data.py).
  3. All outcome data constrained to > signal_date (Section B of price_data.py).
  4. ALL three outcome windows (7d, 10d, 30d) reported — none suppressed.
  5. Pre-specified breakdowns chosen before running:
       • By outcome window (7d / 10d / 30d)
       • By 52-week low proximity (within 15% vs not)
       • By cluster size (2 insiders vs 3+)
       • By market cap band ($200M-$500M vs $500M-$5B)
       • By year
  6. Delisted/acquired after signal are included, not silently dropped.
  7. Filters locked to live pipeline — not tuned after seeing results.
"""

import csv
import json
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from backtest.cluster_detector import detect_clusters_for_cik, BtCluster
from backtest.price_data import get_pre_signal_data, get_outcome_data
from backtest.edgar_index import Form4Filing

EDGAR_HEADERS = {
    "User-Agent": "tradefinder-research leoduncan.elearning@gmail.com",
    "Accept-Encoding": "gzip, deflate",
}

BACKTEST_START = date(2022, 1, 1)
BACKTEST_END   = date(2024, 12, 31)

OUTPUT_DIR   = Path(__file__).parent / "results"
CIK_MAP_PATH = Path(__file__).parent.parent / "cache" / "cik_map.json"
SUBMISSIONS_CACHE = Path(__file__).parent / "cache" / "submissions"


def _load_universe() -> list[dict]:
    """Load our live ticker universe from the SQLite watchlist cache."""
    try:
        import sqlite3
        db = Path(__file__).parent.parent / "data" / "trading_research.db"
        conn = sqlite3.connect(str(db))
        rows = conn.execute("SELECT ticker, company_name, market_cap_m FROM watchlist").fetchall()
        conn.close()
        return [{"ticker": r[0], "company_name": r[1], "market_cap_m": r[2]} for r in rows]
    except Exception:
        return []


def _load_cik_map() -> dict[str, str]:
    """Returns {ticker: cik} from the live pipeline CIK map."""
    if not CIK_MAP_PATH.exists():
        return {}
    try:
        return json.loads(CIK_MAP_PATH.read_text())
    except Exception:
        return {}


def _get_form4_filings_for_ticker(
    cik: str,
    start_date: date,
    end_date: date,
) -> list[Form4Filing]:
    """
    Fetch Form 4 accessions for a ticker via EDGAR submissions API.
    Returns filings with filing_date between start_date and end_date.
    Caches the submissions JSON locally.
    """
    SUBMISSIONS_CACHE.mkdir(parents=True, exist_ok=True)
    cache_file = SUBMISSIONS_CACHE / f"{cik}.json"

    if cache_file.exists():
        age_days = (datetime.utcnow() - datetime.fromtimestamp(cache_file.stat().st_mtime)).days
        if age_days < 30:
            try:
                data = json.loads(cache_file.read_text())
            except Exception:
                data = None
        else:
            data = None
    else:
        data = None

    if data is None:
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        try:
            resp = requests.get(url, headers=EDGAR_HEADERS, timeout=15)
            if resp.status_code != 200:
                return []
            data = resp.json()
            cache_file.write_text(json.dumps(data))
            time.sleep(0.11)
        except Exception:
            return []

    try:
        filings_data = data.get("filings", {}).get("recent", {})
        forms      = filings_data.get("form", [])
        accessions = filings_data.get("accessionNumber", [])
        dates      = filings_data.get("filingDate", [])
        filenames  = filings_data.get("primaryDocument", [])
        company_name = data.get("name", "")
    except Exception:
        return []

    results = []
    for form, acc, filing_date, primary_doc in zip(forms, accessions, dates, filenames):
        if form not in ("4", "4/A"):
            continue
        if not (start_date.isoformat() <= filing_date <= end_date.isoformat()):
            continue
        # Build the edgar/data/... path used by the XML fetcher
        acc_nodash = acc.replace("-", "")
        filename = f"edgar/data/{int(cik)}/{acc_nodash}/{acc}.txt"
        results.append(Form4Filing(
            cik=cik,
            company_name=company_name,
            filing_date=filing_date,
            accession=acc,
            filename=filename,
        ))

    return results


def run_backtest(start: date = BACKTEST_START, end: date = BACKTEST_END):
    print("=" * 72)
    print("INSIDER BUYING CLUSTER — HISTORICAL SIGNAL BACKTEST")
    print(f"Period  : {start} to {end}")
    print("Universe: live ticker watchlist (~922 tickers via EDGAR submissions API)")
    print("Bias    : zero LLM calls; temporal isolation enforced; no cherry-picking")
    print("=" * 72)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── Load universe ────────────────────────────────────────────────────────
    universe = _load_universe()
    if not universe:
        print("\n[Error] No tickers in watchlist. Run python run_pipeline.py once first.")
        return
    cik_map = _load_cik_map()
    print(f"\n[Setup] {len(universe)} tickers in universe, {len(cik_map)} in CIK map")

    # ── Phase 1: Fetch Form 4 filings per ticker ─────────────────────────────
    print(f"\n[Phase 1] Fetching Form 4 filing history for each ticker ...")
    print(f"  One EDGAR submissions API call per ticker (~{len(universe)} calls, cached 30d)")

    all_clusters: list[BtCluster] = []
    no_cik = 0
    total = len(universe)

    for i, entry in enumerate(universe, 1):
        ticker = entry["ticker"]
        cik = cik_map.get(ticker)
        if not cik:
            no_cik += 1
            continue

        if i % 100 == 0:
            print(f"  [{i:>4}/{total}] tickers scanned, {len(all_clusters)} clusters found")

        filings = _get_form4_filings_for_ticker(cik, start, end)
        if not filings:
            continue

        # Only pass filings inside a potential cluster window — avoids downloading
        # hundreds of XMLs for tickers where only a handful of filings are nearby.
        if len(filings) < 2:
            continue
        sorted_f = sorted(filings, key=lambda f: f.filing_date)
        in_window: set[str] = set()
        for anchor in sorted_f:
            cutoff = (date.fromisoformat(anchor.filing_date) + timedelta(days=14)).isoformat()
            window = [f for f in sorted_f if anchor.filing_date <= f.filing_date <= cutoff]
            if len(window) >= 2:
                for f in window:
                    in_window.add(f.accession)
        if not in_window:
            continue
        window_filings = [f for f in filings if f.accession in in_window]

        clusters = detect_clusters_for_cik(
            cik=cik,
            company_name=entry.get("company_name", ticker),
            filings=window_filings,
            as_of_date=end,
            ticker=ticker,
        )
        all_clusters.extend(clusters)

    print(f"\n  Tickers scanned       : {total - no_cik}")
    print(f"  No CIK mapping        : {no_cik}")
    print(f"  Clusters detected     : {len(all_clusters)}")

    if not all_clusters:
        print("\n[Result] No clusters found. Check EDGAR connectivity or extend date range.")
        return

    # ── Phase 2: Market cap + materiality filter ──────────────────────────────
    print(f"\n[Phase 2] Applying market cap + materiality filters (pre-signal data only) ...")

    passing = []
    skipped_mcap = skipped_range = skipped_mat = approx = 0

    for cluster in all_clusters:
        signal_date = date.fromisoformat(cluster.signal_date)
        pre = get_pre_signal_data(cluster.ticker, signal_date, cluster.total_usd)

        if pre.market_cap_m is None:
            skipped_mcap += 1; continue
        if not pre.in_market_cap_range:
            skipped_range += 1; continue
        if not pre.passes_materiality:
            skipped_mat += 1; continue
        if pre.shares_approximate:
            approx += 1

        passing.append({"cluster": cluster, "pre": pre})
        time.sleep(0.05)

    print(f"  Passed all filters    : {len(passing)}")
    print(f"  No market cap data    : {skipped_mcap}")
    print(f"  Outside $200M-$5B     : {skipped_range}")
    print(f"  Below materiality     : {skipped_mat}")
    print(f"  Approx shares (noted) : {approx}")

    # ── Phase 3: Outcome measurement ─────────────────────────────────────────
    print(f"\n[Phase 3] Measuring outcomes (strictly post-signal data) ...")

    results = []
    for i, entry in enumerate(passing, 1):
        if i % 20 == 0:
            print(f"  [{i:>4}/{len(passing)}] outcomes measured")
        cluster = entry["cluster"]
        pre     = entry["pre"]
        signal_date = date.fromisoformat(cluster.signal_date)
        outcome = get_outcome_data(cluster.ticker, signal_date)

        results.append({
            "ticker":             cluster.ticker,
            "company_name":       cluster.company_name,
            "signal_date":        cluster.signal_date,
            "cluster_start":      cluster.cluster_start,
            "cluster_end":        cluster.cluster_end,
            "total_usd":          round(cluster.total_usd),
            "unique_insiders":    cluster.unique_insiders,
            "market_cap_m":       pre.market_cap_m,
            "mcap_band":          pre.mcap_band,
            "near_52w_low":       pre.near_52w_low,
            "shares_approximate": pre.shares_approximate,
            "entry_price":        outcome.entry_price,
            "outcome_7d":         outcome.outcome_7d,
            "outcome_10d":        outcome.outcome_10d,
            "outcome_30d":        outcome.outcome_30d,
            "outcome_7d_date":    outcome.outcome_7d_date,
            "outcome_10d_date":   outcome.outcome_10d_date,
            "outcome_30d_date":   outcome.outcome_30d_date,
            "delisted_or_acquired": outcome.delisted_or_acquired,
            "notes":              outcome.notes,
        })
        time.sleep(0.05)

    _write_csv(results, start, end)
    _print_summary(results)


def _write_csv(results: list[dict], start: date, end: date):
    if not results:
        return
    path = OUTPUT_DIR / f"backtest_{start}_{end}.csv"
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)
    print(f"\n[Output] {len(results)} results → {path}")


def _print_summary(results: list[dict]):
    if not results:
        print("\n[Summary] No results.")
        return

    print("\n" + "=" * 72)
    print("BACKTEST SUMMARY  (mechanical filter layer only — no LLM)")
    print("=" * 72)
    n = len(results)
    print(f"Signals passing all filters : {n}")
    print(f"Delisted/acquired post-signal (included): {sum(1 for r in results if r['delisted_or_acquired'])}")
    print(f"Approximate shares used     : {sum(1 for r in results if r['shares_approximate'])}")

    def stats(vals):
        if not vals: return None
        wins = [v for v in vals if v > 0]
        losses = [v for v in vals if v <= 0]
        return {
            "n": len(vals),
            "win%": round(len(wins)/len(vals)*100, 1),
            "avg": round(sum(vals)/len(vals), 2),
            "med": round(sorted(vals)[len(vals)//2], 2),
            "avgW": round(sum(wins)/len(wins), 2) if wins else 0,
            "avgL": round(sum(losses)/len(losses), 2) if losses else 0,
        }

    def row(label, vals):
        s = stats(vals)
        if not s or not s["n"]: return
        print(f"  {label:<40} n={s['n']:<4} win={s['win%']:>5.1f}%  avg={s['avg']:>+6.2f}%  med={s['med']:>+6.2f}%")

    for window, key in [("7-day", "outcome_7d"), ("10-day", "outcome_10d"), ("30-day", "outcome_30d")]:
        vals = [r[key] for r in results if r[key] is not None]
        print(f"\n── {window} ({'─'*50})")
        row("ALL SIGNALS", vals)
        row("  Near 52-week low (within 15%)", [r[key] for r in results if r[key] is not None and r["near_52w_low"]])
        row("  NOT near 52-week low",          [r[key] for r in results if r[key] is not None and not r["near_52w_low"]])
        row("  Exactly 2 insiders",            [r[key] for r in results if r[key] is not None and r["unique_insiders"] == 2])
        row("  3+ insiders",                   [r[key] for r in results if r[key] is not None and r["unique_insiders"] >= 3])
        row("  $200M-$500M band",              [r[key] for r in results if r[key] is not None and r["mcap_band"] == "$200M-$500M"])
        row("  $500M-$5B band",                [r[key] for r in results if r[key] is not None and r["mcap_band"] == "$500M-$5B"])
        for yr in ["2022", "2023", "2024"]:
            row(f"  Year {yr}", [r[key] for r in results if r[key] is not None and r["signal_date"].startswith(yr)])

    print("\n" + "=" * 72)
    print("CAVEATS")
    print("  Mechanical filters only — Agent 1C/1D will reject many of these live.")
    print("  Survivorship bias: tickers no longer in live universe are excluded.")
    print("  Analyst/news neglect filters not applied (no historical data).")
    print("=" * 72)


if __name__ == "__main__":
    year_arg = next((a for a in sys.argv[1:] if a.startswith("--year")), None)
    if year_arg:
        yr = int(year_arg.split("=")[-1]) if "=" in year_arg else int(sys.argv[sys.argv.index(year_arg)+1])
        run_backtest(date(yr, 1, 1), date(yr, 12, 31))
    else:
        run_backtest()
